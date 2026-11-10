"""The current gym's sessions: the day's classes, start one, write its topic and notes.

A session is one class actually held (migration 0020). There is no timetable: a coach
starts one ad hoc when the class begins, of one of the gym's active class types, and
writes its topic and notes during or after class. The day's sessions are those whose
`starts_at` falls on that calendar day in the gym's timezone, today by default.

A session starts now and is taught by the person starting it unless the body says
otherwise. Its coach is one of the gym's staff when it is started or reassigned; one
who has left since stays its coach. There is no delete: attendance points at it.

Any staff role may use it, coaches included, since they are who start a class and
write what it covered; members may not use it at all.
"""

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dates import gym_today, start_of_local_day
from app.roles import StaffSession
from app.schemas.sessions import Day, Session, SessionCreate, SessionUpdate
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/sessions", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

# Each with its class type, program and coach. RLS keeps every table to the current gym.
SELECT_SESSION = """
    SELECT s.id, s.class_type_id, c.name AS class_type_name, c.program_id,
           p.name AS program_name, s.starts_at, s.coach_id, gp.name AS coach_name,
           s.topic, s.notes, s.created_at, s.updated_at
    FROM session s
    JOIN class_type c ON c.id = s.class_type_id
    JOIN program p ON p.id = c.program_id
    JOIN gym_person gp ON gp.person_id = s.coach_id
"""


def _unprocessable(field: str, kind: str, msg: str) -> RequestValidationError:
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", field)}])


async def _require_class_type(session: AsyncSession, class_type_id: uuid.UUID) -> None:
    """A 422 unless `class_type_id` is one of this gym's active class types."""
    active = await session.scalar(
        text("SELECT active FROM class_type WHERE id = :id"), {"id": class_type_id}
    )
    if active is None:
        raise _unprocessable("class_type_id", "unknown_class_type", "no such class type")
    if not active:
        raise _unprocessable(
            "class_type_id", "inactive_class_type", "the class type is deactivated"
        )


async def _require_coach(session: AsyncSession, person_id: uuid.UUID) -> None:
    """A 422 unless `person_id` is on the gym's staff, in any role."""
    staff = await session.scalar(
        text("SELECT true FROM staff WHERE person_id = :id"), {"id": person_id}
    )
    if not staff:
        raise _unprocessable("coach_id", "unknown_coach", "not on this gym's staff")


async def _timezone(session: AsyncSession, tenant: Tenant) -> str:
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
    zone = await _timezone(session, tenant)
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


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_session(
    body: SessionCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Session:
    await _require_class_type(session, body.class_type_id)
    coach_id = body.coach_id or tenant.person_id
    await _require_coach(session, coach_id)
    result = await session.execute(
        text(
            "INSERT INTO session (gym_id, class_type_id, starts_at, coach_id, topic, notes)"
            " VALUES (current_setting('app.gym_id')::uuid, :class_type_id,"
            " coalesce(:starts_at, now()), :coach_id, :topic, :notes)"
            " RETURNING id"
        ),
        {**body.model_dump(), "coach_id": coach_id},
    )
    return await _get(session, result.scalar_one())


@router.get("/{session_id}")
async def get_session(session_id: uuid.UUID, session: StaffSession) -> Session:
    return await _get(session, session_id)


@router.patch("/{session_id}")
async def update_session(
    session_id: uuid.UUID, body: SessionUpdate, session: StaffSession
) -> Session:
    current = await _get(session, session_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if "coach_id" in changes and changes["coach_id"] != current.coach_id:
        await _require_coach(session, changes["coach_id"])
    columns = {**current.model_dump(include={"topic", "notes", "coach_id"}), **changes}
    await session.execute(
        text(
            "UPDATE session SET topic = :topic, notes = :notes, coach_id = :coach_id,"
            " updated_at = now() WHERE id = :id"
        ),
        {**columns, "id": session_id},
    )
    return await _get(session, session_id)
