"""An operator's sign-in: `/api/platform/auth/{link,callback,code,logout}`.

The same flow as a gym's (`app.magiclink.web`, whose router serves it): an email with a
link, whose page has a button that spends it, and a six-digit code to type instead. A
link and its code expire in 15 minutes and work once; asking again ends the earlier
code. Requests are rate-limited per address and per IP, as a gym's are.

What differs is who it is for and where it lives. `OperatorLinks` issues the links
through migration 0076's functions, never `app.auth`'s directory: an operator is no
gym's person. An address that is no live operator's answers exactly as one that is,
and gets no email; looking it up and sending both run after the answer, as for gyms.
Signing in starts an 8-hour session in the `__Host-platform` cookie
(`app.platform.session`) and lands on `/plataforma`. Every route answers 404 on a
gym's host.
"""

import dataclasses
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import CODE_PER_ADDRESS, CODE_PER_IP, PER_ADDRESS, PER_IP, STYLESHEET, TEXTS
from app.integrations.mailer import Email, Mailer
from app.magiclink import Link, MemoryRateLimiter, RateLimited, RateLimiter, Recipient
from app.magiclink import build_router as build_sign_in_router
from app.magiclink import callback_url as callback_url_of
from app.magiclink.service import LINK_TTL, normalize_address
from app.magiclink.tokens import (
    CodeHasher,
    LinkSigner,
    hash_token,
    new_code,
    new_session_token,
    normalize_code,
)
from app.notices import LOGO_PATH, PLATFORM_LINK, Notice, render
from app.platform.session import on_the_base_host, platform_cookie_name
from app.settings import Settings

logger = logging.getLogger(__name__)

PREFIX = "/api/platform/auth"
# The panel, and its sign-in screen, where "Pedir otro link" goes.
PANEL = "/plataforma"
SIGN_IN = "/plataforma/ingresar"

# 0076's `platform_redeem_link` starts every session with as long; the cookie lasts as long.
SESSION_TTL = timedelta(hours=8)

TEXTS = dataclasses.replace(
    TEXTS,
    title="Entrar a la plataforma de {name}",
    unreachable="Este correo no tiene acceso a la plataforma de {name}.",
)

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]


