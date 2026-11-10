"""The current gym's memberships: start one, change its plan, freeze or cancel it,
read them.

A membership starts on a calendar day in the gym's timezone, and its anchor day and
`current_period_end` follow from its plan (`app.domain.membership.start`). A plan
change waits for the next period: it is stored as pending, from the first day not yet
paid for or billed, and billing applies it then (migration 0009). Proration is v2.
A freeze (#26) runs from today until the day it ends, with a reason, and moves the
due date past the frozen days as it starts: the paid-through date, the billing periods
not yet started and a pending plan change all move by them, and the nightly `freezes`
job returns the membership to Active on the day it ends. Cancelling is terminal and
needs a reason; the database refuses any later change to a cancelled row.

Starting one emails the member, or their guardian, a welcome: how to pay and how to
upload a proof, with their first sign-in link to the student page.

Any staff role may read memberships; only an owner or admin may start, change or
freeze or cancel one, since that sets what a member is charged. Members may not use it at all.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts import Contact, contact_for
from app.domain import membership as domain
from app.domain.dates import gym_today, start_of_local_day
from app.domain.errors import InvalidTransition
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.notices import WELCOME, Notice, Notices, get_notices
from app.roles import AdminSession, StaffSession
from app.schemas.memberships import (
    Cancellation,
    Freeze,
    FreezeCreate,
    Membership,
    MembershipCreate,
    PendingPlanChange,
    PlanChange,
)
from app.tenancy import Tenant, current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memberships", tags=["memberships"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "membership not found")

# RLS keeps every table to the current gym.
SELECT_MEMBERSHIP = """
    SELECT m.id, m.person_id, m.plan_id, pl.name AS plan_name, pl.kind AS plan_kind,
           m.status, m.anchor_day, (m.started_at AT TIME ZONE g.timezone)::date AS started_on,
           m.current_period_end, m.credits_remaining, m.discount_pct,
           m.next_plan_id, np.name AS next_plan_name, m.next_plan_from,
           m.cancel_reason, m.cancelled_at, m.created_at,
           fz.id AS freeze_id, fz.from_date AS freeze_from, fz.to_date AS freeze_to,
           fz.reason AS freeze_reason
    FROM membership m
    JOIN gym g ON g.id = m.gym_id
    JOIN plan pl ON pl.id = m.plan_id
    LEFT JOIN plan np ON np.id = m.next_plan_id
    LEFT JOIN LATERAL (
        SELECT f.id, f.from_date, f.to_date, f.reason FROM membership_freeze f
        WHERE f.membership_id = m.id AND m.status = 'frozen'
        ORDER BY f.from_date DESC LIMIT 1
    ) fz ON true
"""

SELECT_PLAN = """
    SELECT kind, anchor, credits, credit_expiry_days, active FROM plan WHERE id = :id
"""


def _membership(row: Any) -> Membership:
    fields = dict(row._mapping)
    next_plan_id = fields.pop("next_plan_id")
    next_plan_name = fields.pop("next_plan_name")
    next_plan_from = fields.pop("next_plan_from")
    pending = None
    if next_plan_id is not None:
        pending = PendingPlanChange(
            plan_id=next_plan_id, plan_name=next_plan_name, starts_on=next_plan_from
        )
    freeze_id = fields.pop("freeze_id")
    freeze_from = fields.pop("freeze_from")
    freeze_to = fields.pop("freeze_to")
    freeze_reason = fields.pop("freeze_reason")
    freeze = None
    if freeze_id is not None:
        freeze = Freeze(
            id=freeze_id, from_date=freeze_from, to_date=freeze_to, reason=freeze_reason
        )
    return Membership(**fields, next_plan=pending, freeze=freeze)


async def _get(session: AsyncSession, membership_id: uuid.UUID) -> Membership:
    sql = f"{SELECT_MEMBERSHIP} WHERE m.id = :id"
    row = (await session.execute(text(sql), {"id": membership_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return _membership(row)


async def _locked(
    session: AsyncSession, membership_id: uuid.UUID
) -> tuple[domain.Membership, uuid.UUID]:
    """The membership's state and plan, its row locked until the request's transaction
    ends, so a concurrent change waits and then sees this one's result."""
    row = (
        await session.execute(
            text(
                "SELECT pl.kind, m.status, m.current_period_end, m.credits_remaining,"
                " m.anchor_day, m.plan_id"
                " FROM membership m JOIN plan pl ON pl.id = m.plan_id"
                " WHERE m.id = :id FOR UPDATE OF m"
            ),
            {"id": membership_id},
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    state = domain.Membership(
        PlanKind(row.kind),
        MembershipStatus(row.status),
        current_period_end=row.current_period_end,
        credits_remaining=row.credits_remaining,
        anchor_day=row.anchor_day,
    )
    return state, row.plan_id


async def _plan_terms(session: AsyncSession, plan_id: uuid.UUID) -> PlanTerms:
    """An active plan's terms; a 422 for a plan this gym does not have or has deactivated."""
    row = (await session.execute(text(SELECT_PLAN), {"id": plan_id})).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "plan not found")
    if not row.active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "plan is deactivated")
    return PlanTerms(PlanKind(row.kind), row.anchor, row.credits, row.credit_expiry_days)


