from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    attendance,
    blobs,
    block_kinds,
    class_types,
    custom_fields,
    extra_charges,
    grades,
    grading,
    groups,
    guardians,
    gym,
    health,
    hosts,
    inactive,
    join,
    ledger,
    me,
    member_import,
    member_roll,
    memberships,
    people,
    plans,
    privacy,
    programs,
    proof_review,
    proofs,
    reminders,
    schedule,
    session_blocks,
    sessions,
    staff,
    unsubscribe,
)
from app.auth import (
    LANDINGS,
    PREFIX,
    SIGN_IN,
    STYLESHEET,
    TEXTS,
    bind_session,
    build_magic_links,
    site_of,
)
from app.db import create_engine, create_sessionmaker
from app.hosts import GymLookup, HostMiddleware, Hosts
from app.integrations import build_integrations
from app.logging import configure_logging
from app.magiclink import SessionMiddleware, build_router, session_cookie_name
from app.middleware import RequestIdMiddleware
from app.sentry import init_sentry
from app.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # Before the app exists, so Sentry's FastAPI integration hooks into it.
    init_sentry(settings)

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
    app.state.join_limits = join.build_join_limits()
    app.state.hosts = Hosts.of(settings)
    # Added first, so it runs inside RequestIdMiddleware and its queries log the id;
    # and inside HostMiddleware, so a session is bound knowing the host's gym.
    app.add_middleware(
        SessionMiddleware,
        links=links,
        bind=bind_session,
        cookie_name=session_cookie_name(settings.public_base_url),
    )
    # Kept on the state too, so a change to what it keeps (the theme) can drop the entry.
    app.state.gym_lookup = GymLookup(lambda: app.state.sessionmaker)
    app.add_middleware(HostMiddleware, hosts=app.state.hosts, lookup=app.state.gym_lookup)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(hosts.router)
    app.include_router(people.router)
    app.include_router(member_roll.router)
    app.include_router(custom_fields.router)
    app.include_router(guardians.router)
    app.include_router(me.router)
    app.include_router(proofs.router)
    app.include_router(plans.router)
    app.include_router(programs.router)
    app.include_router(class_types.router)
    app.include_router(sessions.router)
    app.include_router(schedule.router)
    app.include_router(schedule.closed)
    app.include_router(attendance.router)
    app.include_router(block_kinds.router)
    app.include_router(session_blocks.router)
    app.include_router(memberships.router)
    app.include_router(member_import.router)
    app.include_router(gym.router)
    app.include_router(staff.router)
    app.include_router(grading.router)
    app.include_router(grades.router)
    app.include_router(ledger.router)
    app.include_router(inactive.router)
    app.include_router(reminders.router)
    app.include_router(proof_review.router)
    app.include_router(extra_charges.router)
    app.include_router(extra_charges.people_router)
    app.include_router(groups.router)
    app.include_router(unsubscribe.router)
    app.include_router(join.public)
    app.include_router(join.router)
    app.include_router(privacy.router)
    app.include_router(
        build_router(
            links,
            prefix=PREFIX,
            base_url=settings.public_base_url,
            landings=LANDINGS,
            texts=TEXTS,
            site=site_of(app.state.hosts),
            sign_in=SIGN_IN,
            stylesheet=STYLESHEET,
        )
    )
    if settings.blob_store == "local":
        app.include_router(blobs.router)
    return app
