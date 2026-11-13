"""The current gym's memberships: start one, change its plan, freeze or cancel it,
read them.

A membership starts on a calendar day in the gym's timezone, and its anchor day and
`current_period_end` follow from its plan (`app.domain.membership.start`). A plan
change waits for the next period: it is stored as pending, from the first day not yet
paid for or billed, and billing applies it then (migration 0009). Proration is v2.
`GET .../plan-change` quotes a change before it is saved: that day, and the first
period the new plan bills from it (#249).
A freeze (#26) runs from its first day until the day it ends, with a reason, and moves
the due date past the frozen days as it starts: the paid-through date, the billing
periods not yet started and a pending plan change all move by them, and the nightly
`freezes` job returns the membership to Active on the day it ends. One from a later day
is booked, and the job starts it then (#115). A freeze running can end early or end on
another day, and the due date moves again by the days it no longer lasts or gains; one
booked can change its end, or be called off. Cancelling is terminal and
needs a reason; the database refuses any later change to a cancelled row but its void.
Voiding (#256) is for a plan started by mistake: it ends as of its start and its
unpaid charges are voided (`app.api.ledger.void_period`), a cancelled one's too.

A membership starting is billed at once, what the nightly job would bill it tonight
(`bill_now`), so a member who pays at the desk on their first day can be recorded
then (#196). A recurring plan assigned to someone whose plan lapsed with days billed past
the day asked for starts the day after the last of them instead: those days are billed
once, on the lapsed plan, and what it owes stays its own ("Deuda anterior"). `GET
.../start` quotes that day and the debt before the form saves (#271).
Starting one emails the member, or their guardian, a welcome: how to pay and how to
upload a proof, with their first sign-in link to the student page; unless the request
says `send_welcome: false` (#249). Nobody who has left
the gym (dado de baja, #157) starts one, by any path: `insert_membership` refuses them
until they are reactivated.

Any staff role may read memberships; only an owner or admin may start, change or
freeze or cancel one, since that sets what a member is charged. Members may not use it at all.
"""

