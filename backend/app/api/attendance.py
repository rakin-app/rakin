"""Attendance: a session's roster, marking it, a trial guest at the mat, a person's counts.

A session's roster is everyone who may train at it: a membership that is not cancelled
(a frozen member who turns up trains, for nothing, and stays frozen), open to its class
type's program, one row per person, plus anyone already marked
(`app.schemas.attendance.Roster`). A mark or a trial guest is held to the same rule.
A coach taps names on and off and sends what changed (`PATCH .../attendance`);
marking takes what the membership pays the class with (`app.domain.attendance`) and
unmarking gives it back. Each change is idempotent, so a
phone that lost signal resends its queue without double-counting anyone.

The roster flags an overdue member with a dot and never says what they owe: a coach
may not read the ledger (migration 0006), so it asks `overdue_memberships()` (0023)
for the ids alone.

A trial guest is someone trying a class: the screen adds them by RUT or email, with
their phone (`POST /api/people`), then starts them on one of the gym's trial plans,
present at the class (`POST .../trials`). A trial charges nothing, which is why a coach
may start one where only an owner or admin may start any other membership. No welcome
is sent: the person added at the mat has nothing to pay yet.

A cancelled class (migration 0033) takes no attendance: marking at it, or adding a
trial guest to it, is a 409. Cancelling is refused once anyone is marked, so it has
none to count. Deleting a class removes its attendance (`remove_attendance`), giving
back what each mark took, as unmarking would.

Any staff role may use it, coaches included; members may not. A member reads their own
counts on the student page (`/api/me/page`).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.grades import readable_scheme
from app.api.memberships import HAS_LEFT, PersonHasLeft, insert_membership
from app.api.people import NOT_FOUND as PERSON_NOT_FOUND
from app.api.people import in_gym
from app.domain import membership as memberships
from app.domain.attendance import credits_to_consume
from app.domain.dates import gym_today, start_of_local_day
from app.domain.membership import Membership, MembershipStatus, PlanKind, PlanTerms
from app.roles import StaffSession
from app.schemas.attendance import (
    AlreadyMember,
    AttendanceChange,
    PersonAttendance,
    Roster,
    RosterMember,
    TrialGuest,
)
from app.schemas.grades import Rank
from app.schemas.memberships import HasLeft
from app.tenancy import Tenant, current_tenant

router = APIRouter(tags=["classes"])

SESSION_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
CANCELLED = HTTPException(status.HTTP_409_CONFLICT, "the class is cancelled")

SELECT_SESSION = """
    SELECT s.id, s.starts_at, s.cancelled_at, s.class_type_id, c.program_id, c.credit_cost,
           g.timezone, g.settings
    FROM session s
    JOIN class_type c ON c.id = s.class_type_id
    JOIN gym g ON g.id = s.gym_id
    WHERE s.id = :id
"""

# The statuses that may train: everyone but a cancelled membership. A frozen member
# who turns up is marked, spends nothing (`app.domain.attendance`) and stays frozen.
ON_ROSTER = ("active", "trial", "lapsed", "frozen")

# Days before a class in which coming to one of its type makes someone a regular of it.
REGULAR_DAYS = 30

# One row per person: the membership marked present, else their one the program admits,
# by `ON_ROSTER`'s order, latest first. `days_absent` counts from their last class
# before this one, on the gym's calendar, once per person kept. `regular` is whether
# they came to a class of this one's type in the `REGULAR_DAYS` before it, which the
# screen lists first (#178). RLS keeps every table to the current gym.
ROSTER = f"""
SELECT roster.*,
       (:starts_at AT TIME ZONE :zone)::date - (
           SELECT max((ps.starts_at AT TIME ZONE :zone)::date)
           FROM attendance pa
           JOIN session ps ON ps.id = pa.session_id
           JOIN membership pm ON pm.id = pa.membership_id
           WHERE pm.person_id = roster.person_id AND ps.starts_at < :starts_at
       ) AS days_absent,
       EXISTS (
           SELECT FROM attendance ra
           JOIN session rs ON rs.id = ra.session_id
           JOIN membership rm ON rm.id = ra.membership_id
           WHERE rm.person_id = roster.person_id AND rs.class_type_id = :class_type
             AND rs.starts_at < :starts_at
             AND rs.starts_at >= :starts_at - make_interval(days => {REGULAR_DAYS})
       ) AS regular
