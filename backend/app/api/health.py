import asyncio
import logging

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.health import HealthStatus

router = APIRouter()
logger = logging.getLogger(__name__)


async def check_database(engine: AsyncEngine, limit_seconds: float) -> bool:
    try:
        async with asyncio.timeout(limit_seconds):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("healthz: database check failed", exc_info=True)
        return False
    return True


@router.get("/healthz", response_model=HealthStatus)
async def healthz(request: Request, response: Response) -> HealthStatus:
    settings = request.app.state.settings
    db_ok = await check_database(request.app.state.engine, settings.healthz_db_timeout_seconds)
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="error", database="error")
    return HealthStatus(status="ok", database="ok")
