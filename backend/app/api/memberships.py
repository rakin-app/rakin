"""The current gym's memberships: start one, change its plan, cancel it, read them.

A membership starts on a calendar day in the gym's timezone, and its anchor day and
`current_period_end` follow from its plan (`app.domain.membership.start`). A plan
change waits for the next period: it is stored as pending, from the first day not yet
paid for or billed, and billing applies it then (migration 0009). Proration is v2.
Cancelling is terminal and needs a reason; the database refuses any later change to
a cancelled row.

Starting one emails the member, or their guardian, a welcome: how to pay and how to
upload a proof, with their first sign-in link to the student page.

Any staff role may read memberships; only an owner or admin may start, change or
cancel one, since that sets what a member is charged. Members may not use it at all.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.contacts import Contact, contact_for
from app.domain import membership as domain
from app.domain.dates import local_date, start_of_local_day
from app.domain.errors import InvalidTransition
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.notices import WELCOME, Notice, Notices, get_notices
from app.roles import AdminSession, StaffSession
from app.schemas.memberships import (
    Cancellation,
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
           m.cancel_reason, m.cancelled_at, m.created_at
    FROM membership m
    JOIN gym g ON g.id = m.gym_id
    JOIN plan pl ON pl.id = m.plan_id
    LEFT JOIN plan np ON np.id = m.next_plan_id
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
    return Membership(**fields, next_plan=pending)


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
    started_on = body.started_on or local_date(datetime.now(UTC), timezone)
    try:
        started = domain.start(terms, started_on)
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None

    result = await session.execute(
        text(
            "INSERT INTO membership (gym_id, person_id, plan_id, status, anchor_day,"
            " started_at, current_period_end, credits_remaining)"
            " VALUES (current_setting('app.gym_id')::uuid, :person_id, :plan_id, :status,"
            " :anchor_day, :started_at, :current_period_end, :credits_remaining)"
            " RETURNING id"
        ),
        {
            "person_id": body.person_id,
            "plan_id": body.plan_id,
            "status": started.status.value,
            "anchor_day": started.anchor_day,
            "started_at": start_of_local_day(started_on, timezone),
            "current_period_end": started.current_period_end,
            "credits_remaining": started.credits_remaining,
        },
    )
    created = await _get(session, result.scalar_one())

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
