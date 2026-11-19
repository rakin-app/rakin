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

A slug a gym had before a rename (#438) redirects for 90 days: when no gym has the
host's slug, `auth_gym_alias` (0078) is asked for the gym's current one, and the
request is answered with a 301 to the same path and query there, or a 308 for any
method but GET and HEAD, which keeps the method and its body; it never reaches the
app. Caddy serves the SPA's pages without the app, so on a gym's host it asks
`GET /internal/host` (`app.api.hosts`) first (#472), which answers the same redirect.
A live alias is kept for a minute too, as a found gym is; `GymLookup.forget` drops
both, and a rename forgets the old slug and the new.

A domain the gyms were served under before (`MOVED_FROM_DOMAIN`, #464) is Caddy's to
redirect: `<slug>.<it>` to the gym's host, `<it>` itself to the base host. The app only
says which of its names may have a certificate (`moved_slug_of`, `app.api.hosts`).
"""

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import URL, Headers
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.logos import logo_path
from app.schemas.theme import DEFAULT_THEME, Theme
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
        "rsend",  # Resend's own record, `rsend.<domain>`, a CNAME in the zone
        "send",  # Resend's return path, `send.<domain>`, has records of its own
        "sitio",  # staging's landing page
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


def slug_refusal(slug: str) -> Literal["format", "reserved"] | None:
    """Which way `slug` cannot be a gym's, or None when it can."""
    if not SLUG.match(slug):
        return "format"
    if slug in RESERVED:
        return "reserved"
    return None


def slug_problem(slug: str) -> str | None:
    """Why `slug` cannot be a gym's, or None when it can."""
    refusal = slug_refusal(slug)
    if refusal == "format":
        return (
            "a slug is lower-case letters, digits and hyphens, at most 63, and does not"
            " start or end with a hyphen"
        )
    if refusal == "reserved":
        return f"{slug!r} is reserved"
    return None


def host_name(host: str) -> str:
    """A `Host` header's name: lower-case, without its port or a trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):  # an IPv6 literal is never a gym's
        return host
    return host.rpartition(":")[0].rstrip(".") if ":" in host else host.rstrip(".")


def slug_under(host: str, domain: str) -> str | None:
    """The slug `host` names as one label under `domain`; None with no `domain`, for
    `domain` itself, a reserved name or any other host."""
    if not domain:
        return None
    label, dot, rest = host_name(host).partition(".")
    if not dot or rest != domain:
        return None
    return label if slug_problem(label) is None else None


@dataclass(frozen=True)
class Hosts:
    """Where each gym is served: `public_base_url`'s scheme and port, on
    `<slug>.<base_domain>`. With no `base_domain`, every gym is on `public_base_url`.
    `moved_from_domain`, when set, is where they were served before."""

    public_base_url: str
    base_domain: str = ""
    moved_from_domain: str = ""

    @classmethod
    def of(cls, settings: Settings) -> "Hosts":
        return cls(settings.public_base_url, settings.base_domain, settings.moved_from_domain)

    def slug_of(self, host: str) -> str | None:
        """The gym slug a host names, from a `Host` header or a bare name; None for
        the base host, a reserved name or a host outside the base domain."""
        return slug_under(host, self.base_domain)

    def moved_slug_of(self, host: str) -> str | None:
        """The slug a host names under `moved_from_domain`, as `slug_of` does under
        the base domain; None for every host when it is not set."""
        return slug_under(host, self.moved_from_domain)

    def is_moved_base(self, host: str) -> bool:
        """Whether `host` is `moved_from_domain` itself, the old base host."""
        return bool(self.moved_from_domain) and host_name(host) == self.moved_from_domain

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
    # The gym's theme (#199), for the pages shown before anyone signs in.
    theme: Theme = DEFAULT_THEME
    # Its logo's version (#223, `app.logos`), None with no logo; for the same pages.
    logo_version: str | None = None
    # Suspended from the platform's panel (#439): its host shows only a notice.
    suspended: bool = False

    @property
    def logo(self) -> str | None:
        """Where its logo's files are, `<logo>/<variant>`; None with no logo."""
        return logo_path(self.id, self.logo_version)


async def gym_by_slug(session: AsyncSession, slug: str) -> HostGym | None:
    row = (
        await session.execute(
            text("SELECT id, name, theme, logo_version, suspended FROM auth_gym_by_slug(:slug)"),
            {"slug": slug},
        )
    ).one_or_none()
    if row is None:
        return None
    return HostGym(row.id, slug, row.name, row.theme, row.logo_version, row.suspended)


async def alias_of(session: AsyncSession, slug: str) -> str | None:
    """The current slug of the gym that had `slug` before a rename, while it redirects."""
    current: str | None = await session.scalar(
        text("SELECT slug FROM auth_gym_alias(:slug)"), {"slug": slug}
    )
    return current


class GymLookup:
    """Gyms by slug through the app's database, each one found kept `ttl` seconds; and
    the slugs that redirect to a gym (`alias`), each one live kept as long."""

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
        self._aliases: dict[str, tuple[float, str]] = {}

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

    async def alias(self, slug: str) -> str | None:
        """The slug `slug` redirects to, or None when it redirects nowhere."""
        now = self._clock()
        kept = self._aliases.get(slug)
        if kept is not None and kept[0] > now:
            return kept[1]
        async with self._sessionmaker()() as session:
            current = await alias_of(session, slug)
        if current is None:
            self._aliases.pop(slug, None)
        else:
            self._aliases[slug] = (now + self._ttl, current)
        return current

    def forget(self, slug: str) -> None:
        """Drops what is kept for `slug`, so the next request reads it afresh: after a
        change to what a host shows, such as the gym's theme or logo, or its slug. The
        API runs as one process (backend/Dockerfile), so this is every copy there is."""
        self._found.pop(slug, None)
        self._aliases.pop(slug, None)


class HostMiddleware:
    """Puts the gym the request's host names, or None, on `request.state.host_gym`; on
    the host of a slug that redirects (`alias`), answers a 301 to the gym's own, or a
    308 for any method but GET and HEAD."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        hosts: Hosts,
        lookup: Callable[[str], Awaitable[HostGym | None]],
        alias: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self.app = app
        self.hosts = hosts
        self.lookup = lookup
        self.alias = alias

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            slug = self.hosts.slug_of(Headers(scope=scope).get("host", ""))
            gym = None if slug is None else await self.lookup(slug)
            if slug is not None and gym is None and self.alias is not None:
                current = await self.alias(slug)
                if current is not None:
                    url = URL(scope=scope)
                    query = f"?{url.query}" if url.query else ""
                    response = moved(self.hosts, current, scope["method"], f"{url.path}{query}")
                    await response(scope, receive, send)
                    return
            scope.setdefault("state", {})["host_gym"] = gym
        await self.app(scope, receive, send)


def moved(hosts: Hosts, slug: str, method: str, uri: str) -> RedirectResponse:
    """A redirect to `uri`, a path and query, on the host of the gym's slug `slug`: a
    301 for GET and HEAD, a 308 for any other method."""
    # 308 keeps a POST a POST, with its body; a 301 may turn it into a GET.
    code = 301 if method in ("GET", "HEAD") else 308
    return RedirectResponse(f"{hosts.base_url(slug)}{uri}", status_code=code)


def host_gym(state: object) -> HostGym | None:
    """The gym of the request whose `request.state` (or ASGI state dict) this is."""
    if isinstance(state, dict):
        return state.get("host_gym")
    return getattr(state, "host_gym", None)
