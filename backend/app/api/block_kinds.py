"""The current gym's block kinds: list, create, edit, order, archive, delete (migration 0024).

A block kind is a part of a class the coach's timer counts down (Calentamiento,
Técnica, Sparring), and `is_sparring` says its time is sparring. Every gym starts with
six. A name is unique in the gym, case ignored: a second "Juegos" is a 409.

One that sessions' blocks are of is archived (`PATCH {"archived": true}`), not deleted,
and whether it is sparring is fixed, since that is what its recorded time already
counts as: both are a 409, `block_kind_in_use`, with how many blocks are of it. An
archived kind keeps its blocks and is planned no more.

Any staff role may read them, coaches included, since the coach plans the class; only
an owner or admin may change them, as for class types.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.programs import execute_refusing
from app.roles import AdminSession, StaffSession
from app.schemas.blocks import (
    BlockKind,
    BlockKindCreate,
    BlockKindInUse,
    BlockKindOrder,
    BlockKindsInUse,
    BlockKindUpdate,
)

router = APIRouter(prefix="/api/block-kinds", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "block kind not found")
NAME_TAKEN = HTTPException(
    status.HTTP_409_CONFLICT, "the gym already has a block kind by this name"
)
REFUSALS = {"block_kind_name_key": NAME_TAKEN}
IN_USE: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": BlockKindsInUse, "description": "in use"}
}

# RLS on `block_kind` keeps every query to the current gym.
SELECT_KIND = "SELECT id, name, is_sparring, position, archived, created_at FROM block_kind"
ORDER = " ORDER BY archived, position, lower(name), created_at"


async def _get(session: AsyncSession, kind_id: uuid.UUID, *, lock: bool = False) -> BlockKind:
    sql = f"{SELECT_KIND} WHERE id = :id{' FOR UPDATE' if lock else ''}"
    row = (await session.execute(text(sql), {"id": kind_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return BlockKind.model_validate(row, from_attributes=True)


async def _list(session: AsyncSession, archived: bool | None = None) -> list[BlockKind]:
    where = "" if archived is None else " WHERE archived = :archived"
    result = await session.execute(text(SELECT_KIND + where + ORDER), {"archived": archived})
    return [BlockKind.model_validate(row, from_attributes=True) for row in result]


async def _refuse_in_use(session: AsyncSession, kind_id: uuid.UUID) -> None:
    """A 409 `block_kind_in_use` if any session's block is of the kind."""
    blocks: int = await session.scalar(
        text("SELECT count(*) FROM session_block WHERE block_kind_id = :id"), {"id": kind_id}
    )
    if blocks:
        conflict = BlockKindInUse(blocks=blocks)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))


@router.get("")
async def list_block_kinds(session: StaffSession, archived: bool | None = None) -> list[BlockKind]:
    """In the gym's order, archived ones last; `?archived=false` for the ones to plan."""
    return await _list(session, archived)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_block_kind(body: BlockKindCreate, session: AdminSession) -> BlockKind:
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO block_kind (gym_id, name, is_sparring, position)"
            " SELECT current_setting('app.gym_id')::uuid, :name, :is_sparring,"
            " coalesce(max(position) + 1, 0) FROM block_kind"
            " RETURNING id"
        ),
        body.model_dump(),
        REFUSALS,
    )
    return await _get(session, result.scalar_one())


@router.put("/order")
async def order_block_kinds(body: BlockKindOrder, session: AdminSession) -> list[BlockKind]:
    """Every kind of the gym, each once, in its new order; anything else is a 422."""
    current = await session.execute(text("SELECT id FROM block_kind FOR UPDATE"))
    if len(body.ids) != len(set(body.ids)) or set(body.ids) != set(current.scalars()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "send every block kind of the gym, once each"
        )
    await session.execute(
        text(
            "UPDATE block_kind SET position = o.position - 1"
            " FROM unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS o (id, position)"
            " WHERE block_kind.id = o.id"
        ),
        {"ids": body.ids},
    )
    return await _list(session)


@router.patch(
    "/{kind_id}",
    responses={
        status.HTTP_409_CONFLICT: {"model": BlockKindsInUse, "description": "in use, or name taken"}
    },
)
async def update_block_kind(
    kind_id: uuid.UUID, body: BlockKindUpdate, session: AdminSession
) -> BlockKind:
    current = await _get(session, kind_id, lock=True)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_sparring", current.is_sparring) != current.is_sparring:
        await _refuse_in_use(session, kind_id)
    columns = {**current.model_dump(include={"name", "is_sparring", "archived"}), **changes}
    await execute_refusing(
        session,
        text(
            "UPDATE block_kind SET name = :name, is_sparring = :is_sparring,"
            " archived = :archived WHERE id = :id"
        ),
        {**columns, "id": kind_id},
        REFUSALS,
    )
    return await _get(session, kind_id)


@router.delete("/{kind_id}", status_code=status.HTTP_204_NO_CONTENT, responses=IN_USE)
async def delete_block_kind(kind_id: uuid.UUID, session: AdminSession) -> Response:
    await _get(session, kind_id, lock=True)
    await _refuse_in_use(session, kind_id)
    await session.execute(text("DELETE FROM block_kind WHERE id = :id"), {"id": kind_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
