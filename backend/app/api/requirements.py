"""What the gym asks before someone trains, and each person's records of it (#349).

The list (`/api/requirements`, migration 0062): every staff role reads the ones it may
see; owner and admin (`AdminSession`) add, rename, reorder and deactivate them. Who
sees a requirement (`visible_to`) and whether it is `sensitive` are the owner's alone,
as for a custom field: an admin who sends either gets a 403. A requirement the caller
may not see is answered exactly as one that does not exist.

A person's (`/api/people/{id}/requirements`): every active requirement the caller
sees, with where the person stands on it (`app.domain.requirements`) by their current
record, the latest recorded. Every staff role that sees one may record it: the day it
was done, today by default and never after it, and a note. Records are never changed;
a new one takes the place of the last. A sensitive requirement's note is stored sealed
(`FieldCipher`, bound to the record), and is resealed or opened when the owner marks
the requirement sensitive or not.

A change to a requirement locks its row `FOR UPDATE`, and a record locks it `FOR
SHARE`, so a note is never stored in the clear while the owner is marking it sensitive.

The student page reads its own and its dependents' (`/api/me/requirements`): no notes,
which are the staff's.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.custom_fields import field_cipher
from app.api.history import refuse_outside_history
from app.api.people import NOT_FOUND, in_gym
from app.domain import custom_fields as cf
from app.domain.dates import gym_today
from app.domain.requirements import expires_on, state_of
from app.roles import FORBIDDEN, AdminSession, Role, StaffSession, role_in_gym
from app.schemas.requirements import (
    MyRequirement,
    PersonRequirement,
    PersonRequirements,
    Requirement,
    RequirementCreate,
    RequirementOrder,
    RequirementRecord,
    RequirementUpdate,
)
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(tags=["requirements"])

REQUIREMENT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "requirement not found")

CurrentTenant = Annotated[Tenant, Depends(current_tenant)]

# RLS keeps every query to the current gym.
SELECT_REQUIREMENT = "SELECT id, name, valid_months, sensitive, visible_to, active FROM requirement"
ORDER = " ORDER BY position, created_at, id"

# Each active requirement with the person's current record of it, if any.
CURRENT = text("""
    SELECT r.id, r.name, r.valid_months, r.sensitive, r.visible_to,
           c.id AS record_id, c.done_on, c.note, c.note_secret, c.recorded_at
    FROM requirement r
    LEFT JOIN LATERAL (
        SELECT pr.id, pr.done_on, pr.note, pr.note_secret, pr.recorded_at
        FROM person_requirement pr
        WHERE pr.requirement_id = r.id AND pr.person_id = :person
        ORDER BY pr.recorded_at DESC, pr.id DESC
        LIMIT 1
    ) c ON true
    WHERE r.active
    ORDER BY r.position, r.created_at, r.id
""")


# Whose requirements the student page shows: their own, unless they only pay for
# dependents (no plan of their own, and someone to pay for), then each dependent's.
# Unlike the classes' list, someone with no plan yet is there: a waiver comes first.
TRAINEES = text("""
    SELECT gp.person_id, gp.name FROM gym_person gp
    WHERE gp.person_id = :me
      AND (EXISTS (SELECT FROM membership m WHERE m.person_id = gp.person_id)
           OR NOT EXISTS (SELECT FROM guardian_link gl WHERE gl.guardian_person_id = :me))
    UNION ALL
    (SELECT gp.person_id, gp.name FROM guardian_link gl
     JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
     WHERE gl.guardian_person_id = :me
     ORDER BY lower(gp.name), gp.person_id)
""")


def bound_to(record_id: uuid.UUID) -> str:
    """What a record's sealed note is bound to, beside the gym and the person."""
    return f"requirement/{record_id}"


async def _role(session: AsyncSession, tenant: Tenant) -> Role:
    role = await role_in_gym(session, tenant)
    # The session dependency already refused anyone without a staff role.
    assert role is not None
    return role


async def _today(session: AsyncSession, tenant: Tenant) -> date:
    zone = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(str(zone))


def _sees(role: Role, visible_to: str) -> bool:
    return cf.sees(role, {"visible_to": visible_to})


def _only_the_owner(role: Role, sent: set[str]) -> None:
    if role is not Role.OWNER and sent & {"sensitive", "visible_to"}:
        raise FORBIDDEN


async def _all(session: AsyncSession, *, lock: bool = False) -> Sequence[Row[Any]]:
    sql = SELECT_REQUIREMENT + ORDER + (" FOR UPDATE" if lock else "")
    return (await session.execute(text(sql))).all()


