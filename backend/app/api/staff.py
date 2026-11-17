"""The gym's team (`/api/staff`): who is on it, their appointments, and its history.

What a person may do here is the union of the gym's roles they hold today
(`app.permissions`). Each appointment is a row, from `starts_on` until the day before
`ends_on` (half-open, so a successor starts on the day it ends), with the role's name as
it was (docs/design/expenses-and-officers.md, sections 3, 4 and 8):

- `GET /api/staff`: everyone on the team, the titular first, each with what they may do
  today and the appointments that hold today or from a later day.
- `POST /api/staff`: invite someone, to one or more roles, from a day (today unless
  given) and until another if given; emails them a sign-in link naming the roles.
- `POST /{person_id}/appointments`: appoint one of the gym's people to a role. A 409
  when it overlaps one they hold to that role already, checked under a lock on the
  person, so two requests at once are one after the other.
- `POST /{person_id}/appointments/{id}/end` ("Terminar cargo"): it ends today. One that
  began today, or has yet to begin, ends on the day it starts: it granted nothing, and
  is kept for the history, so a same-day change of role still leaves a trail.
- `PATCH /{person_id}/appointments/{id}`: a correction of its dates, never of who holds
  it or which role; it may clear the contact shown with it, never set one (section 9).
- `DELETE /{person_id}`: end every appointment they hold, and take them off the team.
- `GET /api/staff/history` (Historial): every appointment, newest first, under the name
  its role had then.

Each write is audited in `audit_event`: `appointment_started`, `appointment_ended`,
`appointment_corrected`, with the dates before and after.

**The `staff` row follows the appointments.** A person's first appointment, current or
future, writes their row in the same transaction, so nothing has to run when it starts;
what they may do comes from the dates alone, at each request. Ending a person's last
appointment by hand deletes the row at once; a term that ends on its date leaves it to
the nightly job (`app.jobs.team`). Their requests are refused from the start of that
day either way. Without the row their session reaches the gym only as anyone with a
record there does (migrations 0005, 0042), never its staff screens. The titular's row is
never deleted: the titular holds the account, not an appointment.

An invite adds the person the way a member is added, through `join_gym`: by their RUT
when given, so a RUT another gym knows attaches that person without the gym learning
so, else by the email in this gym (migration 0036). Someone this gym already has, a
member say, keeps their record and joins the team; the invite's email becomes the
record's, since it is the address they sign in with. The phone is optional, a contact
only. A sign-in with an email reaches only the gyms whose own record holds it
(migration 0029), so the invite's email signs in to this gym and no other.

Whoever holds `team_manage` (`TeamSession`) manages the team, by the strictly-fewer
rule (`app.permissions.manages`, section 4): they appoint, end or correct only for a
person whose permissions today are a proper subset of theirs, and only to a role whose
permissions are a proper subset of theirs. So an Administrador manages Coaches and not
another Administrador, a Presidente of the Club federado preset appoints only a
Director, nobody grants a permission they lack, and the titular manages everyone. The
titular is not changed here at all, so a gym always keeps its titular, who can never be
locked out. Each refusal is a 403 that says which rule.
"""

import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import find_in_gym, give_identity, join_gym, refuse_email_in_gym
from app.notices import STAFF_INVITE, Notice, Notices, get_notices
from app.permissions import (
    NOBODY,
    Permission,
    Standing,
    TeamSession,
    manages,
    standing_in_gym,
    standing_of,
)
from app.roles import Role
from app.schemas.staff import (
    AlreadyStaff,
    Appointment,
    AppointmentCorrection,
    HistoryEntry,
    StaffAppointment,
    StaffConflict,
    StaffInvite,
    StaffMember,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/staff", tags=["staff"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "not on this gym's staff")
NOT_IN_GYM = HTTPException(status.HTTP_404_NOT_FOUND, "not one of this gym's people")
NO_TITLE = HTTPException(status.HTTP_404_NOT_FOUND, "no such role in this gym")
NOT_HELD = HTTPException(status.HTTP_404_NOT_FOUND, "they hold no such appointment")
OVERLAPS = HTTPException(
    status.HTTP_409_CONFLICT, "they hold this role already on some of those days"
)
BAD_TERM = HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "a term ends after it starts")
TITULAR_FIXED = HTTPException(status.HTTP_403_FORBIDDEN, "the account holder is not changed here")
NOT_FEWER_PERSON = HTTPException(
    status.HTTP_403_FORBIDDEN,
    "you manage only people whose permissions are strictly fewer than yours",
)
NOT_FEWER_ROLE = HTTPException(
    status.HTTP_403_FORBIDDEN,
    "you give only a role whose permissions are strictly fewer than yours",
)