import logging
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entries import CURRENT_PERSON
from app.api.ledger import period_money, void_period
from app.contacts import Contact, contact_for
from app.db import driver_connection
from app.domain import billing
from app.domain import membership as domain
from app.domain.dates import gym_today, start_of_local_day
from app.domain.errors import InvalidTransition
from app.domain.membership import (
    MAX_FREEZE_DAYS,
    RECURRING,
    MembershipStatus,
    PlanKind,
    PlanTerms,
)
from app.jobs.billing import billable_membership, write_billing
from app.notices import WELCOME, Notice, Notices, get_notices
from app.roles import AdminSession, SeesMoney, StaffSession
from app.schemas.ledger import VoidConflict
from app.schemas.memberships import (
    Cancellation,
    Freeze,
    FreezeCreate,
    FreezeEdit,
    HasLeft,
    HasLeftConflict,
    Membership,
    MembershipCreate,
    MembershipForCoach,
    MembershipStart,
    PendingPlanChange,
    PlanChange,
    PlanChangeQuote,
    StartQuote,
    for_coach,
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
           m.cancel_reason, m.cancelled_at, m.voided_at, m.void_reason, m.created_at,
           fz.id AS freeze_id, fz.from_date AS freeze_from, fz.to_date AS freeze_to,
           fz.reason AS freeze_reason, fz.started AS freeze_started
    FROM membership m
    JOIN gym g ON g.id = m.gym_id
    JOIN plan pl ON pl.id = m.plan_id
    LEFT JOIN plan np ON np.id = m.next_plan_id
    LEFT JOIN LATERAL (
        SELECT f.id, f.from_date, f.to_date, f.reason, f.started FROM membership_freeze f
        WHERE f.membership_id = m.id AND f.to_date > f.from_date
        ORDER BY f.from_date DESC LIMIT 1
    ) fz ON (m.status = 'frozen' AND fz.started) OR (m.status = 'active' AND NOT fz.started)
"""

SELECT_PLAN = """
    SELECT kind, anchor, credits, credit_expiry_days, active FROM plan WHERE id = :id
"""


def membership_of(row: Any) -> Membership:
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
    freeze_started = fields.pop("freeze_started")
    freeze = None
    if freeze_id is not None:
        freeze = Freeze(
            id=freeze_id,
            from_date=freeze_from,
            to_date=freeze_to,
            reason=freeze_reason,
            started=freeze_started,
        )
    return Membership(**fields, next_plan=pending, freeze=freeze)


async def _get(session: AsyncSession, membership_id: uuid.UUID) -> Membership:
    sql = f"{SELECT_MEMBERSHIP} WHERE m.id = :id"
    row = (await session.execute(text(sql), {"id": membership_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return membership_of(row)


SELECT_STATE = (
    "SELECT pl.kind, m.status, m.current_period_end, m.credits_remaining,"
    " m.anchor_day, m.plan_id FROM membership m JOIN plan pl ON pl.id = m.plan_id"
    " WHERE m.id = :id"
)


async def _locked(
    session: AsyncSession, membership_id: uuid.UUID, *, lock: bool = True
) -> tuple[domain.Membership, uuid.UUID]:
    """The membership's state and plan, its row locked until the request's transaction
    ends, so a concurrent change waits and then sees this one's result; read only,
    with `lock=False`."""
    sql = f"{SELECT_STATE} FOR UPDATE OF m" if lock else SELECT_STATE
    row = (await session.execute(text(sql), {"id": membership_id})).one_or_none()
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


class PersonHasLeft(Exception):
    """`insert_membership` was asked to start someone who has left the gym."""


HAS_LEFT = HTTPException(status.HTTP_409_CONFLICT, HasLeftConflict().model_dump())


async def insert_membership(
    session: AsyncSession,
    person_id: uuid.UUID,
    plan_id: uuid.UUID,
    started: domain.Membership,
    started_at: datetime,
) -> uuid.UUID:
    """Write `started`, a new membership of `person_id` on `plan_id`, in the current gym.
    Raises `PersonHasLeft` for someone who has left it: their record is read `FOR SHARE`,
    so a baja and a new membership take turns."""
    left_on = await session.scalar(
        text("SELECT left_on FROM gym_person WHERE person_id = :id FOR SHARE"), {"id": person_id}
    )
    if left_on is not None:
        raise PersonHasLeft(person_id)
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


# The last day the person's lapsed plans have billed, their voided charges aside: a plan
# assigned again starts after it, so no day is billed twice (#271).
LAPSED_BILLED_THROUGH = text(
    """
    SELECT max(bp.period_end) FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    WHERE m.person_id = :person AND m.status = 'lapsed' AND m.voided_at IS NULL
      AND NOT EXISTS (
          SELECT FROM ledger_entry v WHERE v.billing_period_id = bp.id AND v.voids
      )
    """
)


async def _starts_on(
    session: AsyncSession, person_id: uuid.UUID, terms: PlanTerms, asked: date
) -> tuple[date, date | None]:
    """The day a plan on `terms` asked to start on `asked` starts, and the last day the
    person's lapsed plans billed when that moved it: a recurring one starts after it."""
    billed_through: date | None = await session.scalar(LAPSED_BILLED_THROUGH, {"person": person_id})
    if terms.kind not in RECURRING or billed_through is None or billed_through < asked:
        return asked, None
    return billed_through + timedelta(days=1), billed_through


async def start_membership(
    session: AsyncSession, tenant: Tenant, person_id: uuid.UUID, body: MembershipStart
) -> Membership:
    """Start `person_id`, someone in this gym, on `body`'s plan from its day, today in
    the gym's timezone when it has none, or after what a lapsed plan of theirs billed
    (`_starts_on`); a 422 for a plan this gym cannot start."""
    terms = await _plan_terms(session, body.plan_id)
    timezone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    started_on, _ = await _starts_on(
        session, person_id, terms, body.started_on or gym_today(timezone)
    )
    try:
        started = domain.start(terms, started_on)
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None

    try:
        membership_id = await insert_membership(
            session, person_id, body.plan_id, started, start_of_local_day(started_on, timezone)
        )
    except PersonHasLeft:
        raise HAS_LEFT from None
    await bill_now(session, membership_id, gym_today(timezone))
    return await _get(session, membership_id)


# The most periods a membership starting is billed in its request: a start back-dated
# years catches up the rest in the nightly job, which bills on after the latest period.
BILLED_AT_START = 24


async def bill_now(session: AsyncSession, membership_id: uuid.UUID, today: date) -> None:
    """Bill what the membership owes by `today` plus the job's lead time, as the nightly
    job would tonight, its first `BILLED_AT_START` periods at most: a member starting
    today can pay at the desk today (#196)."""
    conn = await driver_connection(session)
    billable = await billable_membership(conn, membership_id)
    if billable is None:  # just written, in this transaction
        raise NOT_FOUND
    owed = billing.due_periods(billable, today, limit=BILLED_AT_START)
    await write_billing(conn, membership_id, owed)


async def welcome_for(session: AsyncSession, tenant: Tenant, created: Membership) -> Notice | None:
    """The welcome to `created`, to the member or their guardian; `None` when there is no
    email to send it to."""
    return await welcome_to(session, tenant, created.person_id, created.plan_name)


async def welcome_to(
    session: AsyncSession, tenant: Tenant, person_id: uuid.UUID, plan_name: str | None
) -> Notice | None:
    """The welcome to `person_id`, or their guardian, on `plan_name`, or with none, that
    they are on the gym's roster (#246); `None` when there is no email to send it to."""
    contact = await contact_for(session, person_id)
    if contact is None or not contact.email:
        logger.info("welcome: no email to send it to", extra={"person_id": str(person_id)})
        return None
    gym = (
        await session.execute(
            text("SELECT name, settings -> 'bank_account' AS bank_account FROM gym WHERE id = :id"),
            {"id": tenant.gym_id},
        )
    ).one()
    dependent = None
    if contact.on_behalf_of:
        dependent = await session.scalar(
            text("SELECT name FROM gym_person WHERE person_id = :id"), {"id": person_id}
        )
    return welcome(
        contact,
        gym_id=tenant.gym_id,
        gym=gym.name,
        plan_name=plan_name,
        bank_account=gym.bank_account,
        dependent_name=dependent,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": HasLeft}},
)
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
    created = await start_membership(session, tenant, body.person_id, body)
    notice = await welcome_for(session, tenant, created) if body.send_welcome else None
    if notice is not None:
        # After the response, which is after the membership has committed.
        background.add_task(notices.send, notice)
    return created


def welcome(
    contact: Contact,
    *,
    gym_id: uuid.UUID,
    gym: str,
    plan_name: str | None,
    bank_account: dict[str, Any] | None,
    dependent_name: str | None,
) -> Notice:
    """The welcome: the plan, how to pay it and where to upload the proof; with no plan,
    that they are on the gym's roster, and the sign-in link alone."""
    assert contact.email is not None
    return Notice(
        WELCOME,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym_id,
        context={
            # Whom it is about, the dependent for a guardian: what the ficha reads back.
            "about_id": str(contact.on_behalf_of or contact.person_id),
            "name": contact.name,
            "gym": gym,
            "plan_name": plan_name,
            "bank_account": bank_account,
            "dependent_name": dependent_name,
        },
    )


# What the person's lapsed plans owe on periods due by `:today`: "Deuda anterior".
LAPSED_DEBT = text(
    f"""
    SELECT coalesce(sum(bp.amount_due_clp - coalesce(paid.amount, 0)), 0)::bigint
    FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    LEFT JOIN LATERAL (
        SELECT sum({billing.settled_amount("e")}) AS amount FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = 'validated'
          AND e.kind IN ('payment', 'adjustment', 'refund')
    ) paid ON true
    WHERE m.person_id = :person AND m.status = 'lapsed' AND m.voided_at IS NULL
      AND bp.due_date <= :today AND bp.amount_due_clp > coalesce(paid.amount, 0)
    """
)


@router.get("/start")
async def start_quote(
    person_id: uuid.UUID,
    plan_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    started_on: date | None = None,
) -> StartQuote:
    """What `POST /api/memberships` would start, saving nothing (#271): the day the plan
    starts, after the last day a lapsed plan billed when that moves it, and what the
    lapsed plans still owe, for "Asignar plan" to warn of before it saves. Someone not in
    this gym is a 404."""
    known = await session.scalar(
        text("SELECT true FROM gym_person WHERE person_id = :id"), {"id": person_id}
    )
    if not known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "person not found")
    terms = await _plan_terms(session, plan_id)
    today = await _gym_today(session, tenant)
    starts_on, billed_through = await _starts_on(session, person_id, terms, started_on or today)
    debt = await session.scalar(LAPSED_DEBT, {"person": person_id, "today": today})
    return StartQuote(starts_on=starts_on, billed_through=billed_through, debt_clp=debt or 0)