async def _visible(session: AsyncSession, role: Role) -> list[Requirement]:
    return [
        Requirement.model_validate(r, from_attributes=True)
        for r in await _all(session)
        if _sees(role, r.visible_to)
    ]


async def _get(
    session: AsyncSession, role: Role, requirement_id: uuid.UUID, lock: str = ""
) -> Requirement:
    sql = f"{SELECT_REQUIREMENT} WHERE id = :id" + (f" FOR {lock}" if lock else "")
    row = (await session.execute(text(sql), {"id": requirement_id})).one_or_none()
    if row is None or not _sees(role, row.visible_to):
        raise REQUIREMENT_NOT_FOUND
    return Requirement.model_validate(row, from_attributes=True)


@router.get("/api/requirements")
async def list_requirements(tenant: CurrentTenant, session: StaffSession) -> list[Requirement]:
    """The requirements the caller sees, in order, inactive ones included."""
    return await _visible(session, await _role(session, tenant))


@router.post("/api/requirements", status_code=status.HTTP_201_CREATED)
async def create_requirement(
    body: RequirementCreate, tenant: CurrentTenant, session: AdminSession
) -> Requirement:
    role = await _role(session, tenant)
    _only_the_owner(role, body.model_fields_set)
    visible_to = body.visible_to or cf.default_visible_to(body.sensitive)
    created = await session.scalar(
        text(
            "INSERT INTO requirement (gym_id, name, valid_months, sensitive, visible_to, position)"
            " SELECT current_setting('app.gym_id')::uuid, :name, :valid_months, :sensitive,"
            " :visible_to, coalesce(max(position) + 1, 0) FROM requirement"
            " RETURNING id"
        ),
        {**body.model_dump(exclude={"visible_to"}), "visible_to": visible_to.value},
    )
    assert created is not None
    return await _get(session, role, created)


@router.put("/api/requirements/order")
async def reorder_requirements(
    body: RequirementOrder, tenant: CurrentTenant, session: AdminSession
) -> list[Requirement]:
    """Those the caller sees in the order of `ids`; the others keep their places."""
    role = await _role(session, tenant)
    rows = await _all(session, lock=True)
    defs = [{"key": str(r.id), "visible_to": r.visible_to} for r in rows]
    try:
        ordered = cf.reorder(defs, [str(i) for i in body.ids], role)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "send every requirement you see, once each"
        ) from None
    await session.execute(
        text(
            "UPDATE requirement SET position = o.position - 1"
            " FROM unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS o (id, position)"
            " WHERE requirement.id = o.id"
        ),
        {"ids": [uuid.UUID(d["key"]) for d in ordered]},
    )
    return await _visible(session, role)


@router.patch("/api/requirements/{requirement_id}")
async def update_requirement(
    requirement_id: uuid.UUID,
    body: RequirementUpdate,
    request: Request,
    tenant: CurrentTenant,
    session: AdminSession,
) -> Requirement:
    role = await _role(session, tenant)
    found = await _get(session, role, requirement_id, lock="UPDATE")
    changes = body.model_dump(exclude_unset=True)
    _only_the_owner(role, set(changes))
    if changes.get("sensitive") and not found.sensitive and "visible_to" not in changes:
        changes["visible_to"] = cf.VisibleTo.OWNER
    updated = found.model_copy(update=changes)
    if updated.sensitive != found.sensitive:
        await _reseal(session, tenant, field_cipher(request), requirement_id, updated.sensitive)
    await session.execute(
        text(
            "UPDATE requirement SET name = :name, valid_months = :valid_months,"
            " sensitive = :sensitive, visible_to = :visible_to, active = :active WHERE id = :id"
        ),
        {
            **updated.model_dump(include={"name", "valid_months", "sensitive", "active"}),
            "visible_to": cf.VisibleTo(updated.visible_to).value,
            "id": requirement_id,
        },
    )
    return await _get(session, role, requirement_id)


async def _reseal(
    session: AsyncSession,
    tenant: Tenant,
    cipher: cf.FieldCipher,
    requirement_id: uuid.UUID,
    sealed: bool,
) -> None:
    """Move the requirement's notes to `note_secret` (sealed) or back to `note`."""
    rows = await session.execute(
        text(
            "SELECT id, person_id, note, note_secret FROM person_requirement"
            " WHERE requirement_id = :id AND (note IS NOT NULL OR note_secret IS NOT NULL)"
        ),
        {"id": requirement_id},
    )
    for r in rows.all():
        if sealed:
            if r.note is None:
                continue
            note, secret = None, cipher.seal(tenant.gym_id, r.person_id, bound_to(r.id), r.note)
        else:
            if r.note_secret is None:
                continue
            note = cipher.open(tenant.gym_id, r.person_id, bound_to(r.id), r.note_secret)
            secret = None
        await session.execute(
            text(
                "UPDATE person_requirement SET note = :note, note_secret = :secret WHERE id = :id"
            ),
            {"note": note, "secret": secret, "id": r.id},
        )


