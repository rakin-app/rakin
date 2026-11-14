"""Issuing and redeeming links, and the sessions they turn into.

The application supplies three things: a `Directory` (who an address belongs to), a
`Store` (where hashed links and sessions live) and a `Sender` (how a link reaches
its recipient). Accounts are opaque strings here, `subject`s, and so is a session's
`scope`: whatever the application wants a session to start in, such as a tenant.

A link remembers the address it was sent to, and so does the session it turns into:
one account may be reached at several addresses, and what a session may do can depend
on which one it signed in with. `Directory.scope` is asked with both.

One application may serve several sites, each at its own base URL and each its own
scope (a tenant on its own host). A link can then point at the site it was asked for
from (`base_url=`), and be redeemed `within` that site's scope: the session starts
there, or not at all (`Unreachable`).

A link may come with a six-digit code (`issue(code=True)`), for whoever cannot open the
link in the window they asked from: an app installed to an iPhone's home screen, which
mail and WhatsApp never open links in. The code is bound to the link's address and
site, expires with it and is spent with it, either way round. Asking for links again
(`send_links`) ends every earlier code of the account's at the address; a code sent
unasked, in a welcome, ends none, so it never undoes the one just asked for. A code is
good for `CODE_TRIES` wrong codes typed at its address; then it is spent too, and the
link still works.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from app.magiclink.ratelimit import MemoryRateLimiter, RateLimiter
from app.magiclink.tokens import (
    CodeHasher,
    LinkSigner,
    hash_token,
    new_code,
    new_session_token,
    normalize_code,
)

logger = logging.getLogger(__name__)

LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)
# Wrong codes typed at an address before its codes are spent.
CODE_TRIES = 5


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
    code: str | None = None  # six digits that sign in as the link does


@dataclass(frozen=True)
class Pending:
    """An unused link's account, and the address it was sent to."""

    subject: str
    address: str


@dataclass(frozen=True)
class CodeLink:
    """The unused link a code came with, expired or not."""

    token_hash: bytes
    subject: str
    address: str
    expires_at: datetime


@dataclass(frozen=True)
class Session:
    subject: str
    address: str  # the address its link was sent to
    scope: str | None
    expires_at: datetime


class Directory(Protocol):
    async def recipients(self, address: str) -> Sequence[Recipient]:
        """The accounts a link for `address` goes to; empty if none."""
        ...

    async def scope(self, subject: str, address: str, within: str | None = None) -> str | None:
        """What a new session for `subject`, signed in at `address`, starts in, if
        anything. With `within`, that scope if such a session may start there, else
        None."""
        ...


class Store(Protocol):
    async def add_link(
        self,
        token_hash: bytes,
        subject: str,
        address: str,
        expires_at: datetime,
        code_hash: bytes | None = None,
        replace_codes: bool = False,
    ) -> None:
        """Store a link, and with `code_hash` its code. With `replace_codes`, every
        earlier code of `subject`'s at `address` (case ignored) stops working."""
        ...

    async def code_link(self, code_hash: bytes) -> CodeLink | None:
        """The unused link whose code has this hash, while the code works; else None."""
        ...

    async def miss_code(self, address: str, now: datetime, tries: int) -> None:
        """Count a wrong code against every working, unexpired code at `address` (case
        ignored), and spend those that reach `tries` misses."""
        ...

    async def pending_link(self, token_hash: bytes, now: datetime) -> Pending | None:
        """The account and address of an unused, unexpired link, leaving it unused;
        else None."""
        ...

    async def redeem_link(
        self, token_hash: bytes, now: datetime, session_hash: bytes, session: Session
    ) -> bool:
        """Mark the link used and store `session` in one transaction; False if it can't.

        It can't when the link is used, expired, or not `session.subject`'s at
        `session.address`. Must be atomic: of two concurrent redemptions of one link,
        exactly one gets through, and a failure leaves the link unused.
        """
        ...

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


class Unreachable(Exception):
    """The link's account may not sign in within the scope it was redeemed in."""


