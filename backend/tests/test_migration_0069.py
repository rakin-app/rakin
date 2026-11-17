"""Migration 0069: the members' writes ask `members_manage` (#310).

A downgrade puts the group policies and `audit_event_correct` back as 0067 left them
(0068 changed neither), and an upgrade after it rewrites them again. What each policy
lets through, permission by permission, is `tests/test_permissions_rls.py`'s.
"""

from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

POLICIES = (
    "SELECT tablename, policyname, cmd, qual, with_check FROM pg_policies"
    " WHERE tablename IN ('charge_group', 'charge_group_member', 'audit_event')"
    " ORDER BY tablename, policyname"
)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0068")
        yield database


def policies(db: Database) -> list[tuple[Any, ...]]:
    async def query(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
        return [tuple(r) for r in await conn.fetch(POLICIES)]

    result: list[tuple[Any, ...]] = run(db.admin_url, query)
    return result


def test_a_downgrade_puts_back_each_policy_and_an_upgrade_rewrites_it(db: Database) -> None:
    before = policies(db)
    migrate(db)
    after = policies(db)
    # The writes 0067 gave the group tables; their gym isolation (0037) stays.
    groups = [p for p in after if p[1].endswith(("_insert", "_update", "_delete"))]
    assert groups and all("members_manage" in f"{p[3]} {p[4]}" for p in groups)
    assert all("money_write" not in f"{p[3]} {p[4]}" for p in groups)
    correct = next(p for p in after if p[1] == "audit_event_correct")
    assert "members_manage" in correct[4] and "money_write" in correct[4]

    command.downgrade(db.alembic(), "0068")
    assert policies(db) == before
    migrate(db)
    assert policies(db) == after
