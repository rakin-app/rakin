"""The platform's panel (#436): who is signed in, and every gym Rakin hosts.

Every endpoint takes an `OperatorSession` (`app.platform.session`): a platform operator,
on the base host. What it reads comes through migration 0076's functions, each of which
checks the operator's session itself, so the API's own role never reads across gyms.
"""

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.gyms import PROCESSOR_TERMS_VERSION
from app.hosts import Hosts
from app.platform.session import FRESH, OperatorSession
from app.schemas.platform import OperatorMe, PlatformGym

router = APIRouter(prefix="/api/platform", tags=["platform"])


@router.get("/me")
async def me(operator: OperatorSession) -> OperatorMe:
    return OperatorMe(
        email=operator.email, name=operator.name, fresh_until=operator.fresh_at + FRESH
    )


@router.get("/gyms")
async def gyms(operator: OperatorSession, request: Request) -> list[PlatformGym]:
    hosts: Hosts = request.app.state.hosts
    rows = await operator.db.execute(
        text("SELECT * FROM platform_gyms(:h, :terms)"),
        {"h": operator.session_hash, "terms": PROCESSOR_TERMS_VERSION},
    )
    return [
        PlatformGym.model_validate({**row._mapping, "address": hosts.base_url(row.slug)})
        for row in rows
    ]
