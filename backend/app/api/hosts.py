"""What a host is (#155): the gym it serves, for the sign-in page; and, for Caddy,
whether a host may have a certificate.

Both answer before anyone signs in. `GET /api/host` says only what the address bar
already does, the gym's name for its slug, and the theme its pages wear (#199) and
its logo (#223), and what the gym calls itself and its members (#344), for the join form
and the privacy page; and whether it is suspended (#439), for every page to show a
notice instead.
`GET /internal/tls-allowed?domain=` is Caddy's on-demand TLS `ask` (deploy/Caddyfile):
200 for a gym's host, and for the host of a slug that still redirects to one (#438),
as the redirect is answered after the TLS handshake; 404 for any other, so a
certificate is only ever requested for a gym that exists. With `MOVED_FROM_DOMAIN` set
(#464), also 200 for that domain itself and for `<slug>.<it>` when the slug is a gym's
or still redirects to one, which Caddy redirects to the gym's host on the base domain.
`GET /internal/host` is Caddy's `forward_auth` before it serves a page of the SPA on a
gym's host (#472), with the request's host, method and URI in `X-Forwarded-*`: the
same 301 or 308 `HostMiddleware` answers on the host of a slug that still redirects,
and 200 for any other host, whose page Caddy then serves. Caddy reaches both on the
api's own port; the public site proxies only `/api/*` and `/healthz`.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import text

from app.api.unsubscribe import in_gym
from app.domain import vocabulary
from app.hosts import GymLookup, Hosts, alias_of, gym_by_slug, host_gym, moved
from app.schemas.hosts import HostGymInfo, HostInfo

router = APIRouter(tags=["hosts"])


@router.get("/api/host")
async def this_host(request: Request) -> HostInfo:
    gym = host_gym(request.state)
    if gym is None:
        return HostInfo(gym=None)
    async with in_gym(request, gym.id) as session:
        words = await session.scalar(
            text("SELECT settings -> 'vocabulary' FROM gym WHERE id = :id"), {"id": gym.id}
        )
    return HostInfo(
        gym=HostGymInfo(
            slug=gym.slug,
            name=gym.name,
            theme=gym.theme,
            logo=gym.logo,
            vocabulary=vocabulary.read(words),
            suspended=gym.suspended,
        )
    )


@router.get(
    "/internal/tls-allowed",
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_404_NOT_FOUND: {"description": "No gym is served there"}},
)
async def tls_allowed(
    request: Request, domain: Annotated[str, Query(max_length=253)] = ""
) -> Response:
    hosts: Hosts = request.app.state.hosts
    if hosts.is_moved_base(domain):
        return Response(status_code=status.HTTP_200_OK)
    slug = hosts.slug_of(domain) or hosts.moved_slug_of(domain)
    if slug is not None:
        # Asked afresh, not through the middleware's lookup: a new gym is at once.
        async with request.app.state.sessionmaker() as session:
            if await gym_by_slug(session, slug) is not None:
                return Response(status_code=status.HTTP_200_OK)
            if await alias_of(session, slug) is not None:
                return Response(status_code=status.HTTP_200_OK)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no gym is served there")


@router.get(
    "/internal/host",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_301_MOVED_PERMANENTLY: {"description": "A GET or HEAD, on an old slug"},
        status.HTTP_308_PERMANENT_REDIRECT: {"description": "Any other method, on an old slug"},
    },
)
async def page_host(
    request: Request,
    x_forwarded_host: Annotated[str, Header(max_length=253)] = "",
    x_forwarded_method: Annotated[str, Header(max_length=16)] = "GET",
    x_forwarded_uri: Annotated[str, Header()] = "/",
) -> Response:
    hosts: Hosts = request.app.state.hosts
    lookup: GymLookup = request.app.state.gym_lookup
    slug = hosts.slug_of(x_forwarded_host)
    if slug is not None and await lookup(slug) is None:
        current = await lookup.alias(slug)
        if current is not None:
            uri = x_forwarded_uri if x_forwarded_uri.startswith("/") else "/"
            return moved(hosts, current, x_forwarded_method.upper(), uri)
    return Response(status_code=status.HTTP_200_OK)
