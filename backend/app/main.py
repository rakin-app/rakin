from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    activities,
    attendance,
    blobs,
    block_kinds,
    check_in,
    class_tags,
    class_types,
    consent,
    corrections,
    custom_fields,
    due_dates,
    expense_recurring,
    expenses,
    extra_charges,
    finances,
    freeze_requests,
    grades,
    grading,
    groups,
    guardians,
    gym,
    health,
    history,
    hosts,
    import_undo,
    inactive,
    join,
    ledger,
    ledger_export,
    logos,
    me,
    member_import,
    member_roll,
    memberships,
    moves,
    paid_through,
    people,
    plans,
    platform,
    privacy,
    programs,
    proof_review,
    proofs,
    reminders,
    requirements,
    reverts,
    schedule,
    session_blocks,
    sessions,
    staff,
    study_material,
    summary,
    terms,
    titles,
    unsubscribe,
    webhooks,
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
from app.idempotency import IdempotencyMiddleware
from app.integrations import build_integrations
from app.logging import configure_logging
from app.magiclink import SessionMiddleware, build_router, is_secure, session_cookie_name
from app.middleware import RequestIdMiddleware
from app.platform.web import build_operator_links, build_platform_router
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
    # The platform's operators sign in apart from every gym (#436).
    app.state.platform_links = build_operator_links(
        settings, app.state.integrations.mailer, lambda: app.state.sessionmaker
    )
    app.state.join_limits = join.build_join_limits()
    app.state.hosts = Hosts.of(settings)
    # Inside SessionMiddleware, so a key is scoped to the tenant it sets.
    app.add_middleware(IdempotencyMiddleware, sessionmaker=lambda: app.state.sessionmaker)
    # Added before the next two, so it runs inside RequestIdMiddleware and its queries log the id;
    # and inside HostMiddleware, so a session is bound knowing the host's gym.
    app.add_middleware(
        SessionMiddleware,
        links=links,
        bind=bind_session,
        cookie_name=session_cookie_name(settings.public_base_url),
        secure=is_secure(settings.public_base_url),
    )
    # Kept on the state too, so a change to what it keeps (the theme) can drop the entry.
    app.state.gym_lookup = GymLookup(lambda: app.state.sessionmaker)
    app.add_middleware(
        HostMiddleware,
        hosts=app.state.hosts,
        lookup=app.state.gym_lookup,
        alias=app.state.gym_lookup.alias,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(hosts.router)
    app.include_router(people.router)
    app.include_router(member_roll.router)
    app.include_router(history.router)
    app.include_router(custom_fields.router)
    app.include_router(requirements.router)
    app.include_router(guardians.router)
    app.include_router(consent.router)
    app.include_router(consent.mine)
    app.include_router(me.router)
    app.include_router(proofs.router)
    app.include_router(plans.router)
    app.include_router(programs.router)
    app.include_router(class_types.router)
    app.include_router(class_tags.router)
    app.include_router(activities.router)
    app.include_router(sessions.router)
    app.include_router(schedule.router)
    app.include_router(schedule.closed)
    app.include_router(attendance.router)
    app.include_router(check_in.router)
    app.include_router(block_kinds.router)
    app.include_router(session_blocks.router)
    app.include_router(study_material.router)
    app.include_router(study_material.mine)
    app.include_router(memberships.router)
    app.include_router(freeze_requests.mine)
    app.include_router(freeze_requests.router)
    app.include_router(member_import.router)
    app.include_router(import_undo.router)
    app.include_router(gym.router)
    app.include_router(staff.router)
    app.include_router(titles.router)
    app.include_router(grading.router)
    app.include_router(grades.router)
    app.include_router(ledger.router)
    app.include_router(corrections.router)
    app.include_router(moves.router)
    app.include_router(due_dates.router)
    app.include_router(reverts.router)
    app.include_router(paid_through.router)
    app.include_router(ledger_export.router)
    app.include_router(inactive.router)
    app.include_router(summary.router)
    app.include_router(reminders.router)
    app.include_router(proof_review.router)
    app.include_router(extra_charges.router)
    app.include_router(extra_charges.people_router)
    app.include_router(groups.router)
    app.include_router(expense_recurring.router)
    app.include_router(expenses.router)
    app.include_router(finances.router)
    app.include_router(unsubscribe.router)
    app.include_router(webhooks.router)
    app.include_router(join.public)
    app.include_router(join.router)
    app.include_router(privacy.router)
    app.include_router(terms.router)
    app.include_router(logos.router)
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
    app.include_router(platform.router)
    app.include_router(build_platform_router(app.state.platform_links, settings))
    if settings.blob_store == "local":
        app.include_router(blobs.router)
    return app
