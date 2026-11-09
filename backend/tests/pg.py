"""Throwaway Postgres databases for the tests that need real roles and RLS.

Each one is created on the `TEST_DATABASE_URL` server (which must be a superuser) and
bootstrapped with `app.db_bootstrap`, so the database that URL names is never
migrated or written to. Roles are cluster-wide: every throwaway database shares the
default owner and API users, which bootstrap re-creates idempotently.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.db_bootstrap import bootstrap, to_dsn
from app.settings import Settings
from tests.conftest import make_settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

Query = Callable[[asyncpg.Connection], Awaitable[Any]]


@dataclass(frozen=True)
class Database:
    admin_url: str  # the superuser from TEST_DATABASE_URL
    settings: Settings  # the owner and API users, pointed at this database

    @property
    def owner_url(self) -> str:
        return self.settings.migration_database_url

    @property
    def api_url(self) -> str:
        return self.settings.database_url

    def alembic(self) -> Config:
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", self.owner_url.replace("%", "%%"))
        config.attributes["configure_logging"] = False
        return config


def with_database(url: str, name: str) -> str:
    return make_url(url).set(database=name).render_as_string(hide_password=False)


def as_user_of(url: str, server_url: str, name: str) -> str:
    """`url`'s user and password, on `server_url`'s host, in database `name`."""
    user = make_url(url)
    server = make_url(server_url)
    return server.set(
        username=user.username, password=user.password, database=name
    ).render_as_string(hide_password=False)


def run(url: str, query: Query) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(url))
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


@contextmanager
def throwaway_database(server_url: str) -> Iterator[Database]:
    name = f"rakin_test_{uuid.uuid4().hex[:12]}"
    run(server_url, lambda c: c.execute(f'CREATE DATABASE "{name}"'))
    try:
        # The users from the settings' defaults, never from the environment.
        api, owner = (
            Settings.model_fields[f].default for f in ("database_url", "migration_database_url")
        )
        database = Database(
            admin_url=with_database(server_url, name),
            settings=make_settings(
                database_url=as_user_of(api, server_url, name),
                migration_database_url=as_user_of(owner, server_url, name),
            ),
        )
        asyncio.run(bootstrap(database.admin_url, database.settings))
        yield database
    finally:
        run(server_url, lambda c: c.execute(f'DROP DATABASE "{name}" WITH (FORCE)'))


def migrate(database: Database, revision: str = "head") -> None:
    command.upgrade(database.alembic(), revision)


def in_gym(
    gym_id: uuid.UUID | None, sql: str, *args: object, person: uuid.UUID | None = None
) -> Query:
    """Run `sql` in a transaction, with `app.gym_id` set to `gym_id` and `app.person_id`
    to `person`, each if given."""

    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            if gym_id is not None:
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
            if person is not None:
                await conn.execute("SELECT set_config('app.person_id', $1, true)", str(person))
            return await conn.fetch(sql, *args)

    return query


def seeded_owner(gym_id: uuid.UUID) -> uuid.UUID:
    """The owner `seed_gym` gives `gym_id`: derived from it, so callers need only the gym."""
    return uuid.uuid5(gym_id, "owner")


def seed_gym(db: Database, slug: str) -> uuid.UUID:
    """A gym with one person, its owner (`seeded_owner`: a staff and a `gym_person`
    row), and a plan, membership, period and ledger entry.

    Seeded as the owner, which FORCEd RLS applies to: it sets `app.gym_id` first.
    """
    gym_id = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
            await conn.execute("INSERT INTO gym (id, name, slug) VALUES ($1, $2, $2)", gym_id, slug)
            # Not `RETURNING id`: until its gym_person row exists the person is not
            # visible in this gym, and RETURNING is held to the read policy (0003).
            person_id = seeded_owner(gym_id)
            await conn.execute(
                "INSERT INTO person (id, name) VALUES ($1, $2)", person_id, f"owner of {slug}"
            )
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, $3)",
                gym_id,
                person_id,
                f"owner of {slug}",
            )
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'owner')",
                gym_id,
                person_id,
            )
            plan_id = await conn.fetchval(
                "INSERT INTO plan (gym_id, name, kind, price_clp)"
                " VALUES ($1, 'Mensual', 'monthly', 45000) RETURNING id",
                gym_id,
            )
            membership_id = await conn.fetchval(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " VALUES ($1, $2, $3, 'active') RETURNING id",
                gym_id,
                person_id,
                plan_id,
            )
            period_id = await conn.fetchval(
                "INSERT INTO billing_period"
                " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
                " VALUES ($1, $2, '2026-11-01', '2026-11-30', 45000, '2026-11-01') RETURNING id",
                gym_id,
                membership_id,
            )
            await conn.execute(
                "INSERT INTO ledger_entry"
                " (gym_id, membership_id, billing_period_id, amount_clp, kind)"
                " VALUES ($1, $2, $3, 45000, 'charge')",
                gym_id,
                membership_id,
                period_id,
            )

    run(db.owner_url, query)
    return gym_id