FROM (
    SELECT DISTINCT ON (m.person_id)
           m.id AS membership_id, m.person_id, gp.name, gp.rut, pl.name AS plan_name,
           pl.kind AS plan_kind, m.status, m.credits_remaining,
           a.membership_id IS NOT NULL AS present,
           m.id IN (SELECT overdue_memberships()) AS overdue,
           r.rank_key, r.sub_rank, r.awarded_on
    FROM membership m
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.person_id = m.person_id
    LEFT JOIN attendance a ON a.session_id = :session AND a.membership_id = m.id
    LEFT JOIN LATERAL (
        SELECT ge.rank_key, ge.sub_rank, ge.awarded_on
        FROM grade_event ge JOIN membership gm ON gm.id = ge.membership_id
        WHERE gm.person_id = m.person_id
        ORDER BY ge.awarded_on DESC, ge.created_at DESC, ge.id
        LIMIT 1
    ) r ON true
    WHERE a.membership_id IS NOT NULL
       OR (m.status IN {ON_ROSTER}
           AND (pl.program_id IS NULL OR pl.program_id = :program))
    ORDER BY m.person_id, a.membership_id IS NOT NULL DESC,
             array_position(ARRAY{list(ON_ROSTER)}, m.status), m.started_at DESC
) roster
ORDER BY lower(name), person_id
"""

LOCK_MEMBERSHIP = """
    SELECT pl.kind, pl.program_id, m.status, m.credits_remaining
    FROM membership m JOIN plan pl ON pl.id = m.plan_id
    WHERE m.id = :id FOR UPDATE OF m
"""

INSERT_ATTENDANCE = """
    INSERT INTO attendance (gym_id, session_id, membership_id, marked_by, credits_consumed)
    VALUES (current_setting('app.gym_id')::uuid, :session, :membership, :marked_by, :credits)
    ON CONFLICT (session_id, membership_id) DO NOTHING
    RETURNING credits_consumed
"""

DELETE_ATTENDANCE = """
    DELETE FROM attendance WHERE session_id = :session AND membership_id = :membership
    RETURNING credits_consumed
"""

SPEND = "UPDATE membership SET credits_remaining = credits_remaining - :credits WHERE id = :id"

# A cancelled membership never changes again (0009), so it keeps what it had.
REFUND = """
    UPDATE membership SET credits_remaining = credits_remaining + :credits
    WHERE id = :id AND credits_remaining IS NOT NULL AND status <> 'cancelled'
"""

LIVE_MEMBERSHIP = """
    SELECT id FROM membership
    WHERE person_id = :person AND status IN ('trial', 'active', 'frozen')
    ORDER BY started_at DESC, created_at DESC
    LIMIT 1
"""

# The person's classes over every membership they hold here, in all and from each of
# two instants: sessions of a class type that counts as a class, so not an open mat by
# default (migration 0028). RLS keeps it to the current gym.
COUNTS = """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE s.starts_at >= :recent) AS recent,
           count(*) FILTER (WHERE s.starts_at >= :since) AS since
    FROM attendance a
    JOIN session s ON s.id = a.session_id
    JOIN class_type c ON c.id = s.class_type_id
    JOIN membership m ON m.id = a.membership_id
    WHERE m.person_id = :person AND c.counts_as_class
"""


@dataclass(frozen=True)
class _Class:
    id: uuid.UUID
    starts_at: datetime
    cancelled_at: datetime | None
    class_type_id: uuid.UUID
    program_id: uuid.UUID
    credit_cost: int
    timezone: str
    settings: Any


def _unprocessable(field: str, kind: str, msg: str) -> RequestValidationError:
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", field)}])


def _admits(program_id: uuid.UUID | None, held: _Class) -> bool:
    """Whether a plan in `program_id` covers the class: one in its program, or a plan
    open to any class. The roster's rule, which marks and trials are held to too."""
    return program_id is None or program_id == held.program_id


