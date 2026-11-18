"""The platform's panel (#436): who is signed in, and every gym Rakin hosts.

Every endpoint takes an `OperatorSession` (`app.platform.session`): a platform operator,
on the base host. What it reads comes through migration 0076's functions, each of which
checks the operator's session itself, so the API's own role never reads across gyms.

A new gym (#437) is written by `platform_create_gym` (0077), through the same
`gym_create` as `python -m app.gyms create`, with the values `app.gyms` computes. Its
owner is then emailed a sign-in link that points at the new host; whether it went is
logged, and a gym whose latest link did not go shows so in the list, which sends it
again.
"""

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.grading import PRESETS
from app.gyms import PROCESSOR_TERMS_VERSION, gym_create_values
from app.hosts import Hosts, slug_refusal
from app.platform.session import FRESH, OperatorSession
from app.schemas.gym import TIMEZONES
from app.schemas.platform import (
    CreatedGym,
    NewGymChoices,
    OperatorMe,
    OwnerLink,
    PanelNewGym,
    PlatformGym,
    PresetOption,
    SlugCheck,
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
async def slug_check(slug: str, operator: OperatorSession, request: Request) -> SlugCheck:
    """Where a gym with `slug` would be, and why it cannot have it, as the form types."""
    hosts: Hosts = request.app.state.hosts
    problem: Literal["format", "reserved", "taken"] | None = slug_refusal(slug)
    if problem is None:
        taken = await operator.db.scalar(
            text("SELECT platform_slug_taken(:h, :slug)"),
            {"h": operator.session_hash, "slug": slug},
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
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
        if constraint != SLUG_UNIQUE:
            raise
        raise SLUG_TAKEN from None
    # Live slugs only, for now: #438 refuses the renamed ones it keeps as well.
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
