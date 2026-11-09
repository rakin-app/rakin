"""Family links in the current gym: who pays for whom (migration 0010).

A guardian is anyone in the gym; a dependent is either someone already in it or a new
person added by name alone, with no phone, since kids have none. Every staff role may
use it, as for the rest of the people API; members may not.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND, in_gym
from app.roles import StaffSession
from app.schemas.guardians import (
    ConflictCode,
    Family,
    FamilyConflict,
    FamilyRefused,
    LinkDependent,
    NewDependent,
)
from app.schemas.people import PersonRef

router = APIRouter(prefix="/api/people", tags=["people"])

# The constraint each refusal comes from, and the code the API answers with.
CONFLICTS: dict[str | None, ConflictCode] = {
    "guardian_link_pkey": "has_guardian",
    "guardian_link_one_level": "one_level",
}

FAMILY = """
    SELECT 'guardian' AS side, gp.person_id AS id, gp.name
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.guardian_person_id
    WHERE gl.dependent_person_id = :id
    UNION ALL
    SELECT 'dependent', gp.person_id, gp.name
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
    WHERE gl.guardian_person_id = :id
"""

LINK = """
    INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)
    VALUES (NULLIF(current_setting('app.gym_id', true), '')::uuid, :guardian, :dependent)
"""

# A new dependent's own record starts with what this gym entered, as in
# `join_gym_by_phone` (0004). The id is made here: RLS hides the person from
# `RETURNING` until their `gym_person` row exists.
NEW_PERSON = (
    "INSERT INTO person (id, name, email, rut, dob) VALUES (:id, :name, :email, :rut, :dob)"
)
NEW_GYM_PERSON = """
    INSERT INTO gym_person (gym_id, person_id, name, email, rut, dob)
    VALUES (NULLIF(current_setting('app.gym_id', true), '')::uuid, :id, :name, :email, :rut, :dob)
"""


async def family(session: AsyncSession, person_id: uuid.UUID) -> Family:
    rows = (await session.execute(text(FAMILY), {"id": person_id})).all()
    guardian = next((PersonRef(id=r.id, name=r.name) for r in rows if r.side == "guardian"), None)
    dependents = sorted(
        (PersonRef(id=r.id, name=r.name) for r in rows if r.side == "dependent"),
        key=lambda p: (p.name.casefold(), p.id),
    )
    return Family(guardian=guardian, dependents=dependents)


async def link(
    session: AsyncSession, guardian: uuid.UUID, dependent: uuid.UUID
) -> ConflictCode | None:
    """Make `dependent` `guardian`'s, or answer why the database refuses to."""
    try:
        # A savepoint, so a refusal leaves the request's transaction usable.
        async with session.begin_nested():
            await session.execute(text(LINK), {"guardian": guardian, "dependent": dependent})
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
        if constraint not in CONFLICTS:
            raise
        return CONFLICTS[constraint]
    return None


async def _link(session: AsyncSession, guardian: uuid.UUID, dependent: uuid.UUID) -> None:
    if guardian == dependent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nobody is their own guardian")
    if (code := await link(session, guardian, dependent)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, FamilyConflict(code=code).model_dump())


@router.get("/{person_id}/family")
async def get_family(person_id: uuid.UUID, session: StaffSession) -> Family:
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    return await family(session, person_id)


@router.post(
    "/{person_id}/dependents",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": FamilyRefused}},
)
async def add_dependent(
    person_id: uuid.UUID, body: LinkDependent | NewDependent, session: StaffSession
) -> Family:
    """Link `body.person_id`, someone in this gym, or add a new person by name."""
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    if isinstance(body, LinkDependent):
        if not await in_gym(session, body.person_id):
            raise NOT_FOUND
        dependent = body.person_id
    else:
        dependent = uuid.uuid4()
        values = {"id": dependent, **body.model_dump()}
        await session.execute(text(NEW_PERSON), values)
        await session.execute(text(NEW_GYM_PERSON), values)
    await _link(session, person_id, dependent)
    return await family(session, person_id)


@router.delete("/{person_id}/dependents/{dependent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dependent(
    person_id: uuid.UUID, dependent_id: uuid.UUID, session: StaffSession
) -> Response:
    """Unlink; both people stay in the gym."""
    result = await session.execute(
        text(
            "DELETE FROM guardian_link"
            " WHERE guardian_person_id = :guardian AND dependent_person_id = :dependent"
        ),
        {"guardian": person_id, "dependent": dependent_id},
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such dependent")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
