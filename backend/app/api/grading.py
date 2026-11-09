"""The current gym's grading scheme: read it, replace it, start from a preset.

Any staff role may read the scheme and the presets (`StaffSession`), since coaches
award promotions against it; only an owner or admin may change it (`AdminSession`).
A preset is applied by sending its scheme, edited or not, to `PUT`.

A stored scheme that no longer fits the model, as one written before a change to it
would, reads as a 409 `grading_scheme_invalid` rather than a 500: the admin re-applies
a preset, and the `PUT` that does so replaces it.
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import text

from app.roles import AdminSession, StaffSession
from app.schemas.grading import PRESETS, GradingScheme, Preset
from app.tenancy import Tenant, current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gym/grading-scheme", tags=["grading"])


@router.get("")
async def get_scheme(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: StaffSession
) -> GradingScheme:
    settings = await session.scalar(
        text("SELECT settings FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    try:
        return GradingScheme.from_settings(settings)
    except ValidationError as error:
        logger.warning(
            "grading scheme stored for gym %s is invalid: %s",
            tenant.gym_id,
            error.errors(include_input=False, include_url=False),
        )
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "grading_scheme_invalid"}) from None


@router.put("")
async def replace_scheme(
    body: GradingScheme,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> GradingScheme:
    settings = await session.scalar(
        text(
            "UPDATE gym SET settings = settings"
            " || jsonb_build_object('grading', CAST(:scheme AS jsonb))"
            " WHERE id = :id RETURNING settings"
        ),
        {"scheme": json.dumps(body.model_dump(mode="json")), "id": tenant.gym_id},
    )
    return GradingScheme.from_settings(settings)


@router.get("/presets")
async def list_presets(session: StaffSession) -> list[Preset]:
    return PRESETS