APPOINTMENT_STARTED = "appointment_started"
APPOINTMENT_ENDED = "appointment_ended"
APPOINTMENT_CORRECTED = "appointment_corrected"

# RLS keeps every table to the current gym.
SELECT_STAFF = """
    SELECT s.person_id, gp.name, gp.phone, gp.email, s.role, s.created_at AS since,
           s.account_holder
    FROM staff s
    JOIN gym_person gp ON gp.gym_id = s.gym_id AND gp.person_id = s.person_id
"""

# The titular first, then everyone by name.
ORDER = "s.account_holder DESC, lower(gp.name), s.person_id"

# An appointment `st` that holds on `:today` or a later day: not ended, and not one that
# ended on the day it started.
LIVE = "(st.ends_on IS NULL OR st.ends_on > greatest(st.starts_on, :today))"

SELECT_LIVE = f"""
    SELECT st.id, st.person_id, st.title_id, t.name AS title_name, t.permissions,
           st.starts_on, st.ends_on, st.public_contact
    FROM staff_title st
    JOIN gym_title t ON t.id = st.title_id
    WHERE {LIVE}
"""
LIVE_ORDER = "st.starts_on, t.sort, lower(t.name), st.id"

# Another appointment of the person to the role, with a day in common with
# [`:starts`, `:ends`). One that ended on the day it started has none.
OVERLAP = """
    SELECT true FROM staff_title st
    WHERE st.person_id = :id AND st.title_id = :title AND st.id IS DISTINCT FROM :self
      AND (st.ends_on IS NULL OR st.ends_on > st.starts_on)
      AND st.starts_on < coalesce(CAST(:ends AS date), 'infinity'::date)
      AND CAST(:starts AS date) < coalesce(st.ends_on, 'infinity'::date)
    LIMIT 1
"""

# The `staff` row of someone who holds nothing today or later, unless they are the
# titular.
TIDY = f"""
    DELETE FROM staff s
    WHERE s.person_id = :id AND NOT s.account_holder
      AND NOT EXISTS (SELECT FROM staff_title st WHERE st.person_id = s.person_id AND {LIVE})
"""

# Whose the log row is; `now()` is the transaction's, as the policy wants it.
RECORD = """
    INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, detail)
    VALUES (current_setting('app.gym_id')::uuid, now(), current_setting('app.person_id')::uuid,
            :person, :action, CAST(:detail AS jsonb))
"""

Acting = Annotated[Tenant, Depends(current_tenant)]


async def acting_standing(session: AsyncSession, tenant: Tenant) -> Standing:
    standing = await standing_in_gym(session, tenant)
    # `TeamSession` already refused anyone not on the team.
    assert standing is not None
    return standing


async def gym_today(session: AsyncSession) -> date:
    """Today in the gym's timezone, as the database reads it at each request."""
    today: date = await session.scalar(text("SELECT (now() AT TIME ZONE timezone)::date FROM gym"))
    return today


async def record(
    session: AsyncSession, action: str, detail: dict[str, Any], person_id: uuid.UUID | None
) -> None:
    """A row of the gym's log, by the person acting, about `person_id` if any."""
    await session.execute(
        text(RECORD),
        {"person": person_id, "action": action, "detail": json.dumps(detail, default=str)},
    )


def _permissions(codes: list[str]) -> frozenset[Permission]:
    return frozenset(map(Permission, codes))


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


