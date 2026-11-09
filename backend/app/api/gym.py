"""The current gym's settings: read them, change them.

Owner and admin only (`AdminSession`): the bank details decide where students send
their money, so a coach may neither read nor change them.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.roles import AdminSession
from app.schemas.gym import SETTINGS_KEYS, GymSettings, GymSettingsUpdate
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/gym", tags=["gym"])

COLUMNS = "name, slug, timezone, settings"


def _settings(row: Any) -> GymSettings:
    return GymSettings.from_row(row.name, row.slug, row.timezone, row.settings)


@router.get("/settings")
async def get_settings(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> GymSettings:
    row = (
        await session.execute(
            text(f"SELECT {COLUMNS} FROM gym WHERE id = :id"), {"id": tenant.gym_id}
        )
    ).one()
    return _settings(row)


@router.patch("/settings")
async def update_settings(
    body: GymSettingsUpdate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> GymSettings:
    changes = body.model_dump(mode="json", exclude_unset=True)
    columns: dict[str, Any] = {c: changes.pop(c) for c in ("name", "timezone") if c in changes}
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
    return _settings(row)
