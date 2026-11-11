"""A gym's logo, to anyone: `GET /api/logos/<gym_id>/<version>/<variant>` (#223).

The sign-in, join and privacy pages show it before anyone signs in, and email clients
fetch it with no session at all, so this asks for none. It says nothing the pages do
not already show: the files are the logo and only the logo (`app.logos`), and a
version is a random name that only the gym's own pages and emails carry.

The API serves the bytes itself, from whichever blob store this instance has, so the
URL is the app's own, the same on R2 as on local disk, and never expires the way a
presigned one would. A version's files never change (a new logo is a new version), so
they are cached for a year; a version that is no longer stored is a 404.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from app.integrations import Integrations, get_integrations
from app.logos import PATH_PREFIX, VARIANTS, key

router = APIRouter(prefix=PATH_PREFIX, tags=["logos"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "no such logo")

HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
    # An image, never a page: nothing in it may run, whatever it turns out to be.
    "Content-Security-Policy": "default-src 'none'; sandbox",
    # Email clients and the pages of any of the gym's hosts load it.
    "Cross-Origin-Resource-Policy": "cross-origin",
}


@router.get("/{gym_id}/{version}/{variant}")
async def logo(
    gym_id: uuid.UUID,
    version: Annotated[str, Path(pattern=r"^[0-9a-f]{16,32}$")],
    variant: str,
    integrations: Annotated[Integrations, Depends(get_integrations)],
) -> Response:
    found = VARIANTS.get(variant)
    if found is None:
        raise NOT_FOUND
    data = await integrations.blob_store.get(key(gym_id, version, variant))
    if data is None:
        raise NOT_FOUND
    return Response(data, media_type=found.content_type, headers=HEADERS)
