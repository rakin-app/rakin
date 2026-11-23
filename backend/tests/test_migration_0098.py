"""Migration 0098: a member reads their own history payments, and their dependents'
(#371).

What they read is `test_my_data`; here, that the policy is a read for `rakin_app`
alone, and a downgrade drops it.
"""

from collections.abc import Iterator

import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

POLICY = (
    "SELECT cmd, roles::text FROM pg_policies"
    " WHERE tablename = 'history_payment' AND policyname = 'history_payment_own'"
)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0098")
        yield database


def test_history_payment_own_is_a_read_and_goes_on_downgrade(db: Database) -> None:
    [policy] = run(db.admin_url, lambda c: c.fetch(POLICY))
    assert (policy["cmd"], policy["roles"]) == ("SELECT", "{rakin_app}")

    command.downgrade(db.alembic(), "0097")
    assert run(db.admin_url, lambda c: c.fetch(POLICY)) == []
