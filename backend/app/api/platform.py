"""The platform's panel (#436): who is signed in, and every gym Rakin hosts.

Every endpoint takes an `OperatorSession` (`app.platform.session`): a platform operator,
on the base host. What it reads comes through migration 0076's functions, each of which
checks the operator's session itself, so the API's own role never reads across gyms.

A new gym (#437) is written by `platform_create_gym` (0077), through the same
`gym_create` as `python -m app.gyms create`, with the values `app.gyms` computes. Its
owner is then emailed a sign-in link that points at the new host; whether it went is
logged, and a gym whose latest link did not go shows so in the list, which sends it
again.

A gym is edited (#438) through 0078's functions: its name and its titular's contact
(`platform_edit_gym`), a new signature of the Términos de encargo
(`platform_record_terms`) and its slug (`platform_rename_gym`), the old one redirecting
for 90 days (`app.hosts`). The slug asks for a session proved in the last 10 minutes
(`require_fresh`); a stale one gets `401 {"code": "reauth"}`, and the panel asks for a
code by `/reauth/send` and spends it at `/reauth`, then tries again.
"""

import logging
import math
import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.grading import PRESETS
from app.gyms import PROCESSOR_TERMS_VERSION, gym_create_values
from app.hosts import GymLookup, Hosts, slug_refusal
from app.magiclink import RateLimited
from app.platform.session import FRESH, Operator, OperatorSession, require_fresh
from app.platform.web import OperatorLinks
from app.schemas.gym import TIMEZONES
from app.schemas.platform import (
    CreatedGym,
    GymEdit,
    GymEdited,
    NewGymChoices,
    NewSlug,
    OperatorMe,
    OwnerLink,
    PanelNewGym,
    PlatformGym,
    PlatformGymDetail,
    PresetOption,
    ReauthCode,
    Renamed,
    SlugAlias,
    SlugCheck,
    TermsRecorded,
    TermsSignature,
    TermsToRecord,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/me")
async def me(operator: OperatorSession) -> OperatorMe:
    return OperatorMe(
        email=operator.email, name=operator.name, fresh_until=operator.fresh_at + FRESH
    )


@router.get("/gyms")
async def gyms(operator: OperatorSession, request: Request) -> list[PlatformGym]:
    hosts: Hosts = request.app.state.hosts
    rows = await operator.db.execute(
        text("SELECT * FROM platform_gyms(:h, :terms)"),
        {"h": operator.session_hash, "terms": PROCESSOR_TERMS_VERSION},
    )
    return [
        PlatformGym.model_validate({**row._mapping, "address": hosts.base_url(row.slug)})
        for row in rows
    ]


@router.get("/slug")
async def slug_check(
    slug: str, operator: OperatorSession, request: Request, gym: uuid.UUID | None = None
) -> SlugCheck:
    """Where a gym with `slug` would be, and why it cannot have it, as the form types:
    a new gym's, or `gym`'s new one, which may be a slug it had (#438)."""
    hosts: Hosts = request.app.state.hosts
    problem: Literal["format", "reserved", "taken"] | None = slug_refusal(slug)
    if problem is None:
        taken = await operator.db.scalar(
            text("SELECT platform_slug_taken(:h, :slug, :gym)"),
            {"h": operator.session_hash, "slug": slug, "gym": gym},
        )
        problem = "taken" if taken else None
    return SlugCheck(address=hosts.base_url(slug), problem=problem)


@router.get("/presets")
async def presets(operator: OperatorSession) -> NewGymChoices:
    return NewGymChoices(
        grading=[PresetOption(key=p["key"], label=p["label"]) for p in PRESETS],
        terms_version=PROCESSOR_TERMS_VERSION,
        timezones=list(TIMEZONES),
    )


# `platform_create_gym`'s arguments after the session and the preset, as `gym_create`
# takes them (0077).
VALUES = ", ".join(f":v{n}" for n in range(15))


# The slug's UNIQUE (0001), which `gym_create`'s lock should leave nothing to trip.
SLUG_UNIQUE = "gym_slug_key"
# What 0078's functions raise, as a constraint's name, for what the panel cannot do.
SLUG_IN_USE = "gym_slug_taken"
HANDOVER = "titular_handover"
NO_TITULAR = "no_titular"


def constraint_of(error: DBAPIError) -> str | None:
    """The constraint a database error names, through the wrapper SQLAlchemy raises."""
    return getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)


SLUG_TAKEN = RequestValidationError(
    [{"type": "slug_taken", "msg": "a gym has this slug", "loc": ("body", "slug")}]
)