async def _lock_person(session: AsyncSession, tenant: Tenant, person_id: uuid.UUID) -> None:
    """Writes to one person's appointments one after the other, until the transaction
    ends: "do they hold this role then?" is a read before a write."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('rakin.appointment'), hashtext(:name))"),
        {"name": f"{tenant.gym_id}:{person_id}"},
    )


async def _in_gym(session: AsyncSession, person_id: uuid.UUID) -> None:
    found = await session.scalar(
        text("SELECT true FROM gym_person WHERE person_id = :id"), {"id": person_id}
    )
    if not found:
        raise NOT_IN_GYM


async def _overlaps(
    session: AsyncSession,
    person_id: uuid.UUID,
    title_id: uuid.UUID,
    starts_on: date,
    ends_on: date | None,
    self_id: uuid.UUID | None = None,
) -> bool:
    found = await session.scalar(
        text(OVERLAP),
        {
            "id": person_id,
            "title": title_id,
            "self": self_id,
            "starts": starts_on,
            "ends": ends_on,
        },
    )
    return bool(found)


async def titles_to_give(
    session: AsyncSession, acting: Standing, title_ids: list[uuid.UUID]
) -> list[Any]:
    """The gym's live roles `title_ids`, in that order, once `acting` may give each: a 404
    for one the gym has not, or has archived; a 403 for one not strictly fewer."""
    rows = {
        row.id: row
        for row in await session.execute(
            text(
                "SELECT id, name, permissions FROM gym_title"
                " WHERE id = ANY(:ids) AND archived_at IS NULL AND system IS NULL"
            ),
            {"ids": title_ids},
        )
    }
    if set(rows) != set(title_ids):
        raise NO_TITLE
    if not all(manages(acting, _permissions(rows[t].permissions)) for t in title_ids):
        raise NOT_FEWER_ROLE
    return [rows[t] for t in title_ids]


def _term(today: date, starts_on: date | None, ends_on: date | None) -> tuple[date, date | None]:
    starts = starts_on or today
    if ends_on is not None and ends_on <= starts:
        raise BAD_TERM
    return starts, ends_on


async def _appoint(
    session: AsyncSession,
    tenant: Tenant,
    person_id: uuid.UUID,
    title: Any,
    starts_on: date,
    ends_on: date | None,
) -> None:
    """Appoint `person_id` to `title` for the term, writing their `staff` row if this is
    their first appointment. The caller holds the person's lock."""
    if await _overlaps(session, person_id, title.id, starts_on, ends_on):
        raise OVERLAPS
    # The column is still NOT NULL until #313; nothing reads it.
    role = Role.ADMIN if Permission.GYM_SETUP in title.permissions else Role.COACH
    await session.execute(
        text(
            "INSERT INTO staff (gym_id, person_id, role) VALUES (:gym, :id, :role)"
            " ON CONFLICT DO NOTHING"
        ),
        {"gym": tenant.gym_id, "id": person_id, "role": role.value},
    )
    appointment = await session.scalar(
        text(
            "INSERT INTO staff_title"
            " (gym_id, person_id, title_id, title_name, starts_on, ends_on, created_by)"
            " VALUES (:gym, :id, :title, :name, :starts, :ends, :by) RETURNING id"
        ),
        {
            "gym": tenant.gym_id,
            "id": person_id,
            "title": title.id,
            "name": title.name,
            "starts": starts_on,
            "ends": ends_on,
            "by": tenant.person_id,
        },
    )
    await record(
        session,
        APPOINTMENT_STARTED,
        {
            "appointment_id": appointment,
            "title_id": title.id,
            "title_name": title.name,
            "starts_on": starts_on,
            "ends_on": ends_on,
        },
        person_id,
    )


async def _end(session: AsyncSession, tenant: Tenant, appointment: Any, today: date) -> None:
    """End `appointment` today, or on the day it starts if that is later."""
    ends_on = max(today, appointment.starts_on)
    await session.execute(
        text(
            "UPDATE staff_title SET ends_on = :ends, ended_by = :by, ended_at = now()"
            " WHERE id = :id"
        ),
        {"id": appointment.id, "ends": ends_on, "by": tenant.person_id},
    )
    await record(
        session,
        APPOINTMENT_ENDED,
        {
            "appointment_id": appointment.id,
            "title_id": appointment.title_id,
            "title_name": appointment.title_name,
            "starts_on": appointment.starts_on,
            "ends_on": ends_on,
        },
        appointment.person_id,
    )


async def _tidy(session: AsyncSession, person_id: uuid.UUID, today: date) -> None:
    """Take `person_id` off the team when they hold nothing today or later."""
    await session.execute(text(TIDY), {"id": person_id, "today": today})


async def _appointment(
    session: AsyncSession, person_id: uuid.UUID, appointment_id: uuid.UUID
) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT st.id, st.person_id, st.title_id, st.title_name, st.starts_on,"
                " st.ends_on, st.public_contact, t.permissions"
                " FROM staff_title st JOIN gym_title t ON t.id = st.title_id"
                " WHERE st.id = :id AND st.person_id = :person"
            ),
            {"id": appointment_id, "person": person_id},
        )
    ).one_or_none()
    if row is None:
        raise NOT_HELD
    return row


