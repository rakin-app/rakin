"""People in the current gym: add one by phone, read and edit this gym's record.

Identity is global by phone (docs/technical.md#domain-model), so adding someone whose
phone another gym already has attaches that person rather than duplicating them. The
answer gives no sign of it: the same 201, carrying what this gym entered and this
gym's timestamps, whether the phone was new or known (migration 0004). Only a phone
already in *this* gym is refused, with a 409 naming that person, so the admin can open
them instead.

Every staff role may use it, coaches included; members may not.
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.roles import StaffSession
from app.schemas.people import Person, PersonCreate, PersonUpdate, PhoneConflict, PhoneInGym

router = APIRouter(prefix="/api/people", tags=["people"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "person not found")

# This gym's record, and the phone it was added by. RLS on `gym_person` keeps it to
# the current gym.
SELECT_PERSON = """
    SELECT gp.person_id AS id, p.phone, gp.name, gp.email, gp.rut, gp.dob,
           gp.created_at, gp.updated_at
    FROM gym_person gp JOIN person p ON p.id = gp.person_id
    WHERE gp.person_id = :id
"""


async def _get(session: AsyncSession, person_id: uuid.UUID) -> Person:
    row = (await session.execute(text(SELECT_PERSON), {"id": person_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Person.model_validate(row, from_attributes=True)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": PhoneInGym}},
)
async def create_person(body: PersonCreate, session: StaffSession) -> Person:
    result = await session.execute(
        text("SELECT person_id, joined FROM join_gym_by_phone(:phone, :name, :email, :rut, :dob)"),
        body.model_dump(),
    )
    person_id, joined = result.one()
    if not joined:
        # Raised, not returned, so the transaction rolls back (nothing was written).
        conflict = PhoneConflict(person_id=person_id)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))
    return await _get(session, person_id)


@router.get("/{person_id}")
async def get_person(person_id: uuid.UUID, session: StaffSession) -> Person:
    return await _get(session, person_id)


@router.patch("/{person_id}")
async def update_person(person_id: uuid.UUID, body: PersonUpdate, session: StaffSession) -> Person:
    changes = body.model_dump(exclude_unset=True)
    if changes:
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        result = await session.execute(
            text(f"UPDATE gym_person SET {assignments}, updated_at = now() WHERE person_id = :id"),
            {**changes, "id": person_id},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NOT_FOUND
    return await _get(session, person_id)
