"""Issuing and redeeming links, and the sessions they turn into.

The application supplies three things: a `Directory` (who an address belongs to), a
`Store` (where hashed links and sessions live) and a `Sender` (how a link reaches
its recipient). Accounts are opaque strings here, `subject`s, and so is a session's
`scope`: whatever the application wants a session to start in, such as a tenant.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from app.magiclink.ratelimit import RateLimiter
from app.magiclink.tokens import LinkSigner, hash_token, new_session_token

LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)


@dataclass(frozen=True)
class Recipient:
    subject: str  # the application's id for the account
    address: str  # where the link is sent
    name: str


@dataclass(frozen=True)
class Link:
    recipient: Recipient
    url: str
    expires_at: datetime


@dataclass(frozen=True)
class Session:
    subject: str
    scope: str | None
    expires_at: datetime


class Directory(Protocol):
    async def recipients(self, address: str) -> Sequence[Recipient]:
        """The accounts a link for `address` goes to; empty if none."""
        ...

    async def scope(self, subject: str) -> str | None:
        """What a new session for `subject` starts in, if anything."""
        ...


class Store(Protocol):
    async def add_link(self, token_hash: bytes, subject: str, expires_at: datetime) -> None: ...

    async def redeem_link(self, token_hash: bytes, now: datetime) -> str | None:
        """Mark an unused, unexpired link used and return its subject; else None.

        Must be atomic: two concurrent redemptions of one link let exactly one through.
        """
        ...

    async def add_session(self, token_hash: bytes, session: Session) -> None: ...

    async def session(self, token_hash: bytes, now: datetime) -> Session | None:
        """The live session with this hash: not expired, not ended."""
        ...

    async def end_session(self, token_hash: bytes, now: datetime) -> None: ...


class Sender(Protocol):
    async def send(self, link: Link) -> None:
        """Deliver `link` to its recipient. Runs after the response is sent."""
        ...


class RateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"too many link requests; retry in {retry_after:.0f}s")
        self.retry_after = retry_after


def normalize_address(address: str) -> str:
    return address.strip().lower()


class MagicLinks:
    def __init__(
        self,
        *,
        secret_key: str,
        callback_url: str,
        directory: Directory,
        store: Store,
        sender: Sender,
        per_address: RateLimiter,
        per_ip: RateLimiter,
        link_ttl: timedelta = LINK_TTL,
        session_ttl: timedelta = SESSION_TTL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.callback_url = callback_url
        self.directory = directory
        self.store = store
        self.sender = sender
        self.per_address = per_address
        self.per_ip = per_ip
        self.link_ttl = link_ttl
        self.session_ttl = session_ttl
        self._signer = LinkSigner(secret_key)
        self._clock = clock

    async def request_links(self, address: str, ip: str) -> list[Link]:
        """Links for every account at `address`, to be sent; raises `RateLimited`.

        Counts against both the address and the IP, whether or not anyone is at the
        address, so the answer says nothing about who has an account.
        """
        for limiter, key in ((self.per_ip, ip), (self.per_address, normalize_address(address))):
            retry_after = limiter.hit(key)
            if retry_after is not None:
                raise RateLimited(retry_after)
        return [await self.issue(r) for r in await self.directory.recipients(address)]

    async def issue(self, recipient: Recipient) -> Link:
        """A new single-use link for `recipient`, stored and ready to send."""
        expires_at = self._clock() + self.link_ttl
        token = self._signer.issue(expires_at)
        await self.store.add_link(hash_token(token), recipient.subject, expires_at)
        return Link(recipient, f"{self.callback_url}?{urlencode({'token': token})}", expires_at)

    def looks_valid(self, token: str) -> bool:
        """Signed here and not expired; says nothing about whether it was used."""
        return self._signer.valid(token, self._clock())

    async def redeem(self, token: str) -> str | None:
        """Spend a link on a new session; returns the session token, or None."""
        now = self._clock()
        if not self._signer.valid(token, now):
            return None
        subject = await self.store.redeem_link(hash_token(token), now)
        if subject is None:
            return None
        session_token = new_session_token()
        session = Session(subject, await self.directory.scope(subject), now + self.session_ttl)
        await self.store.add_session(hash_token(session_token), session)
        return session_token

    async def session(self, session_token: str) -> Session | None:
        return await self.store.session(hash_token(session_token), self._clock())

    async def end_session(self, session_token: str) -> None:
        await self.store.end_session(hash_token(session_token), self._clock())