async def _members(
    session: AsyncSession, acting: Standing, today: date, person_id: uuid.UUID | None = None
) -> list[StaffMember]:
    """The team, or `person_id` alone, as the person acting `acting` sees it."""
    one = " WHERE s.person_id = :id" if person_id else ""
    params = {"id": person_id, "today": today}
    people = (await session.execute(text(f"{SELECT_STAFF}{one} ORDER BY {ORDER}"), params)).all()
    only = " AND st.person_id = :id" if person_id else ""
    held: dict[uuid.UUID, list[Any]] = {}
    for row in await session.execute(text(f"{SELECT_LIVE}{only} ORDER BY {LIVE_ORDER}"), params):
        held.setdefault(row.person_id, []).append(row)

    members = []
    for person in people:
        appointments = held.get(person.person_id, [])
        if person.account_holder:
            permissions = frozenset(Permission)
        else:
            current = [a for a in appointments if a.starts_on <= today]
            permissions = frozenset(p for a in current for p in _permissions(a.permissions))
        # `standing_of` reads someone with no current appointment as off the team.
        manageable = not person.account_holder and manages(acting, permissions)
        members.append(
            StaffMember(
                person_id=person.person_id,
                name=person.name,
                phone=person.phone,
                email=person.email,
                role=person.role,
                since=person.since,
                account_holder=person.account_holder,
                permissions=sorted(permissions, key=list(Permission).index),
                appointments=[
                    StaffAppointment(
                        id=a.id,
                        title_id=a.title_id,
                        title_name=a.title_name,
                        starts_on=a.starts_on,
                        ends_on=a.ends_on,
                        public_contact=a.public_contact,
                        manageable=manageable and manages(acting, _permissions(a.permissions)),
                    )
                    for a in appointments
                ],
                manageable=manageable,
            )
        )
    return members


async def _get(session: AsyncSession, tenant: Tenant, person_id: uuid.UUID) -> StaffMember:
    acting = await acting_standing(session, tenant)
    found = await _members(session, acting, await gym_today(session), person_id)
    if not found:
        raise NOT_FOUND
    return found[0]


@router.get("")
async def list_staff(tenant: Acting, session: TeamSession) -> list[StaffMember]:
    acting = await acting_standing(session, tenant)
    return await _members(session, acting, await gym_today(session))


