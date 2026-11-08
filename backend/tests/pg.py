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
