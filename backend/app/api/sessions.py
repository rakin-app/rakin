"""The current gym's sessions: the day's classes, start one, edit, cancel or delete it.

A session is one class (migration 0020). The weekly schedule makes most of them ahead
of time (`app.api.schedule`, #167); a coach may also start one ad hoc when the class
begins, of one of the gym's active class types, and writes its topic and notes during
or after class, and the gym's tags it is about (#243). The day's sessions are those
whose `starts_at` falls on that calendar day in the gym's timezone, today by default.
A session may carry how long it lasts.

A session starts now and is taught by the person starting it unless the body says
otherwise. Its coach is one of the gym's staff when it is started or reassigned; one
who has left since stays its coach.

Each session carries `present`, how many are marked at it: none is a class whose
attendance was never taken. The owner's dashboard lists those of the last week
(`GET /api/sessions/unmarked`, owner and admin), so a class nobody marked does not
leave the second ledger quietly empty.

Any staff role may read them and start one, coaches included, since they are who
start a class and write what it covered; members may not use them at all. Changing
one is narrower (#163): an owner or admin may move it, change its duration, its type
or its coach,
and its own coach may write its topic and notes and set its tags. A type changed after the class
re-applies the new type's `counts_as_class` and `kind`, since every count reads them
off the type; its attendance stays.

Changing one class of the schedule changes that class only, and it keeps its slot and
date, so the schedule never makes that date again.

An owner or admin cancels a class that won't happen (`POST .../cancel`, undone by
`POST .../reactivate`): it stays on the day, `cancelled_at` set, and is refused
attendance and the timer, so it counts for nothing. Once attendance has been taken it
is refused with a 409, to delete instead. Deleting (`DELETE`, owner and admin, held to
them by RLS too, migration 0033) removes a class made by mistake with its attendance,
giving back the credits each took, and its timer blocks. A deleted class of the
schedule is not made again by the nightly run (migration 0035, `generated_until`).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attendance import remove_attendance
from app.api.class_tags import require_tags, set_tags, tags_of_session
from app.domain.dates import gym_today, start_of_local_day
from app.roles import ADMIN_ROLES, FORBIDDEN, AdminSession, StaffSession, role_in_gym
from app.schemas.classes import ClassKind
from app.schemas.sessions import Day, Session, SessionCreate, SessionUpdate, Unmarked
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/sessions", tags=["classes"])

# The dashboard looks this many gym days back, today included, for classes nobody marked.
UNMARKED_DAYS = 7

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
# Cancelling a class someone was marked at: delete it instead, or unmark them first.
HAS_ATTENDANCE = HTTPException(
    status.HTTP_409_CONFLICT, "attendance was taken at the class; delete it instead"
)

# What a session's own coach may change; everything else is an owner's or admin's.
COACH_FIELDS = frozenset({"topic", "notes", "tag_ids"})

# Each with its class type, program, coach and tags. RLS keeps every table to the
# current gym.
SELECT_SESSION = f"""
    SELECT s.id, s.class_type_id, c.name AS class_type_name, c.program_id,
           p.name AS program_name, s.starts_at, s.coach_id, gp.name AS coach_name,
           s.duration_minutes, s.topic, s.notes, s.cancelled_at, s.created_at, s.updated_at,
           (SELECT count(*) FROM attendance a WHERE a.session_id = s.id) AS present,
           s.slot_id, s.slot_date, {tags_of_session("s")} AS tags
    FROM session s
    JOIN class_type c ON c.id = s.class_type_id
    JOIN program p ON p.id = c.program_id
    JOIN gym_person gp ON gp.person_id = s.coach_id
"""


def unprocessable(field: str, kind: str, msg: str) -> RequestValidationError:
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", field)}])


async def require_class_type(session: AsyncSession, class_type_id: uuid.UUID) -> None:
    """A 422 unless `class_type_id` is one of this gym's active class types."""
    active = await session.scalar(
        text("SELECT active FROM class_type WHERE id = :id"), {"id": class_type_id}
    )
    if active is None:
        raise unprocessable("class_type_id", "unknown_class_type", "no such class type")
    if not active:
        raise unprocessable("class_type_id", "inactive_class_type", "the class type is deactivated")


