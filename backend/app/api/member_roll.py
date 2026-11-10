"""Members in and out by hand (#157): add one, dar de baja, reactivar, eliminar.

`POST /api/people/enrol` adds a member as the import would, all or nothing: their
record, by RUT or email as anyone joins (`add_to_gym`, #165) or, for a dependent with
neither, by name alone; the guardian a minor needs, someone already here or someone new
by their RUT or email; the gym's custom fields; and the plan they start on, with the
welcome if asked. A RUT someone in this gym already has, or the email of someone here
when no RUT is given, is a 409 naming them, as for `POST /api/people`; a new guardian
whose RUT or email is someone's here is that person.

`POST .../leave` is the normal way out (dado de baja): every membership they hold ends
with the reason `dado de baja` (`app.domain.membership.leave`), so billing writes no
new period and the roster, the inactive list and "Hoy" no longer count them, and the
member list leaves them out by `gym_person.left_on` (migration 0032). Whatever they
owe stays owed. `POST .../return` (reactivar) brings them back, on a plan again if
given one.

`DELETE /api/people/{id}` is for a mistake or a data-deletion request: it deletes this
gym's records of someone with no ledger entries here (`forget_gym_person`, 0032), and
answers why not otherwise; `GET .../deletion` answers the same without deleting.

Adding, leaving and returning are the owner's and admins': each starts or ends what a
member is charged. Deleting is the owner's alone.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.custom_fields import field_cipher, write_person_fields
from app.api.guardians import link
from app.api.memberships import CALL_OFF_BOOKED, start_membership, welcome_for
from app.api.people import NOT_FOUND, add_to_gym, in_gym, join_gym, read_person
from app.domain import membership as domain
from app.domain.dates import add_months, gym_today, is_minor
from app.domain.membership import MembershipStatus, PlanKind
from app.notices import Notices, get_notices
from app.roles import AdminSession, OwnerSession
from app.schemas.guardians import FamilyConflict, FamilyRefused
from app.schemas.memberships import STARTED_ON_WINDOW_YEARS
from app.schemas.people import (
    Deletion,
    Enrolment,
    ExistingGuardian,
    ForgetConflict,
    ForgetRefused,
    Leaving,
    NewGuardian,
    Person,
    PersonInGym,
    Return,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/people", tags=["people"])

CurrentTenant = Annotated[Tenant, Depends(current_tenant)]

# Whoever this gym's record gives the RUT. RLS keeps it to the gym.
RUT_IN_GYM = text("SELECT person_id FROM gym_person WHERE rut = :rut LIMIT 1")

# A phone, or "No tiene WhatsApp", for a record that has neither.
FILL_CONTACT = text("""
    UPDATE gym_person
    SET phone = coalesce(phone, :phone), no_whatsapp = no_whatsapp OR :no_whatsapp
    WHERE person_id = :id AND phone IS NULL AND NOT no_whatsapp
