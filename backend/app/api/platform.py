"""The platform's panel (#436): who is signed in, and every gym Rakin hosts.

Every endpoint takes an `OperatorSession` (`app.platform.session`): a platform operator,
on the base host. What it reads comes through migration 0076's functions, each of which
checks the operator's session itself, so the API's own role never reads across gyms.

A new gym (#437) is written by `platform_create_gym` (0077), through the same
`gym_create` as `python -m app.gyms create`, with the values `app.gyms` computes. Its
owner is then emailed a sign-in link that points at the new host.
"""

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text

from app.domain.grading import PRESETS
from app.gyms import PROCESSOR_TERMS_VERSION, gym_create_values
from app.hosts import Hosts, slug_refusal
from app.platform.session import FRESH, OperatorSession
from app.schemas.gym import TIMEZONES
from app.schemas.platform import (
    CreatedGym,
    NewGymChoices,
    OperatorMe,
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


@router.post("/gyms", status_code=201)
async def create_gym(
    body: PanelNewGym, operator: OperatorSession, request: Request, background: BackgroundTasks
) -> CreatedGym:
    hosts: Hosts = request.app.state.hosts
    values = gym_create_values(body, uuid.uuid4())
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
    if not row.created:
        raise RequestValidationError(
            [{"type": "slug_taken", "msg": "a gym has this slug", "loc": ("body", "slug")}]
        )
    address = hosts.base_url(body.slug)
    # After the answer, so after the commit: the owner is found by their address.
    background.add_task(
        send_owner_link, request.app, operator.session_hash, row.id, body.owner_email, address
    )
    return CreatedGym(id=row.id, slug=body.slug, address=address)


async def send_owner_link(
    app: FastAPI, session_hash: bytes, gym_id: uuid.UUID, email: str, address: str
) -> None:
    """Email the new gym's owner a link and its code that sign in on its host, and log
    that it went. A link that did not go is in the log; the owner asks for another there."""
    try:
        sent = await app.state.magic_links.send_links(email, base_url=address)
        if not sent:
            logger.warning("the new gym's owner was sent no link", extra={"gym_id": str(gym_id)})
            return
        async with app.state.sessionmaker() as db, db.begin():
            await db.execute(
                text("SELECT platform_owner_link_sent(:h, :g)"), {"h": session_hash, "g": gym_id}
            )
    except Exception:
        logger.exception("the new gym's owner link was not logged", extra={"gym_id": str(gym_id)})
