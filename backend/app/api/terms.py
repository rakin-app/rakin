"""The titular accepts the Términos de servicio and de encargo in the app (#499).

A gym is created pending its terms (`app.gyms`, the panel), and until its titular
accepts them its API takes no data (`app.tenancy`). Once it accepted some version, a
new one holds back only the titular's own writes (`app.permissions`). Either way the
titular's admin shows only the acceptance page, which these endpoints serve: they take
`TermsSession`, the titular's session that does not wait on the terms.

- `GET /api/terms`: both texts, rendered for this gym (`app.legal.terms`), the
  titular's blanks empty; for a gym that accepted an earlier version, what changed in
  each version since; what the form starts with, and each checkbox's words.
- `POST /api/terms/accept`: the versions the page showed, which must still be the
  current ones (`409 terms_changed` otherwise, and the page reloads), and what the
  titular filled in. The server renders both texts again with it, and
  `app_accept_terms` (0081) keeps that HTML, its SHA-256, the checkboxes' words, the
  sign-in that accepted and the request's IP and user agent, on that row only. A copy
  of both texts then goes to the address the session signed in with, attached in full
  (#500, requirement 13), and to the first contact for breaches if that is another.
- `GET /api/terms/acceptances`, and one's copy: the page a titular downloads, the same
  the email attached, built from what was stored.

The record is what makes the click hold up as a signature (Ley 19.799, art. 2 f), so
it keeps exactly the list of #500 ("Requirements for #499" in
docs/legal-research.md): never the link or code, a fingerprint or a RUT of the person.
"""

import logging
import uuid
from datetime import datetime
from email.utils import make_msgid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.mailer import Attachment
from app.legal import PROCESSOR_TERMS_VERSION, SERVICE_TERMS_VERSION
from app.legal import terms as legal
from app.legal.terms import PROCESSOR, SERVICE, Accepted, Text
from app.notices import TERMS_ACCEPTED, Notice, Notices, Outcome, get_notices
from app.permissions import TermsSession
from app.schemas.terms import (
    TermsAcceptance,
    TermsAccepted,
    TermsChange,
    TermsDocument,
    TermsPage,
    TermsRecord,
)
from app.tenancy import SignIn, Tenant, current_tenant, terms_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terms", tags=["terms"])

Acting = Annotated[Tenant, Depends(current_tenant)]

TERMS_CHANGED = HTTPException(status.HTTP_409_CONFLICT, {"code": "terms_changed"})
NO_COPY = HTTPException(status.HTTP_404_NOT_FOUND, "no copy of that acceptance")

GYM = "SELECT name, slug FROM gym WHERE id = :g"
TITULAR = "SELECT name FROM gym_person WHERE person_id = :p"


def texts(request: Request) -> dict[str, Text]:
    return legal.load(request.app.state.settings)


async def app_values(session: AsyncSession, tenant: Tenant) -> tuple[str, dict[str, str]]:
    """The gym's name, and the blanks the app fills: its name and its slug."""
    gym = (await session.execute(text(GYM), {"g": tenant.gym_id})).one()
    return gym.name, {"gym_name": gym.name, "slug": gym.slug}


async def acceptances(session: AsyncSession) -> list[Any]:
    return list((await session.execute(text("SELECT * FROM app_terms_acceptances()"))).all())


def latest(versions: list[str | None]) -> str | None:
    known = [v for v in versions if v is not None]
    return max(known) if known else None


