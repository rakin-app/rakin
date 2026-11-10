"""The current gym's class types: create, list, read, edit, deactivate (migration 0016).

A class type is a kind of class in one of the gym's programs, with the credits an
attendance costs a credits membership (0 for a free class). There is no delete:
sessions point at it (migration 0020), so it is deactivated with `PATCH {"active": false}`.
A name is unique within its program, case ignored: a second "Fundamentos" in Kids is a
409, one in Adultos is not.

A class type is a class or an open mat (`kind`, migration 0028), and `counts_as_class`
says whether attending one counts towards a student's classes: by default a class does
and an open mat does not.

Any staff role may read them, coaches included, since the coach starts a session of
one; only an owner or admin may create or change one. Members may not use it at all.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.programs import execute_refusing, require_program
from app.roles import AdminSession, StaffSession
from app.schemas.classes import ClassType, ClassTypeCreate, ClassTypeUpdate, counts_by_default

router = APIRouter(prefix="/api/class-types", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "class type not found")
NAME_TAKEN = HTTPException(
    status.HTTP_409_CONFLICT, "the program already has a class type by this name"
)
REFUSALS = {"class_type_name_key": NAME_TAKEN}

# Each with its program's name. RLS keeps both tables to the current gym.
SELECT_CLASS_TYPE = """
    SELECT c.id, c.name, c.program_id, p.name AS program_name, c.credit_cost, c.kind,
           c.counts_as_class, c.active, c.created_at
    FROM class_type c JOIN program p ON p.id = c.program_id
"""


async def _get(session: AsyncSession, class_type_id: uuid.UUID, *, lock: bool = False) -> ClassType:
    sql = f"{SELECT_CLASS_TYPE} WHERE c.id = :id{' FOR UPDATE OF c' if lock else ''}"
    row = (await session.execute(text(sql), {"id": class_type_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return ClassType.model_validate(row, from_attributes=True)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_class_type(body: ClassTypeCreate, session: AdminSession) -> ClassType:
    await require_program(session, body.program_id, "program_id")
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO class_type (gym_id, program_id, name, credit_cost, kind, counts_as_class)"
            " VALUES (current_setting('app.gym_id')::uuid, :program_id, :name, :credit_cost,"
            " :kind, :counts_as_class) RETURNING id"
        ),
        {
            **body.model_dump(),
            "counts_as_class": (
                counts_by_default(body.kind)
                if body.counts_as_class is None
                else body.counts_as_class
            ),
        },
        REFUSALS,
    )
    return await _get(session, result.scalar_one())


@router.get("")
async def list_class_types(
    session: StaffSession, active: bool | None = None, program_id: uuid.UUID | None = None
) -> list[ClassType]:
    """Active ones first, then by program and name; `?program_id=` for one program's."""
    where = []
    if active is not None:
        where.append("c.active = :active")
    if program_id is not None:
        where.append("c.program_id = :program_id")
    sql = SELECT_CLASS_TYPE + (" WHERE " + " AND ".join(where) if where else "")
    result = await session.execute(
        text(f"{sql} ORDER BY c.active DESC, lower(p.name), lower(c.name), c.created_at"),
        {"active": active, "program_id": program_id},
    )
    return [ClassType.model_validate(row, from_attributes=True) for row in result]


@router.get("/{class_type_id}")
async def get_class_type(class_type_id: uuid.UUID, session: StaffSession) -> ClassType:
    return await _get(session, class_type_id)


@router.patch(
    "/{class_type_id}", responses={status.HTTP_409_CONFLICT: {"description": "name taken"}}
)
async def update_class_type(
    class_type_id: uuid.UUID, body: ClassTypeUpdate, session: AdminSession
) -> ClassType:
    current = await _get(session, class_type_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if "program_id" in changes and changes["program_id"] != current.program_id:
        await require_program(session, changes["program_id"], "program_id")
    if changes.get("kind", current.kind) != current.kind and "counts_as_class" not in changes:
        changes["counts_as_class"] = counts_by_default(changes["kind"])
    fields = {"name", "program_id", "credit_cost", "kind", "counts_as_class", "active"}
    columns = {**current.model_dump(include=fields), **changes}
    await execute_refusing(
        session,
        text(
            "UPDATE class_type SET name = :name, program_id = :program_id,"
            " credit_cost = :credit_cost, kind = :kind, counts_as_class = :counts_as_class,"
            " active = :active WHERE id = :id"
        ),
        {**columns, "id": class_type_id},
        REFUSALS,
    )
    return await _get(session, class_type_id)