class OperatorLinks:
    """Links and codes for operators, kept in `operator_link` and `operator_session`
    through 0076's functions: what `app.magiclink.build_router` asks of `MagicLinks`."""

    def __init__(
        self,
        *,
        secret_key: str,
        callback_url: str,
        sessionmaker: Sessionmaker,
        mailer: Mailer,
        per_address: RateLimiter,
        per_ip: RateLimiter,
        code_per_address: RateLimiter,
        code_per_ip: RateLimiter,
        link_ttl: timedelta = LINK_TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.callback_url = callback_url
        self.session_ttl = SESSION_TTL
        self.mailer = mailer
        self._sessionmaker = sessionmaker
        self._per_address = per_address
        self._per_ip = per_ip
        self._code_per_address = code_per_address
        self._code_per_ip = code_per_ip
        self._link_ttl = link_ttl
        self._signer = LinkSigner(secret_key)
        self._codes = CodeHasher(secret_key)
        self._clock = clock
        parts = urlsplit(callback_url)
        self._origin = f"{parts.scheme}://{parts.netloc}"

    def admit(self, address: str, ip: str) -> None:
        _admit(((self._per_ip, ip), (self._per_address, normalize_address(address))))

    def admit_code(self, address: str, ip: str) -> None:
        _admit(((self._code_per_ip, ip), (self._code_per_address, normalize_address(address))))

    async def _fetch(self, sql: str, params: dict[str, Any]) -> Any:
        async with self._sessionmaker()() as session, session.begin():
            return (await session.execute(text(sql), params)).one_or_none()

    async def send_links(self, address: str, *, base_url: str | None = None) -> list[Link]:
        """Issue and send a link, with a code, if `address` is a live operator's; the
        links sent. Always on the base host, whatever `base_url` the router names."""
        address = normalize_address(address)
        expires_at = self._clock() + self._link_ttl
        token = self._signer.issue(expires_at)
        code = new_code()
        try:
            found = await self._fetch(
                "SELECT operator_id, name FROM platform_issue_link(:a, :h, :c, :e)",
                {
                    "a": address,
                    "h": hash_token(token),
                    "c": self._codes.hash(code, address, self._origin),
                    "e": expires_at,
                },
            )
            if found is None:
                return []
            link = Link(
                Recipient(str(found.operator_id), address, found.name),
                f"{self.callback_url}?{urlencode({'token': token})}",
                expires_at,
                code,
            )
            await self.mailer.send(self._email(link))
        # After the answer, with no one to tell. The log names the operator, never the link.
        except Exception:
            logger.exception("platform link not sent")
            return []
        return [link]

    def _email(self, link: Link) -> Email:
        recipient = link.recipient
        # Never through `Notices.send`, so nothing reaches `message_log`, a gym's record.
        return render(
            Notice(
                PLATFORM_LINK,
                to=recipient.address,
                person_id=uuid.UUID(recipient.subject),
                gym_id=None,
                context={"name": recipient.name, "url": link.url, "code": link.code},
            ),
            logo_url=f"{self._origin}{LOGO_PATH}",
        )

    def looks_valid(self, token: str) -> bool:
        return self._signer.valid(token, self._clock())

    async def _start(self, link_hash: bytes | None, code_hash: bytes | None) -> str | None:
        session_token = new_session_token()
        started = await self._fetch(
            "SELECT platform_redeem_link(CAST(:h AS bytea), CAST(:c AS bytea), :s, :now)"
            " AS started",
            {"h": link_hash, "c": code_hash, "s": hash_token(session_token), "now": self._clock()},
        )
        return session_token if started is not None and started.started else None

    async def redeem(self, token: str, *, within: str | None = None) -> str | None:
        """Spend a link on a new session; its token, or None."""
        if not self._signer.valid(token, self._clock()):
            return None
        return await self._start(hash_token(token), None)

    async def redeem_code(
        self, address: str, code: str, *, base_url: str | None = None, within: str | None = None
    ) -> str | None:
        """Spend the link `code` came with at `address` on a new session; its token, or
        None for a wrong, spent or expired code alike."""
        digits = normalize_code(code)
        if digits is None:
            return None
        return await self._start(
            None, self._codes.hash(digits, normalize_address(address), self._origin)
        )

    async def end_session(self, session_token: str) -> None:
        await self._fetch("SELECT platform_end_session(:h)", {"h": hash_token(session_token)})


def _admit(hits: tuple[tuple[RateLimiter, str], ...]) -> None:
    for limiter, key in hits:
        retry_after = limiter.hit(key)
        if retry_after is not None:
            raise RateLimited(retry_after)


def build_operator_links(
    settings: Settings, mailer: Mailer, sessionmaker: Sessionmaker
) -> OperatorLinks:
    return OperatorLinks(
        secret_key=settings.secret_key,
        callback_url=callback_url_of(settings.public_base_url, PREFIX),
        sessionmaker=sessionmaker,
        mailer=mailer,
        per_address=MemoryRateLimiter(limit=PER_ADDRESS[0], window_seconds=PER_ADDRESS[1]),
        per_ip=MemoryRateLimiter(limit=PER_IP[0], window_seconds=PER_IP[1]),
        code_per_address=MemoryRateLimiter(
            limit=CODE_PER_ADDRESS[0], window_seconds=CODE_PER_ADDRESS[1]
        ),
        code_per_ip=MemoryRateLimiter(limit=CODE_PER_IP[0], window_seconds=CODE_PER_IP[1]),
    )


def build_platform_router(links: OperatorLinks, settings: Settings) -> APIRouter:
    """The sign-in endpoints, on the base host only."""
    router = APIRouter()
    router.include_router(
        build_sign_in_router(
            links,
            prefix=PREFIX,
            base_url=settings.public_base_url,
            after_login=PANEL,
            cookie_name=platform_cookie_name(settings.public_base_url),
            texts=TEXTS,
            sign_in=SIGN_IN,
            stylesheet=STYLESHEET,
        ),
        dependencies=[Depends(on_the_base_host)],
    )
    return router