@router.post("/gyms", status_code=201)
async def create_gym(
    body: PanelNewGym, operator: OperatorSession, request: Request, background: BackgroundTasks
) -> CreatedGym:
    hosts: Hosts = request.app.state.hosts
    values = gym_create_values(body, uuid.uuid4())
    try:
        row = (
            await operator.db.execute(
                text(f"SELECT id, created FROM platform_create_gym(:h, :grading, {VALUES})"),
                {
                    "h": operator.session_hash,
                    "grading": body.grading,
                    **{f"v{n}": value for n, value in enumerate(values)},
                },
            )
        ).one()
    except IntegrityError as error:
        if constraint_of(error) != SLUG_UNIQUE:
            raise
        raise SLUG_TAKEN from None
    # A gym's slug, or one that still redirects to a gym (#438).
    if not row.created:
        raise SLUG_TAKEN
    address = hosts.base_url(body.slug)
    # After the answer, so after the commit: the owner is found by their address.
    background.add_task(
        send_owner_link, request.app, operator.session_hash, row.id, body.owner_email, address
    )
    return CreatedGym(id=row.id, slug=body.slug, address=address)


@router.post("/gyms/{gym_id}/owner-link")
async def resend_owner_link(
    gym_id: uuid.UUID, operator: OperatorSession, request: Request
) -> OwnerLink:
    """Email the gym's titular a sign-in link on its host again: after one that did not
    go (`owner_link_failed`), or one that lapsed unused."""
    hosts: Hosts = request.app.state.hosts
    row = (
        await operator.db.execute(
            text("SELECT slug, email FROM platform_titular(:h, :g)"),
            {"h": operator.session_hash, "g": gym_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such gym")
    if not row.email:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "no_titular_email"})
    sent = await try_sending(request.app, gym_id, row.email, hosts.base_url(row.slug))
    await record_link(operator.db, operator.session_hash, gym_id, sent)
    return OwnerLink(sent=sent)


async def try_sending(app: FastAPI, gym_id: uuid.UUID, email: str, address: str) -> bool:
    """Whether a link and its code that sign in on `address` went to `email`."""
    try:
        sent = bool(await app.state.magic_links.send_links(email, base_url=address))
    except Exception:
        logger.exception("the gym's owner was sent no link", extra={"gym_id": str(gym_id)})
        return False
    if not sent:
        logger.warning("the gym's owner was sent no link", extra={"gym_id": str(gym_id)})
    return sent


async def record_link(db: AsyncSession, session_hash: bytes, gym_id: uuid.UUID, sent: bool) -> None:
    """`owner_link_sent`, or `owner_link_failed`, which the list shows (0077)."""
    await db.execute(
        text("SELECT platform_owner_link(:h, :g, :sent)"),
        {"h": session_hash, "g": gym_id, "sent": sent},
    )


async def send_owner_link(
    app: FastAPI, session_hash: bytes, gym_id: uuid.UUID, email: str, address: str
) -> None:
    """Email the new gym's owner a link and its code that sign in on its host, and log
    whether it went: one that did not shows in the list, which sends it again."""
    sent = await try_sending(app, gym_id, email, address)
    try:
        async with app.state.sessionmaker() as db, db.begin():
            await record_link(db, session_hash, gym_id, sent)
    except Exception:
        logger.exception("the gym's owner link was not logged", extra={"gym_id": str(gym_id)})


# --- editing a gym (#438) --------------------------------------------------------------


@router.get("/gyms/{gym_id}")
async def gym_detail(
    gym_id: uuid.UUID, operator: OperatorSession, request: Request
) -> PlatformGymDetail:
    hosts: Hosts = request.app.state.hosts
    row = (
        await operator.db.execute(
            text("SELECT * FROM platform_gym(:h, :g)"), {"h": operator.session_hash, "g": gym_id}
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such gym")
    return PlatformGymDetail(
        id=row.id,
        slug=row.slug,
        name=row.name,
        address=hosts.base_url(row.slug),
        titular_name=row.titular_name,
        titular_email=row.titular_email,
        titular_phone=row.titular_phone,
        titular_signed_in=row.titular_signed_in,
        terms=[TermsSignature.model_validate(t) for t in row.terms],
        terms_version=PROCESSOR_TERMS_VERSION,
        aliases=[
            SlugAlias(slug=a["slug"], address=hosts.base_url(a["slug"]), until=a["until"])
            for a in row.aliases
        ],
    )


@router.patch(
    "/gyms/{gym_id}",
    responses={status.HTTP_409_CONFLICT: {"description": "The titular's email after sign-in"}},
)
async def edit_gym(
    gym_id: uuid.UUID, body: GymEdit, operator: OperatorSession, request: Request
) -> GymEdited:
    """The gym's name and its titular's name, phone and email; what is left out stays.
    The email only before the titular's first sign-in there: after it, a new address is
    a handover (#321), and the answer is `409 titular_handover`."""
    try:
        row = (
            await operator.db.execute(
                text("SELECT slug, fields FROM platform_edit_gym(:h, :g, :n, :on, :op, :oe)"),
                {
                    "h": operator.session_hash,
                    "g": gym_id,
                    "n": body.name,
                    "on": body.owner_name,
                    "op": body.owner_phone,
                    "oe": body.owner_email,
                },
            )
        ).one_or_none()
    except IntegrityError as error:
        constraint = constraint_of(error)
        if constraint == HANDOVER:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"code": HANDOVER, "issue": 321}
            ) from None
        if constraint == NO_TITULAR:
            raise HTTPException(status.HTTP_409_CONFLICT, {"code": NO_TITULAR}) from None
        raise
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such gym")
    if "name" in row.fields:
        # Its host shows the new name at once.
        lookup: GymLookup = request.app.state.gym_lookup
        lookup.forget(row.slug)
    return GymEdited(fields=list(row.fields))


@router.post("/gyms/{gym_id}/terms")
async def record_terms(
    gym_id: uuid.UUID, body: TermsToRecord, operator: OperatorSession
) -> TermsRecorded:
    """A signature of the current Términos de encargo. A version the gym signed already
    records nothing, and its first date stays."""
    recorded = await operator.db.scalar(
        text("SELECT platform_record_terms(:h, :g, :v, :d)"),
        {
            "h": operator.session_hash,
            "g": gym_id,
            "v": PROCESSOR_TERMS_VERSION,
            "d": body.signed_on,
        },
    )
    if recorded is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such gym")
    return TermsRecorded(recorded=recorded)


SLUG_IN_USE_ERROR = RequestValidationError(
    [
        {
            "type": "slug_taken",
            "msg": "a gym has this slug, or redirects from it",
            "loc": ("body", "slug"),
        }
    ]
)

REAUTH = HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "reauth"})


