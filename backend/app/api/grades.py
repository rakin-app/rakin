"""A person's ranks in the current gym: the promotion log, and awarding the next one.

A promotion names a rank and sub-rank of the gym's grading scheme by key, and is
checked against it when awarded; the labels are the scheme's when read
(`app.schemas.grades`). It attaches to the membership the person's ficha shows, their
latest one not cancelled, and their current rank is their latest award over every
membership here (migration 0016).

Awarding a rank that becomes the person's current one writes a `promoted` plan event
(0013) in the same transaction, for the plan-event emails (#54); recording an older
promotion, as when a gym enters a member's history, writes none.

Every staff role may read and award, coaches included, since they are who promote;
members may not. A member reads their own rank on the student page (`/api/me/page`).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.grading import stored_scheme
from app.api.people import NOT_FOUND, in_gym
from app.domain.dates import local_date
from app.roles import StaffSession
from app.schemas.grades import GradeAward, GradeEvent, Grading, Rank
from app.schemas.grading import GradingScheme
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/people", tags=["grading"])

# A person's promotions over every membership they hold here, newest first. RLS keeps
# every table to the current gym.
EVENTS = """
    SELECT ge.id, ge.rank_key, ge.sub_rank, ge.awarded_on, ge.note, ge.created_at,
           ab.name AS awarded_by_name
    FROM grade_event ge
    JOIN membership m ON m.id = ge.membership_id
    LEFT JOIN gym_person ab ON ab.gym_id = ge.gym_id AND ab.person_id = ge.awarded_by
    WHERE m.person_id = :person
    ORDER BY ge.awarded_on DESC, ge.created_at DESC, ge.id
"""

# The person's current rank: their latest promotion.
CURRENT = """
    SELECT ge.id, ge.rank_key, ge.sub_rank, ge.awarded_on
    FROM grade_event ge JOIN membership m ON m.id = ge.membership_id
    WHERE m.person_id = :person
    ORDER BY ge.awarded_on DESC, ge.created_at DESC, ge.id
    LIMIT 1
"""

# A promotion attaches to the membership the ficha shows (`SHOWN_MEMBERSHIP`), but
# never a cancelled one.
AWARDED_MEMBERSHIP = """
    SELECT id FROM membership
    WHERE person_id = :person AND status <> 'cancelled'
    ORDER BY started_at DESC, created_at DESC
    LIMIT 1
"""

INSERT_EVENT = """
    INSERT INTO grade_event (gym_id, membership_id, rank_key, sub_rank, awarded_on,
                             awarded_by, note)
    VALUES (:gym, :membership, :rank_key, :sub_rank, :awarded_on, :awarded_by, :note)
    RETURNING id
"""

# One `promoted` event per membership and day: a second award on the day is still one
# promotion to tell the member about.
PROMOTED = """
    INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)
    VALUES (:gym, :membership, 'promoted', :occurred_on)
    ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING
"""


def _refused(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": code})


def readable_scheme(settings: Any) -> GradingScheme:
    """The scheme to label ranks with. One stored before a change to the model reads as
    none, so a page still shows the ranks, by key, until an admin re-applies a preset."""
    try:
        return GradingScheme.from_settings(settings)
    except ValueError:
        return GradingScheme(ranks=[])


async def current_rank(
    session: AsyncSession, person_id: uuid.UUID, scheme: GradingScheme
) -> Rank | None:
    """The person's latest promotion in the current gym, labelled; `None` without one."""
    row = (await session.execute(text(CURRENT), {"person": person_id})).one_or_none()
    if row is None:
        return None
    return Rank.labelled(scheme, row.rank_key, row.sub_rank, row.awarded_on)


async def _grading(session: AsyncSession, person_id: uuid.UUID, scheme: GradingScheme) -> Grading:
    rows = await session.execute(text(EVENTS), {"person": person_id})
    events = [
        GradeEvent(
            **Rank.labelled(scheme, row.rank_key, row.sub_rank, row.awarded_on).model_dump(),
            id=row.id,
            awarded_by_name=row.awarded_by_name,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return Grading(
        current=Rank(**events[0].model_dump(include=set(Rank.model_fields))) if events else None,
        events=events,
    )


async def _gym(session: AsyncSession, gym_id: uuid.UUID) -> Any:
    return (
        await session.execute(
            text("SELECT timezone, settings FROM gym WHERE id = :id"), {"id": gym_id}
        )
    ).one()


@router.get("/{person_id}/grades")
async def get_grades(
    person_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Grading:
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    gym = await _gym(session, tenant.gym_id)
    return await _grading(session, person_id, readable_scheme(gym.settings))


@router.post(
    "/{person_id}/grades",
    status_code=status.HTTP_201_CREATED,
)
async def award_grade(
    person_id: uuid.UUID,
    body: GradeAward,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
) -> Grading:
    """Award a rank. 422 with a `code` for a rank or sub-rank the scheme does not have
    (`unknown_rank`, `unknown_sub_rank`), a missing sub-rank on a rank that has them
    (`sub_rank_required`) or a day after today (`awarded_in_future`); 409
    `no_membership` for a person with no membership here that is not cancelled."""
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    gym = await _gym(session, tenant.gym_id)
    scheme = stored_scheme(tenant.gym_id, gym.settings)

    rank = scheme.rank(body.rank_key)
    if rank is None:
        raise _refused("unknown_rank")
    if body.sub_rank is None:
        if rank.sub_ranks:
            raise _refused("sub_rank_required")
    elif all(s.key != body.sub_rank for s in rank.sub_ranks):
        raise _refused("unknown_sub_rank")
    today: date = local_date(datetime.now(UTC), str(gym.timezone))
    awarded_on = body.awarded_on or today
    if awarded_on > today:
        raise _refused("awarded_in_future")

    membership = await session.scalar(text(AWARDED_MEMBERSHIP), {"person": person_id})
    if membership is None:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_membership"})

    event = await session.scalar(
        text(INSERT_EVENT),
        {
            "gym": tenant.gym_id,
            "membership": membership,
            "rank_key": body.rank_key,
            "sub_rank": body.sub_rank,
            "awarded_on": awarded_on,
            "awarded_by": tenant.person_id,
            "note": body.note,
        },
    )
    latest = (await session.execute(text(CURRENT), {"person": person_id})).one()
    if latest.id == event:
        await session.execute(
            text(PROMOTED),
            {"gym": tenant.gym_id, "membership": membership, "occurred_on": awarded_on},
        )
    return await _grading(session, person_id, scheme)
