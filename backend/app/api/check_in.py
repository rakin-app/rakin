"""Check-in at the door: open access, with no class scheduled (#348).

A climbing gym is open all day and has no classes: people come when they want. Its
class type is of the kind `open_access` (migration 0059), and each visit is an
attendance at that type's session of the day, so attendance keeps one shape: a credits
pack spends the type's `credit_cost`, inactivity and a student's classes count the
visit, as any other class's. The first check-in of a day, in the gym's timezone, makes
the day's session, taught by whoever checked them in; `session.open_day` is its date,
and its unique index makes two first check-ins at once one session.

"Entrada" asks `GET /api/check-in` for the gym's active open-access types, each with
the day's arrivals, newest first, and when each came in (`marked_at`). An empty list is
a gym with none, which shows no Entrada at all. Searching (`.../search?q=`, by name or
RUT, as the member list's search reads them) finds who may be checked in by the
roster's rule (`app.api.attendance`): one membership per person, not cancelled, open to
the type's program. A check-in (`POST`) marks that membership, and is idempotent, so a
second tap changes nothing; undoing one (`DELETE .../{membership_id}`) unmarks it,
giving its credits back. A lapsed plan or a spent pack is the screen's warning, never a
refusal: the membership checks in for what it has, as at a class.

The day's session is a session like any other: its roster, its deletion and its
cancelling are `app.api.sessions`'. A cancelled one refuses check-ins (409) until an
admin reactivates it; deleting it gives back the credits, and the next check-in makes
a new one.

Any staff role may use it, coaches included; members may not.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attendance import ON_ROSTER, class_of, mark_present, require_open, unmark
from app.api.people import people_matching
from app.api.sessions import gym_timezone
from app.domain.dates import gym_today
from app.roles import StaffSession
from app.schemas.check_in import Arrival, Candidate, CheckIn, Door
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/check-in", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "no such open-access class type")

# A search shows this many, by name: enough to pick from, typed a letter more if not.
SEARCH_LIMIT = 20

# The open-access types with their program's name; RLS keeps them to the current gym.
SELECT_TYPE = """
    SELECT c.id AS class_type_id, c.name, c.program_id, p.name AS program_name,
           c.credit_cost, c.active
    FROM class_type c JOIN program p ON p.id = c.program_id
    WHERE c.kind = 'open_access'
"""

# A membership as the screen shows it.
VISITOR = """
    m.id AS membership_id, m.person_id, gp.name, gp.rut, pl.name AS plan_name,
    pl.kind AS plan_kind, m.status, m.credits_remaining,
    m.id IN (SELECT overdue_memberships()) AS overdue
"""

ARRIVALS = f"""
    SELECT {VISITOR}, a.marked_at, a.credits_consumed
    FROM attendance a
    JOIN membership m ON m.id = a.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.person_id = m.person_id
    WHERE a.session_id = :session
    ORDER BY a.marked_at DESC, lower(gp.name), m.id
"""

# One row per person found, by the roster's rule: the membership checked in today,
# else their one the program admits, by `ON_ROSTER`'s order, latest first.
CANDIDATES = f"""
SELECT * FROM (
    SELECT DISTINCT ON (m.person_id) {VISITOR}, a.marked_at AS checked_in_at
    FROM membership m
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.person_id = m.person_id
    LEFT JOIN attendance a
           ON a.session_id = CAST(:session AS uuid) AND a.membership_id = m.id
    WHERE m.person_id IN ({{matching}})
      AND (a.membership_id IS NOT NULL
           OR (m.status IN {ON_ROSTER}
               AND (pl.program_id IS NULL OR pl.program_id = :program)))
    ORDER BY m.person_id, a.membership_id IS NOT NULL DESC,
             array_position(ARRAY{list(ON_ROSTER)}, m.status), m.created_at DESC,
             m.started_at DESC
) found
ORDER BY lower(name), person_id
LIMIT {SEARCH_LIMIT}
"""

DAY_SESSION = """
    SELECT id, cancelled_at IS NOT NULL AS cancelled FROM session
    WHERE class_type_id = :type AND open_day = :day