class CodeExpired(Exception):
    """The code is right but has expired with its link."""


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
        code_per_address: RateLimiter | None = None,
        code_per_ip: RateLimiter | None = None,
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
        # Codes typed, apart from links asked for: a mistyped code must not cost a link.
        self.code_per_address = code_per_address or MemoryRateLimiter(
            limit=CODE_TRIES, window_seconds=LINK_TTL.total_seconds()
        )
        self.code_per_ip = code_per_ip or MemoryRateLimiter(
            limit=60, window_seconds=LINK_TTL.total_seconds()
        )
        self.link_ttl = link_ttl
        self.session_ttl = session_ttl
        self._signer = LinkSigner(secret_key)
        self._codes = CodeHasher(secret_key)
        self._clock = clock

    def admit(self, address: str, ip: str) -> None:
        """Count a request for a link against the IP and the address; raises `RateLimited`.

        Counted whether or not anyone is at the address, so the answer says nothing
        about who has an account.
        """
        _admit(((self.per_ip, ip), (self.per_address, normalize_address(address))))

    def admit_code(self, address: str, ip: str) -> None:
        """Count a code typed at `address` from `ip`; raises `RateLimited`. Counted
        whoever is at the address, as `admit` is."""
        _admit(((self.code_per_ip, ip), (self.code_per_address, normalize_address(address))))

    async def send_links(self, address: str, *, base_url: str | None = None) -> list[Link]:
        """Issue and send a link, with a code, to every account at `address`; returns
        those sent.

        The links point at `base_url`'s origin when given, as `issue` does. Run it
        after answering the request: it is all the work a known address costs and an
        unknown one does not.
        """
        sent = []
        for recipient in await self.directory.recipients(address):
            # One failure must not cost the others theirs (a parent and child share an
            # address). The log names the account, never the link.
            try:
                link = await self.issue(recipient, base_url=base_url, code=True, replace_codes=True)
                await self.sender.send(link)
            except Exception:
                logger.exception("magic link not sent", extra={"subject": recipient.subject})
                continue
            sent.append(link)
        return sent

    async def issue(
        self,
        recipient: Recipient,
        *,
        ttl: timedelta | None = None,
        landing: str | None = None,
        base_url: str | None = None,
        code: bool = False,
        replace_codes: bool = False,
    ) -> Link:
        """A new single-use link for `recipient`, stored and ready to send.

        It expires after `ttl`, `link_ttl` unless given: a link sent unasked, inside a
        message read days later, needs longer than one the person just asked for.
        `landing` is where signing in with it lands, if the router lists it among its
        `landings`; anywhere else lands on its `after_login`. It points at
        `callback_url`, on `base_url`'s origin when given: another of the sites one
        application serves.

        With `code`, it comes with a code that signs in as it does, on that site only,
        until it expires. With `replace_codes` as well, as when they ask again, any
        earlier code for `recipient` stops working; else the earlier ones keep working.
        """
        expires_at = self._clock() + (self.link_ttl if ttl is None else ttl)
        token = self._signer.issue(expires_at)
        callback = self.callback_on(base_url)
        sign_in_code = new_code() if code else None
        code_hash = (
            None
            if sign_in_code is None
            else self._codes.hash(
                sign_in_code, normalize_address(recipient.address), _origin(callback)
            )
        )
        await self.store.add_link(
            hash_token(token),
            recipient.subject,
            recipient.address,
            expires_at,
            code_hash,
            replace_codes=replace_codes and code_hash is not None,
        )
        query = {"token": token} if landing is None else {"token": token, "next": landing}
        return Link(recipient, f"{callback}?{urlencode(query)}", expires_at, sign_in_code)

    def callback_on(self, base_url: str | None) -> str:
        """`callback_url`, on `base_url`'s origin; as it is for None."""
        if base_url is None:
            return self.callback_url
        site = urlsplit(base_url)
        return urlsplit(self.callback_url)._replace(scheme=site.scheme, netloc=site.netloc).geturl()

    def looks_valid(self, token: str) -> bool:
        """Signed here and not expired; says nothing about whether it was used."""
        return self._signer.valid(token, self._clock())

    async def redeem(self, token: str, *, within: str | None = None) -> str | None:
        """Spend a link on a new session; returns the session token, or None.

        With `within`, the session starts in that scope, and if the directory says it
        may not, raises `Unreachable` and leaves the link unspent.
        """
        now = self._clock()
        if not self._signer.valid(token, now):
            return None
        link_hash = hash_token(token)
        pending = await self.store.pending_link(link_hash, now)
        if pending is None:
            return None
        return await self._spend(link_hash, pending, now, within)

    async def redeem_code(
        self, address: str, code: str, *, base_url: str | None = None, within: str | None = None
    ) -> str | None:
        """Spend the link a code came with on a new session; returns the session token,
        or None for a code that is wrong at `address` on `base_url`'s site, spent or
        unknown, which counts as a miss.

        Raises `CodeExpired` for a right code whose link has expired, and `Unreachable`
        as `redeem` does, leaving the code unspent.
        """
        now = self._clock()
        address = normalize_address(address)
        digits = normalize_code(code)
        found = (
            None
            if digits is None
            else await self.store.code_link(
                self._codes.hash(digits, address, _origin(self.callback_on(base_url)))
            )
        )
        if found is None:
            await self.store.miss_code(address, now, CODE_TRIES)
            return None
        if now >= found.expires_at:
            raise CodeExpired
        return await self._spend(
            found.token_hash, Pending(found.subject, found.address), now, within
        )

    async def _spend(
        self, link_hash: bytes, pending: Pending, now: datetime, within: str | None
    ) -> str | None:
        # Everything that can fail happens before the link is spent, so a failure
        # leaves it usable.
        session_token = new_session_token()
        scope = await self.directory.scope(pending.subject, pending.address, within)
        if within is not None and scope != within:
            raise Unreachable
        session = Session(pending.subject, pending.address, scope, now + self.session_ttl)
        if not await self.store.redeem_link(link_hash, now, hash_token(session_token), session):
            return None
        return session_token

    async def session(self, session_token: str) -> Session | None:
        return await self.store.session(hash_token(session_token), self._clock())

    async def end_session(self, session_token: str) -> None:
        await self.store.end_session(hash_token(session_token), self._clock())


def _admit(hits: Sequence[tuple[RateLimiter, str]]) -> None:
    for limiter, key in hits:
        retry_after = limiter.hit(key)
        if retry_after is not None:
            raise RateLimited(retry_after)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
