"""The current gym's settings: read them, change them.

Owner and admin only (`AdminSession`): the bank details decide where students send
their money, so a coach may neither read nor change them.

Saving the privacy details stamps them with the gym's today (`updated_on`), in the
timezone the same change leaves it in: the date the public notice says it was last
updated.

The logo (#223) has endpoints of its own, since it is a file: `PUT /api/gym/logo` takes
the picture as the owner picked it, its bytes as the body, with the square they drew
on it as `x`, `y` and `size`; `DELETE` takes it away. Each answers the settings, like
a `PATCH`, and deletes the previous files once the change is saved (`app.logos`).
"""

import asyncio
import json
import logging
import uuid
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi import status as http
from sqlalchemy import text

from app.domain.dates import gym_today
from app.hosts import Hosts
from app.integrations import Integrations, get_integrations
from app.integrations.blobstore import BlobStore
from app.logos import (
    CONTENT_TYPES,
    MAX_LOGO_BYTES,
    VARIANTS,
    Crop,
    LogoRefused,
    key,
    logo_path,
    make_variants,
    new_version,
)
from app.roles import AdminSession
from app.schemas.gym import SETTINGS_KEYS, GymSettings, GymSettingsUpdate
from app.tenancy import Tenant, current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gym", tags=["gym"])

COLUMNS = "id, name, slug, timezone, theme, logo_version, settings"

TOO_LARGE = HTTPException(http.HTTP_413_CONTENT_TOO_LARGE, "logo_too_large")


def _settings(request: Request, row: Any) -> GymSettings:
    hosts: Hosts = request.app.state.hosts
    # The address as the address bar shows it: `academia-sur.rakin.app`, no scheme.
    address = urlsplit(hosts.base_url(row.slug)).netloc
    return GymSettings.from_row(
        row.name,
        row.slug,
        address,
        row.timezone,
        row.theme,
        logo_path(row.id, row.logo_version),
        row.settings,
    )


@router.get("/settings")
async def get_settings(
    request: Request, tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> GymSettings:
    row = (
        await session.execute(
            text(f"SELECT {COLUMNS} FROM gym WHERE id = :id"), {"id": tenant.gym_id}
        )
    ).one()
    return _settings(request, row)


@router.patch("/settings")
async def update_settings(
    request: Request,
    body: GymSettingsUpdate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> GymSettings:
    changes = body.model_dump(mode="json", exclude_unset=True)
    columns: dict[str, Any] = {
        c: changes.pop(c) for c in ("name", "timezone", "theme") if c in changes
    }
    if changes.get("privacy") is not None:
        timezone = columns.get("timezone") or await session.scalar(
            text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
        )
        changes["privacy"]["updated_on"] = gym_today(timezone).isoformat()
    # A cleared key is removed rather than stored as JSON null, so it reads as unset.
    removed = [k for k in SETTINGS_KEYS if k in changes and changes[k] is None]
    patch = {k: v for k, v in changes.items() if v is not None}
    assignments = "".join(f"{c} = :{c}, " for c in columns)
    row = (
        await session.execute(
            text(
                f"UPDATE gym SET {assignments}"
                "settings = (settings - CAST(:removed AS text[])) || CAST(:patch AS jsonb)"
                f" WHERE id = :id RETURNING {COLUMNS}"
            ),
            {**columns, "removed": removed, "patch": json.dumps(patch), "id": tenant.gym_id},
        )
    ).one()
    if "theme" in columns:
        # The pages shown before sign-in wear it at once, not when the kept copy expires.
        request.app.state.gym_lookup.forget(row.slug)
    return _settings(request, row)


async def _body(request: Request, content_length: int | None) -> bytes:
    """The request's body, refused once it passes `MAX_LOGO_BYTES`."""
    if content_length is not None and content_length > MAX_LOGO_BYTES:
        raise TOO_LARGE
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_LOGO_BYTES:
            raise TOO_LARGE
    return bytes(data)


async def _delete_logo(store: BlobStore, gym_id: uuid.UUID, version: str) -> None:
    """The files of a logo no longer shown. One left behind is only space: log it."""
    try:
        for variant in VARIANTS:
            await store.delete(key(gym_id, version, variant))
    except Exception:
        logger.exception("old logo not deleted", extra={"gym_id": str(gym_id)})


async def _set_logo(
    request: Request,
    session: AdminSession,
    tenant: Tenant,
    background: BackgroundTasks,
    store: BlobStore,
    version: str | None,
) -> GymSettings:
    previous = await session.scalar(
        text("SELECT logo_version FROM gym WHERE id = :id FOR UPDATE"), {"id": tenant.gym_id}
    )
    row = (
        await session.execute(
            text(f"UPDATE gym SET logo_version = :v WHERE id = :id RETURNING {COLUMNS}"),
            {"v": version, "id": tenant.gym_id},
        )
    ).one()
    if previous is not None and previous != version:
        # After the answer, once the change is saved: until then the old files are
        # the ones the gym's pages name.
        background.add_task(_delete_logo, store, tenant.gym_id, previous)
    # The pages shown before sign-in show it at once, not when the kept copy expires.
    request.app.state.gym_lookup.forget(row.slug)
    return _settings(request, row)


@router.put("/logo")
async def upload_logo(
    request: Request,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
    background: BackgroundTasks,
    content_type: Annotated[str | None, Header()] = None,
    content_length: Annotated[int | None, Header()] = None,
    x: Annotated[int | None, Query(ge=0)] = None,
    y: Annotated[int | None, Query(ge=0)] = None,
    size: Annotated[int | None, Query(ge=1)] = None,
) -> GymSettings:
    """The picture as the owner picked it, cut to the square they drew: all three of
    `x`, `y` and `size`, or none for the middle square."""
    # SVG above all: a document that can carry script, never an image here.
    if (content_type or "").split(";")[0].strip().lower() not in CONTENT_TYPES:
        raise HTTPException(http.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "logo_type")
    crop = None
    if (x, y, size) != (None, None, None):
        if x is None or y is None or size is None:
            raise HTTPException(http.HTTP_422_UNPROCESSABLE_CONTENT, "logo_crop")
        crop = Crop(x, y, size)
    data = await _body(request, content_length)
    try:
        # Decoding and resizing are CPU work: off the event loop.
        variants = await asyncio.to_thread(make_variants, data, crop)
    except LogoRefused as exc:
        if exc.code == "logo_too_large":
            raise TOO_LARGE from None
        raise HTTPException(http.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from None
    store = integrations.blob_store
    version = new_version()
    for variant, content in variants.items():
        await store.put(
            key(tenant.gym_id, version, variant), VARIANTS[variant].content_type, content
        )
    try:
        return await _set_logo(request, session, tenant, background, store, version)
    except Exception:
        await _delete_logo(store, tenant.gym_id, version)
        raise


@router.delete("/logo")
async def remove_logo(
    request: Request,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
    background: BackgroundTasks,
) -> GymSettings:
    """'Quitar logo': the gym shows its initials again."""
    return await _set_logo(request, session, tenant, background, integrations.blob_store, None)