@router.get("")
async def terms_page(tenant: Acting, session: TermsSession, request: Request) -> TermsPage:
    """Both texts as the acceptance page shows them, and what it asks."""
    found = texts(request)
    state = await terms_state(session)
    gym_name, values = await app_values(session, tenant)
    rows = await acceptances(session)
    since = {
        SERVICE: latest([r.service_version for r in rows]),
        PROCESSOR: latest([r.processor_version for r in rows]),
    }
    documents = []
    for key in (SERVICE, PROCESSOR):
        text_ = found[key]
        changes = legal.render_changes(text_, since[key]) if state == "outdated" else []
        documents.append(
            TermsDocument(
                key=key,
                title=text_.title,
                version=text_.version,
                html=legal.render(text_, values),
                changes=[TermsChange(version=v, html=h) for v, h in changes],
            )
        )
    filled = next((r.filled for r in rows if r.channel == "in_app"), None)
    if filled is None:
        name = await session.scalar(text(TITULAR), {"p": tenant.person_id})
        filled = {"representative": name}
    names = legal.subprocessors(found[PROCESSOR])
    return TermsPage(
        state=state,
        gym_name=gym_name,
        documents=documents,
        prefill=filled,
        declarations=legal.declarations("{legal_name}", names),
        subprocessors=names,
    )


def sign_in_of(request: Request) -> SignIn:
    sign_in = getattr(request.state, "sign_in", None)
    if not isinstance(sign_in, SignIn):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return sign_in


@router.post("/accept", status_code=status.HTTP_201_CREATED)
async def accept(
    body: TermsAcceptance,
    tenant: Acting,
    session: TermsSession,
    request: Request,
    background: BackgroundTasks,
    notices: Annotated[Notices, Depends(get_notices)],
) -> TermsAccepted:
    """Accept both texts as the page showed them, filled in with `body.filled`."""
    found = texts(request)
    if (body.service_version, body.processor_version) != (
        SERVICE_TERMS_VERSION,
        PROCESSOR_TERMS_VERSION,
    ):
        raise TERMS_CHANGED
    sign_in = sign_in_of(request)
    _, values = await app_values(session, tenant)
    values |= body.filled.values()
    names = legal.subprocessors(found[PROCESSOR])
    said = legal.declarations(body.filled.legal_name, names)
    row = (
        await session.execute(
            text(
                "SELECT id, accepted_at FROM app_accept_terms("
                ":sv, :pv, :sh, :ph, :sd, :pd, :subs, CAST(:filled AS jsonb),"
                " :email, :signed_in_at, :ip, :ua)"
            ),
            {
                "sv": found[SERVICE].version,
                "pv": found[PROCESSOR].version,
                "sh": legal.render(found[SERVICE], values),
                "ph": legal.render(found[PROCESSOR], values),
                "sd": said[SERVICE],
                "pd": said[PROCESSOR],
                "subs": names,
                "filled": body.filled.model_dump_json(),
                "email": sign_in.email,
                "signed_in_at": sign_in.at,
                "ip": request.client.host if request.client else None,
                "ua": request.headers.get("user-agent"),
            },
        )
    ).one()
    contact = body.filled.breach_contacts[0].email
    to = [sign_in.email]
    if contact.lower() != sign_in.email.lower():
        to.append(contact)
    # After the answer, which is after the row has committed.
    background.add_task(send_copy, request, notices, tenant, row.id, to)
    return TermsAccepted(id=row.id, accepted_at=row.accepted_at)


async def copy_of(session: AsyncSession, tenant: Tenant, acceptance: uuid.UUID) -> Accepted | None:
    """One acceptance made in the app, as its copy shows it; None for none, or one
    signed outside the app, which has no copy here."""
    row = (
        await session.execute(text("SELECT * FROM app_terms_copy(:a)"), {"a": acceptance})
    ).one_or_none()
    if row is None or row.channel != "in_app":
        return None
    gym_name = await session.scalar(
        text("SELECT name FROM gym WHERE id = :g"), {"g": tenant.gym_id}
    )
    return Accepted(
        gym_name=str(gym_name),
        name=str(row.accepted_by_name),
        legal_name=str(row.filled["legal_name"]),
        email=row.session_email,
        accepted_at=row.accepted_at,
        service_version=row.service_version,
        processor_version=row.processor_version,
        service_html=row.service_html,
        processor_html=row.processor_html,
        service_sha256=bytes(row.service_sha256),
        processor_sha256=bytes(row.processor_sha256),
        service_declaration=row.service_declaration,
        processor_declaration=row.processor_declaration,
    )


