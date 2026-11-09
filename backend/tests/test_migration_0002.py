"""Migration 0002 against real Postgres: ledger entries are append-only for every role.

The API user already lacks `DELETE`, so deletes and immutable-column updates also run
as the owner and the superuser: the triggers have to hold where grants and RLS don't.
"""

import datetime as dt
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    throwaway_database,
)

pytestmark = pytest.mark.postgres

SETTLEMENT_COLUMNS = {"status", "validated_by", "validated_at", "note"}

# A new value for every column a settlement must not touch.
IMMUTABLE: dict[str, object] = {
    "id": uuid.uuid4(),
    "gym_id": uuid.uuid4(),
    "membership_id": uuid.uuid4(),
    "billing_period_id": None,
    "amount_clp": 1,
    "kind": "refund",
    "method": "cash",
    "claimed_by": uuid.uuid4(),
    "claimed_at": dt.datetime(2026, 11, 2, tzinfo=dt.UTC),
    "proof_object_key": "proofs/other.jpg",
    "bank_tx_ref": "TX-OTHER",
    "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
}

APPEND_ONLY = "append-only"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def admin_id(db: Database) -> uuid.UUID:
    person: uuid.UUID = run(
        db.admin_url,
        lambda c: c.fetchval("INSERT INTO person (name) VALUES ('admin') RETURNING id"),
    )
    return person


def url_of(db: Database, user: str) -> str:
    return {"api": db.api_url, "owner": db.owner_url, "superuser": db.admin_url}[user]


def new_entry(db: Database, gym: uuid.UUID, status: str = "pending") -> uuid.UUID:
    """A payment entry on the gym's membership, every column filled, inserted as `status`."""

    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval(
            """
            INSERT INTO ledger_entry
                (gym_id, membership_id, billing_period_id, amount_clp, kind, status, method,
                 claimed_by, claimed_at, proof_object_key, bank_tx_ref)
            SELECT gym_id, membership_id, billing_period_id, 45000, 'payment', $2, 'transfer',
                   (SELECT person_id FROM staff WHERE gym_id = $1), '2026-11-01T12:00:00Z',
                   -- One per entry: a proof backs one entry (0012).
                   'proofs/' || gen_random_uuid() || '.jpg', 'TX-1'
            FROM ledger_entry WHERE gym_id = $1 AND kind = 'charge'
            RETURNING id
            """,
            gym,
            status,
        )

    entry: uuid.UUID = run(db.admin_url, query)
    return entry


def fetch_entry(db: Database, entry: uuid.UUID) -> asyncpg.Record:
    return run(
        db.admin_url, lambda c: c.fetchrow("SELECT * FROM ledger_entry WHERE id = $1", entry)
    )


def test_immutable_columns_are_every_column_but_the_settlement_ones(db: Database) -> None:
    # A new ledger_entry column needs a case here, so its immutability is tested.
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = 'ledger_entry'"
        ),
    )
    assert {r["column_name"] for r in rows} == SETTLEMENT_COLUMNS | IMMUTABLE.keys()


@pytest.mark.parametrize("user", ["owner", "superuser"])
def test_delete_is_rejected(db: Database, gym: uuid.UUID, user: str) -> None:
    entry = new_entry(db, gym)
    with pytest.raises(asyncpg.RestrictViolationError, match="cannot be deleted"):
        run(url_of(db, user), in_gym(gym, "DELETE FROM ledger_entry WHERE id = $1", entry))
    assert fetch_entry(db, entry) is not None


def test_api_delete_is_still_refused_by_grants(db: Database, gym: uuid.UUID) -> None:
    entry = new_entry(db, gym)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(db.api_url, in_gym(gym, "DELETE FROM ledger_entry WHERE id = $1", entry))


@pytest.mark.parametrize("user", ["owner", "superuser"])
def test_truncate_is_rejected(db: Database, gym: uuid.UUID, user: str) -> None:
    new_entry(db, gym)
    with pytest.raises(asyncpg.RestrictViolationError, match="cannot be deleted"):
        run(url_of(db, user), lambda c: c.execute("TRUNCATE ledger_entry"))
    count = run(db.admin_url, lambda c: c.fetchval("SELECT count(*) FROM ledger_entry"))
    assert count > 0