async def _class(session: AsyncSession, session_id: uuid.UUID, *, lock: bool = False) -> _Class:
    """The session with what the roster needs; locked, every change to its attendance
    waits for this one's."""
    sql = f"{SELECT_SESSION}{' FOR UPDATE OF s' if lock else ''}"
    row = (await session.execute(text(sql), {"id": session_id})).one_or_none()
    if row is None:
        raise SESSION_NOT_FOUND
    return _Class(**row._mapping)


def _open(held: _Class) -> None:
    """A 409 if the class is cancelled: it takes no attendance."""
    if held.cancelled_at is not None:
        raise CANCELLED


async def _roster(session: AsyncSession, held: _Class) -> Roster:
    scheme = readable_scheme(held.settings)
    rows = await session.execute(
        text(ROSTER),
        {
            "session": held.id,
            "program": held.program_id,
            "class_type": held.class_type_id,
            "starts_at": held.starts_at,
            "zone": held.timezone,
        },
    )
    members = []
    for row in rows:
        fields = dict(row._mapping)
        rank_key, sub_rank, awarded_on = (
            fields.pop(k) for k in ("rank_key", "sub_rank", "awarded_on")
        )
        rank = None if rank_key is None else Rank.labelled(scheme, rank_key, sub_rank, awarded_on)
        members.append(RosterMember(**fields, rank=rank))
    return Roster(session_id=held.id, present=sum(m.present for m in members), members=members)


async def _mark(
    session: AsyncSession, held: _Class, membership_id: uuid.UUID, marked_by: uuid.UUID
) -> None:
    row = (await session.execute(text(LOCK_MEMBERSHIP), {"id": membership_id})).one_or_none()
    if row is None:
        raise _unprocessable("mark", "unknown_membership", f"no membership {membership_id}")
    if row.status == MembershipStatus.CANCELLED:
        raise _unprocessable(
            "mark", "cancelled_membership", f"membership {membership_id} is cancelled"
        )
    if row.status not in ON_ROSTER:
        raise _unprocessable(
            "mark", "not_on_roster", f"membership {membership_id} is {row.status}, not on a roster"
        )
    if not _admits(row.program_id, held):
        raise _unprocessable(
            "mark", "not_in_program", f"membership {membership_id} is not for this class"
        )
    state = Membership(
        PlanKind(row.kind), MembershipStatus(row.status), credits_remaining=row.credits_remaining
    )
    credits = credits_to_consume(state, held.credit_cost)
    inserted = await session.scalar(
        text(INSERT_ATTENDANCE),
        {
            "session": held.id,
            "membership": membership_id,
            "marked_by": marked_by,
            "credits": credits,
        },
    )
    if inserted:
        await session.execute(text(SPEND), {"id": membership_id, "credits": inserted})


async def _unmark(session: AsyncSession, held: _Class, membership_id: uuid.UUID) -> None:
    credits = await session.scalar(
        text(DELETE_ATTENDANCE), {"session": held.id, "membership": membership_id}
    )
    if credits:
        await session.execute(text(REFUND), {"id": membership_id, "credits": credits})


async def remove_attendance(session: AsyncSession, session_id: uuid.UUID) -> None:
    """Everyone's attendance at the session, gone, each giving back what it took. The
    caller holds the session locked; memberships go in id order, as every change here
    takes them."""
    rows = await session.execute(
        text(
            "DELETE FROM attendance WHERE session_id = :session"
            " RETURNING membership_id, credits_consumed"
        ),
        {"session": session_id},
    )
    for row in sorted(rows, key=lambda r: r.membership_id):
        if row.credits_consumed:
            await session.execute(
                text(REFUND), {"id": row.membership_id, "credits": row.credits_consumed}
            )


@router.get("/api/sessions/{session_id}/roster")
async def get_roster(session_id: uuid.UUID, session: StaffSession) -> Roster:
    return await _roster(session, await _class(session, session_id))


