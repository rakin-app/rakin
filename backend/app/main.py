from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import blobs, health, people
from app.db import create_engine, create_sessionmaker
from app.integrations import build_integrations
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Rakin API", lifespan=lifespan)
    app.state.settings = settings
    app.state.integrations = build_integrations(settings)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(people.router)
    if settings.blob_store == "local":
        app.include_router(blobs.router)
    return app