@pytest.mark.parametrize("column", sorted(IMMUTABLE))
def test_updating_an_immutable_column_of_a_pending_entry_is_rejected(
    db: Database, gym: uuid.UUID, column: str
) -> None:
    # As the superuser, so neither RLS nor a foreign key gets there before the trigger.
    entry = new_entry(db, gym)
    before = fetch_entry(db, entry)
    sql = f"UPDATE ledger_entry SET {column} = $2 WHERE id = $1"
    with pytest.raises(
        asyncpg.RestrictViolationError,
        match="only status, validated_by, validated_at, note can change",
    ):
        run(db.admin_url, in_gym(gym, sql, entry, IMMUTABLE[column]))
    assert fetch_entry(db, entry) == before


@pytest.mark.parametrize("user", ["api", "owner"])
def test_settling_does_not_carry_other_changes_along(
    db: Database, gym: uuid.UUID, admin_id: uuid.UUID, user: str
) -> None:
    entry = new_entry(db, gym)
    sql = (
        "UPDATE ledger_entry SET status = 'validated', validated_by = $2,"
        " validated_at = now(), amount_clp = 40000 WHERE id = $1"
    )
    with pytest.raises(asyncpg.RestrictViolationError, match="can change"):
        run(url_of(db, user), in_gym(gym, sql, entry, admin_id, person=seeded_owner(gym)))
    assert fetch_entry(db, entry)["status"] == "pending"


def test_api_can_validate_a_pending_entry(
    db: Database, gym: uuid.UUID, admin_id: uuid.UUID
) -> None:
    entry = new_entry(db, gym)
    before = fetch_entry(db, entry)
    sql = (
        "UPDATE ledger_entry SET status = 'validated', validated_by = $2,"
        " validated_at = now(), note = 'ok' WHERE id = $1"
    )
    run(db.api_url, in_gym(gym, sql, entry, admin_id, person=seeded_owner(gym)))
    after = fetch_entry(db, entry)
    assert (after["status"], after["validated_by"], after["note"]) == ("validated", admin_id, "ok")
    assert {k: after[k] for k in IMMUTABLE} == {k: before[k] for k in IMMUTABLE}


def test_api_can_reject_a_pending_entry(db: Database, gym: uuid.UUID, admin_id: uuid.UUID) -> None:
    entry = new_entry(db, gym)
    sql = (
        "UPDATE ledger_entry SET status = 'rejected', validated_by = $2,"
        " validated_at = now(), note = 'comprobante ilegible' WHERE id = $1"
    )
    run(db.api_url, in_gym(gym, sql, entry, admin_id, person=seeded_owner(gym)))
    assert fetch_entry(db, entry)["status"] == "rejected"


@pytest.mark.parametrize("user", ["api", "owner", "superuser"])
@pytest.mark.parametrize("status", ["validated", "rejected"])
@pytest.mark.parametrize(
    "assignment",
    ["status = 'pending'", "status = 'validated'", "note = 'changed'", "validated_at = now()"],
)
def test_a_settled_entry_cannot_change(
    db: Database, gym: uuid.UUID, status: str, assignment: str, user: str
) -> None:
    entry = new_entry(db, gym, status)
    before = fetch_entry(db, entry)
    sql = f"UPDATE ledger_entry SET {assignment} WHERE id = $1"
    with pytest.raises(asyncpg.RestrictViolationError, match="only pending entries can change"):
        run(url_of(db, user), in_gym(gym, sql, entry, person=seeded_owner(gym)))
    assert fetch_entry(db, entry) == before


def test_violations_carry_the_append_only_hint(db: Database, gym: uuid.UUID) -> None:
    entry = new_entry(db, gym)
    with pytest.raises(asyncpg.RestrictViolationError) as raised:
        run(db.owner_url, in_gym(gym, "DELETE FROM ledger_entry WHERE id = $1", entry))
    assert APPEND_ONLY in (raised.value.hint or "")


def test_downgrade_to_0001_drops_the_triggers(scratch_db: Database) -> None:
    migrate(scratch_db)
    command.downgrade(scratch_db.alembic(), "0001")
    triggers = run(
        scratch_db.admin_url,
        lambda c: c.fetch(
            "SELECT tgname FROM pg_trigger"
            " WHERE tgrelid = 'ledger_entry'::regclass AND NOT tgisinternal"
        ),
    )
    assert triggers == []
    migrate(scratch_db)


@pytest.fixture
def scratch_db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        yield database