def copy_name(slug: str, accepted_at: datetime) -> str:
    return f"terminos-{slug}-{accepted_at.astimezone(legal.CHILE):%Y-%m-%d}.html"


async def send_copy(
    request: Request,
    notices: Notices,
    tenant: Tenant,
    acceptance: uuid.UUID,
    to: list[str],
) -> None:
    """Email the copy of `acceptance` to each of `to`, and record when it went to the
    first, the address the session signed in with."""
    extra = {"gym_id": str(tenant.gym_id), "acceptance": str(acceptance)}
    try:
        async with request.app.state.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "SELECT set_config('app.gym_id', :g, true),"
                    " set_config('app.person_id', :p, true)"
                ),
                {"g": str(tenant.gym_id), "p": str(tenant.person_id)},
            )
            accepted = await copy_of(session, tenant, acceptance)
            slug = await session.scalar(
                text("SELECT slug FROM gym WHERE id = :g"), {"g": tenant.gym_id}
            )
    except Exception:
        logger.exception("the terms' copy was not built", extra=extra)
        return
    if accepted is None:
        logger.error("the terms' copy was not found", extra=extra)
        return
    attachment = Attachment(
        copy_name(str(slug), accepted.accepted_at),
        legal.copy_document(accepted).encode(),
        "text/html",
    )
    context = {
        "name": accepted.name,
        "gym": accepted.gym_name,
        "legal_name": accepted.legal_name,
        "accepted_at": legal.chile_time(accepted.accepted_at),
        "service_version": accepted.service_version,
        "processor_version": accepted.processor_version,
        "service_sha256": accepted.service_sha256.hex(),
        "processor_sha256": accepted.processor_sha256.hex(),
    }
    for n, address in enumerate(to):
        message_id = make_msgid(domain="rakin.app")
        outcome = await notices.send(
            Notice(
                TERMS_ACCEPTED,
                to=address,
                person_id=tenant.person_id,
                gym_id=tenant.gym_id,
                context=context,
                attachments=(attachment,),
                message_id=message_id,
            )
        )
        if n == 0 and outcome == Outcome.SENT:
            await mark_sent(request, tenant, acceptance, message_id)


async def mark_sent(
    request: Request, tenant: Tenant, acceptance: uuid.UUID, message_id: str
) -> None:
    """When the copy went to the address that accepted, and which message it was."""
    try:
        async with request.app.state.sessionmaker() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.gym_id', :g, true)"), {"g": str(tenant.gym_id)}
            )
            await session.execute(
                text("SELECT app_terms_copy_sent(:a, :m)"), {"a": acceptance, "m": message_id}
            )
    except Exception:
        logger.exception(
            "the terms' copy was sent, and not recorded",
            extra={"gym_id": str(tenant.gym_id), "acceptance": str(acceptance)},
        )


@router.get("/acceptances")
async def terms_acceptances(session: TermsSession) -> list[TermsRecord]:
    """Every acceptance of the gym, the latest first, and the signatures before them."""
    return [
        TermsRecord(
            id=r.id,
            accepted_at=r.accepted_at,
            channel=r.channel,
            service_version=r.service_version,
            processor_version=r.processor_version,
            accepted_by_name=r.accepted_by_name,
            signed_on=r.signed_on,
            has_copy=r.channel == "in_app",
        )
        for r in await acceptances(session)
    ]


@router.get(
    "/acceptances/{acceptance_id}/copy",
    response_class=Response,
    responses={200: {"content": {"text/html": {}}}},
)
async def terms_copy(acceptance_id: uuid.UUID, tenant: Acting, session: TermsSession) -> Response:
    """The copy of one acceptance made in the app, to download: both texts as stored,
    each with its acceptance block, as the email attached it."""
    accepted = await copy_of(session, tenant, acceptance_id)
    if accepted is None:
        raise NO_COPY
    slug = await session.scalar(text("SELECT slug FROM gym WHERE id = :g"), {"g": tenant.gym_id})
    return Response(
        legal.copy_document(accepted),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{copy_name(str(slug), accepted.accepted_at)}"'
            ),
            "Cache-Control": "no-store",
        },
    )
