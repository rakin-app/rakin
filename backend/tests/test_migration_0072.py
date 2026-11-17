"""Migration 0072: a plan's enrolment fee and the matrícula cobros it charges (#355).

A downgrade keeps every matrícula, with its line, as a cobro of category `otro`, and
drops the fee and the column that tied it to its membership; an upgrade after it puts
them back.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres

SCHEMA = (
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
    " WHERE conrelid IN ('plan'::regclass, 'extra_charge'::regclass) ORDER BY 1"
)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0071")
        yield database


def fetch(db: Database, sql: str) -> list[tuple[Any, ...]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
        async with conn.transaction():
            await conn.execute("SET LOCAL row_security = off")
            return [tuple(r) for r in await conn.fetch(sql)]

    result: list[tuple[Any, ...]] = run(db.admin_url, query)
    return result


def test_a_downgrade_keeps_each_matricula_as_otro_and_an_upgrade_restores_the_rest(
    db: Database,
) -> None:
    before = fetch(db, SCHEMA)
    migrate(db)
    after = fetch(db, SCHEMA)
    gym = seed_gym(db, f"matricula-{uuid.uuid4().hex[:6]}")
    [(membership, person)] = run(db.owner_url, in_gym(gym, "SELECT id, person_id FROM membership"))
    run(
        db.owner_url,
        in_gym(
            gym,
            "WITH x AS (INSERT INTO extra_charge (gym_id, title, category, due_date,"
            " amount_mode, amount_clp, target_kind, membership_id)"
            " VALUES (current_setting('app.gym_id')::uuid, 'Matrícula', 'matricula',"
            " current_date, 'fixed', 30000, 'people', $1) RETURNING id)"
            " INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp)"
            " SELECT current_setting('app.gym_id')::uuid, x.id, $2, 30000 FROM x",
            membership,
            person,
        ),
    )

    command.downgrade(db.alembic(), "0071")

    assert fetch(db, SCHEMA) == before
    assert fetch(
        db,
        "SELECT x.category, l.amount_due_clp FROM extra_charge x"
        " JOIN extra_line l ON l.extra_charge_id = x.id WHERE x.title = 'Matrícula'",
    ) == [("otro", 30000)]
    migrate(db)
    assert fetch(db, SCHEMA) == after