@router.get("/history")
async def staff_history(session: TeamSession) -> list[HistoryEntry]:
    """Every appointment, newest first, under the name its role had when it was made."""
    rows = await session.execute(
        text(
            "SELECT st.id, st.person_id, gp.name AS person_name, st.title_name,"
            " st.starts_on, st.ends_on"
            " FROM staff_title st"
            " JOIN gym_person gp ON gp.gym_id = st.gym_id AND gp.person_id = st.person_id"
            " ORDER BY st.starts_on DESC, st.created_at DESC, st.id"
        )
    )
    return [HistoryEntry.model_validate(row, from_attributes=True) for row in rows]


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
    acting = await acting_standing(session, tenant)
    titles = await titles_to_give(session, acting, body.title_ids)
    starts_on, ends_on = _term(await gym_today(session), body.starts_on, body.ends_on)
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
    role = Role.ADMIN if any(Permission.GYM_SETUP in t.permissions for t in titles) else Role.COACH
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
    await _lock_person(session, tenant, person_id)
    for title in titles:
        await _appoint(session, tenant, person_id, title, starts_on, ends_on)
    # A record new here took the invite's email from `join_gym`; a known one did not.
    if not joined:
        await session.execute(
            text(
                "UPDATE gym_person SET email = :email, updated_at = now()"
                " WHERE person_id = :id AND email IS DISTINCT FROM :email"
            ),
            {"id": person_id, "email": body.email},
        )
    invited = await _get(session, tenant, person_id)
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
    granted = {Permission(p) for t in titles for p in t.permissions}
    notice = Notice(
        STAFF_INVITE,
        to=invited.email,
        person_id=person_id,
        gym_id=tenant.gym_id,
        context={
            "name": invited.name,
            "gym": names.gym,
            "inviter": names.inviter,
            "roles": [t.name for t in titles],
            # In the order Ajustes lists them.
            "can": [p.value for p in Permission if p in granted],
        },
    )
    # After the response, which is after the staff row has committed.
    background.add_task(notices.send, notice)
    return invited


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_staff(person_id: uuid.UUID, tenant: Acting, session: TeamSession) -> Response:
    """End today every appointment they hold today or later, and take them off the team."""
    acting = await acting_standing(session, tenant)
    on_team = await session.scalar(
        text("SELECT true FROM staff WHERE person_id = :id FOR UPDATE"), {"id": person_id}
    )
    if not on_team:
        raise NOT_FOUND
    await _may_manage_person(session, tenant, acting, person_id)
    await _lock_person(session, tenant, person_id)
    today = await gym_today(session)
    live = await session.execute(
        text(
            "SELECT st.id, st.person_id, st.title_id, st.title_name, st.starts_on"
            f" FROM staff_title st WHERE st.person_id = :id AND {LIVE}"
        ),
        {"id": person_id, "today": today},
    )
    for appointment in live.all():
        await _end(session, tenant, appointment, today)
    await session.execute(text("DELETE FROM staff WHERE person_id = :id"), {"id": person_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{person_id}/appointments", status_code=status.HTTP_201_CREATED)
async def appoint(
    person_id: uuid.UUID, body: Appointment, tenant: Acting, session: TeamSession
) -> StaffMember:
    """Appoint one of the gym's people to `body.title_id`, from `body.starts_on` (today
    unless given); a 409 when the term overlaps one they hold to it already."""
    acting = await acting_standing(session, tenant)
    await _in_gym(session, person_id)
    await _lock_person(session, tenant, person_id)
    await _may_manage_person(session, tenant, acting, person_id)
    [title] = await titles_to_give(session, acting, [body.title_id])
    starts_on, ends_on = _term(await gym_today(session), body.starts_on, body.ends_on)
    await _appoint(session, tenant, person_id, title, starts_on, ends_on)
    return await _get(session, tenant, person_id)


async def _to_manage(
    session: AsyncSession, tenant: Tenant, person_id: uuid.UUID, appointment_id: uuid.UUID
) -> Any:
    """The appointment, locked to the person acting, once they may change it: the person
    and the role each strictly fewer, an archived role's included."""
    acting = await acting_standing(session, tenant)
    await _lock_person(session, tenant, person_id)
    appointment = await _appointment(session, person_id, appointment_id)
    await _may_manage_person(session, tenant, acting, person_id)
    if not manages(acting, _permissions(appointment.permissions)):
        raise NOT_FEWER_ROLE
    return appointment


@router.post(
    "/{person_id}/appointments/{appointment_id}/end", status_code=status.HTTP_204_NO_CONTENT
)
async def end_appointment(
    person_id: uuid.UUID, appointment_id: uuid.UUID, tenant: Acting, session: TeamSession
) -> Response:
    """ "Terminar cargo": it ends today; a 404 when it holds no day from today on. Their
    last ended, they are off the team at once."""
    appointment = await _to_manage(session, tenant, person_id, appointment_id)
    today = await gym_today(session)
    if appointment.ends_on is not None and appointment.ends_on <= max(today, appointment.starts_on):
        raise NOT_HELD
    await _end(session, tenant, appointment, today)
    await _tidy(session, person_id, today)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{person_id}/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def correct_appointment(
    person_id: uuid.UUID,
    appointment_id: uuid.UUID,
    body: AppointmentCorrection,
    tenant: Acting,
    session: TeamSession,
) -> Response:
    """Correct the dates of an appointment, running, future or past, or clear the contact
    it shows. A 422 for a term that would end before it starts, a 409 for one that would
    overlap another of theirs to the role."""
    appointment = await _to_manage(session, tenant, person_id, appointment_id)
    sent = body.model_fields_set
    if "starts_on" in sent and body.starts_on is None:
        raise BAD_TERM
    before = {
        "starts_on": appointment.starts_on,
        "ends_on": appointment.ends_on,
        "public_contact": appointment.public_contact,
    }
    after = {**before, **{field: getattr(body, field) for field in sent}}
    if after == before:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if after["ends_on"] is not None and after["ends_on"] < after["starts_on"]:
        raise BAD_TERM
    empty = after["ends_on"] == after["starts_on"]
    if not empty and await _overlaps(
        session,
        person_id,
        appointment.title_id,
        after["starts_on"],
        after["ends_on"],
        appointment.id,
    ):
        raise OVERLAPS
    await session.execute(
        text(
            "UPDATE staff_title SET starts_on = :starts_on, ends_on = :ends_on,"
            " public_contact = :public_contact WHERE id = :id"
        ),
        {**after, "id": appointment.id},
    )
    changed = [field for field in after if after[field] != before[field]]
    await record(
        session,
        APPOINTMENT_CORRECTED,
        {
            "appointment_id": appointment.id,
            "title_id": appointment.title_id,
            "title_name": appointment.title_name,
            "before": {field: before[field] for field in changed},
            "after": {field: after[field] for field in changed},
        },
        person_id,
    )
    today = await gym_today(session)
    # A correction can make the term end before today, or start later: what they hold
    # today or later decides whether they stay on the team.
    await _tidy(session, person_id, today)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