# --- a person's records ---------------------------------------------------------


async def _current(session: AsyncSession, person_id: uuid.UUID) -> Sequence[Row[Any]]:
    return (await session.execute(CURRENT, {"person": person_id})).all()


async def _person_requirements(
    session: AsyncSession, tenant: Tenant, cipher: cf.FieldCipher, person_id: uuid.UUID
) -> list[PersonRequirement]:
    role = await _role(session, tenant)
    today = await _today(session, tenant)
    out = []
    for r in await _current(session, person_id):
        if not _sees(role, r.visible_to):
            continue
        note = r.note
        if r.note_secret is not None:
            note = cipher.open(tenant.gym_id, person_id, bound_to(r.record_id), r.note_secret)
        out.append(
            PersonRequirement(
                id=r.id,
                name=r.name,
                valid_months=r.valid_months,
                sensitive=r.sensitive,
                state=state_of(r.done_on, r.valid_months, today),
                done_on=r.done_on,
                expires_on=None if r.done_on is None else expires_on(r.done_on, r.valid_months),
                note=note,
                recorded_at=r.recorded_at,
            )
        )
    return out


@router.get("/api/people/{person_id}/requirements")
async def get_person_requirements(
    person_id: uuid.UUID, request: Request, tenant: CurrentTenant, session: StaffSession
) -> list[PersonRequirement]:
    """The gym's active requirements the caller sees, in order, with where the person
    stands on each."""
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    return await _person_requirements(session, tenant, field_cipher(request), person_id)


@router.post("/api/people/{person_id}/requirements/{requirement_id}")
async def record_requirement(
    person_id: uuid.UUID,
    requirement_id: uuid.UUID,
    body: RequirementRecord,
    request: Request,
    tenant: CurrentTenant,
    session: StaffSession,
) -> list[PersonRequirement]:
    """A new record of it, which becomes the person's current one; the last is kept."""
    if not await in_gym(session, person_id):
        raise NOT_FOUND
    role = await _role(session, tenant)
    # Held to the commit: whether the note is sealed is decided on a settled requirement.
    requirement = await _get(session, role, requirement_id, lock="SHARE")
    if not requirement.active:
        raise REQUIREMENT_NOT_FOUND
    refuse_outside_history("done_on", body.done_on, await _today(session, tenant))
    cipher = field_cipher(request)
    record_id = uuid.uuid4()
    note = body.note or None
    sealed = requirement.sensitive and note is not None
    await session.execute(
        text(
            "INSERT INTO person_requirement (id, gym_id, person_id, requirement_id, done_on,"
            " note, note_secret, recorded_by)"
            " VALUES (:id, :gym, :person, :requirement, :done_on, :note, :secret,"
            " current_setting('app.person_id')::uuid)"
        ),
        {
            "id": record_id,
            "gym": tenant.gym_id,
            "person": person_id,
            "requirement": requirement_id,
            "done_on": body.done_on,
            "note": None if sealed else note,
            "secret": cipher.seal(tenant.gym_id, person_id, bound_to(record_id), note)
            if sealed
            else None,
        },
    )
    return await _person_requirements(session, tenant, cipher, person_id)


# --- the student page ----------------------------------------------------------


@router.get("/api/me/requirements")
async def my_requirements(
    tenant: CurrentTenant, session: TenantSession
) -> list[PersonRequirements]:
    """The signed-in person's requirements and their dependents', each with every active
    requirement of the gym and where they stand on it. None when the gym has none."""
    today = await _today(session, tenant)
    out = []
    for who in (await session.execute(TRAINEES, {"me": tenant.person_id})).all():
        rows = await _current(session, who.person_id)
        if not rows:
            # The gym asks for nothing.
            return []
        out.append(
            PersonRequirements(
                person_id=who.person_id,
                name=who.name,
                requirements=[
                    MyRequirement(
                        id=r.id,
                        name=r.name,
                        state=state_of(r.done_on, r.valid_months, today),
                        done_on=r.done_on,
                        expires_on=None
                        if r.done_on is None
                        else expires_on(r.done_on, r.valid_months),
                    )
                    for r in rows
                ],
            )
        )
    return out
