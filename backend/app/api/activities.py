"""The current gym's activities: list, add, rename, grade or not, remove (#245).

An activity is one discipline the gym teaches (migration 0043): "Ballet",
"Escalada", "Piano". A name is unique in the gym, case ignored: a second "ballet" is a 409. Its
`uses_grades` decides whether the gym's screens show belts and ranks: they do while
any activity has it on (`gym_uses_grades`, which `/api/me/role` answers). Removing an
activity leaves its class types with none.

Any staff role may read them, since a coach sees the class types that belong to one;
only an owner or admin may change them.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.programs import execute_refusing
from app.roles import AdminSession, StaffSession
from app.schemas.activities import Activity, ActivityCreate, ActivityUpdate

router = APIRouter(prefix="/api/activities", tags=["gym"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "activity not found")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the gym already has an activity by this name")
REFUSALS = {"gym_activity_name_key": NAME_TAKEN}

# RLS on both tables keeps every query to the current gym.
SELECT_ACTIVITY = """
    SELECT a.id, a.name, a.uses_grades, a.created_at,
           (SELECT count(*) FROM class_type c WHERE c.activity_id = a.id) AS class_types
    FROM gym_activity a
"""


async def gym_uses_grades(session: AsyncSession) -> bool:
    """Whether any of the current gym's activities grades its students."""
    graded: bool = await session.scalar(
        text("SELECT EXISTS (SELECT FROM gym_activity WHERE uses_grades)")
    )
    return graded


async def _get(session: AsyncSession, activity_id: uuid.UUID, *, lock: bool = False) -> Activity:
    sql = f"{SELECT_ACTIVITY} WHERE a.id = :id{' FOR UPDATE OF a' if lock else ''}"
    row = (await session.execute(text(sql), {"id": activity_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Activity.model_validate(row, from_attributes=True)


@router.get("")
async def list_activities(session: StaffSession) -> list[Activity]:
    """By name."""
    result = await session.execute(text(f"{SELECT_ACTIVITY} ORDER BY lower(a.name), a.created_at"))
    return [Activity.model_validate(row, from_attributes=True) for row in result]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_activity(body: ActivityCreate, session: AdminSession) -> Activity:
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO gym_activity (gym_id, name, uses_grades)"
            " VALUES (current_setting('app.gym_id')::uuid, :name, :uses_grades) RETURNING id"
        ),
        body.model_dump(),
        REFUSALS,
    )
    return await _get(session, result.scalar_one())


@router.patch("/{activity_id}", responses={status.HTTP_409_CONFLICT: {"description": "name taken"}})
async def update_activity(
    activity_id: uuid.UUID, body: ActivityUpdate, session: AdminSession
) -> Activity:
    current = await _get(session, activity_id, lock=True)
    columns = {
        **current.model_dump(include={"name", "uses_grades"}),
        **body.model_dump(exclude_unset=True),
    }
    await execute_refusing(
        session,
        text("UPDATE gym_activity SET name = :name, uses_grades = :uses_grades WHERE id = :id"),
        {**columns, "id": activity_id},
        REFUSALS,
    )
    return await _get(session, activity_id)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(activity_id: uuid.UUID, session: AdminSession) -> None:
    """Its class types stay, with no activity."""
    deleted = await session.scalar(
        text("DELETE FROM gym_activity WHERE id = :id RETURNING id"), {"id": activity_id}
    )
    if deleted is None:
        raise NOT_FOUND
