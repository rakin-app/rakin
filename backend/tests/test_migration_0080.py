"""Migration 0080: a session lasts while it is used (#491).

A session already started keeps its `expires_at`, and is found as before, now with its
sign-in. A downgrade puts 0079's `auth_live_session` back and drops
`auth_renew_session`.
"""

import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from alembic import command
from app.magiclink.tokens import hash_token
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0079")
        yield database


def columns(db: Database, function: str) -> list[str]:
    """The names of the columns `function` returns."""

    async def query(conn: asyncpg.Connection) -> list[str]:
        names = await conn.fetchval("SELECT proargnames FROM pg_proc WHERE proname = $1", function)
        modes = await conn.fetchval("SELECT proargmodes FROM pg_proc WHERE proname = $1", function)
        return [n for n, m in zip(names, modes, strict=True) if m in ("t", b"t")]

    return list(run(db.admin_url, query))


def start_session(db: Database) -> bytes:
    """A session in no gym, started a day ago under the 30-day rule."""
    token_hash = hash_token(uuid.uuid4().hex)

    async def query(conn: asyncpg.Connection) -> None:
        person = await conn.fetchval("INSERT INTO person (name) VALUES ('Ana') RETURNING id")
        await conn.execute(
            "INSERT INTO auth_session (token_hash, person_id, email, expires_at, created_at)"
            " VALUES ($1, $2, 'a@example.cl', now() + interval '29 days',"
            " now() - interval '1 day')",
            token_hash,
            person,
        )

    run(db.admin_url, query)
    return token_hash


def test_a_session_already_started_keeps_its_expiry(db: Database) -> None:
    token_hash = start_session(db)
    migrate(db)

    row = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT expires_at - created_at AS lasts FROM auth_live_session($1, now())",
            token_hash,
        ),
    )
    assert row["lasts"].days == 30


def test_a_downgrade_puts_everything_back(db: Database) -> None:
    token_hash = start_session(db)
    before = columns(db, "auth_live_session")
    migrate(db)
    assert columns(db, "auth_live_session") == [*before, "created_at"]

    command.downgrade(db.alembic(), "0079")

    assert columns(db, "auth_live_session") == before
    renew = "SELECT to_regproc('auth_renew_session')"
    assert run(db.admin_url, lambda c: c.fetchval(renew)) is None
    live = "SELECT person_id FROM auth_live_session($1, now())"
    assert run(db.admin_url, lambda c: c.fetchval(live, token_hash)) is not None
