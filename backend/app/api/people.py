"""People in the current gym: list and search them, add one by phone, read and edit
this gym's record.

Identity is global by phone (docs/technical.md#domain-model), so adding someone whose
phone another gym already has attaches that person rather than duplicating them. The
answer gives no sign of it: the same 201, carrying what this gym entered and this
gym's timestamps, whether the phone was new or known (migration 0004). Only a phone
already in *this* gym is refused, with a 409 naming that person, so the admin can open
them instead.

Every staff role may use it, coaches included; members may not.
"""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.membership import MembershipStatus
from app.roles import StaffSession
from app.schemas.people import (
    MemberPage,
    MemberRow,
    MembershipSummary,
    Person,
    PersonCreate,
    PersonUpdate,
    PhoneConflict,
    PhoneInGym,
)

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


# Accents and case ignored, so "martin" finds "Martín" and "nunez" finds "Núñez".
def _fold(sql: str) -> str:
    return f"lower(translate({sql}, 'ÁÉÍÓÚÜÑáéíóúüñ', 'AEIOUUNaeiouun'))"


# Everyone this gym has a record of, except staff who hold no membership here, each
# with the membership the list shows (`MembershipSummary`). RLS keeps every table to
# the current gym.
MEMBERS = """
    SELECT gp.person_id AS id, gp.name, p.phone, gp.rut,
           m.id AS membership_id, m.status, m.plan_id, pl.name AS plan_name
    FROM gym_person gp
    JOIN person p ON p.id = gp.person_id
    LEFT JOIN LATERAL (
        SELECT id, status, plan_id FROM membership
        WHERE gym_id = gp.gym_id AND person_id = gp.person_id
        ORDER BY status = 'cancelled', started_at DESC, created_at DESC
        LIMIT 1
    ) m ON true
    LEFT JOIN plan pl ON pl.id = m.plan_id
    WHERE m.id IS NOT NULL
       OR NOT EXISTS (SELECT FROM staff s WHERE s.person_id = gp.person_id)
"""

_LIKE_SPECIALS = re.compile(r"([\\%_])")


def _contains(value: str) -> str:
    return "%" + _LIKE_SPECIALS.sub(r"\\\1", value) + "%"


def _search(q: str) -> tuple[str, dict[str, Any]]:
    """`q` matched against the name, and, when it holds a digit, the phone and RUT as
    typed in any format (`9 8765 4321`, `7.654.321-6`)."""
    where = [f"{_fold('name')} LIKE {_fold(':name')} ESCAPE '\\'"]
    params: dict[str, Any] = {"name": _contains(q)}
    digits = re.sub(r"[^0-9]", "", q)
    if digits:
        where.append("phone LIKE :phone")
        params["phone"] = _contains(digits)
        where.append("replace(rut, '-', '') LIKE :rut")
        params["rut"] = _contains(re.sub(r"[^0-9K]", "", q.upper()))
    return "(" + " OR ".join(where) + ")", params


@router.get("")
async def list_people(
    session: StaffSession,
    q: Annotated[str, Query(max_length=100)] = "",
    # Repeatable, `?status=active&status=trial`. FastAPI copies the defaults per request.
    statuses: Annotated[list[MembershipStatus], Query(alias="status")] = [],  # noqa: B006
    plan_ids: Annotated[list[uuid.UUID], Query(alias="plan_id")] = [],  # noqa: B006
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemberPage:
    """The member list, by name. Filters combine with AND; several values of one filter
    with OR. `status` and `plan_id` match the membership each row shows."""
    where: list[str] = []
    params: dict[str, Any] = {}
    if q.strip():
        clause, params = _search(q.strip())
        where.append(clause)
    if statuses:
        where.append("status = ANY(CAST(:statuses AS text[]))")
        params["statuses"] = [s.value for s in statuses]
    if plan_ids:
        where.append("plan_id = ANY(CAST(:plan_ids AS uuid[]))")
        params["plan_ids"] = plan_ids
    filtered = f"SELECT * FROM ({MEMBERS}) members"
    if where:
        filtered += " WHERE " + " AND ".join(where)

    total = await session.scalar(text(f"SELECT count(*) FROM ({filtered}) f"), params)
    rows = await session.execute(
        text(f"{filtered} ORDER BY {_fold('name')}, id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    items = [
        MemberRow(
            id=row.id,
            name=row.name,
            phone=row.phone,
            rut=row.rut,
            membership=None
            if row.membership_id is None
            else MembershipSummary(
                id=row.membership_id,
                status=row.status,
                plan_id=row.plan_id,
                plan_name=row.plan_name,
            ),
        )
        for row in rows
    ]
    return MemberPage(items=items, total=total or 0)


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