@router.get("")
async def list_memberships(
    person_id: uuid.UUID, session: StaffSession, money: SeesMoney
) -> list[Membership] | list[MembershipForCoach]:
    """A person's memberships in this gym, their current one first (`current_first`,
    #271), then the latest created; a coach's without discounts."""
    result = await session.execute(
        text(f"{SELECT_MEMBERSHIP} WHERE m.person_id = :id ORDER BY {domain.current_first('m')}"),
        {"id": person_id},
    )
    memberships = [membership_of(row) for row in result]
    return memberships if money else [for_coach(m) for m in memberships]


@router.get("/{membership_id}")
async def get_membership(
    membership_id: uuid.UUID, session: StaffSession, money: SeesMoney
) -> Membership | MembershipForCoach:
    membership = await _get(session, membership_id)
    return membership if money else for_coach(membership)


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
    starts_on = await _change_starts(session, membership_id, current, terms.kind)
    await session.execute(
        text("UPDATE membership SET next_plan_id = :plan, next_plan_from = :from WHERE id = :id"),
        {"plan": body.plan_id, "from": starts_on, "id": membership_id},
    )
    return await _get(session, membership_id)


async def _change_starts(
    session: AsyncSession, membership_id: uuid.UUID, current: domain.Membership, to: PlanKind
) -> date:
    """The day a change of `current` to a plan of kind `to` takes effect: a 409 for a
    membership that cannot change plan, a 422 for a plan it cannot change to."""
    billed_through = await session.scalar(
        text("SELECT max(period_end) FROM billing_period WHERE membership_id = :id"),
        {"id": membership_id},
    )
    try:
        return domain.plan_change_starts(current, to, billed_through=billed_through)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None


