from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import blobs, guardians, gym, health, ledger, me, people, plans
from app.auth import PREFIX, TEXTS, bind_session, build_magic_links
from app.db import create_engine, create_sessionmaker
from app.integrations import build_integrations
from app.logging import configure_logging
from app.magiclink import SessionMiddleware, build_router
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
    links = build_magic_links(
        settings, app.state.integrations.mailer, lambda: app.state.sessionmaker
    )
    app.state.magic_links = links
    # Added first, so it runs inside RequestIdMiddleware and its queries log the id.
    app.add_middleware(SessionMiddleware, links=links, bind=bind_session)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(people.router)
    app.include_router(guardians.router)
    app.include_router(me.router)
    app.include_router(plans.router)
    app.include_router(gym.router)
    app.include_router(ledger.router)
    app.include_router(
        build_router(links, prefix=PREFIX, base_url=settings.public_base_url, texts=TEXTS)
    )
    if settings.blob_store == "local":
        app.include_router(blobs.router)
    return app
