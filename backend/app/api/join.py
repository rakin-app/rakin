"""The join link (#154): a gym shares one link, people fill in their own details, and
staff approve them into members.

- `/api/join-link` is the gym's link, for owner and admin: generate it (a new token,
  so the old one stops working), change the program it pre-selects or the last day
  it works, and revoke it.
- `/api/join/{token}` is the public form behind it, for anyone with the link and no
  session. A `GET` says what the form shows; a `POST` leaves a request in the queue,
  not a person, and answers 202 whatever it holds: nothing in the answer says
  whether the phone, RUT or email is someone's already, here or in another gym. A
  token that is unknown, revoked or past its last day answers 404 `invalid_link`.
  Sending is rate-limited per IP and per link, a filled-in honeypot is answered
  like any submission and stores nothing, and with a human check configured
  (`app.integrations.humancheck`) its token must pass.
- `/api/join-requests` is the queue, for every staff role: each request with whoever
  in this gym already has its phone or RUT, approving one and rejecting one.

Approving adds the person through the importer's writer (`app.api.member_import`), so
they are added exactly as a row of the gym's spreadsheet would be: found again by
phone in this gym, else joined by phone (`join_gym_by_phone`, so a phone another gym
knows attaches that identity without this gym learning so), a minor with their
guardian, linked. Whoever is already here keeps this gym's record of them. With a
plan, a membership starts on it today and the welcome goes out with its sign-in
link; that is owner and admin only, since a plan is money, so a coach approves with
no plan and the member shows as "sin plan". Without one, `join_approved` tells them
they are in. Either way the request is deleted: it was only ever a request.
Rejecting deletes it too, and the nightly `join_requests` job deletes any left for
30 days (`app.jobs.join_requests`).

The email the request carries is written into this gym's record of the person, which
signs in to this gym and no other (migration 0029).
"""

import math
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.member_import import RowRefused, Writer
from app.api.memberships import start_membership
from app.api.unsubscribe import in_gym
from app.contacts import contact_for
from app.domain.dates import gym_today
from app.integrations import Integrations, get_integrations
from app.magiclink.ratelimit import MemoryRateLimiter, RateLimiter
from app.member_import.rows import Member
from app.notices import JOIN_APPROVED, Notice, Notices, get_notices
from app.roles import ADMIN_ROLES, AdminSession, StaffSession, role_in_gym
from app.schemas.join import (
    ADULT_AGE,
    JoinApproval,
    JoinApproved,
    JoinForm,
    JoinGuardian,
    JoinLink,
    JoinLinkOptions,
    JoinRefusal,
    JoinRefused,
    JoinRequest,
    JoinSubmission,
    age_on,
)
from app.schemas.people import PersonRef
from app.tenancy import Tenant, current_tenant

public = APIRouter(prefix="/api/join", tags=["join"])
router = APIRouter(prefix="/api", tags=["join"])

# Where the SPA serves the form. On the bare host until gyms have their own (#155).
FORM_PATH = "/unirse"

# The gym's WiFi is one IP for everyone at the mat, so a class signing up together
# fits; a script does not.
PER_IP = (20, 3600.0)
PER_LINK = (100, 3600.0)

INVALID_LINK = HTTPException(status.HTTP_404_NOT_FOUND, "invalid_link")
NO_LINK = HTTPException(status.HTTP_404_NOT_FOUND, "no join link")
NO_REQUEST = HTTPException(status.HTTP_404_NOT_FOUND, "join request not found")
PLAN_IS_MONEY = HTTPException(status.HTTP_403_FORBIDDEN, "only an owner or admin gives a plan")


@dataclass(frozen=True)
class JoinLimits:
    per_ip: RateLimiter
    per_link: RateLimiter


def build_join_limits() -> JoinLimits:
    return JoinLimits(
        per_ip=MemoryRateLimiter(limit=PER_IP[0], window_seconds=PER_IP[1]),
        per_link=MemoryRateLimiter(limit=PER_LINK[0], window_seconds=PER_LINK[1]),
    )


def new_token() -> str:
    return secrets.token_urlsafe(24)


