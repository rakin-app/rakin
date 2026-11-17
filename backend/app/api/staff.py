"""The gym's staff (`/api/staff`): who holds a role here, invite, change role, revoke.

Roles are per gym, a `staff` row for the person and the gym, and what they may do is
their appointment to one of the gym's roles (`app.permissions`): the Academia preset's
Administrador for an admin, its Coach for a coach. So each of these writes both: an
invite writes the row and an appointment from today, a change rewrites the row's role
and moves the appointment to the other role from today, a revoke ends the appointment
and deletes the row. The row's role is still written, though no policy reads it since
#309. An appointment that began only today is deleted rather than ended, since it
would end on the day it starts. A revoked person keeps the gym's record of them and
everything that names them, such as the classes they taught (migration 0020) and the
terms they held; with no membership either, their session here ends at once
(migration 0005).

An invite adds the person the way a member is added, through `join_gym`: by their RUT
when given, so a RUT another gym knows attaches that person without the gym learning
so, else by the email in this gym (migration 0036). Someone this gym already has, a
member say, keeps their record and gains the role; the invite's email becomes the
record's, since it is the address they sign in with. The phone is optional, a contact
only. It then emails them a sign-in link to the admin screens.

A sign-in with an email reaches only the gyms whose own record holds it (migration
0029), so the invite's email signs in to this gym and no other, whoever else knows the
person: it is always written, and the invite always goes to it.

Whoever holds `team_manage` (`TeamSession`) manages the team, by the strictly-fewer
rule (`app.permissions.manages`, docs/design/expenses-and-officers.md, section 4): they
invite, change, appoint, end or revoke only a person whose permissions today are a
proper subset of theirs, and only to a role whose permissions are a proper subset of
theirs. So an Administrador manages Coaches and not another Administrador, a Presidente
of the Club federado preset appoints only a Director, nobody grants a permission they
lack, and the titular manages everyone. The titular's own row is not changed here at
all, so a gym always keeps its titular. Each refusal is a 403 that says which rule.

`POST /{person_id}/appointments` appoints someone already on the staff list to one of
the gym's roles from today, and `DELETE /{person_id}/appointments/{title_id}` ends
theirs to it today. Their `staff` row and its role stay as they are: Equipo makes the
row follow the appointments (#311).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import find_in_gym, give_identity, join_gym, refuse_email_in_gym
from app.notices import STAFF_INVITE, Notice, Notices, get_notices
from app.permissions import (
    ACADEMIA,
    NOBODY,
    Permission,
    Standing,
    TeamSession,
    manages,
    preset_title_id,
    standing_in_gym,
    standing_of,
)
from app.roles import TITLE_OF, Role
from app.schemas.staff import (
    AlreadyStaff,
    Appointment,
    StaffConflict,
    StaffInvite,
    StaffMember,
    StaffRoleChange,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/staff", tags=["staff"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "not on this gym's staff")
NO_TITLE = HTTPException(status.HTTP_404_NOT_FOUND, "no such role in this gym")
NOT_HELD = HTTPException(status.HTTP_404_NOT_FOUND, "they hold no such appointment")
HOLDS_IT = HTTPException(status.HTTP_409_CONFLICT, "they hold this role already")
TITULAR_FIXED = HTTPException(status.HTTP_403_FORBIDDEN, "the account holder is not changed here")
NOT_FEWER_PERSON = HTTPException(
    status.HTTP_403_FORBIDDEN,
    "you manage only people whose permissions are strictly fewer than yours",
)
NOT_FEWER_ROLE = HTTPException(
    status.HTTP_403_FORBIDDEN,
    "you give only a role whose permissions are strictly fewer than yours",
)

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

# An appointment from today, in the gym's timezone, to the role `:title`, under the
# name it has today.
APPOINT = """
    INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on, created_by)
    SELECT t.gym_id, :id, t.id, t.name, (now() AT TIME ZONE g.timezone)::date, :by
    FROM gym_title t JOIN gym g ON g.id = t.gym_id
    WHERE t.id = :title
    RETURNING id
"""

# The person's appointments that hold today or later, ended today: from today on they
# hold none. One that began before today ends today; the rest never ran a day, and are
# deleted, since a term ends after it starts.
TODAY = "(SELECT (now() AT TIME ZONE timezone)::date FROM gym WHERE id = staff_title.gym_id)"
END_APPOINTMENTS = f"""
    UPDATE staff_title SET ends_on = {TODAY}, ended_by = :by, ended_at = now()
    WHERE person_id = :id AND starts_on < {TODAY} AND (ends_on IS NULL OR ends_on > {TODAY})
"""
DROP_UNSTARTED = f"""
    DELETE FROM staff_title
    WHERE person_id = :id AND starts_on >= {TODAY} AND (ends_on IS NULL OR ends_on > {TODAY})
"""

Acting = Annotated[Tenant, Depends(current_tenant)]


async def _acting(session: AsyncSession, tenant: Tenant) -> Standing:
    standing = await standing_in_gym(session, tenant)
    # `TeamSession` already refused anyone not on the team.
    assert standing is not None
    return standing


async def _may_manage_person(
    session: AsyncSession, tenant: Tenant, acting: Standing, person_id: uuid.UUID
) -> None:
    """A 403 unless `acting` may manage `person_id`: never the titular, and otherwise
    someone holding strictly fewer permissions today (none, off the team)."""
    standing = await standing_of(session, tenant.gym_id, person_id) or NOBODY
    if standing.account_holder:
        raise TITULAR_FIXED
    if not manages(acting, standing.permissions):
        raise NOT_FEWER_PERSON


async def _may_give(session: AsyncSession, acting: Standing, title_id: uuid.UUID) -> None:
    """A 403 unless `acting` may appoint someone to, or end, the gym's role `title_id`;
    a 404 when the gym has no such role, unarchived."""
    permissions = await session.scalar(
        text("SELECT permissions FROM gym_title WHERE id = :id AND archived_at IS NULL"),
        {"id": title_id},
    )
    if permissions is None:
        raise NO_TITLE
    if not manages(acting, frozenset(map(Permission, permissions))):
        raise NOT_FEWER_ROLE


def _academia(tenant: Tenant, role: Role) -> uuid.UUID:
    """The gym's Academia role that `role` stands for."""
    return preset_title_id(tenant.gym_id, ACADEMIA, TITLE_OF[role].key)