""")
REACHABLE = text("SELECT phone IS NOT NULL OR no_whatsapp FROM gym_person WHERE person_id = :id")

# Their record, locked so a leave and a return take turns. RLS keeps it to the gym.
LOCK_RECORD = text("SELECT left_on FROM gym_person WHERE person_id = :id FOR UPDATE")

# Every membership they hold that has not ended, locked, in id order as every
# request takes them.
LOCK_LIVE = text(
    "SELECT m.id, pl.kind, m.status FROM membership m JOIN plan pl ON pl.id = m.plan_id"
    " WHERE m.person_id = :id AND m.status <> 'cancelled' ORDER BY m.id FOR UPDATE OF m"
)

# A running freeze ends with the membership, today.
END_RUNNING_FREEZE = text(
    "UPDATE membership_freeze SET to_date = :today"
    " WHERE membership_id = :id AND started AND to_date > :today"
)

END_MEMBERSHIP = text(
    "UPDATE membership SET status = :status, cancel_reason = :reason, cancelled_at = now(),"
    " next_plan_id = NULL, next_plan_from = NULL"
    " WHERE id = :id"
)

SET_LEFT_ON = text(
    "UPDATE gym_person SET left_on = :left_on, updated_at = now() WHERE person_id = :id"
)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


async def _today(session: AsyncSession, tenant: Tenant) -> date:
    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(timezone)


async def _guardian(session: AsyncSession, body: Enrolment) -> uuid.UUID | None:
    """The guardian `body` names, added to the gym if new to it. They are who the gym
    messages about the minor, so they need a phone, or "No tiene WhatsApp" ticked: a new
    guardian's fills in one this gym's record lacks."""
    guardian = body.guardian
    if guardian is None:
        return None
    if isinstance(guardian, ExistingGuardian):
        if not await in_gym(session, guardian.person_id):
            raise _unprocessable("guardian not found")
        guardian_id = guardian.person_id
    elif (found := await session.scalar(RUT_IN_GYM, {"rut": guardian.rut})) is not None:
        # Their RUT is who they are, so the guardian is whoever here has it.
        guardian_id = found
    else:
        # Whoever they are, here already (by RUT, or by email with none) or new.
        guardian_id, _ = await join_gym(session, **guardian.model_dump())
    if isinstance(guardian, NewGuardian):
        await session.execute(
            FILL_CONTACT,
            {"id": guardian_id, "phone": guardian.phone, "no_whatsapp": guardian.no_whatsapp},
        )
    if not await session.scalar(REACHABLE, {"id": guardian_id}):
        raise _unprocessable("the guardian needs a phone, or no_whatsapp")
    return guardian_id


async def _member(session: AsyncSession, body: Enrolment) -> uuid.UUID:
    """The new member's record in this gym, by RUT or email, or by name alone, for a
    dependent, with neither."""
    return await add_to_gym(
        session,
        name=body.name,
        rut=body.rut,
        email=body.email,
        phone=body.phone,
        no_whatsapp=body.no_whatsapp,
        dob=body.dob,
    )


@router.post(
    "/enrol",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {"model": PersonInGym | FamilyRefused},
    },
)
async def enrol(
    body: Enrolment,
    request: Request,
    tenant: CurrentTenant,
    session: AdminSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Person:
    """Add a member by hand; on a refusal nothing is written. A minor needs a guardian."""
    if (
        body.dob is not None
        and body.guardian is None
        and is_minor(body.dob, await _today(session, tenant))
    ):
        raise _unprocessable("a minor needs a guardian")
    guardian_id = await _guardian(session, body)
    person_id = await _member(session, body)
    if guardian_id is not None and (code := await link(session, guardian_id, person_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, FamilyConflict(code=code).model_dump())
    if body.fields:
        await write_person_fields(session, tenant, field_cipher(request), person_id, body.fields)
    if body.membership is not None:
        created = await start_membership(session, tenant, person_id, body.membership)
        if body.send_welcome and (notice := await welcome_for(session, tenant, created)):
            # After the response, which is after the member has committed.
            background.add_task(notices.send, notice)
    return await read_person(session, person_id)


@router.post("/{person_id}/leave")
async def leave(
    person_id: uuid.UUID, body: Leaving, tenant: CurrentTenant, session: AdminSession
) -> Person:
    """Dar de baja from `left_on`: every membership they hold ends now, so nothing more
    is billed, and what is owed stays owed. A 409 if they have already left."""
    record = (await session.execute(LOCK_RECORD, {"id": person_id})).one_or_none()
    if record is None:
        raise NOT_FOUND
    if record.left_on is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already left the gym")
    today = await _today(session, tenant)
    left_on = body.left_on or today
    if left_on > today:
        raise _unprocessable("a member leaves today at the latest")
    if left_on < add_months(today, -12 * STARTED_ON_WINDOW_YEARS):
        raise _unprocessable(f"left_on must be within {STARTED_ON_WINDOW_YEARS} years of today")

    for row in (await session.execute(LOCK_LIVE, {"id": person_id})).all():
        ended = domain.leave(domain.Membership(PlanKind(row.kind), MembershipStatus(row.status)))
        await session.execute(CALL_OFF_BOOKED, {"id": row.id})
        await session.execute(END_RUNNING_FREEZE, {"id": row.id, "today": today})
        await session.execute(
            END_MEMBERSHIP,
            {"id": row.id, "status": ended.status.value, "reason": ended.cancel_reason},
        )
    await session.execute(SET_LEFT_ON, {"id": person_id, "left_on": left_on})
    return await read_person(session, person_id)


@router.post("/{person_id}/return")
async def return_to_gym(
    person_id: uuid.UUID, body: Return, tenant: CurrentTenant, session: AdminSession
) -> Person:
    """Reactivar: back on the member list, and on `body.membership`'s plan if given.
    No welcome: they know the gym. A 409 if they have not left."""
    record = (await session.execute(LOCK_RECORD, {"id": person_id})).one_or_none()
    if record is None:
        raise NOT_FOUND
    if record.left_on is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "has not left the gym")
    await session.execute(SET_LEFT_ON, {"id": person_id, "left_on": None})
    if body.membership is not None:
        await start_membership(session, tenant, person_id, body.membership)
    return await read_person(session, person_id)


@router.get("/{person_id}/deletion")
async def deletion(person_id: uuid.UUID, session: OwnerSession) -> Deletion:
    """Whether `DELETE` would delete them, and if not why: for the screen to say so
    before it is asked."""
    code = await session.scalar(text("SELECT forget_refusal(:id)"), {"id": person_id})
    if code == "not_found":
        raise NOT_FOUND
    return Deletion(refused=code)


@router.delete(
    "/{person_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_409_CONFLICT: {"model": ForgetRefused}},
)
async def forget(person_id: uuid.UUID, session: OwnerSession) -> Response:
    """Eliminar: this gym's records of them, gone. Refused, writing nothing, while they
    have ledger entries here, are staff, or answer for a dependent."""
    code = await session.scalar(text("SELECT forget_gym_person(:id)"), {"id": person_id})
    if code == "not_found":
        raise NOT_FOUND
    if code is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, ForgetConflict(code=code).model_dump())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
