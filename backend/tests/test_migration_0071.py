"""Migration 0071: Equipo's same-day terms, first-run choice and team log (#311).

The gyms already here have chosen how their team is organised; a downgrade drops the
team's log rows and every term that ends on its first day, puts each policy and
constraint back as 0070 left them, and an upgrade after it rewrites them again.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import (
    Database,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)

pytestmark = pytest.mark.postgres

SCHEMA = (
    "SELECT 'policy', policyname, qual || '|' || coalesce(with_check, '') FROM pg_policies"
    " WHERE tablename = 'audit_event'"
    " UNION ALL SELECT 'constraint', conname, pg_get_constraintdef(oid) FROM pg_constraint"
    " WHERE conrelid IN ('audit_event'::regclass, 'staff_title'::regclass)"
    " ORDER BY 1, 2"
)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0070")
        yield database


def fetch(db: Database, sql: str, *args: object) -> list[tuple[Any, ...]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
        async with conn.transaction():
            # FORCEd RLS holds even the superuser's session here to one gym, or none.
            await conn.execute("SET LOCAL row_security = off")
            return [tuple(r) for r in await conn.fetch(sql, *args)]

    result: list[tuple[Any, ...]] = run(db.admin_url, query)
    return result


def test_a_gym_already_here_has_chosen_and_a_new_one_has_not(db: Database) -> None:
    before = seed_gym(db, f"antes-{uuid.uuid4().hex[:6]}")
    migrate(db)
    after = seed_gym(db, f"despues-{uuid.uuid4().hex[:6]}")

    chosen = dict(fetch(db, "SELECT id, roles_chosen_at IS NOT NULL FROM gym"))
    assert (chosen[before], chosen[after]) == (True, False)


def test_a_downgrade_drops_what_0069_could_not_hold_and_an_upgrade_restores_the_rest(
    db: Database,
) -> None:
    before = fetch(db, SCHEMA)
    migrate(db)
    after = fetch(db, SCHEMA)
    gym = seed_gym(db, f"equipo-{uuid.uuid4().hex[:6]}")
    coach, today = uuid.uuid4(), seeded_today()

    async def write(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", coach)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym,
                coach,
            )
            await make_staff(conn, gym, coach, "coach", starts_on=today, ends_on=today)
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
                " VALUES ($1, $2, 'title_created', '{}')",
                gym,
                seeded_owner(gym),
            )

    run(db.owner_url, write)

    command.downgrade(db.alembic(), "0070")

    assert fetch(db, SCHEMA) == before
    assert fetch(db, "SELECT 1 FROM staff_title WHERE person_id = $1", coach) == []
    assert fetch(db, "SELECT 1 FROM audit_event WHERE action = 'title_created'") == []
    migrate(db)
    assert fetch(db, SCHEMA) == after