def _conflict(error: InvalidTransition) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(error))


# OverflowError: a date past the edge of `date`'s range, which the schema keeps far off.
def _unprocessable(error: ValueError | OverflowError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))


async def insert_membership(
    session: AsyncSession,
    person_id: uuid.UUID,
    plan_id: uuid.UUID,
    started: domain.Membership,
    started_at: datetime,
) -> uuid.UUID:
    """Write `started`, a new membership of `person_id` on `plan_id`, in the current gym."""
    result = await session.execute(
        text(
            "INSERT INTO membership (gym_id, person_id, plan_id, status, anchor_day,"
            " started_at, current_period_end, credits_remaining)"
            " VALUES (current_setting('app.gym_id')::uuid, :person_id, :plan_id, :status,"
            " :anchor_day, :started_at, :current_period_end, :credits_remaining)"
            " RETURNING id"
        ),
        {
            "person_id": person_id,
            "plan_id": plan_id,
            "status": started.status.value,
            "anchor_day": started.anchor_day,
            "started_at": started_at,
            "current_period_end": started.current_period_end,
            "credits_remaining": started.credits_remaining,
        },
    )
    membership_id: uuid.UUID = result.scalar_one()
    return membership_id


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_membership(
    body: MembershipCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Membership:
    known = await session.scalar(
        text("SELECT true FROM gym_person WHERE person_id = :id"), {"id": body.person_id}
    )
    if not known:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "person not found")
    terms = await _plan_terms(session, body.plan_id)
    timezone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    started_on = body.started_on or gym_today(timezone)
    try:
        started = domain.start(terms, started_on)
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None

    membership_id = await insert_membership(
        session, body.person_id, body.plan_id, started, start_of_local_day(started_on, timezone)
    )
    created = await _get(session, membership_id)

    contact = await contact_for(session, created.person_id)
    if contact is None or not contact.email:
        logger.info("welcome: no email to send it to", extra={"membership_id": str(created.id)})
        return created
    gym = (
        await session.execute(
            text("SELECT name, settings -> 'bank_account' AS bank_account FROM gym WHERE id = :id"),
            {"id": tenant.gym_id},
        )
    ).one()
    dependent = None
    if contact.on_behalf_of:
        dependent = await session.scalar(
            text("SELECT name FROM gym_person WHERE person_id = :id"), {"id": created.person_id}
        )
    notice = welcome(
        contact,
        gym_id=tenant.gym_id,
        gym=gym.name,
        plan_name=created.plan_name,
        bank_account=gym.bank_account,
        dependent_name=dependent,
    )
    # After the response, which is after the membership has committed.
    background.add_task(notices.send, notice)
    return created


def welcome(
    contact: Contact,
    *,
    gym_id: uuid.UUID,
    gym: str,
    plan_name: str,
    bank_account: dict[str, Any] | None,
    dependent_name: str | None,
) -> Notice:
    """The welcome: the plan, how to pay it and where to upload the proof."""
    assert contact.email is not None
    return Notice(
        WELCOME,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym_id,
        context={
            "name": contact.name,
            "gym": gym,
            "plan_name": plan_name,
            "bank_account": bank_account,
            "dependent_name": dependent_name,
        },
    )


@router.get("")
async def list_memberships(person_id: uuid.UUID, session: StaffSession) -> list[Membership]:
    """A person's memberships in this gym, latest first."""
    result = await session.execute(
        text(f"{SELECT_MEMBERSHIP} WHERE m.person_id = :id ORDER BY m.started_at DESC, m.id"),
        {"id": person_id},
    )
    return [_membership(row) for row in result]


@router.get("/{membership_id}")
async def get_membership(membership_id: uuid.UUID, session: StaffSession) -> Membership:
    return await _get(session, membership_id)


