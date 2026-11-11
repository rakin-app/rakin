"""Groups: named, reusable lists of people a cobro extra can target (#195).

"Clasificados final", "Competidores kids": the admin builds one from the member list's
filters plus people picked by hand, and saves it as a fixed list, a snapshot rather
than a live filter. Saving replaces the list. A coach may read the groups' names and
sizes, which can help with rosters; only an owner or admin reads who is in one or
changes it.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.roles import AdminSession, StaffSession
from app.schemas.extra_charges import Group, GroupSummary, GroupWrite
from app.schemas.ledger import PersonRef

router = APIRouter(prefix="/api/groups", tags=["groups"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "a group by that name exists")
UNKNOWN_PEOPLE = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT, "someone in the list is not in this gym"
)

SUMMARIES = text(
    """
    SELECT g.id, g.name, count(m.person_id) AS size
    FROM charge_group g LEFT JOIN charge_group_member m ON m.group_id = g.id
    GROUP BY g.id ORDER BY lower(g.name), g.id
    """
)

MEMBERS = text(
    """
    SELECT gp.person_id AS id, gp.name FROM charge_group_member m
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    WHERE m.group_id = :id ORDER BY lower(gp.name), gp.person_id
    """
)

IN_GYM = text("SELECT count(*) FROM gym_person WHERE person_id = ANY(CAST(:ids AS uuid[]))")


@router.get("")
async def list_groups(session: StaffSession) -> list[GroupSummary]:
    """Every group, by name, with how many people it holds."""
    return [
        GroupSummary.model_validate(row, from_attributes=True)
        for row in await session.execute(SUMMARIES)
    ]


async def read_group(session: AsyncSession, group_id: uuid.UUID) -> Group:
    name = await session.scalar(
        text("SELECT name FROM charge_group WHERE id = :id"), {"id": group_id}
    )
    if name is None:
        raise NOT_FOUND
    members = await session.execute(MEMBERS, {"id": group_id})
    return Group(
        id=group_id,
        name=name,
        members=[PersonRef(id=row.id, name=row.name) for row in members],
    )


@router.get("/{group_id}")
async def get_group(group_id: uuid.UUID, session: AdminSession) -> Group:
    return await read_group(session, group_id)


async def write_members(
    session: AsyncSession, group_id: uuid.UUID, person_ids: list[uuid.UUID]
) -> None:
    ids = sorted(set(person_ids))
    if await session.scalar(IN_GYM, {"ids": ids}) != len(ids):
        raise UNKNOWN_PEOPLE
    await session.execute(
        text("DELETE FROM charge_group_member WHERE group_id = :id"), {"id": group_id}
    )
    if ids:
        await session.execute(
            text(
                "INSERT INTO charge_group_member (gym_id, group_id, person_id)"
                " SELECT current_setting('app.gym_id')::uuid, :id, p"
                " FROM unnest(CAST(:ids AS uuid[])) AS p"
            ),
            {"id": group_id, "ids": ids},
        )


async def named(
    session: AsyncSession, statement: str, params: dict[str, object]
) -> uuid.UUID | None:
    """Run the insert or rename `statement`, a 409 if another group has the name."""
    try:
        async with session.begin_nested():
            found: uuid.UUID | None = await session.scalar(text(statement), params)
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
        if constraint != "charge_group_name":
            raise
        raise NAME_TAKEN from None
    return found


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupWrite, session: AdminSession) -> Group:
    group_id = await named(
        session,
        "INSERT INTO charge_group (gym_id, name)"
        " VALUES (current_setting('app.gym_id')::uuid, :name) RETURNING id",
        {"name": body.name},
    )
    assert group_id is not None
    await write_members(session, group_id, body.person_ids)
    return await read_group(session, group_id)


@router.put("/{group_id}")
async def update_group(group_id: uuid.UUID, body: GroupWrite, session: AdminSession) -> Group:
    """Rename the group and replace who is in it."""
    found = await named(
        session,
        "UPDATE charge_group SET name = :name WHERE id = :id RETURNING id",
        {"id": group_id, "name": body.name},
    )
    if found is None:
        raise NOT_FOUND
    await write_members(session, group_id, body.person_ids)
    return await read_group(session, group_id)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: uuid.UUID, session: AdminSession) -> Response:
    """The cobros that targeted it keep their lines: a group is only a list."""
    deleted = await session.scalar(
        text("DELETE FROM charge_group WHERE id = :id RETURNING id"), {"id": group_id}
    )
    if deleted is None:
        raise NOT_FOUND
    return Response(status_code=status.HTTP_204_NO_CONTENT)