@router.get("/{membership_id}/plan-change")
async def plan_change_quote(
    membership_id: uuid.UUID, plan_id: uuid.UUID, session: AdminSession
) -> PlanChangeQuote:
    """What `POST .../plan-change` to `plan_id` would do, saving nothing (#249): the day
    it takes effect and the first period the new plan bills from it, as the nightly job
    will bill it. Refused as that request would be, and for the plan it is on."""
    current, current_plan = await _locked(session, membership_id, lock=False)
    if current.status is MembershipStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "a cancelled membership cannot change plan")
    if plan_id == current_plan:
        raise HTTPException(status.HTTP_409_CONFLICT, "the membership is on this plan")
    terms = await _plan_terms(session, plan_id)
    starts_on = await _change_starts(session, membership_id, current, terms.kind)
    row = (
        await session.execute(
            text(
                "SELECT pl.price_clp, pl.period_months, m.discount_pct"
                " FROM plan pl, membership m WHERE pl.id = :plan AND m.id = :id"
            ),
            {"plan": plan_id, "id": membership_id},
        )
    ).one()
    try:
        first = billing.first_period_after_change(
            billing.Plan(terms, row.price_clp, row.period_months), starts_on, row.discount_pct
        )
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None
    return PlanChangeQuote(
        starts_on=first.period_start,
        period_end=first.period_end,
        amount_due_clp=first.amount_due_clp,
    )


