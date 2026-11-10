"""A gym's privacy notice (#168), public: `GET /api/privacy`.

The notice is a template the SPA keeps (`/privacidad`), filled in with what the gym
set in Ajustes (`app.schemas.gym.Privacy`): this answers those details and the gym's
name. It is meant to be read by anyone, before they sign in or join, so it needs no
session, and it says nothing a published notice does not.

Which gym's: the one the host names (`meta.rakin.app`), else the one the session is
in, else the one whose join link `link` is, for the join form on the base host. A gym
that has not filled in its details, or none at all, is a 404 `no_privacy_notice`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import text

from app.api.unsubscribe import in_gym
from app.hosts import host_gym
from app.schemas.gym import StoredPrivacy
from app.schemas.privacy import PrivacyNotice
from app.tenancy import Tenant

router = APIRouter(prefix="/api/privacy", tags=["privacy"])

NO_NOTICE = HTTPException(status.HTTP_404_NOT_FOUND, "no_privacy_notice")


async def _gym_of(request: Request, link: str | None) -> uuid.UUID | None:
    gym = host_gym(request.state)
    if gym is not None:
        return gym.id
    tenant = getattr(request.state, "tenant", None)
    if isinstance(tenant, Tenant):
        return tenant.gym_id
    if link:
        async with request.app.state.sessionmaker() as lookup:
            found: uuid.UUID | None = await lookup.scalar(
                text("SELECT join_link_gym(:token)"), {"token": link}
            )
            return found
    return None


def stored_privacy(settings: Any) -> StoredPrivacy | None:
    """The privacy details in a `gym.settings` document, or None while unset."""
    found = settings.get("privacy")
    return None if found is None else StoredPrivacy.model_validate(found)


@router.get("")
async def privacy_notice(
    request: Request, link: Annotated[str | None, Query(max_length=64)] = None
) -> PrivacyNotice:
    gym_id = await _gym_of(request, link)
    if gym_id is None:
        raise NO_NOTICE
    async with in_gym(request, gym_id) as session:
        row = (
            await session.execute(
                text("SELECT name, settings FROM gym WHERE id = :id"), {"id": gym_id}
            )
        ).one_or_none()
    privacy = None if row is None else stored_privacy(row.settings)
    if row is None or privacy is None:
        raise NO_NOTICE
    return PrivacyNotice(gym=row.name, **privacy.model_dump())