def link_url(request: Request, token: str) -> str:
    base: str = request.app.state.settings.public_base_url
    return f"{base.rstrip('/')}{FORM_PATH}/{token}"


# --- the gym's link (owner and admin) -------------------------------------------------

# RLS keeps every table to the current gym.
SELECT_LINK = """
    SELECT l.token, l.program_id, pr.name AS program_name, l.expires_on, l.created_at,
           g.timezone
    FROM join_link l
    JOIN gym g ON g.id = l.gym_id
    LEFT JOIN program pr ON pr.gym_id = l.gym_id AND pr.id = l.program_id
"""


async def _link(request: Request, session: AsyncSession) -> JoinLink:
    row = (await session.execute(text(SELECT_LINK))).one_or_none()
    if row is None:
        raise NO_LINK
    return JoinLink(
        url=link_url(request, row.token),
        token=row.token,
        program_id=row.program_id,
        program_name=row.program_name,
        expires_on=row.expires_on,
        expired=row.expires_on is not None and row.expires_on < gym_today(row.timezone),
        created_at=row.created_at,
    )


async def _check_program(session: AsyncSession, program_id: uuid.UUID | None) -> None:
    if program_id is None:
        return
    found = await session.scalar(
        text("SELECT true FROM program WHERE id = :id"), {"id": program_id}
    )
    if not found:
        raise RequestValidationError(
            [{"type": "unknown_program", "loc": ("body", "program_id"), "msg": "no such program"}]
        )


@router.get("/join-link")
async def get_join_link(request: Request, session: AdminSession) -> JoinLink:
    """The gym's link; a 404 when it has none."""
    return await _link(request, session)


