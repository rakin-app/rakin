"""Migration 0084: every gym has its expense categories, a suspended one included (#525).

A gym suspended when 0083 ran, or resumed and not yet caught up on by the jobs, got no
categories from it; 0084 gives it its twelve. A gym that has them keeps them as they
are. `migration_gym_ids()` lists every gym, for the owner alone. A downgrade drops it.
"""

from collections.abc import Iterator
from uuid import UUID

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres

DEFAULTS = [
    "Arriendo",
    "Luz",
    "Agua",
    "Gas",
    "Internet y teléfono",
    "Federación",
    "Seguros",
    "Sueldos y honorarios",
    "Equipamiento",
    "Eventos y competencias",
    "Mantención y aseo",
    "Otros",
]


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0082")
        yield database


def categories(db: Database, gym: UUID) -> list[str]:
    rows = run(db.owner_url, in_gym(gym, "SELECT name FROM expense_category ORDER BY sort"))
    return [r["name"] for r in rows]


def test_a_gym_suspended_at_0083_gets_its_categories(db: Database) -> None:
    active = seed_gym(db, unique_slug("norte"))
    suspended = seed_gym(db, unique_slug("sur"))
    owed = seed_gym(db, unique_slug("este"))
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym SET suspended_at = now(), suspended_reason = 'impago' WHERE id = $1",
            suspended,
        ),
    )
    # Resumed, and the jobs not caught up on it yet.
    run(
        db.admin_url,
        lambda c: c.execute("UPDATE gym SET jobs_owed_since = now() WHERE id = $1", owed),
    )

    migrate(db, "0083")
    assert categories(db, active) == DEFAULTS
    assert categories(db, suspended) == []
    assert categories(db, owed) == []

    # A gym that has its categories keeps them as it changed them.
    run(
        db.owner_url,
        in_gym(active, "UPDATE expense_category SET name = 'Renta' WHERE name = 'Arriendo'"),
    )

    migrate(db, "0084")
    assert categories(db, suspended) == DEFAULTS
    assert categories(db, owed) == DEFAULTS
    assert categories(db, active) == ["Renta", *DEFAULTS[1:]]


def test_only_the_owner_lists_every_gym(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    run(db.admin_url, lambda c: c.execute("UPDATE gym SET suspended_at = now() WHERE id = $1", gym))
    migrate(db, "0084")

    ids = {r[0] for r in run(db.owner_url, lambda c: c.fetch("SELECT migration_gym_ids()"))}
    assert gym in ids
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, lambda c: c.fetch("SELECT migration_gym_ids()"))


def test_a_downgrade_drops_the_lookup_and_keeps_the_categories(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    run(db.admin_url, lambda c: c.execute("UPDATE gym SET suspended_at = now() WHERE id = $1", gym))
    migrate(db, "0084")

    command.downgrade(db.alembic(), "0083")
    lookup = run(db.admin_url, lambda c: c.fetchval("SELECT to_regproc('migration_gym_ids')"))
    assert lookup is None
    assert categories(db, gym) == DEFAULTS

    # And up again.
    migrate(db)
    assert categories(db, gym) == DEFAULTS
