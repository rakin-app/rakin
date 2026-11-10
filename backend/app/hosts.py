"""Each gym on its own host, `<slug>.<base domain>` (#155): `meta.rakin.app`.

A gym's slug is a DNS label (migration 0030), and not one of the names the app keeps
for itself (`RESERVED`). A request to a gym's host acts for that gym: its sign-in page
names it, a link asked for there points back there and signs in to it alone
(`app.auth`), and a session there works only in it. The base host itself, and every
host when `BASE_DOMAIN` is empty, keeps the behaviour of before: one host for every
gym, the gym picked from the person's records.

`HostMiddleware` puts the request's gym, if its host names one, on `request.state` as
`host_gym`, before the session middleware reads it. Looking a slug up is a query
through `auth_gym_by_slug` (0030), since nobody has signed in yet; a gym found is kept
for a minute, since a gym's slug and name hardly change and every request on its host
asks. A slug that names no gym is asked again each time: a gym just created is found
at once, and a host no gym has never gets a certificate (`app.api.tls`), so its
requests do not reach here over HTTPS.
"""

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.settings import Settings

# A DNS label: what 0030's CHECK holds every slug to.
SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Host names the app or its operators may want for something other than a gym.
RESERVED = frozenset(
    {
        "admin",
        "api",
        "app",
        "assets",
        "auth",
        "blog",
        "cdn",
        "dev",
        "docs",
        "ftp",
        "help",
        "internal",
        "localhost",
        "mail",
        "prod",
        "production",
        "rakin",
        "smtp",
        "soporte",
        "staging",
        "static",
        "status",
        "support",
        "test",
        "www",
    }
)

GYM_TTL_SECONDS = 60.0

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]


def slug_problem(slug: str) -> str | None:
    """Why `slug` cannot be a gym's, or None when it can."""
    if not SLUG.match(slug):
        return (
            "a slug is lower-case letters, digits and hyphens, at most 63, and does not"
            " start or end with a hyphen"
        )
    if slug in RESERVED:
        return f"{slug!r} is reserved"
    return None


def host_name(host: str) -> str:
    """A `Host` header's name: lower-case, without its port or a trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):  # an IPv6 literal is never a gym's
        return host
    return host.rpartition(":")[0].rstrip(".") if ":" in host else host.rstrip(".")


@dataclass(frozen=True)
class Hosts:
    """Where each gym is served: `public_base_url`'s scheme and port, on
    `<slug>.<base_domain>`. With no `base_domain`, every gym is on `public_base_url`."""

    public_base_url: str
    base_domain: str = ""

    @classmethod
    def of(cls, settings: Settings) -> "Hosts":
        return cls(settings.public_base_url, settings.base_domain)

    def slug_of(self, host: str) -> str | None:
        """The gym slug a host names, from a `Host` header or a bare name; None for
        the base host, a reserved name or a host outside the base domain."""
        if not self.base_domain:
            return None
        label, dot, rest = host_name(host).partition(".")
        if not dot or rest != self.base_domain:
            return None
        return label if slug_problem(label) is None else None

    def base_url(self, slug: str | None) -> str:
        """Where browsers reach the gym with `slug`, or the base host for None."""
        base = self.public_base_url.rstrip("/")
        if slug is None or not self.base_domain:
            return base
        parts = urlsplit(base)
        port = f":{parts.port}" if parts.port else ""
        return parts._replace(netloc=f"{slug}.{self.base_domain}{port}").geturl()


@dataclass(frozen=True)
class HostGym:
    id: uuid.UUID
    slug: str
    name: str


async def gym_by_slug(session: AsyncSession, slug: str) -> HostGym | None:
    row = (
        await session.execute(text("SELECT id, name FROM auth_gym_by_slug(:slug)"), {"slug": slug})
    ).one_or_none()
    return None if row is None else HostGym(row.id, slug, row.name)


class GymLookup:
    """Gyms by slug through the app's database, each one found kept `ttl` seconds."""

    def __init__(
        self,
        sessionmaker: Sessionmaker,
        *,
        ttl: float = GYM_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._ttl = ttl
        self._clock = clock
        self._found: dict[str, tuple[float, HostGym]] = {}

    async def __call__(self, slug: str) -> HostGym | None:
        now = self._clock()
        kept = self._found.get(slug)
        if kept is not None and kept[0] > now:
            return kept[1]
        async with self._sessionmaker()() as session:
            gym = await gym_by_slug(session, slug)
        if gym is None:
            self._found.pop(slug, None)
        else:
            self._found[slug] = (now + self._ttl, gym)
        return gym


class HostMiddleware:
    """Puts the gym the request's host names, or None, on `request.state.host_gym`."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        hosts: Hosts,
        lookup: Callable[[str], Awaitable[HostGym | None]],
    ) -> None:
        self.app = app
        self.hosts = hosts
        self.lookup = lookup

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            slug = self.hosts.slug_of(Headers(scope=scope).get("host", ""))
            gym = None if slug is None else await self.lookup(slug)
            scope.setdefault("state", {})["host_gym"] = gym
        await self.app(scope, receive, send)


def host_gym(state: object) -> HostGym | None:
    """The gym of the request whose `request.state` (or ASGI state dict) this is."""
    if isinstance(state, dict):
        return state.get("host_gym")
    return getattr(state, "host_gym", None)