async def require_coach(session: AsyncSession, person_id: uuid.UUID) -> None:
    """A 422 unless `person_id` is on the gym's staff, in any role."""
    staff = await session.scalar(
        text("SELECT true FROM staff WHERE person_id = :id"), {"id": person_id}
    )
    if not staff:
        raise unprocessable("coach_id", "unknown_coach", "not on this gym's staff")


async def gym_timezone(session: AsyncSession, tenant: Tenant) -> str:
    zone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return zone


async def _get(session: AsyncSession, session_id: uuid.UUID, *, lock: bool = False) -> Session:
    sql = f"{SELECT_SESSION} WHERE s.id = :id{' FOR UPDATE OF s' if lock else ''}"
    row = (await session.execute(text(sql), {"id": session_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Session.model_validate(row, from_attributes=True)


@router.get("")
async def list_sessions(
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> Day:
    """`?date=` (an ISO day, default today in the gym's timezone): that day's sessions."""
    zone = await gym_timezone(session, tenant)
    day = day or gym_today(zone)
    result = await session.execute(
        text(
            f"{SELECT_SESSION} WHERE s.starts_at >= :start AND s.starts_at < :end"
            " ORDER BY s.starts_at, lower(c.name), s.created_at"
        ),
        {
            "start": start_of_local_day(day, zone),
            "end": start_of_local_day(day + timedelta(days=1), zone),
        },
    )
    sessions = [Session.model_validate(row, from_attributes=True) for row in result]
    return Day(date=day, timezone=zone, sessions=sessions)


@router.get("/unmarked")
async def unmarked_sessions(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> Unmarked:
    """The last `UNMARKED_DAYS` gym days' sessions with no one marked, latest first.

    Only those already started: one set to start later has no attendance to take yet.
    A cancelled one has none to take at all.
    """
    zone = await gym_timezone(session, tenant)
    since = gym_today(zone) - timedelta(days=UNMARKED_DAYS - 1)
    result = await session.execute(
        text(
            f"{SELECT_SESSION} WHERE s.starts_at >= :start AND s.starts_at <= now()"
            " AND s.cancelled_at IS NULL"
            " AND NOT EXISTS (SELECT FROM attendance a WHERE a.session_id = s.id)"
            " ORDER BY s.starts_at DESC, lower(c.name), s.created_at"
        ),
        {"start": start_of_local_day(since, zone)},
    )
    sessions = [Session.model_validate(row, from_attributes=True) for row in result]
    return Unmarked(since=since, timezone=zone, sessions=sessions)


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_session(
    body: SessionCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Session:
    await require_class_type(session, body.class_type_id)
    coach_id = body.coach_id or tenant.person_id
    await require_coach(session, coach_id)
    result = await session.execute(
        text(
            "INSERT INTO session"
            " (gym_id, class_type_id, starts_at, duration_minutes, coach_id, topic, notes)"
            " VALUES (current_setting('app.gym_id')::uuid, :class_type_id,"
            " coalesce(:starts_at, now()), :duration_minutes, :coach_id, :topic, :notes)"
            " RETURNING id"
        ),
        {**body.model_dump(), "coach_id": coach_id},
    )
    return await _get(session, result.scalar_one())


@router.get("/{session_id}")
async def get_session(session_id: uuid.UUID, session: StaffSession) -> Session:
    return await _get(session, session_id)


async def _require_plan_fits(session: AsyncSession, session_id: uuid.UUID) -> None:
    """A 422 unless the session's timer plan fits an open mat: none yet, or one sparring
    block, the rule `PUT .../blocks` holds an open mat to."""
    blocks = (
        await session.execute(
            text(
                "SELECT k.is_sparring FROM session_block b"
                " JOIN block_kind k ON k.id = b.block_kind_id WHERE b.session_id = :id"
            ),
            {"id": session_id},
        )
    ).all()
    if blocks and (len(blocks) != 1 or not blocks[0].is_sparring):
        raise unprocessable(
            "class_type_id", "open_mat_plan", "an open mat is one sparring block; fix its blocks"
        )


@router.patch("/{session_id}")
async def update_session(
    session_id: uuid.UUID,
    body: SessionUpdate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Session:
    """The fields sent, as they then stand. A field sent as it already is changes
    nothing, so a form may send them all; changing any but the topic and notes is an
    owner's or admin's, and those two the session's own coach's too, else a 403."""
    current = await _get(session, session_id, lock=True)
    sent = body.model_dump(exclude_unset=True)
    tag_ids = [tag.id for tag in current.tags]
    changes = {
        k: v
        for k, v in sent.items()
        if (set(v) != set(tag_ids) if k == "tag_ids" else v != getattr(current, k))
    }
    coaching = current.coach_id == tenant.person_id and changes.keys() <= COACH_FIELDS
    if changes and not coaching and await role_in_gym(session, tenant) not in ADMIN_ROLES:
        raise FORBIDDEN
    if "coach_id" in changes:
        await require_coach(session, changes["coach_id"])
    if "class_type_id" in changes:
        await require_class_type(session, changes["class_type_id"])
        kind = await session.scalar(
            text("SELECT kind FROM class_type WHERE id = :id"), {"id": changes["class_type_id"]}
        )
        if kind == ClassKind.OPEN_MAT:
            await _require_plan_fits(session, session_id)
    if "tag_ids" in changes:
        await require_tags(session, changes["tag_ids"], tag_ids, "tag_ids")
        await set_tags(session, "session_tag", "session_id", session_id, changes.pop("tag_ids"))
    fields = {"topic", "notes", "coach_id", "class_type_id", "starts_at", "duration_minutes"}
    columns = {**current.model_dump(include=fields), **changes}
    await session.execute(
        text(
            "UPDATE session SET topic = :topic, notes = :notes, coach_id = :coach_id,"
            " class_type_id = :class_type_id, starts_at = :starts_at,"
            " duration_minutes = :duration_minutes, updated_at = now()"
            " WHERE id = :id"
        ),
        {**columns, "id": session_id},
    )
    return await _get(session, session_id)


@router.post(
    "/{session_id}/cancel",
    responses={status.HTTP_409_CONFLICT: {"description": "attendance was taken at it"}},
)
async def cancel_session(session_id: uuid.UUID, session: AdminSession) -> Session:
    """Cancel a class that won't happen. Cancelling it again keeps when it was."""
    current = await _get(session, session_id, lock=True)
    if current.present:
        raise HAS_ATTENDANCE
    await session.execute(
        text(
            "UPDATE session SET cancelled_at = coalesce(cancelled_at, now()),"
            " updated_at = now() WHERE id = :id"
        ),
        {"id": session_id},
    )
    return await _get(session, session_id)


@router.post("/{session_id}/reactivate")
async def reactivate_session(session_id: uuid.UUID, session: AdminSession) -> Session:
    """Undo a cancel; a class that stands already is left as it is."""
    await _get(session, session_id, lock=True)
    await session.execute(
        text(
            "UPDATE session SET cancelled_at = NULL, updated_at = now()"
            " WHERE id = :id AND cancelled_at IS NOT NULL"
        ),
        {"id": session_id},
    )
    return await _get(session, session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: uuid.UUID, session: AdminSession) -> None:
    """Delete a class made by mistake: its attendance, each giving back the credits it
    took, its timer blocks, then the class."""
    await _get(session, session_id, lock=True)
    await remove_attendance(session, session_id)
    await session.execute(
        text("DELETE FROM session_block WHERE session_id = :id"), {"id": session_id}
    )
    await session.execute(text("DELETE FROM session WHERE id = :id"), {"id": session_id})