@router.patch(
    "/api/sessions/{session_id}/attendance",
    responses={status.HTTP_409_CONFLICT: {"description": "the class is cancelled"}},
)
async def change_attendance(
    session_id: uuid.UUID,
    body: AttendanceChange,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Roster:
    """Mark and unmark at once; the roster as it then stands."""
    held = await _class(session, session_id, lock=True)
    _open(held)
    marking = set(body.mark)
    # One membership at a time in id order, as every request here takes them, so two
    # changes to different sessions never wait on each other's locks in a cycle.
    for membership_id in sorted(marking | set(body.unmark)):
        if membership_id in marking:
            await _mark(session, held, membership_id, tenant.person_id)
        else:
            await _unmark(session, held, membership_id)
    return await _roster(session, held)


@router.post(
    "/api/sessions/{session_id}/trials",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": AlreadyMember | HasLeft,
            "description": "already a member, has left, or the class is cancelled",
        }
    },
)
async def add_trial_guest(
    session_id: uuid.UUID,
    body: TrialGuest,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Roster:
    """Start the person on a trial plan from today, marked present at the session. A
    409 names the membership of someone who already has a live one, to mark instead, or
    says `has_left` for someone dado de baja, whom an admin reactivates; a cancelled
    class is a 409 too."""
    held = await _class(session, session_id, lock=True)
    _open(held)
    if not await in_gym(session, body.person_id):
        raise _unprocessable("person_id", "unknown_person", "no such person")
    plan = (
        await session.execute(
            text(
                "SELECT kind, program_id, credits, credit_expiry_days, active"
                " FROM plan WHERE id = :id"
            ),
            {"id": body.plan_id},
        )
    ).one_or_none()
    if plan is None or plan.kind != PlanKind.TRIAL:
        raise _unprocessable("plan_id", "not_a_trial_plan", "not one of the gym's trial plans")
    if not plan.active:
        raise _unprocessable("plan_id", "inactive_plan", "the plan is deactivated")
    if not _admits(plan.program_id, held):
        raise _unprocessable("plan_id", "not_in_program", "the plan is not for this class")
    live = await session.scalar(text(LIVE_MEMBERSHIP), {"person": body.person_id})
    if live is not None:
        conflict = AlreadyMember(membership_id=live)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))

    today = gym_today(held.timezone)
    terms = PlanTerms(
        PlanKind.TRIAL, credits=plan.credits, credit_expiry_days=plan.credit_expiry_days
    )
    started = memberships.start(terms, today)
    try:
        membership_id = await insert_membership(
            session, body.person_id, body.plan_id, started, start_of_local_day(today, held.timezone)
        )
    except PersonHasLeft:
        # Someone dado de baja comes back through Reactivar, not a trial.
        raise HAS_LEFT from None
    await _mark(session, held, membership_id, tenant.person_id)
    return await _roster(session, held)


# "The last 30 days": today and the 29 before it, by the gym's calendar.
RECENT_DAYS = 30


def recent_from(today: date, zone: str) -> datetime:
    """The first instant of "the last 30 days" ending `today`, in the gym's timezone."""
    return start_of_local_day(today - timedelta(days=RECENT_DAYS - 1), zone)


async def attended(
    session: AsyncSession, person_id: uuid.UUID, *, recent: datetime, since: datetime | None
) -> tuple[int, int, int | None]:
    """The person's classes here: in all, from `recent`, and from `since` if given."""
    row = (
        await session.execute(text(COUNTS), {"person": person_id, "recent": recent, "since": since})
    ).one()
    return row.total, row.recent, None if since is None else row.since


async def _promoted_on(session: AsyncSession, person_id: uuid.UUID) -> date | None:
    """The day of the person's current rank: their latest promotion's."""
    day: date | None = await session.scalar(
        text(
            "SELECT max(ge.awarded_on) FROM grade_event ge"
            " JOIN membership m ON m.id = ge.membership_id WHERE m.person_id = :person"
        ),
        {"person": person_id},
    )
    return day


@router.get("/api/people/{person_id}/attendance")
async def person_attendance(
    person_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> PersonAttendance:
    if not await in_gym(session, person_id):
        raise PERSON_NOT_FOUND
    zone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    today = gym_today(zone)
    promoted = await _promoted_on(session, person_id)
    total, recent, since = await attended(
        session,
        person_id,
        recent=recent_from(today, zone),
        since=None if promoted is None else start_of_local_day(promoted + timedelta(days=1), zone),
    )
    return PersonAttendance(last_30_days=recent, total=total, since_promotion=since)
