"""Migration 0072: a Cobro extra in instalments (#356).

Every line already here is the one instalment of a cobro paid at once, due when its
cobro is. A downgrade refuses while a cobro is in instalments, and goes through once
none is.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0071")
        yield database


def a_cobro(db: Database, gym: uuid.UUID) -> uuid.UUID:
    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            charge: uuid.UUID = await conn.fetchval(
                "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode,"
                " amount_clp, target_kind) VALUES ($1, 'Rifa', 'rifa', '2027-01-31', 'fixed',"
                " 10000, 'people') RETURNING id",
                gym,
            )
            await conn.execute(
                "INSERT INTO extra_line (gym_id, extra_charge_id, person_id, amount_due_clp)"
                " VALUES ($1, $2, $3, 10000)",
                gym,
                charge,
                seeded_owner(gym),
            )
            return charge

    result: uuid.UUID = run(db.owner_url, query)
    return result


def fetch(db: Database, sql: str) -> list[tuple[Any, ...]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
        return [tuple(r) for r in await conn.fetch(sql)]

    result: list[tuple[Any, ...]] = run(db.admin_url, query)
    return result


def test_every_line_is_one_instalment_due_with_its_cobro(db: Database) -> None:
    charge = a_cobro(db, seed_gym(db, f"sur-{uuid.uuid4().hex[:6]}"))
    migrate(db)
    [(instalments, instalment, due)] = fetch(
        db,
        "SELECT x.instalments, l.instalment, l.due_date = x.due_date FROM extra_line l"
        f" JOIN extra_charge x ON x.id = l.extra_charge_id WHERE x.id = '{charge}'",
    )
    assert (instalments, instalment, due) == (1, 1, True)


def test_a_downgrade_refuses_while_a_cobro_is_in_instalments(db: Database) -> None:
    charge = a_cobro(db, seed_gym(db, f"sur-{uuid.uuid4().hex[:6]}"))
    migrate(db)
    fetch(db, f"UPDATE extra_charge SET instalments = 3 WHERE id = '{charge}' RETURNING id")
    with pytest.raises(Exception, match="in instalments"):
        command.downgrade(db.alembic(), "0071")

    fetch(db, f"UPDATE extra_charge SET instalments = 1 WHERE id = '{charge}' RETURNING id")
    command.downgrade(db.alembic(), "0071")
    assert fetch(db, "SELECT count(*) FROM extra_line") == [(1,)]