@router.post("/join-link", status_code=status.HTTP_201_CREATED)
async def generate_join_link(
    body: JoinLinkOptions,
    request: Request,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> JoinLink:
    """A new link with these options. Any link the gym had stops working."""
    await _check_program(session, body.program_id)
    await session.execute(
        text(
            "INSERT INTO join_link (gym_id, token, program_id, expires_on)"
            " VALUES (:gym, :token, :program_id, :expires_on)"
            " ON CONFLICT (gym_id) DO UPDATE SET token = EXCLUDED.token,"
            " program_id = EXCLUDED.program_id, expires_on = EXCLUDED.expires_on,"
            " created_at = now()"
        ),
        {"gym": tenant.gym_id, "token": new_token(), **body.model_dump()},
    )
    return await _link(request, session)


@router.patch("/join-link")
async def change_join_link(
    body: JoinLinkOptions, request: Request, session: AdminSession
) -> JoinLink:
    """Change what the link says, keeping its token: only the fields sent change."""
    changes = body.model_dump(exclude_unset=True)
    if "program_id" in changes:
        await _check_program(session, body.program_id)
    if changes:
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        result = await session.execute(text(f"UPDATE join_link SET {assignments}"), changes)
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise NO_LINK
    return await _link(request, session)


@router.delete("/join-link", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_join_link(session: AdminSession) -> Response:
    """The link stops working. Requests already sent stay in the queue."""
    await session.execute(text("DELETE FROM join_link"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the public form ------------------------------------------------------------------

Token = Annotated[str, Path(min_length=20, max_length=64)]

# The link, read with `app.gym_id` set to its gym.
FORM = """
    SELECT g.name AS gym, g.timezone, pr.id AS program_id, pr.name AS program,
           l.expires_on
    FROM join_link l
    JOIN gym g ON g.id = l.gym_id
    LEFT JOIN program pr ON pr.gym_id = l.gym_id AND pr.id = l.program_id
    WHERE l.token = :token
"""


@dataclass(frozen=True)
class _OpenLink:
    gym: str
    timezone: str
    program_id: uuid.UUID | None
    program: str | None
    session: AsyncSession


@asynccontextmanager
async def _open(request: Request, token: str) -> AsyncIterator[_OpenLink]:
    """The link's gym, in a transaction acting there; a 404 when it does not work."""
    async with request.app.state.sessionmaker() as lookup:
        gym_id = await lookup.scalar(text("SELECT join_link_gym(:token)"), {"token": token})
    if gym_id is None:
        raise INVALID_LINK
    async with in_gym(request, gym_id) as session:
        row = (await session.execute(text(FORM), {"token": token})).one_or_none()
        # Revoked or regenerated between the two, or past its last day.
        if row is None or (row.expires_on is not None and row.expires_on < gym_today(row.timezone)):
            raise INVALID_LINK
        yield _OpenLink(row.gym, row.timezone, row.program_id, row.program, session)


@public.get("/{token}")
async def join_form(
    token: Token,
    request: Request,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> JoinForm:
    async with _open(request, token) as link:
        return JoinForm(
            gym=link.gym,
            program=link.program,
            today=gym_today(link.timezone),
            human_check_site_key=integrations.human_check.site_key,
        )


def _missing(*fields: str) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "missing", "loc": ("body", f), "msg": "Field required"} for f in fields]
    )


def _admit(request: Request, token: str, ip: str) -> None:
    limits: JoinLimits = request.app.state.join_limits
    for limiter, key in ((limits.per_ip, ip), (limits.per_link, token)):
        retry_after = limiter.hit(key)
        if retry_after is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "too many requests; try again later",
                headers={"Retry-After": str(math.ceil(retry_after))},
            )


INSERT_REQUEST = """
    INSERT INTO join_request (gym_id, first_name, last_name, rut, phone, email, dob,
                              guardian_name, guardian_phone, guardian_email, program_id,
                              consented_at)
    VALUES (current_setting('app.gym_id')::uuid, :first_name, :last_name, :rut, :phone,
            :email, :dob, :guardian_name, :guardian_phone, :guardian_email, :program_id,
            now())
"""


@public.post(
    "/{token}",
    status_code=status.HTTP_202_ACCEPTED,
    responses={429: {"description": "Too many requests from this IP or for this link"}},
)
async def submit_join_request(
    token: Token,
    body: JoinSubmission,
    request: Request,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> Response:
    """Leave a request for the gym's staff. The answer is the same whatever it holds."""
    ip = request.client.host if request.client else "unknown"
    _admit(request, token, ip)
    if not await integrations.human_check.verify(body.human_check_token, ip):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "human_check_failed")
    async with _open(request, token) as link:
        if body.website:
            # A script filled in the field people never see: answer as if it worked.
            return Response(status_code=status.HTTP_202_ACCEPTED)
        values = body.model_dump(
            include={"first_name", "last_name", "rut", "phone", "email", "dob"}
        )
        if age_on(body.dob, gym_today(link.timezone)) < ADULT_AGE:
            missing = [
                f
                for f in ("guardian_name", "guardian_phone", "guardian_email")
                if getattr(body, f) is None
            ]
            if missing:
                raise _missing(*missing)
            guardian = {
                "guardian_name": body.guardian_name,
                "guardian_phone": body.guardian_phone,
                "guardian_email": body.guardian_email,
            }
            # A child given their parent's phone has none of their own.
            if body.phone == body.guardian_phone:
                values["phone"] = None
        else:
            if missing := [f for f in ("phone", "email") if getattr(body, f) is None]:
                raise _missing(*missing)
            guardian = dict.fromkeys(("guardian_name", "guardian_phone", "guardian_email"))
        await link.session.execute(
            text(INSERT_REQUEST), {**values, **guardian, "program_id": link.program_id}
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)


# --- the queue (every staff role) -----------------------------------------------------

# RLS keeps every table to the current gym. Whoever here has the request's phone, or
# its RUT: one each, the first by name.
SELECT_REQUESTS = """
    SELECT r.*, pr.name AS program_name,
           bp.person_id AS phone_person_id, bp.name AS phone_person_name,
           br.person_id AS rut_person_id, br.name AS rut_person_name
    FROM join_request r
    LEFT JOIN program pr ON pr.gym_id = r.gym_id AND pr.id = r.program_id
    LEFT JOIN LATERAL (
        SELECT gp.person_id, gp.name FROM gym_person gp JOIN person p ON p.id = gp.person_id
        WHERE p.phone = r.phone ORDER BY gp.name, gp.person_id LIMIT 1
    ) bp ON true
    LEFT JOIN LATERAL (
        SELECT gp.person_id, gp.name FROM gym_person gp
        WHERE gp.rut = r.rut ORDER BY gp.name, gp.person_id LIMIT 1
    ) br ON true
"""


def _ref(person_id: uuid.UUID | None, name: str | None) -> PersonRef | None:
    return None if person_id is None or name is None else PersonRef(id=person_id, name=name)


def _request(row: Any) -> JoinRequest:
    guardian = None
    if row.guardian_name is not None:
        guardian = JoinGuardian(
            name=row.guardian_name, phone=row.guardian_phone, email=row.guardian_email
        )
    return JoinRequest(
        id=row.id,
        first_name=row.first_name,
        last_name=row.last_name,
        rut=row.rut,
        phone=row.phone,
        email=row.email,
        dob=row.dob,
        guardian=guardian,
        program_id=row.program_id,
        program_name=row.program_name,
        created_at=row.created_at,
        phone_in_gym=_ref(row.phone_person_id, row.phone_person_name),
        rut_in_gym=_ref(row.rut_person_id, row.rut_person_name),
    )


@router.get("/join-requests")
async def list_join_requests(session: StaffSession) -> list[JoinRequest]:
    """The queue, oldest first."""
    rows = await session.execute(text(f"{SELECT_REQUESTS} ORDER BY r.created_at, r.id"))
    return [_request(row) for row in rows]


@router.post(
    "/join-requests/{request_id}/approve",
    responses={status.HTTP_409_CONFLICT: {"model": JoinRefused}},
)
async def approve_join_request(
    request_id: uuid.UUID,
    body: JoinApproval,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> JoinApproved:
    if body.plan_id is not None and await role_in_gym(session, tenant) not in ADMIN_ROLES:
        raise PLAN_IS_MONEY
    # Deleted first: it was only ever a request, and a second approval at once waits
    # for this one and then finds nothing. Anything below that fails rolls it back.
    row = (
        await session.execute(
            text("DELETE FROM join_request WHERE id = :id RETURNING *"), {"id": request_id}
        )
    ).one_or_none()
    if row is None:
        raise NO_REQUEST

    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    member = Member(
        number=0,
        name=f"{row.first_name} {row.last_name}",
        phone=row.phone,
        email=row.email,
        rut=row.rut,
        dob=row.dob,
        guardian_name=row.guardian_name,
        guardian_phone=row.guardian_phone,
        guardian_email=row.guardian_email,
    )
    try:
        person_id, _ = await Writer(session, timezone, gym_today(timezone)).write(member)
    except RowRefused as refused:
        conflict = JoinRefusal(code=refused.code, field=refused.on.value)
        raise HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump()) from None

    membership_id = None
    if body.plan_id is not None:
        membership, notice = await start_membership(session, tenant.gym_id, person_id, body.plan_id)
        membership_id = membership.id
    else:
        notice = await _approved(session, tenant.gym_id, person_id)
    if notice is not None:
        # After the response, which is after the person has committed.
        background.add_task(notices.send, notice)
    return JoinApproved(person_id=person_id, membership_id=membership_id)


async def _approved(
    session: AsyncSession, gym_id: uuid.UUID, person_id: uuid.UUID
) -> Notice | None:
    """`join_approved`, to the person or their guardian, when there is an email."""
    contact = await contact_for(session, person_id)
    if contact is None or not contact.email:
        return None
    gym = await session.scalar(text("SELECT name FROM gym WHERE id = :id"), {"id": gym_id})
    dependent = None
    if contact.on_behalf_of:
        dependent = await session.scalar(
            text("SELECT name FROM gym_person WHERE person_id = :id"), {"id": person_id}
        )
    return Notice(
        JOIN_APPROVED,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym_id,
        context={"name": contact.name, "gym": gym, "dependent_name": dependent},
    )


@router.delete("/join-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_join_request(request_id: uuid.UUID, session: StaffSession) -> Response:
    """Reject it: its data is deleted."""
    result = await session.execute(
        text("DELETE FROM join_request WHERE id = :id"), {"id": request_id}
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise NO_REQUEST
    return Response(status_code=status.HTTP_204_NO_CONTENT)