async def _appoint(
    session: AsyncSession, tenant: Tenant, person_id: uuid.UUID, title_id: uuid.UUID
) -> None:
    """Appoint `person_id` from today to the gym's role `title_id`."""
    appointed = await session.scalar(
        text(APPOINT), {"id": person_id, "title": title_id, "by": tenant.person_id}
    )
    # `_may_give` found the role: every gym is given the Academia ones (0065).
    assert appointed is not None, f"gym {tenant.gym_id} has no role {title_id}"


async def _end_appointments(
    session: AsyncSession, tenant: Tenant, person_id: uuid.UUID, title_id: uuid.UUID | None = None
) -> bool:
    """End today what `person_id` holds today or later, of `title_id` alone when given;
    whether there was any."""
    only, params = "", {"id": person_id}
    if title_id is not None:
        only, params = " AND title_id = :title", {**params, "title": title_id}
    ended = await session.execute(
        text(f"{END_APPOINTMENTS}{only} RETURNING id"), {**params, "by": tenant.person_id}
    )
    dropped = await session.execute(text(f"{DROP_UNSTARTED}{only} RETURNING id"), params)
    return bool(ended.all()) | bool(dropped.all())


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
async def list_staff(session: TeamSession) -> list[StaffMember]:
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
    session: TeamSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> StaffMember:
    role = Role(body.role)
    acting = await _acting(session, tenant)
    await _may_give(session, acting, _academia(tenant, role))
    # One invite of an email, and of a RUT, at a time: `find_in_gym` matches either, so a
    # second waits and finds the first's person, a 409, instead of creating another
    # (#204). Taken in one order, so two invites never wait on each other; released when
    # the transaction ends.
    locks = {f"email:{body.email.lower()}"} | ({f"rut:{body.rut.lower()}"} if body.rut else set())
    for name in sorted(locks):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('rakin.invite'), hashtext(:name))"),
            {"name": f"{tenant.gym_id}:{name}"},
        )

    found = await find_in_gym(session, body.rut, body.email)
    if found is not None:
        # Whoever this gym has under the RUT, or, with no RUT of their own, the email.
        person_id, joined = found.person_id, False
        if found.by == "email_in_gym":
            await give_identity(session, person_id, body.rut, None)
    else:
        await refuse_email_in_gym(session, body.email)
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
    await _appoint(session, tenant, person_id, _academia(tenant, role))
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
    person_id: uuid.UUID, body: StaffRoleChange, tenant: Acting, session: TeamSession
) -> StaffMember:
    """Move someone between admin and coach; the role they have already is a no-op."""
    acting = await _acting(session, tenant)
    current = await _role_of(session, person_id)
    role = Role(body.role)
    await _may_manage_person(session, tenant, acting, person_id)
    await _may_give(session, acting, _academia(tenant, role))
    if role is not current:
        await session.execute(
            text("UPDATE staff SET role = :role WHERE person_id = :id"),
            {"id": person_id, "role": role.value},
        )
        await _end_appointments(session, tenant, person_id)
        await _appoint(session, tenant, person_id, _academia(tenant, role))
    return await _get(session, person_id)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_staff(person_id: uuid.UUID, tenant: Acting, session: TeamSession) -> Response:
    acting = await _acting(session, tenant)
    await _role_of(session, person_id)
    await _may_manage_person(session, tenant, acting, person_id)
    await _end_appointments(session, tenant, person_id)
    await session.execute(text("DELETE FROM staff WHERE person_id = :id"), {"id": person_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{person_id}/appointments", status_code=status.HTTP_201_CREATED)
async def appoint(
    person_id: uuid.UUID, body: Appointment, tenant: Acting, session: TeamSession
) -> StaffMember:
    """Appoint someone on the staff list to `body.title_id` from today; a 409 when they
    hold it today or from a later day already."""
    acting = await _acting(session, tenant)
    # Locks their row, so two appointments of them at once are one after the other.
    await _role_of(session, person_id)
    await _may_manage_person(session, tenant, acting, person_id)
    await _may_give(session, acting, body.title_id)
    held = await session.scalar(
        text(
            "SELECT true FROM staff_title WHERE person_id = :id AND title_id = :title"
            f" AND (ends_on IS NULL OR ends_on > {TODAY})"
        ),
        {"id": person_id, "title": body.title_id},
    )
    if held:
        raise HOLDS_IT
    await _appoint(session, tenant, person_id, body.title_id)
    return await _get(session, person_id)


@router.delete("/{person_id}/appointments/{title_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_appointment(
    person_id: uuid.UUID, title_id: uuid.UUID, tenant: Acting, session: TeamSession
) -> Response:
    """End today their appointment to `title_id`, running or yet to start; a 404 when
    they hold none."""
    acting = await _acting(session, tenant)
    await _role_of(session, person_id)
    await _may_manage_person(session, tenant, acting, person_id)
    await _may_give(session, acting, title_id)
    if not await _end_appointments(session, tenant, person_id, title_id):
        raise NOT_HELD
    return Response(status_code=status.HTTP_204_NO_CONTENT)