@router.post("/{membership_id}/plan-change")
async def change_plan(
    membership_id: uuid.UUID, body: PlanChange, session: AdminSession
) -> Membership:
    """Move to `plan_id` from the next period; the current plan withdraws the change."""
    current, plan_id = await _locked(session, membership_id)
    if current.status is MembershipStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "a cancelled membership cannot change plan")
    if body.plan_id == plan_id:
        await session.execute(
            text("UPDATE membership SET next_plan_id = NULL, next_plan_from = NULL WHERE id = :id"),
            {"id": membership_id},
        )
        return await _get(session, membership_id)

    terms = await _plan_terms(session, body.plan_id)
    billed_through = await session.scalar(
        text("SELECT max(period_end) FROM billing_period WHERE membership_id = :id"),
        {"id": membership_id},
    )
    try:
        starts_on = domain.plan_change_starts(current, terms.kind, billed_through=billed_through)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None
    await session.execute(
        text("UPDATE membership SET next_plan_id = :plan, next_plan_from = :from WHERE id = :id"),
        {"plan": body.plan_id, "from": starts_on, "id": membership_id},
    )
    return await _get(session, membership_id)


# The billing periods a freeze moves, latest first: each moves past the next one's start
# before that one moves, so no two share a start on the way.
PERIODS_FROM = text(
    "SELECT id FROM billing_period WHERE membership_id = :id AND period_start >= :from"
    " ORDER BY period_start DESC FOR UPDATE"
)

SHIFT_PERIOD = text(
    "UPDATE billing_period SET period_start = period_start + CAST(:days AS integer),"
    " period_end = period_end + CAST(:days AS integer),"
    " due_date = due_date + CAST(:days AS integer) WHERE id = :id"
)

# A pending plan change waits for the first day not yet billed, which moves by the
# frozen days with everything else.
FREEZE_MEMBERSHIP = text(
    "UPDATE membership SET status = :status, current_period_end = :end, anchor_day = :anchor,"
    " next_plan_from = next_plan_from + CAST(:days AS integer) WHERE id = :id"
)

INSERT_FREEZE = text(
    "INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :id, :from, :to, :reason, :by)"
)

INSERT_FROZEN_EVENT = text(
    "INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)"
    " VALUES (current_setting('app.gym_id')::uuid, :id, 'frozen', :on)"
    " ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING"
)


@router.post("/{membership_id}/freeze")
async def freeze_membership(
    membership_id: uuid.UUID,
    body: FreezeCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Membership:
    """Frozen from today, in the gym's timezone, until `to_date`; a `frozen` plan event
    is written with it, for the plan-event emails."""
    current, _ = await _locked(session, membership_id)
    timezone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    today = gym_today(timezone)
    billed_before = await session.scalar(
        text(
            "SELECT max(period_end) FROM billing_period"
            " WHERE membership_id = :id AND period_start < :from"
        ),
        {"id": membership_id, "from": today},
    )
    try:
        frozen = domain.freeze(current, today, body.to_date, billed_through=billed_before)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None

    days = (body.to_date - today).days
    for row in await session.execute(PERIODS_FROM, {"id": membership_id, "from": today}):
        await session.execute(SHIFT_PERIOD, {"id": row.id, "days": days})
    await session.execute(
        FREEZE_MEMBERSHIP,
        {
            "id": membership_id,
            "status": frozen.status.value,
            "end": frozen.current_period_end,
            "anchor": frozen.anchor_day,
            "days": days,
        },
    )
    await session.execute(
        INSERT_FREEZE,
        {
            "id": membership_id,
            "from": today,
            "to": body.to_date,
            "reason": body.reason,
            "by": tenant.person_id,
        },
    )
    await session.execute(INSERT_FROZEN_EVENT, {"id": membership_id, "on": today})
    return await _get(session, membership_id)


@router.post("/{membership_id}/cancel")
async def cancel_membership(
    membership_id: uuid.UUID, body: Cancellation, session: AdminSession
) -> Membership:
    """Terminal: a pending plan change goes with it."""
    current, _ = await _locked(session, membership_id)
    try:
        cancelled = domain.cancel(current, body.reason)
    except InvalidTransition as error:
        raise _conflict(error) from None
    await session.execute(
        text(
            "UPDATE membership SET status = :status, cancel_reason = :reason,"
            " cancelled_at = now(), next_plan_id = NULL, next_plan_from = NULL"
            " WHERE id = :id"
        ),
        {"status": cancelled.status.value, "reason": cancelled.cancel_reason, "id": membership_id},
    )
    return await _get(session, membership_id)
