"""What a host is (#155): the gym it serves, for the sign-in page; and, for Caddy,
whether a host may have a certificate.

Both answer before anyone signs in. `GET /api/host` says only what the address bar
already does, the gym's name for its slug. `GET /internal/tls-allowed?domain=` is
Caddy's on-demand TLS `ask` (deploy/Caddyfile): 200 for a gym's host, 404 for any
other, so a certificate is only ever requested for a gym that exists. Caddy reaches
it on the api's own port; the public site proxies only `/api/*` and `/healthz`.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.hosts import Hosts, gym_by_slug, host_gym
from app.schemas.hosts import HostGymInfo, HostInfo

router = APIRouter(tags=["hosts"])


@router.get("/api/host")
async def this_host(request: Request) -> HostInfo:
    gym = host_gym(request.state)
    return HostInfo(gym=None if gym is None else HostGymInfo(slug=gym.slug, name=gym.name))


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
    raise HTTPException(status.HTTP_404_NOT_FOUND, "no gym is served there")
