"""The emails Rakin sends: rendered from Spanish templates, recorded in `message_log`.

Each notice is a `Template` under `templates/`: `<name>.subject.txt`, `<name>.txt` and
`<name>.html`, the last two extending `_layout.txt` and `_layout.html`. A caller builds
a `Notice` (the template, who it goes to and the values to render it with) and hands
it to `Notices.send`, which renders it, sends it through the `Mailer` and records the
attempt and its outcome in `message_log` (migration 0015). The values are the row's
`payload`, less the template's `redact` keys, so a sign-in link never lands in it.

Every notice about someone's membership carries a sign-in link to the student page
(`page_link`): issued as it is sent, single use like any other, but good for
`PAGE_LINK_TTL` rather than 15 minutes, since a statement is read days before it is
due. It goes in under the message as `page_url`, which is never part of the payload.

A non-essential notice (plan events, announcements) carries a one-click unsubscribe
link, in its footer and as `List-Unsubscribe` with `List-Unsubscribe-Post` (RFC 8058),
and is not sent, but recorded as `suppressed`, to someone who used it
(`app.api.unsubscribe`). Essential ones (sign-in links, proofs, receipts) always go.

`send` never raises for a notice it could not send: it runs after the response, where
there is no one left to tell, so the outcome goes to `message_log` and the log. That
includes a template that cannot render, such as one missing a value: a bug, so it is
logged as an error (and reaches Sentry), and still recorded as `failed`.
"""

import enum
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Request
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    Undefined,
    select_autoescape,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.money import format_clp
from app.integrations.mailer import Email, MailDeliveryError, Mailer, check_recipient
from app.magiclink import MagicLinks, Recipient
from app.notices.unsubscribe import UNSUBSCRIBE_PATH, UnsubscribeSigner

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]

# Where a notice's sign-in link lands, and for how long it works: a statement goes out
# 7 days before the due date, so its link lasts until then.
STUDENT_PAGE = "/me"
PAGE_LINK_TTL = timedelta(days=7)


@dataclass(frozen=True)
class Template:
    name: str
    # Essential notices ignore unsubscribes and carry no unsubscribe link.
    essential: bool = True
    # Values rendered into the message but never written to `message_log`.
    redact: frozenset[str] = frozenset()
    # Carries a sign-in link to the student page, issued when it is sent.
    page_link: bool = True


MAGIC_LINK = Template("magic_link", redact=frozenset({"url"}), page_link=False)
WELCOME = Template("welcome")
STATEMENT = Template("statement")
PROOF_RECEIVED = Template("proof_received")
RECEIPT = Template("receipt")
PROOF_REJECTED = Template("proof_rejected")


@dataclass(frozen=True)
class Notice:
    template: Template
    to: str
    person_id: uuid.UUID  # whom it is addressed to: the guardian, for a dependent
    gym_id: uuid.UUID | None  # None only for what belongs to no gym: sign-in links
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.template.essential and self.gym_id is None:
            raise ValueError("a non-essential notice is some gym's, to unsubscribe from")


class Outcome(enum.StrEnum):
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


def _fecha(value: date) -> str:
    return f"{value:%d-%m-%Y}"


def _defined[T, R](filter_: Callable[[T], R]) -> Callable[[T], R]:
    """`filter_`, failing like any other missing value when given one."""

    def apply(value: T) -> R:
        if isinstance(value, Undefined):
            value._fail_with_undefined_error()
        return filter_(value)

    return apply


