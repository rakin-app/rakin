"""The current gym's programs: create, list, read, rename, deactivate (migration 0016).

A program is a group of students the gym names itself: adults, kids, competition.
There is no delete: class types and plans point at a program, so it is deactivated
with `PATCH {"active": false}`. A name is unique in the gym, case ignored: a second
"Kids" is a 409.

Any staff role may read them, coaches included; only an owner or admin may create or
change one, as for plans. Members may not use it at all.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.roles import AdminSession, StaffSession
from app.schemas.classes import Program, ProgramCreate, ProgramUpdate

router = APIRouter(prefix="/api/programs", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "program not found")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the gym already has a program by this name")

# RLS on `program` keeps every query to the current gym.
SELECT_PROGRAM = "SELECT id, name, active, created_at FROM program"


async def execute_refusing(
    session: AsyncSession,
    statement: TextClause,
    params: Mapping[str, Any],
    refusals: Mapping[str, HTTPException],
) -> Any:
    """`statement`'s result, or the refusal for the constraint it violates. A savepoint,
    so a refusal leaves the request's transaction usable."""
    try:
        async with session.begin_nested():
            return await session.execute(statement, params)
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
        refusal = refusals.get(constraint) if isinstance(constraint, str) else None
        if refusal is None:
            raise
        raise refusal from None


async def require_program(session: AsyncSession, program_id: uuid.UUID, field: str) -> None:
    """A 422 on `field` unless `program_id` is one of this gym's programs."""
    found = await session.scalar(
        text("SELECT EXISTS (SELECT FROM program WHERE id = :id)"), {"id": program_id}
    )
    if not found:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", field), "msg": "no such program in this gym"}]
        )


async def _get(session: AsyncSession, program_id: uuid.UUID, *, lock: bool = False) -> Program:
    sql = f"{SELECT_PROGRAM} WHERE id = :id{' FOR UPDATE' if lock else ''}"
    row = (await session.execute(text(sql), {"id": program_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Program.model_validate(row, from_attributes=True)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_program(body: ProgramCreate, session: AdminSession) -> Program:
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO program (gym_id, name)"
            " VALUES (current_setting('app.gym_id')::uuid, :name) RETURNING id"
        ),
        body.model_dump(),
        {"program_name_key": NAME_TAKEN},
    )
    return await _get(session, result.scalar_one())


@router.get("")
async def list_programs(session: StaffSession, active: bool | None = None) -> list[Program]:
    """Active programs first, then by name."""
    where = "" if active is None else " WHERE active = :active"
    result = await session.execute(
        text(f"{SELECT_PROGRAM}{where} ORDER BY active DESC, lower(name), created_at"),
        {"active": active},
    )
    return [Program.model_validate(row, from_attributes=True) for row in result]


@router.get("/{program_id}")
async def get_program(program_id: uuid.UUID, session: StaffSession) -> Program:
    return await _get(session, program_id)


@router.patch("/{program_id}", responses={status.HTTP_409_CONFLICT: {"description": "name taken"}})
async def update_program(
    program_id: uuid.UUID, body: ProgramUpdate, session: AdminSession
) -> Program:
    current = await _get(session, program_id, lock=True)
    columns = {
        **current.model_dump(include={"name", "active"}),
        **body.model_dump(exclude_unset=True),
    }
    await execute_refusing(
        session,
        text("UPDATE program SET name = :name, active = :active WHERE id = :id"),
        {**columns, "id": program_id},
        {"program_name_key": NAME_TAKEN},
    )
    return await _get(session, program_id)
