"""The current gym's activities: list, add, rename, grade or not, remove (#245).

An activity is one discipline the gym teaches (migration 0043): "Ballet",
"Escalada", "Piano". A name is unique in the gym, case ignored: a second "ballet" is a 409. Its
`uses_grades` decides whether the gym's screens show belts and ranks: they do while
any activity has it on (`gym_uses_grades`, which `/api/me/role` answers). Removing an
activity leaves its class types with none.

The gym's first activity also sets what the gym calls itself, its members and its coach
(#344, `app.domain.vocabulary`): its preset's words, or the neutral ones for a name the
gym wrote. Never once the owner has picked the words by hand, and never a later
activity: Ajustes offers those as a suggestion.

The first activity with a preset names the gym's free practice too (#346, `app.domain.practice`):
Sparring, Randori, Escalada libre. An activity added or removed that changes it renames
the practice's block kind (`follow_practice`), unless the gym renamed it itself.

Any staff role may read them, since a coach sees the class types that belong to one;
only an owner or admin may change them.
"""

import json
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.programs import execute_refusing
from app.domain.practice import KIND, Practice, practice_of
from app.domain.vocabulary import stored, words_of
from app.permissions import AdminSession, StaffSession
from app.schemas.activities import Activity, ActivityCreate, ActivityUpdate
from app.schemas.people import PracticeNames

router = APIRouter(prefix="/api/activities", tags=["gym"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "activity not found")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the gym already has an activity by this name")
REFUSALS = {"gym_activity_name_key": NAME_TAKEN}

# RLS on both tables keeps every query to the current gym.
SELECT_ACTIVITY = """
    SELECT a.id, a.name, a.uses_grades, a.preset, a.created_at,
           (SELECT count(*) FROM class_type c WHERE c.activity_id = a.id) AS class_types
    FROM gym_activity a
"""


async def gym_uses_grades(session: AsyncSession) -> bool:
    """Whether any of the current gym's activities grades its students."""
    graded: bool = await session.scalar(
        text("SELECT EXISTS (SELECT FROM gym_activity WHERE uses_grades)")
    )
    return graded


async def gym_practice(session: AsyncSession) -> Practice:
    """The current gym's practice, as its first activity with a preset names it."""
    presets = list(
        await session.scalars(text("SELECT preset FROM gym_activity ORDER BY created_at, id"))
    )
    return practice_of(presets)


# The default kind that is the practice (0028), in the current gym.
PRACTICE_KIND = "block_kind_default_id(current_setting('app.gym_id')::uuid, :key)"


async def practice_names(session: AsyncSession) -> PracticeNames:
    """What the screens call the practice and its open mat: the practice kind's name as
    the gym has it now, which the owner may have changed, and the open mat's own name,
    else the same."""
    practice = await gym_practice(session)
    block: str = (
        await session.scalar(
            text(f"SELECT name FROM block_kind WHERE id = {PRACTICE_KIND} AND is_sparring"),
            {"key": KIND},
        )
        or practice.block
    )
    return PracticeNames(block=block, open_mat=practice.open_mat or block)


async def follow_practice(session: AsyncSession, before: Practice) -> None:
    """Once a change has moved the gym's practice from `before`, the new name on its
    kind, if that still has the old one's and no other kind has the new."""
    after = await gym_practice(session)
    if after.block == before.block:
        return
    await session.execute(
        text(
            f"UPDATE block_kind k SET name = :new WHERE id = {PRACTICE_KIND}"
            " AND name = :old AND NOT EXISTS"
            " (SELECT FROM block_kind o WHERE lower(o.name) = lower(:new) AND o.id <> k.id)"
        ),
        {"new": after.block, "old": before.block, "key": KIND},
    )


def _activity(row: object) -> Activity:
    activity = Activity.model_validate(row, from_attributes=True)
    if activity.preset is None:
        return activity
    return activity.model_copy(update={"words": words_of(activity.preset)})


# The first activity's words, unless the owner picked theirs by hand. Run after the
# insert, so "first" is the only one there is.
FIRST_WORDS = """
    UPDATE gym SET settings = settings || jsonb_build_object('vocabulary', CAST(:words AS jsonb))
    WHERE id = current_setting('app.gym_id')::uuid
      AND coalesce((settings -> 'vocabulary' ->> 'by_hand')::boolean, false) IS NOT TRUE
      AND (SELECT count(*) FROM gym_activity) = 1
"""


async def _get(session: AsyncSession, activity_id: uuid.UUID, *, lock: bool = False) -> Activity:
    sql = f"{SELECT_ACTIVITY} WHERE a.id = :id{' FOR UPDATE OF a' if lock else ''}"
    row = (await session.execute(text(sql), {"id": activity_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return _activity(row)


@router.get("")
async def list_activities(session: StaffSession) -> list[Activity]:
    """By name."""
    result = await session.execute(text(f"{SELECT_ACTIVITY} ORDER BY lower(a.name), a.created_at"))
    return [_activity(row) for row in result]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_activity(body: ActivityCreate, session: AdminSession) -> Activity:
    before = await gym_practice(session)
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO gym_activity (gym_id, name, uses_grades, preset)"
            " VALUES (current_setting('app.gym_id')::uuid, :name, :uses_grades, :preset)"
            " RETURNING id"
        ),
        body.model_dump(),
        REFUSALS,
    )
    activity_id = result.scalar_one()
    words = stored(words_of(body.preset), by_hand=False)
    await session.execute(text(FIRST_WORDS), {"words": json.dumps(words)})
    await follow_practice(session, before)
    return await _get(session, activity_id)


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
    before = await gym_practice(session)
    deleted = await session.scalar(
        text("DELETE FROM gym_activity WHERE id = :id RETURNING id"), {"id": activity_id}
    )
    if deleted is None:
        raise NOT_FOUND
    await follow_practice(session, before)
