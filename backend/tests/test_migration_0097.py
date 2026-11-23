"""Migration 0097: `platform_gym` says whether the gym is exempt from the terms (#559).

The panel's detail reads it (`test_platform_edit`); here, that the function gains the
column, stays the platform role's, and a downgrade puts 0094's back.
"""

from collections.abc import Iterator

import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

COLUMNS = (
    "SELECT array_agg(a ORDER BY n) FROM pg_proc p,"
    " unnest(p.proargnames, p.proargmodes) WITH ORDINALITY AS x(a, m, n)"
    " WHERE p.proname = 'platform_gym' AND m = 't'"
)
OWNER = "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'platform_gym'"


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0097")
        yield database


def test_platform_gym_gains_terms_exempt_and_loses_it_on_downgrade(db: Database) -> None:
    columns = run(db.admin_url, lambda c: c.fetchval(COLUMNS))
    assert columns[-1] == "terms_exempt"
    assert run(db.admin_url, lambda c: c.fetchval(OWNER)) == "rakin_platform"

    command.downgrade(db.alembic(), "0096")
    columns = run(db.admin_url, lambda c: c.fetchval(COLUMNS))
    assert "terms_exempt" not in columns
    assert columns[-1] == "early_deletion_on"
    assert run(db.admin_url, lambda c: c.fetchval(OWNER)) == "rakin_platform"