"""

# Nothing if another check-in made it first; the caller reads theirs.
NEW_DAY_SESSION = """
    INSERT INTO session (gym_id, class_type_id, starts_at, coach_id, open_day)
    VALUES (current_setting('app.gym_id')::uuid, :type, now(), :coach, :day)
    ON CONFLICT (class_type_id, open_day) WHERE open_day IS NOT NULL DO NOTHING
"""


async def _type(session: AsyncSession, class_type_id: uuid.UUID) -> Any:
    row = (
        await session.execute(text(f"{SELECT_TYPE} AND c.id = :id"), {"id": class_type_id})
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    return row


async def _day_session(session: AsyncSession, class_type_id: uuid.UUID, day: date) -> Any:
    return (
        await session.execute(text(DAY_SESSION), {"type": class_type_id, "day": day})
    ).one_or_none()


async def _door(session: AsyncSession, door: Any, day: date, zone: str) -> Door:
    held = await _day_session(session, door.class_type_id, day)
    arrivals = []
    if held is not None:
        rows = await session.execute(text(ARRIVALS), {"session": held.id})
        arrivals = [Arrival.model_validate(row, from_attributes=True) for row in rows]
    return Door(
        class_type_id=door.class_type_id,
        name=door.name,
        program_id=door.program_id,
        program_name=door.program_name,
        credit_cost=door.credit_cost,
        date=day,
        timezone=zone,
        session_id=None if held is None else held.id,
        cancelled=held is not None and held.cancelled,
        arrivals=arrivals,
    )


@router.get("")
async def list_doors(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: StaffSession
) -> list[Door]:
    """The gym's active open-access class types, by program and name, each with today."""
    zone = await gym_timezone(session, tenant)
    day = gym_today(zone)
    rows = await session.execute(
        text(f"{SELECT_TYPE} AND c.active ORDER BY lower(p.name), lower(c.name), c.created_at")
    )
    return [await _door(session, row, day, zone) for row in rows.all()]


@router.get("/{class_type_id}/search")
async def search(
    class_type_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[Candidate]:
    """Who `q` finds that may be checked in, by name; nothing for a blank `q`."""
    door = await _type(session, class_type_id)
    if not q.strip():
        return []
    zone = await gym_timezone(session, tenant)
    held = await _day_session(session, class_type_id, gym_today(zone))
    matching, params = people_matching(q.strip())
    rows = await session.execute(
        text(CANDIDATES.format(matching=matching)),
        {**params, "session": None if held is None else held.id, "program": door.program_id},
    )
    return [Candidate.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "/{class_type_id}",
    responses={status.HTTP_409_CONFLICT: {"description": "the day's session is cancelled"}},
)
async def check_in(
    class_type_id: uuid.UUID,
    body: CheckIn,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Door:
    """Check the membership in at today's session, making it if this is the first; the
    day as it then stands. Checking in someone already in changes nothing."""
    door = await _type(session, class_type_id)
    if not door.active:
        raise RequestValidationError(
            [
                {
                    "type": "inactive_class_type",
                    "msg": "the class type is deactivated",
                    "loc": ("path", "class_type_id"),
                }
            ]
        )
    zone = await gym_timezone(session, tenant)
    day = gym_today(zone)
    params = {"type": class_type_id, "day": day}
    await session.execute(text(NEW_DAY_SESSION), {**params, "coach": tenant.person_id})
    held = await class_of(session, (await _day_session(session, class_type_id, day)).id, lock=True)
    require_open(held)
    await mark_present(session, held, body.membership_id, tenant.person_id)
    return await _door(session, door, day, zone)


@router.delete("/{class_type_id}/{membership_id}")
async def undo_check_in(
    class_type_id: uuid.UUID,
    membership_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Door:
    """Undo today's check-in of the membership, giving back what it took; the day as it
    then stands. Undoing one that is not there changes nothing."""
    door = await _type(session, class_type_id)
    zone = await gym_timezone(session, tenant)
    day = gym_today(zone)
    found = await _day_session(session, class_type_id, day)
    if found is not None:
        await unmark(session, await class_of(session, found.id, lock=True), membership_id)
    return await _door(session, door, day, zone)
