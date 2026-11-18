"""What a host is (#155): the gym it serves, for the sign-in page; and, for Caddy,
whether a host may have a certificate.

Both answer before anyone signs in. `GET /api/host` says only what the address bar
already does, the gym's name for its slug, and the theme its pages wear (#199) and
its logo (#223), and what the gym calls itself and its members (#344), for the join form
and the privacy page.
`GET /internal/tls-allowed?domain=` is Caddy's on-demand TLS `ask` (deploy/Caddyfile):
200 for a gym's host, and for the host of a slug that still redirects to one (#438),
as the redirect is answered after the TLS handshake; 404 for any other, so a
certificate is only ever requested for a gym that exists. Caddy reaches it on the
api's own port; the public site proxies only `/api/*` and `/healthz`.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import text

from app.api.unsubscribe import in_gym
from app.domain import vocabulary
from app.hosts import Hosts, alias_of, gym_by_slug, host_gym
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
    slug = hosts.slug_of(domain)
    if slug is not None:
        # Asked afresh, not through the middleware's lookup: a new gym is at once.
        async with request.app.state.sessionmaker() as session:
            if await gym_by_slug(session, slug) is not None:
                return Response(status_code=status.HTTP_200_OK)
            if await alias_of(session, slug) is not None:
                return Response(status_code=status.HTTP_200_OK)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no gym is served there")