def not_fresh(error: DBAPIError) -> bool:
    """Whether the database refused a session not proved recently (0076's gate)."""
    return "not fresh" in str(getattr(error.orig, "__cause__", None) or error.orig)


@router.post("/gyms/{gym_id}/slug")
async def rename_gym(
    gym_id: uuid.UUID, body: NewSlug, operator: OperatorSession, request: Request
) -> Renamed:
    """A new slug for the gym, with a session proved in the last 10 minutes. Its old
    address redirects here for 90 days, and no other gym may take it meanwhile.
    Sessions are per host, so whoever was signed in there signs in again here."""
    require_fresh(operator)
    hosts: Hosts = request.app.state.hosts
    try:
        row = (
            await operator.db.execute(
                text("SELECT old_slug, until FROM platform_rename_gym(:h, :g, :s)"),
                {"h": operator.session_hash, "g": gym_id, "s": body.slug},
            )
        ).one_or_none()
    except IntegrityError as error:
        if constraint_of(error) not in (SLUG_IN_USE, SLUG_UNIQUE):
            raise
        raise SLUG_IN_USE_ERROR from None
    except DBAPIError as error:
        # Proved in time to the API's clock, not to the database's.
        if not_fresh(error):
            raise REAUTH from None
        raise
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such gym")
    lookup: GymLookup = request.app.state.gym_lookup
    lookup.forget(row.old_slug)
    lookup.forget(body.slug)
    return Renamed(
        slug=body.slug, address=hosts.base_url(body.slug), old_slug=row.old_slug, until=row.until
    )


# --- a fresh proof ---------------------------------------------------------------------


def too_many(exc: RateLimited) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too many requests; try again later",
        headers={"Retry-After": str(math.ceil(exc.retry_after))},
    )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/reauth/send", status_code=status.HTTP_202_ACCEPTED)
async def send_reauth_code(
    operator: OperatorSession, request: Request, background: BackgroundTasks
) -> Response:
    """Email the signed-in operator a link and a code, as signing in does, for an action
    that asks for a recent proof. Rate-limited as asking to sign in is."""
    links: OperatorLinks = request.app.state.platform_links
    try:
        links.admit(operator.email, client_ip(request))
    except RateLimited as exc:
        raise too_many(exc) from exc
    background.add_task(links.send_links, operator.email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/reauth", status_code=status.HTTP_204_NO_CONTENT)
async def reauth(body: ReauthCode, operator: OperatorSession, request: Request) -> Response:
    """Spend the code emailed to the operator on proving their session again: for the
    next 10 minutes, the actions that ask for it go through. A wrong, spent or expired
    code is a 400."""
    links: OperatorLinks = request.app.state.platform_links
    try:
        links.admit_code(operator.email, client_ip(request))
    except RateLimited as exc:
        raise too_many(exc) from exc
    code_hash = links.code_hash(operator.email, body.code)
    fresh = code_hash is not None and await refresh(operator, code_hash)
    if not fresh:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def refresh(operator: Operator, code_hash: bytes) -> bool:
    return bool(
        await operator.db.scalar(
            text("SELECT platform_refresh(:h, :c)"), {"h": operator.session_hash, "c": code_hash}
        )
    )
