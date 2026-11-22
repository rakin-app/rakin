"""Migration 0086: `expense.extra_charge_id`, the cobro extra that recovers it (#318).

The key carries the gym, so an expense names only a cobro of its own gym, even to the
owner role, which RLS holds to one gym but a foreign key does not. A downgrade drops the
column and leaves the expenses.
"""

import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def a_cobro(db: Database, gym: uuid.UUID) -> uuid.UUID:
    return run(  # type: ignore[no-any-return]
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode,"
            " amount_clp, target_kind) VALUES (current_setting('app.gym_id')::uuid, 'Viaje',"
            " 'gasto_compartido', now()::date, 'fixed', 1000, 'people') RETURNING id",
        ),
    )[0]["id"]


def an_expense(db: Database, gym: uuid.UUID, charge: uuid.UUID) -> None:
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO expense (gym_id, spent_on, amount_clp, category_id, extra_charge_id,"
            " created_by) SELECT current_setting('app.gym_id')::uuid, now()::date, 500, c.id,"
            " $1, $2 FROM expense_category c WHERE c.is_other",
            charge,
            seeded_owner(gym),
        ),
    )


def test_an_expense_names_only_a_cobro_of_its_gym(db: Database) -> None:
    gym = seed_gym(db, unique_slug("sur"))
    other = seed_gym(db, unique_slug("norte"))
    an_expense(db, gym, a_cobro(db, gym))
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        an_expense(db, gym, a_cobro(db, other))


def test_a_downgrade_drops_the_column_and_keeps_the_expenses(db: Database) -> None:
    gym = seed_gym(db, unique_slug("sur"))
    an_expense(db, gym, a_cobro(db, gym))

    command.downgrade(db.alembic(), "0085")
    column = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'expense' AND column_name = 'extra_charge_id'"
        ),
    )
    assert column == 0
    count = "SELECT count(*) AS n FROM expense"
    assert run(db.owner_url, in_gym(gym, count))[0]["n"] == 1

    migrate(db)
    assert run(db.owner_url, in_gym(gym, count))[0]["n"] == 1
