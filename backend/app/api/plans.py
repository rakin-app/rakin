"""The current gym's plans: create, list, read, edit, deactivate.

Five kinds, each with its own parameters (`app.schemas.plans`). There is no delete: a
plan is deactivated with `PATCH {"active": false}`, and the database refuses a
`DELETE` from any role (migration 0007), since memberships and the ledger keep
pointing at it.

Any staff role may read the plans, coaches included; only an owner or admin may
create or change one. Members may not use it at all.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.roles import AdminSession, StaffSession
from app.schemas.plans import (
    COLUMNS,
    PLAN,
    PLAN_CREATE,
    Plan,
    PlanCreate,
    PlanUpdate,
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
async def list_plans(session: StaffSession, active: bool | None = None) -> list[Plan]:
    """Active plans first, then by name; `?active=true` for the ones a member can join."""
    where = "" if active is None else " WHERE active = :active"
    result = await session.execute(
        text(f"{SELECT_PLAN}{where} ORDER BY active DESC, name, created_at"), {"active": active}
    )
    return [_plan(row) for row in result]


@router.get("/{plan_id}")
async def get_plan(plan_id: uuid.UUID, session: StaffSession) -> Plan:
    return await _get(session, plan_id)


@router.patch("/{plan_id}")
async def update_plan(plan_id: uuid.UUID, body: PlanUpdate, session: AdminSession) -> Plan:
    # Locked, so a concurrent edit waits and then merges into this one's result
    # instead of both writing every column from the same read.
    current = await _get(session, plan_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    active = changes.pop("active", current.active)
    if not changes and active == current.active:
        return current

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