# A freeze moves the billing periods from its first day on (migration 0027), and with
# them a pending plan change, which waits for the first day not yet billed.
SHIFT_PERIODS = text("SELECT shift_billing_periods(:id, :from, CAST(:days AS integer))")

MOVE_MEMBERSHIP = text(
    "UPDATE membership SET status = :status, current_period_end = :end, anchor_day = :anchor,"
    " next_plan_from = next_plan_from + CAST(:days AS integer) WHERE id = :id"
)

INSERT_FREEZE = text(
    "INSERT INTO membership_freeze"
    " (gym_id, membership_id, from_date, to_date, reason, created_by, started)"
    " VALUES (current_setting('app.gym_id')::uuid, :id, :from, :to, :reason, :by, :started)"
)

# A plan event a request writes, with whose request it was. One per membership, kind
# and day, deliberately: a freeze ended, frozen again and ended again the same day keeps
# its first `unfrozen` event, so the member is told once and `created_by` is the first
# to end it.
INSERT_EVENT = text(
    "INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :id, :kind, :on, :by)"
    " ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING"
)

# The membership's latest freeze of a day or more, locked.
LATEST_FREEZE = text(
    "SELECT id, from_date, to_date, started FROM membership_freeze"
    " WHERE membership_id = :id AND to_date > from_date"
    " ORDER BY from_date DESC LIMIT 1 FOR UPDATE"
)

UPDATE_FREEZE = text(
    "UPDATE membership_freeze SET to_date = :to, reason = coalesce(:reason, reason) WHERE id = :id"
)

# A freeze booked ahead, called off: it ends on its first day, no day frozen.
CALL_OFF_BOOKED = text(
    "UPDATE membership_freeze SET to_date = from_date"
    " WHERE membership_id = :id AND NOT started AND to_date > from_date"
)

NO_FREEZE = HTTPException(
    status.HTTP_409_CONFLICT, "the membership has no freeze running or booked"
)


async def _gym_today(session: AsyncSession, tenant: Tenant) -> date:
    timezone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(timezone)


async def _current_freeze(
    session: AsyncSession, membership_id: uuid.UUID, current: domain.Membership
) -> tuple[domain.Membership, Any]:
    """The freeze a membership `_locked` is in while Frozen, or has booked ahead while
    Active, its row locked; `None` for neither. The membership comes back with the
    freeze's days when it is in it."""
    row = (await session.execute(LATEST_FREEZE, {"id": membership_id})).one_or_none()
    if row is None:
        return current, None
    if current.status is MembershipStatus.FROZEN and row.started:
        return replace(current, frozen_since=row.from_date, frozen_until=row.to_date), row
    if current.status is MembershipStatus.ACTIVE and not row.started:
        return current, row
    return current, None


async def _move(
    session: AsyncSession,
    membership_id: uuid.UUID,
    moved: domain.Membership,
    *,
    periods_from: date,
    days: int,
) -> None:
    """Write `moved`, its due date moved by `days`, and move its billing periods from
    `periods_from` on, and a pending plan change, by as many."""
    await session.execute(SHIFT_PERIODS, {"id": membership_id, "from": periods_from, "days": days})
    await session.execute(
        MOVE_MEMBERSHIP,
        {
            "id": membership_id,
            "status": moved.status.value,
            "end": moved.current_period_end,
            "anchor": moved.anchor_day,
            "days": days,
        },
    )


