"""The current gym's plans: create, list, read, edit, deactivate.

Six kinds, each with its own parameters (`app.schemas.plans`). There is no delete: a
plan is deactivated with `PATCH {"active": false}`, and the database refuses a
`DELETE` from any role (migration 0007), since memberships and the ledger keep
pointing at it. A `program_id` must be one of the gym's programs, or it is a 422.

Any staff role may read the plans, coaches included, though a coach reads them without
their prices (#205); only an owner or admin may create or change one. Members may not
use it at all.

A fixed-period plan does not renew itself (#351). The owner copies it for the next
period, `POST /{id}/next-period`, and moves the members on its list
(`GET /{id}/memberships`) across in the same request: each gets a plan change to the
copy from the day after it is paid through, so the copy bills its period when it
falls due and the old plan bills nothing more.
"""

import uuid
from datetime import date
from typing import Any, overload

from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.memberships import change_starts, locked_membership
from app.api.programs import require_program
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.permissions import AdminSession, SeesMoney, StaffSession
from app.schemas.plans import (
    COLUMNS,
    PLAN,
    PLAN_CREATE,
    FixedPeriodPlan,
    FixedPeriodPlanCreate,
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


@router.patch("/{plan_id}")
async def update_plan(plan_id: uuid.UUID, body: PlanUpdate, session: AdminSession) -> Plan:
    # Locked, so a concurrent edit waits and then merges into this one's result
    # instead of both writing every column from the same read.
    current = await _get(session, plan_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
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
    return await _get(session, plan_id)


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
