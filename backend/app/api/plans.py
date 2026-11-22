"""The current gym's plans: create, list, read, edit, deactivate.

Six kinds, each with its own parameters (`app.schemas.plans`). There is no delete: a
plan is deactivated with `PATCH {"active": false}`, and the database refuses a
`DELETE` from any role (migration 0007), since memberships and the ledger keep
pointing at it. A `program_id` must be one of the gym's programs, or it is a 422.

Any staff role may read the plans, coaches included, though a coach reads them without
their prices (#205); only an owner or admin may create or change one. Members may not
use it at all.

A monthly plan's anchor changed reaches only the members who join after, unless the
owner moves the members on it too (#547): `PATCH` with `move_members` moves each to the
day the new anchor gives it (the 1st, or the day it started) from its first period not
billed, which runs to the day before the new day at its prorated share of the price, and
records each move in the log. `GET /{id}/anchor-moves?anchor=` quotes the moves first.
No period already billed changes.

A fixed-period plan does not renew itself (#351). The owner copies it for the next
period, `POST /{id}/next-period`, and moves the members on its list
(`GET /{id}/memberships`) across in the same request: each gets a plan change to the
copy from the day after it is paid through, so the copy bills its period when it
falls due and the old plan bills nothing more.
"""

import uuid
from datetime import date
from typing import Annotated, Any, overload

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.corrections import record_audit
from app.api.memberships import change_starts, locked_membership
from app.api.programs import require_program
from app.db import driver_connection
from app.domain import billing
from app.domain import membership as memberships
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.jobs.billing import billables_on_plan
from app.permissions import (
    AdminSession,
    LedgerReadSession,
    Permission,
    SeesMoney,
    StaffSession,
    holds,
)
from app.schemas.plans import (
    COLUMNS,
    PLAN,
    PLAN_CREATE,
    Anchor,
    AnchorMove,
    FixedPeriodPlan,
    FixedPeriodPlanCreate,
    MonthlyPlan,
    NextPeriod,
    NextPeriodResult,
    Plan,
    PlanCreate,
    PlanForCoach,
    PlanMembership,
    PlanUpdate,
    for_coach,
    from_row,
    to_columns,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/plans", tags=["plans"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "plan not found")

# RLS on `plan` keeps every query to the current gym.
SELECT_PLAN = f"SELECT id, {', '.join(COLUMNS)}, active, created_at FROM plan"


def _plan(row: Any) -> Plan:
    return PLAN.validate_python(from_row(dict(row._mapping)))


async def _get(session: AsyncSession, plan_id: uuid.UUID, *, lock: bool = False) -> Plan:
    """The plan; with `lock`, its row locked until the request's transaction ends."""
    sql = f"{SELECT_PLAN} WHERE id = :id{' FOR UPDATE' if lock else ''}"
    row = (await session.execute(text(sql), {"id": plan_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return _plan(row)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanCreate, session: AdminSession) -> Plan:
    if body.program_id is not None:
        await require_program(session, body.program_id, "program_id")
    return await _insert(session, body)


@overload
async def _insert(session: AsyncSession, body: FixedPeriodPlanCreate) -> FixedPeriodPlan: ...
@overload
async def _insert(session: AsyncSession, body: PlanCreate) -> Plan: ...
async def _insert(session: AsyncSession, body: PlanCreate) -> Plan:
    """The new plan, of `body`'s kind."""
    columns = to_columns(body)
    result = await session.execute(
        text(
            f"INSERT INTO plan (gym_id, {', '.join(columns)})"
            f" VALUES (current_setting('app.gym_id')::uuid, {', '.join(f':{c}' for c in columns)})"
            " RETURNING id"
        ),
        columns,
    )
    return await _get(session, result.scalar_one())


@router.get("")
async def list_plans(
    session: StaffSession, money: SeesMoney, active: bool | None = None
) -> list[Plan] | list[PlanForCoach]:
    """Active plans first, then by name; `?active=true` for the ones a member can join."""
    where = "" if active is None else " WHERE active = :active"
    result = await session.execute(
        text(f"{SELECT_PLAN}{where} ORDER BY active DESC, name, created_at"), {"active": active}
    )
    plans = [_plan(row) for row in result]
    return plans if money else [for_coach(plan) for plan in plans]


@router.get("/{plan_id}")
async def get_plan(
    plan_id: uuid.UUID, session: StaffSession, money: SeesMoney
) -> Plan | PlanForCoach:
    plan = await _get(session, plan_id)
    return plan if money else for_coach(plan)


# Moving the members is a change of their billing (`money_write`), as a plan change is.
MOVE_IS_MONEY = HTTPException(status.HTTP_403_FORBIDDEN, "moving members needs money_write")
NOT_MONTHLY = HTTPException(status.HTTP_409_CONFLICT, "only a monthly plan bills on an anchor")


@router.patch("/{plan_id}")
async def update_plan(
    plan_id: uuid.UUID,
    body: PlanUpdate,
    session: AdminSession,
    tenant: Annotated[Tenant, Depends(current_tenant)],
) -> Plan:
    # Locked, so a concurrent edit waits and then merges into this one's result
    # instead of both writing every column from the same read.
    current = await _get(session, plan_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    move = changes.pop("move_members", False)
    if move and not isinstance(current, MonthlyPlan):
        raise NOT_MONTHLY
    if move and not await holds(session, tenant, Permission.MONEY_WRITE):
        raise MOVE_IS_MONEY
    active = changes.pop("active", current.active)
    if not changes and active == current.active:
        return current
    if changes.get("program_id") not in (None, current.program_id):
        await require_program(session, changes["program_id"], "program_id")

    # The plan as it would be, checked as a whole against its kind.
    fields = current.model_dump(exclude={"id", "active", "created_at"})
    try:
        edited = PLAN_CREATE.validate_python({**fields, **changes})
    except ValidationError as error:
        raise RequestValidationError(
            [{**e, "loc": ("body", *e["loc"][1:])} for e in error.errors(include_url=False)]
        ) from None

    columns = {**to_columns(edited), "active": active}
    del columns["kind"]
    assignments = ", ".join(f"{column} = :{column}" for column in columns)
    await session.execute(
        text(f"UPDATE plan SET {assignments} WHERE id = :id"), {**columns, "id": plan_id}
    )
    if move:
        await _move_members(session, plan_id, columns["anchor"])
    return await _get(session, plan_id)


def _moves(
    on_plan: list[tuple[uuid.UUID, billing.Billable]], anchor: str
) -> list[tuple[uuid.UUID, billing.Billable, billing.AnchorMove | None]]:
    """Each membership on the plan, with what moving it to the day `anchor` gives it
    would bill: `None` when it is on that day already, or leaving the plan."""
    terms = PlanTerms(PlanKind.MONTHLY, anchor=anchor)
    moves = []
    for membership_id, billable in on_plan:
        to_day = memberships.anchor_day(terms, billable.started_on)
        assert to_day is not None  # a monthly plan's
        moves.append((membership_id, billable, billing.anchor_move(billable, to_day)))
    return moves


ANCHOR_CHANGED = "anchor_changed"


async def _move_members(session: AsyncSession, plan_id: uuid.UUID, anchor: str) -> None:
    """Move each membership on the plan to the day `anchor` gives it, from its first
    period not billed, with a row in the log for each. One that bills on that day already
    stays on it, and a move to another day it had pending is withdrawn and logged too."""
    on_plan = await billables_on_plan(await driver_connection(session), plan_id, lock=True)
    for membership_id, billable, move in _moves(on_plan, anchor):
        if move is None and (billable.next_anchor_day is None or billable.next_plan is not None):
            continue
        before = billable.next_anchor_day or billable.anchor_day
        if move is None:
            after, starts_on = billable.anchor_day, billing.first_unbilled(billable)
        else:
            after, starts_on = move.to_day, move.transition.period_start
        if before == after:
            continue
        await session.execute(
            text("UPDATE membership SET next_anchor_day = :day WHERE id = :id"),
            {"day": None if move is None else move.to_day, "id": membership_id},
        )
        await record_audit(
            session,
            action=ANCHOR_CHANGED,
            membership_id=membership_id,
            reason=None,
            anchor={"before": before, "after": after, "starts_on": str(starts_on)},
        )


@router.get("/{plan_id}/anchor-moves")
async def anchor_moves(
    plan_id: uuid.UUID, anchor: Anchor, session: LedgerReadSession
) -> list[AnchorMove]:
    """What `PATCH` with `anchor` and `move_members` would do to the memberships on the
    monthly plan now, saving nothing (#547): each one it moves, by name, with the
    transition period to its new day, prorated, and the first whole period on it, as
    the nightly job will bill them. One on that day already, or leaving the plan by a
    plan change, is not listed."""
    current = await _get(session, plan_id)
    if not isinstance(current, MonthlyPlan):
        raise NOT_MONTHLY
    on_plan = await billables_on_plan(await driver_connection(session), plan_id)
    moves = {membership_id: move for membership_id, _, move in _moves(on_plan, anchor)}
    listed = []
    # By name, as the plan's list.
    for person in await session.execute(SELECT_ON_PLAN, {"id": plan_id}):
        move = moves.get(person.membership_id)
        if move is None:
            continue
        listed.append(
            AnchorMove(
                membership_id=person.membership_id,
                person_id=person.person_id,
                name=person.name,
                status=person.status,
                from_day=move.from_day,
                to_day=move.to_day,
                starts_on=move.transition.period_start,
                ends_on=move.transition.period_end,
                amount_due_clp=move.transition.amount_due_clp,
                next_starts_on=move.next_period.period_start,
                next_amount_clp=move.next_period.amount_due_clp,
            )
        )
    return listed


# The memberships on a plan now, by their person's name. RLS keeps both to the gym.
SELECT_ON_PLAN = text(
    "SELECT m.id AS membership_id, m.person_id, gp.name, m.status, np.name AS next_plan_name"
    " FROM membership m"
    " JOIN gym_person gp ON gp.person_id = m.person_id"
    " LEFT JOIN plan np ON np.id = m.next_plan_id"
    " WHERE m.plan_id = :id AND m.status IN ('active', 'frozen') AND m.voided_at IS NULL"
    " ORDER BY gp.name, m.created_at"
)


# The memberships a plan's list holds, and moves to its next period.
LIVE_ON_PLAN = (MembershipStatus.ACTIVE, MembershipStatus.FROZEN)


@router.get("/{plan_id}/memberships")
async def plan_memberships(plan_id: uuid.UUID, session: AdminSession) -> list[PlanMembership]:
    """The memberships on the plan now, Active or Frozen: the list a fixed-period plan's
    members are moved to the next period from."""
    await _get(session, plan_id)
    result = await session.execute(SELECT_ON_PLAN, {"id": plan_id})
    return [PlanMembership.model_validate(dict(row._mapping)) for row in result]


def _refused(field: str, kind: str, message: str, value: object) -> RequestValidationError:
    return RequestValidationError(
        [{"type": kind, "loc": ("body", field), "msg": message, "input": value}]
    )


@router.post("/{plan_id}/next-period", status_code=status.HTTP_201_CREATED)
async def next_period(
    plan_id: uuid.UUID, body: NextPeriod, session: AdminSession
) -> NextPeriodResult:
    """ "Duplicar para el próximo período" (#351): a copy of the fixed-period plan with
    `body`'s name, price and dates, in the same program, and each of `membership_ids`,
    memberships on the plan now, moved to it by a plan change. A 409 for a plan of
    another kind or a membership not on the plan now; a 422 for a period that does not
    start after the plan's, or a membership that cannot change plan."""
    current = await _get(session, plan_id, lock=True)
    if not isinstance(current, FixedPeriodPlan):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only a fixed-period plan is copied for its next period"
        )
    if body.period_start <= current.period_end:
        raise _refused(
            "period_start",
            "after_period",
            f"the next period starts after {current.period_end}",
            body.period_start.isoformat(),
        )
    copy = FixedPeriodPlanCreate(
        kind=PlanKind.FIXED_PERIOD,
        name=body.name,
        program_id=current.program_id,
        price_clp=body.price_clp,
        enrolment_fee_clp=current.enrolment_fee_clp,
        period_start=body.period_start,
        period_end=body.period_end,
    )
    created = await _insert(session, copy)
    terms = _terms(body.period_start, body.period_end)
    moved = 0
    for membership_id in dict.fromkeys(body.membership_ids):
        membership, on_plan = await locked_membership(session, membership_id)
        if on_plan != plan_id or membership.status not in LIVE_ON_PLAN:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "code": "not_on_plan",
                    "message": "the membership is not on this plan now",
                    "membership_id": str(membership_id),
                },
            )
        starts_on = await change_starts(session, membership_id, membership, terms)
        await session.execute(
            text(
                "UPDATE membership SET next_plan_id = :plan, next_plan_from = :from WHERE id = :id"
            ),
            {"plan": created.id, "from": starts_on, "id": membership_id},
        )
        moved += 1
    return NextPeriodResult(plan=created, moved=moved)


def _terms(period_start: date, period_end: date) -> PlanTerms:
    return PlanTerms(PlanKind.FIXED_PERIOD, period_start=period_start, period_end=period_end)