@router.post("/{membership_id}/freeze")
async def freeze_membership(
    membership_id: uuid.UUID,
    body: FreezeCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Membership:
    """Frozen from `from_date`, in the gym's timezone, until `to_date`. One from today
    starts at once, with a `frozen` plan event for the plan-event emails; one from a
    later day is booked, and the `freezes` job starts it on that day. A membership with
    a freeze booked takes no other until it has run."""
    return await freeze(session, tenant, membership_id, body)


async def freeze(
    session: AsyncSession, tenant: Tenant, membership_id: uuid.UUID, body: FreezeCreate
) -> Membership:
    """`freeze_membership`'s work, for a request that freezes a membership another way:
    a freeze request approved (#270). Refusals are the endpoint's, as HTTP errors."""
    current, _ = await _locked(session, membership_id)
    today = await _gym_today(session, tenant)
    from_date = body.from_date or today
    if from_date < today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "a freeze starts today at the earliest"
        )
    if (from_date - today).days > MAX_FREEZE_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"a freeze starts within {MAX_FREEZE_DAYS} days of today",
        )
    billed_before = await session.scalar(
        text(
            "SELECT max(period_end) FROM billing_period"
            " WHERE membership_id = :id AND period_start < :from"
        ),
        {"id": membership_id, "from": from_date},
    )
    try:
        frozen = domain.freeze(current, from_date, body.to_date, billed_through=billed_before)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None
    _, booked = await _current_freeze(session, membership_id, current)
    if booked is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "the membership has a freeze booked")

    starts_now = from_date == today
    if starts_now:
        days = (body.to_date - today).days
        await _move(session, membership_id, frozen, periods_from=today, days=days)
        await session.execute(
            INSERT_EVENT,
            {"id": membership_id, "kind": "frozen", "on": today, "by": tenant.person_id},
        )
    await session.execute(
        INSERT_FREEZE,
        {
            "id": membership_id,
            "from": from_date,
            "to": body.to_date,
            "reason": body.reason,
            "by": tenant.person_id,
            "started": starts_now,
        },
    )
    return await _get(session, membership_id)


