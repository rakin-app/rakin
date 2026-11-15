"""Migration 0049: `voids` becomes `purpose = 'void'`, beside `corrects` (#278).

Every gym's voids move, with nothing else about any entry changing, and a downgrade
puts them back; it refuses once a restore is in the ledger, which 0048 has no place for.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pg = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0048")
        yield database


def adjustment(db: Database, gym: uuid.UUID, amount: int, **columns: Any) -> None:
    names = ", ".join(columns)
    marks = "".join(f", ${i}" for i in range(2, len(columns) + 2))
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            f" kind, status, note{', ' if columns else ''}{names})"
            " SELECT gym_id, membership_id, id, $1, 'adjustment', 'validated', 'cobrado por error'"
            f"{marks} FROM billing_period",
            amount,
            *columns.values(),
        ),
    )


def entries(db: Database) -> dict[uuid.UUID, dict[str, Any]]:
    """Every gym's entries, as the superuser, whom RLS does not hold."""
    rows = run(db.admin_url, lambda c: c.fetch("SELECT * FROM ledger_entry"))
    return {r["id"]: dict(r) for r in rows}


def columns(db: Database) -> set[str]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'ledger_entry'"
        ),
    )
    return {r["column_name"] for r in rows}


@pg
def test_voids_become_purpose_void_and_back(db: Database) -> None:
    voided, other = seed_gym(db, "sur"), seed_gym(db, "norte")
    adjustment(db, voided, 45_000, voids=True)
    adjustment(db, other, 5_000)
    before = entries(db)
    assert sum(e["voids"] for e in before.values()) == 1

    command.upgrade(db.alembic(), "0049")
    assert "voids" not in columns(db)
    after = entries(db)
    assert {i: e["purpose"] for i, e in after.items() if e["purpose"]} == {
        i: "void" for i, e in before.items() if e["voids"]
    }
    assert all(e["corrects"] is None for e in after.values())
    # Nothing else about any entry changed.
    unchanged = {i: {k: v for k, v in e.items() if k != "voids"} for i, e in before.items()}
    assert {
        i: {k: v for k, v in e.items() if k not in ("purpose", "corrects")}
        for i, e in after.items()
    } == unchanged

    command.downgrade(db.alembic(), "0048")
    assert {"purpose", "corrects"}.isdisjoint(columns(db))
    assert entries(db) == before


@pg
def test_a_downgrade_refuses_a_ledger_with_a_restore(db: Database) -> None:
    gym = seed_gym(db, "sur")
    adjustment(db, gym, 45_000, voids=True)
    command.upgrade(db.alembic(), "0049")
    void_id = run(
        db.admin_url, lambda c: c.fetchval("SELECT id FROM ledger_entry WHERE purpose = 'void'")
    )
    adjustment(db, gym, -45_000, purpose="restore", corrects=void_id)
    with pytest.raises(Exception, match="no place for"):
        command.downgrade(db.alembic(), "0048")
