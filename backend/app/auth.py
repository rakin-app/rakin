"""Rakin's side of magic-link sign-in (`app.magiclink`): people, Postgres and email.

An address's links go to every person with that email who belongs to some gym, one
link each. A session starts in the person's gym when they have exactly one; with
several it starts in none until they pick (#16), and gym-scoped routes answer 401.

The session middleware sets `request.state.person_id` and, when the session has a
gym, `request.state.tenant`. It never answers 401 itself: `app.tenancy` stays the one
place a gym-scoped route refuses an anonymous request.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.integrations.mailer import Mailer
from app.magiclink import (
    Link,
    MagicLinks,
    MemoryRateLimiter,
    Recipient,
    Session,
    Texts,
    callback_url,
)
from app.notices import MAGIC_LINK, STUDENT_PAGE, Notice, Notices
from app.settings import Settings
from app.tenancy import Tenant

PREFIX = "/api/auth"

# Where a link may land other than "/": the student page, for the links in notices.
LANDINGS = frozenset({STUDENT_PAGE})

# A link is good for 15 minutes, so five per address covers a person who keeps
# asking; thirty per IP leaves room for a gym's shared wifi.
PER_ADDRESS = (5, 15 * 60)
PER_IP = (30, 15 * 60)

TEXTS = Texts(
    lang="es",
    title="Entrar a Rakin",
    confirm="Toca el botón para entrar.",
    button="Entrar",
    invalid="Este enlace venció o ya se usó. Pide uno nuevo.",
    back="Volver al inicio",
)

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]


class PeopleDirectory:
    """People by email, across gyms, through the `SECURITY DEFINER` lookups (0005)."""

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def recipients(self, address: str) -> Sequence[Recipient]:
        async with self._sessionmaker()() as session:
            rows = await session.execute(
                text("SELECT person_id, name, email FROM auth_people_by_email(:address)"),
                {"address": address},
            )
            return [Recipient(str(r.person_id), r.email, r.name) for r in rows]

    async def scope(self, subject: str) -> str | None:
        async with self._sessionmaker()() as session:
            gyms = (
                await session.scalars(
                    text("SELECT auth_gyms_of(:person)"), {"person": uuid.UUID(subject)}
                )
            ).all()
        return str(gyms[0]) if len(gyms) == 1 else None


class PostgresStore:
    """`auth_link` and `auth_session`, keyed by token hash (0005).

    A session is read and ended before any gym is set, so through the lookups 0005
    defines rather than the RLS-scoped table.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def _execute(self, sql: str, params: dict[str, Any]) -> None:
        async with self._sessionmaker()() as session, session.begin():
            await session.execute(text(sql), params)

    async def _fetch(self, sql: str, params: dict[str, Any]) -> Any:
        async with self._sessionmaker()() as session, session.begin():
            return (await session.execute(text(sql), params)).one_or_none()

    async def add_link(self, token_hash: bytes, subject: str, expires_at: datetime) -> None:
        await self._execute(
            "INSERT INTO auth_link (token_hash, person_id, expires_at) VALUES (:h, :p, :e)",
            {"h": token_hash, "p": uuid.UUID(subject), "e": expires_at},
        )

    async def pending_link(self, token_hash: bytes, now: datetime) -> str | None:
        row = await self._fetch(
            "SELECT person_id FROM auth_link"
            " WHERE token_hash = :h AND used_at IS NULL AND expires_at > :now",
            {"h": token_hash, "now": now},
        )
        return None if row is None else str(row.person_id)

    async def redeem_link(
        self, token_hash: bytes, now: datetime, session_hash: bytes, session: Session
    ) -> bool:
        async with self._sessionmaker()() as db, db.begin():
            # Of two concurrent redemptions, the second waits on the row lock and then
            # finds it used.
            spent = await db.execute(
                text(
                    "UPDATE auth_link SET used_at = :now WHERE token_hash = :h"
                    " AND person_id = :p AND used_at IS NULL AND expires_at > :now"
                    " RETURNING 1"
                ),
                {"h": token_hash, "p": uuid.UUID(session.subject), "now": now},
            )
            if spent.one_or_none() is None:
                return False
            # Fails with the link: the transaction rolls both back.
            await db.execute(
                text(
                    "INSERT INTO auth_session (token_hash, person_id, gym_id, expires_at)"
                    " VALUES (:h, :p, :g, :e)"
                ),
                {
                    "h": session_hash,
                    "p": uuid.UUID(session.subject),
                    "g": None if session.scope is None else uuid.UUID(session.scope),
                    "e": session.expires_at,
                },
            )
        return True

    async def session(self, token_hash: bytes, now: datetime) -> Session | None:
        row = await self._fetch(
            "SELECT person_id, gym_id, expires_at FROM auth_live_session(:h, :now)",
            {"h": token_hash, "now": now},
        )
        if row is None:
            return None
        gym = None if row.gym_id is None else str(row.gym_id)
        return Session(str(row.person_id), gym, row.expires_at)

    async def end_session(self, token_hash: bytes, now: datetime) -> None:
        await self._execute("SELECT auth_end_session(:h, :now)", {"h": token_hash, "now": now})


class MailSender:
    """Sends each link as the `magic_link` notice. It belongs to no gym, and its URL
    is never written to `message_log`."""

    def __init__(self, notices: Notices) -> None:
        self._notices = notices

    async def send(self, link: Link) -> None:
        recipient = link.recipient
        await self._notices.send(
            Notice(
                MAGIC_LINK,
                to=recipient.address,
                person_id=uuid.UUID(recipient.subject),
                gym_id=None,
                context={"name": recipient.name, "url": link.url},
            )
        )


def bind_session(session: Session, state: dict[str, Any]) -> None:
    person_id = uuid.UUID(session.subject)
    state["person_id"] = person_id
    if session.scope is not None:
        state["tenant"] = Tenant(uuid.UUID(session.scope), person_id)


def build_notices(settings: Settings, mailer: Mailer, sessionmaker: Sessionmaker) -> Notices:
    """Notices with their own sign-in links, for code outside a request: the jobs."""
    return Notices(
        mailer,
        sessionmaker,
        base_url=settings.public_base_url,
        secret_key=settings.secret_key,
        links=build_magic_links(settings, mailer, sessionmaker),
    )


def build_magic_links(settings: Settings, mailer: Mailer, sessionmaker: Sessionmaker) -> MagicLinks:
    return MagicLinks(
        secret_key=settings.secret_key,
        callback_url=callback_url(settings.public_base_url, PREFIX),
        directory=PeopleDirectory(sessionmaker),
        store=PostgresStore(sessionmaker),
        sender=MailSender(
            Notices(
                mailer,
                sessionmaker,
                base_url=settings.public_base_url,
                secret_key=settings.secret_key,
            )
        ),
        per_address=MemoryRateLimiter(limit=PER_ADDRESS[0], window_seconds=PER_ADDRESS[1]),
        per_ip=MemoryRateLimiter(limit=PER_IP[0], window_seconds=PER_IP[1]),
    )