def environment(directory: Path = TEMPLATES_DIR) -> Environment:
    env = Environment(
        loader=FileSystemLoader(directory),
        # Escapes every value in `.html`, none in `.txt`.
        autoescape=select_autoescape(["html"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["clp"] = _defined(format_clp)
    env.filters["fecha"] = _defined(_fecha)
    return env


ENVIRONMENT = environment()


def render(
    notice: Notice,
    *,
    unsubscribe_url: str | None = None,
    page_url: str | None = None,
    env: Environment = ENVIRONMENT,
) -> Email:
    """The message `notice` is, with its unsubscribe and sign-in links when it has them."""
    name = notice.template.name
    context = {
        **notice.context,
        "unsubscribe_url": unsubscribe_url,
        "page_url": page_url,
        "page_link_days": PAGE_LINK_TTL.days,
    }
    subject = " ".join(env.get_template(f"{name}.subject.txt").render(context).split())
    headers: tuple[tuple[str, str], ...] = ()
    if unsubscribe_url is not None:
        headers = (
            ("List-Unsubscribe", f"<{unsubscribe_url}>"),
            ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
        )
    return Email(
        to=notice.to,
        subject=subject,
        text=env.get_template(f"{name}.txt").render(context),
        html=env.get_template(f"{name}.html").render(context),
        headers=headers,
    )


def payload(notice: Notice) -> str:
    """What `message_log` keeps of the values: JSON, without the redacted ones."""
    kept = {k: v for k, v in notice.context.items() if k not in notice.template.redact}
    return json.dumps(kept, default=str, ensure_ascii=False, sort_keys=True)


class Notices:
    def __init__(
        self,
        mailer: Mailer,
        sessionmaker: Sessionmaker,
        *,
        base_url: str,
        secret_key: str,
        links: MagicLinks | None = None,
        env: Environment = ENVIRONMENT,
    ) -> None:
        """`links` issues the `page_link` ones; only the sign-in link itself, which
        brings its own, goes without."""
        self._mailer = mailer
        self._sessionmaker = sessionmaker
        self._base_url = base_url.rstrip("/")
        self._signer = UnsubscribeSigner(secret_key)
        self._links = links
        self._env = env

    def unsubscribe_url(self, gym_id: uuid.UUID, person_id: uuid.UUID) -> str:
        return f"{self._base_url}{UNSUBSCRIBE_PATH}/{self._signer.sign(gym_id, person_id)}"

    async def send(self, notice: Notice) -> Outcome:
        """Send `notice` unless its addressee unsubscribed from it, and record what
        happened in `message_log`."""
        unsubscribe_url = None
        if not notice.template.essential:
            assert notice.gym_id is not None
            if await self._unsubscribed(notice.gym_id, notice.person_id):
                await self._record(notice, Outcome.SUPPRESSED)
                return Outcome.SUPPRESSED
            unsubscribe_url = self.unsubscribe_url(notice.gym_id, notice.person_id)
        extra = {"template": notice.template.name, "person_id": str(notice.person_id)}
        page_url = None
        if notice.template.page_link:
            try:
                # No link for an address no mail reaches: it would never be delivered.
                check_recipient(notice.to)
                page_url = await self._page_url(notice)
            except ValueError as exc:
                logger.warning("notice not sent", extra=extra, exc_info=True)
                await self._record(notice, Outcome.FAILED, error=_error(exc))
                return Outcome.FAILED
            # The database down, say: the notice cannot go without its link.
            except Exception as exc:
                logger.exception("notice link not issued", extra=extra)
                await self._record(notice, Outcome.FAILED, error=_error(exc))
                return Outcome.FAILED
        try:
            email = render(
                notice, unsubscribe_url=unsubscribe_url, page_url=page_url, env=self._env
            )
            await self._mailer.send(email)
        # A template that cannot render is a bug, not a bad day at the relay.
        except TemplateError as exc:
            logger.exception("notice not rendered", extra=extra)
            await self._record(notice, Outcome.FAILED, error=_error(exc))
            return Outcome.FAILED
        # An address the gym typed wrong is as unsendable as a relay that said no.
        except (MailDeliveryError, ValueError) as exc:
            logger.warning("notice not sent", extra=extra, exc_info=True)
            await self._record(notice, Outcome.FAILED, error=_error(exc))
            return Outcome.FAILED
        await self._record(notice, Outcome.SENT)
        return Outcome.SENT

    async def _page_url(self, notice: Notice) -> str:
        if self._links is None:
            raise RuntimeError(f"no sign-in links to send {notice.template.name} with")
        # The name is for a sender to greet with; this link goes inside the notice.
        recipient = Recipient(
            str(notice.person_id), notice.to, str(notice.context.get("name") or "")
        )
        link = await self._links.issue(recipient, ttl=PAGE_LINK_TTL, landing=STUDENT_PAGE)
        return link.url

    @asynccontextmanager
    async def _in_gym(self, gym_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker()() as session, session.begin():
            if gym_id is not None:
                await session.execute(
                    text("SELECT set_config('app.gym_id', :gym_id, true)"), {"gym_id": str(gym_id)}
                )
            yield session

    async def _unsubscribed(self, gym_id: uuid.UUID, person_id: uuid.UUID) -> bool:
        async with self._in_gym(gym_id) as session:
            found = await session.scalar(
                text("SELECT 1 FROM mail_unsubscribe WHERE gym_id = :g AND person_id = :p"),
                {"g": gym_id, "p": person_id},
            )
        return found is not None

    async def _record(self, notice: Notice, outcome: Outcome, error: str | None = None) -> None:
        try:
            async with self._in_gym(notice.gym_id) as session:
                await session.execute(
                    text(
                        "INSERT INTO message_log (gym_id, person_id, channel, template,"
                        " to_address, status, error, payload)"
                        " VALUES (:gym_id, :person_id, 'email', :template, :to, :status,"
                        " :error, CAST(:payload AS jsonb))"
                    ),
                    {
                        "gym_id": notice.gym_id,
                        "person_id": notice.person_id,
                        "template": notice.template.name,
                        "to": notice.to,
                        "status": outcome.value,
                        "error": error,
                        "payload": payload(notice),
                    },
                )
        # The message has gone, or not, either way; losing its record is a log line.
        except Exception:
            logger.exception(
                "notice not recorded",
                extra={"template": notice.template.name, "outcome": outcome.value},
            )


def _error(exc: Exception) -> str:
    """What `message_log` says went wrong: the error's class, and its message."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def get_notices(request: Request) -> Notices:
    """FastAPI dependency: notices through the app's mailer, database and settings."""
    settings = request.app.state.settings
    return Notices(
        request.app.state.integrations.mailer,
        lambda: request.app.state.sessionmaker,
        base_url=settings.public_base_url,
        secret_key=settings.secret_key,
        links=request.app.state.magic_links,
    )
