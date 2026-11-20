"""Migration 0079: a gym can be suspended (#439).

The gyms already here stay active, and every lookup finds them as before. A downgrade
drops the columns and puts 0042's lookups, 0040's `auth_gym_by_slug`, 0011's
`jobs_gym_ids`, 0077's `platform_gyms` and 0078's `platform_gym` back; the log keeps
its `gym_suspended` and `gym_resumed` rows.
"""

from collections.abc import Iterator

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0078")
        yield database


def columns(db: Database, function: str) -> list[str]:
    """The names of the columns `function` returns."""

    async def query(conn: asyncpg.Connection) -> list[str]:
        names = await conn.fetchval("SELECT proargnames FROM pg_proc WHERE proname = $1", function)
        modes = await conn.fetchval("SELECT proargmodes FROM pg_proc WHERE proname = $1", function)
        return [n for n, m in zip(names, modes, strict=True) if m in ("t", b"t")]

    return list(run(db.admin_url, query))


def gym_columns(db: Database) -> set[str]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'gym'"
        ),
    )
    return {r["column_name"] for r in rows}


def test_the_gyms_here_stay_active(db: Database) -> None:
    slug = unique_slug("norte")
    gym = seed_gym(db, slug)
    migrate(db, "0079")

    async def query(conn: asyncpg.Connection) -> asyncpg.Record:
        return await conn.fetchrow(
            "SELECT g.suspended_at, g.suspended_reason, g.jobs_owed_since, s.suspended"
            " FROM gym g, auth_gym_by_slug($1) s WHERE g.id = $2",
            slug,
            gym,
        )

    row = run(db.admin_url, query)
    assert tuple(row) == (None, None, None, False)
    assert gym in {r[0] for r in run(db.owner_url, lambda c: c.fetch("SELECT jobs_gym_ids()"))}
    assert columns(db, "platform_gyms")[-2:] == ["owner_link_failed", "suspended_at"]
    assert columns(db, "platform_gym")[-2:] == ["suspended_at", "suspended_reason"]


def test_a_reason_comes_only_with_a_suspension(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    migrate(db)
    with pytest.raises(asyncpg.CheckViolationError, match="gym_suspended_reason_when"):
        run(
            db.admin_url,
            lambda c: c.execute("UPDATE gym SET suspended_reason = 'x' WHERE id = $1", gym),
        )


def test_a_downgrade_puts_everything_back(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    before = {
        name: columns(db, name) for name in ("auth_gym_by_slug", "platform_gyms", "platform_gym")
    }
    migrate(db)
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO platform_event (action, gym_id, detail)"
            " VALUES ('gym_suspended', $1, '{\"by\": \"cli\"}'),"
            " ('gym_resumed', $1, '{\"by\": \"cli\"}')",
            gym,
        ),
    )
    run(db.admin_url, lambda c: c.execute("UPDATE gym SET suspended_at = now() WHERE id = $1", gym))

    command.downgrade(db.alembic(), "0078")

    assert not {"suspended_at", "suspended_reason", "jobs_owed_since"} & gym_columns(db)
    assert {name: columns(db, name) for name in before} == before
    assert (
        run(db.admin_url, lambda c: c.fetchval("SELECT to_regproc('jobs_resumed_gym_ids')")) is None
    )
    # The gym, suspended before, is every job's again.
    assert gym in {r[0] for r in run(db.owner_url, lambda c: c.fetch("SELECT jobs_gym_ids()"))}
    kept = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM platform_event WHERE gym_id = $1"
            " AND action IN ('gym_suspended', 'gym_resumed')",
            gym,
        ),
    )
    assert kept == 2

    # And up again.
    migrate(db)
    assert {"suspended_at", "suspended_reason", "jobs_owed_since"} <= gym_columns(db)