@router.patch("/{membership_id}/freeze")
async def edit_freeze(
    membership_id: uuid.UUID,
    body: FreezeEdit,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Membership:
    """A new end or reason for the freeze running or booked. A running one ends after
    today (ending it today is `end`), and the due date moves by the days it gains or
    loses, as the freeze moved it as it started."""
    current, _ = await _locked(session, membership_id)
    current, row = await _current_freeze(session, membership_id, current)
    if row is None:
        raise NO_FREEZE
    to_date = body.to_date or row.to_date
    try:
        if not row.started:
            domain.freeze_days(row.from_date, to_date)
        elif body.to_date is not None:
            if to_date <= await _gym_today(session, tenant):
                raise ValueError("a running freeze ends after today; end it to end it today")
            moved = domain.move_freeze_end(current, to_date)
            days = (to_date - row.to_date).days
            await _move(session, membership_id, moved, periods_from=row.from_date, days=days)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None
    await session.execute(UPDATE_FREEZE, {"id": row.id, "to": to_date, "reason": body.reason})
    return await _get(session, membership_id)


@router.post("/{membership_id}/freeze/end")
async def end_freeze(
    membership_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Membership:
    """The freeze ends today: a running one returns the membership to Active, its due
    date moved back by the days it no longer lasts, with an `unfrozen` plan event
    recording whose request ended it; a booked one is called off."""
    current, _ = await _locked(session, membership_id)
    current, row = await _current_freeze(session, membership_id, current)
    if row is None:
        raise NO_FREEZE
    if not row.started:
        await session.execute(CALL_OFF_BOOKED, {"id": membership_id})
        return await _get(session, membership_id)

    today = await _gym_today(session, tenant)
    try:
        ended = domain.end_freeze(current, today)
    except InvalidTransition as error:
        raise _conflict(error) from None
    except (ValueError, OverflowError) as error:
        raise _unprocessable(error) from None
    ends_on = min(row.to_date, today)
    days = (ends_on - row.to_date).days
    await _move(session, membership_id, ended, periods_from=row.from_date, days=days)
    await session.execute(UPDATE_FREEZE, {"id": row.id, "to": ends_on, "reason": None})
    await session.execute(
        INSERT_EVENT,
        {"id": membership_id, "kind": "unfrozen", "on": today, "by": tenant.person_id},
    )
    return await _get(session, membership_id)


@router.post("/{membership_id}/cancel")
async def cancel_membership(
    membership_id: uuid.UUID, body: Cancellation, session: AdminSession
) -> Membership:
    """Terminal: a pending plan change goes with it, and a freeze booked ahead."""
    current, _ = await _locked(session, membership_id)
    try:
        cancelled = domain.cancel(current, body.reason)
    except InvalidTransition as error:
        raise _conflict(error) from None
    await session.execute(CALL_OFF_BOOKED, {"id": membership_id})
    await session.execute(
        text(
            "UPDATE membership SET status = :status, cancel_reason = :reason,"
            " cancelled_at = now(), next_plan_id = NULL, next_plan_from = NULL"
            " WHERE id = :id"
        ),
        {"status": cancelled.status.value, "reason": cancelled.cancel_reason, "id": membership_id},
    )
    return await _get(session, membership_id)


# Every period of the membership that still owes, oldest first: what a void voids.
OWING_PERIODS = text(
    f"""
    SELECT bp.id FROM billing_period bp
    WHERE bp.membership_id = :id AND bp.amount_due_clp > (
        SELECT coalesce(sum({billing.settled_amount("e")}), 0) FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = 'validated'
          AND e.kind IN ('payment', 'adjustment', 'refund')
    )
    ORDER BY bp.period_start, bp.id
    """
)

LOCK_FOR_VOID = text("SELECT status, voided_at FROM membership WHERE id = :id FOR UPDATE")

# Ended as of its start, as if it had never run; a running freeze ends today.
VOID_LIVE = text(
    "UPDATE membership SET status = 'cancelled', cancel_reason = :reason,"
    " cancelled_at = started_at, next_plan_id = NULL, next_plan_from = NULL,"
    f" voided_at = now(), voided_by = {CURRENT_PERSON}, void_reason = :reason"
    " WHERE id = :id"
)

# A cancelled membership keeps how it ended; it is only marked voided (0044).
VOID_CANCELLED = text(
    f"UPDATE membership SET voided_at = now(), voided_by = {CURRENT_PERSON},"
    " void_reason = :reason WHERE id = :id"
)

END_RUNNING_FREEZE = text(
    "UPDATE membership_freeze SET to_date = greatest(from_date, :today)"
    " WHERE membership_id = :id AND started AND to_date > :today"
)

ALREADY_VOIDED = HTTPException(status.HTTP_409_CONFLICT, "the membership is voided already")


@router.post(
    "/{membership_id}/void",
    responses={status.HTTP_409_CONFLICT: {"model": VoidConflict}},
)
async def void_membership(
    membership_id: uuid.UUID,
    body: Cancellation,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Membership:
    """Anular un plan started by mistake (#256): it ends as of its start, every unpaid
    charge on it is voided with `reason`, and it bills no more. Unlike cancelling, which
    ends a real plan from a day and keeps what was owed. Refused, writing nothing, while
    any of its periods has money on it (`period_money`); a cancelled one may still be
    voided, keeping how it ended."""
    found = (await session.execute(LOCK_FOR_VOID, {"id": membership_id})).one_or_none()
    if found is None:
        raise NOT_FOUND
    if found.voided_at is not None:
        raise ALREADY_VOIDED
    periods = [row.id for row in await session.execute(OWING_PERIODS, {"id": membership_id})]
    every_period = await session.execute(
        text("SELECT id FROM billing_period WHERE membership_id = :id ORDER BY period_start, id"),
        {"id": membership_id},
    )
    for row in every_period.all():
        refused = await period_money(session, row.id)
        if refused is not None:
            raise refused
    for period_id in periods:
        await void_period(session, membership_id, period_id, body.reason)
    params = {"id": membership_id, "reason": body.reason}
    if found.status == MembershipStatus.CANCELLED.value:
        await session.execute(VOID_CANCELLED, params)
    else:
        await session.execute(CALL_OFF_BOOKED, {"id": membership_id})
        today = await _gym_today(session, tenant)
        await session.execute(END_RUNNING_FREEZE, {"id": membership_id, "today": today})
        await session.execute(VOID_LIVE, params)
    return await _get(session, membership_id)
