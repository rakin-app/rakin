"""The gym's staff (`/api/staff`): who holds a role here, invite, change role, revoke.

Roles are per gym, a `staff` row for the person and the gym (app.roles), so each of
these is that row: an invite writes it, a change rewrites its role, a revoke deletes it.
A revoked person keeps the gym's record of them and everything that names them, such
as the classes they taught (migration 0020); with no membership either, their session
here ends at once (migration 0005).

An invite adds the person the way a member is added, through `join_gym`: by their RUT
when given, so a RUT another gym knows attaches that person without the gym learning
so, else by the email in this gym (migration 0036). Someone this gym already has, a
member say, keeps their record and gains the role; the invite's email becomes the
record's, since it is the address they sign in with. The phone is optional, a contact
only. It then emails them a sign-in link to the admin screens.

A sign-in with an email reaches only the gyms whose own record holds it (migration
0029), so the invite's email signs in to this gym and no other, whoever else knows the
person: it is always written, and the invite always goes to it.

Owner and admin manage the staff, and an admin only its coaches: making, unmaking or
revoking an admin is the owner's. The owner's own row is not changed here at all, so a
gym always keeps its owner.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import find_in_gym, give_identity, join_gym
from app.notices import STAFF_INVITE, Notice, Notices, get_notices
from app.roles import AdminSession, Role, role_in_gym
from app.schemas.staff import (
    AlreadyStaff,
    StaffConflict,
    StaffInvite,
    StaffMember,
    StaffRoleChange,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/staff", tags=["staff"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "not on this gym's staff")
OWNER_FIXED = HTTPException(status.HTTP_403_FORBIDDEN, "the owner's role is not changed here")
OWNERS_CALL = HTTPException(status.HTTP_403_FORBIDDEN, "only the owner manages admins")

# What the invite calls each role, as the person reads it.
ROLE_NAMES = {Role.ADMIN: "administrador", Role.COACH: "coach"}

# RLS keeps every table to the current gym.
SELECT_STAFF = """
    SELECT s.person_id, gp.name, gp.phone, gp.email, s.role, s.created_at AS since
    FROM staff s
    JOIN gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
"""

# The owner first, then admins, then coaches, each by name.
ORDER = "array_position(ARRAY['owner', 'admin', 'coach'], s.role), lower(gp.name), s.person_id"

Acting = Annotated[Tenant, Depends(current_tenant)]


def _may_manage(acting: Role | None, role: Role) -> None:
    """A 403 unless `acting` may give or take away `role`."""
    if role is Role.OWNER:
        raise OWNER_FIXED
    if role is Role.ADMIN and acting is not Role.OWNER:
        raise OWNERS_CALL


async def _get(session: AsyncSession, person_id: uuid.UUID) -> StaffMember:
    row = (
        await session.execute(text(f"{SELECT_STAFF} WHERE s.person_id = :id"), {"id": person_id})
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    return StaffMember.model_validate(row, from_attributes=True)


async def _role_of(session: AsyncSession, person_id: uuid.UUID) -> Role:
    """The role `person_id` holds here, locked until the request commits."""
    role = await session.scalar(
        text("SELECT role FROM staff WHERE person_id = :id FOR UPDATE"), {"id": person_id}
    )
    if role is None:
        raise NOT_FOUND
    return Role(role)


@router.get("")
async def list_staff(session: AdminSession) -> list[StaffMember]:
    rows = await session.execute(text(f"{SELECT_STAFF} ORDER BY {ORDER}"))
    return [StaffMember.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": AlreadyStaff}},
)
async def invite_staff(
    body: StaffInvite,
    tenant: Acting,
    session: AdminSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> StaffMember:
    role = Role(body.role)
    _may_manage(await role_in_gym(session, tenant), role)

    found = await find_in_gym(session, body.rut, body.email)
    if found is not None:
        # Whoever this gym has under the RUT, or, with no RUT of their own, the email.
        person_id, joined = found.person_id, False
        if found.by == "email_in_gym":
            await give_identity(session, person_id, body.rut, None)
    else:
        person_id, joined = await join_gym(
            session, name=body.name, rut=body.rut, email=body.email, phone=body.phone
        )
    # The insert is the check, so two invites of one person at once give a 409, not a 500.
    added = await session.scalar(
        text(
            "INSERT INTO staff (gym_id, person_id, role) VALUES (:gym, :id, :role)"
            " ON CONFLICT DO NOTHING RETURNING true"
        ),
        {"gym": tenant.gym_id, "id": person_id, "role": role.value},
    )
    if not added:
        # Raised, so the transaction rolls back; nothing was written.
        conflict = StaffConflict(person_id=person_id)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))
    # A record new here took the invite's email from `join_gym`; a known one did not.
    if not joined:
        await session.execute(
            text(
                "UPDATE gym_person SET email = :email, updated_at = now()"
                " WHERE person_id = :id AND email IS DISTINCT FROM :email"
            ),
            {"id": person_id, "email": body.email},
        )
    invited = await _get(session, person_id)
    assert invited.email is not None

    names = (
        await session.execute(
            text(
                "SELECT g.name AS gym, gp.name AS inviter FROM gym g"
                " JOIN gym_person gp ON gp.gym_id = g.id AND gp.person_id = :inviter"
                " WHERE g.id = :gym"
            ),
            {"gym": tenant.gym_id, "inviter": tenant.person_id},
        )
    ).one()
    notice = Notice(
        STAFF_INVITE,
        to=invited.email,
        person_id=person_id,
        gym_id=tenant.gym_id,
        context={
            "name": invited.name,
            "gym": names.gym,
            "inviter": names.inviter,
            "role": ROLE_NAMES[role],
            "role_is_coach": role is Role.COACH,
        },
    )
    # After the response, which is after the staff row has committed.
    background.add_task(notices.send, notice)
    return invited


@router.patch("/{person_id}")
async def change_role(
    person_id: uuid.UUID, body: StaffRoleChange, tenant: Acting, session: AdminSession
) -> StaffMember:
    """Move someone between admin and coach; the role they have already is a no-op."""
    acting = await role_in_gym(session, tenant)
    current = await _role_of(session, person_id)
    role = Role(body.role)
    _may_manage(acting, current)
    _may_manage(acting, role)
    if role is not current:
        await session.execute(
            text("UPDATE staff SET role = :role WHERE person_id = :id"),
            {"id": person_id, "role": role.value},
        )
    return await _get(session, person_id)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_staff(person_id: uuid.UUID, tenant: Acting, session: AdminSession) -> Response:
    _may_manage(await role_in_gym(session, tenant), await _role_of(session, person_id))
    await session.execute(text("DELETE FROM staff WHERE person_id = :id"), {"id": person_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
