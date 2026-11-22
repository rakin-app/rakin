"""The `uploads` job (#522): proofs and receipts nobody claimed are deleted once old.

Each test makes a gym of its own (`tests.jobgym`) and a local store of its own, so the
job, which works on every gym, finds only that test's files.
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest

from app.db_bootstrap import to_dsn
from app.integrations.blobstore import LocalBlobStore
from app.jobs import run_due, uploads
from app.jobs.runner import Outcome
from tests.conftest import require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, migrate, throwaway_database

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 11, 22, 4, 0, tzinfo=UTC)
DAY = date(2026, 11, 22)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def gym(db: Database) -> Gym:
    return Gym(db)


@pytest.fixture
def store(tmp_path: Path) -> LocalBlobStore:
    return LocalBlobStore(root=tmp_path, secret_key="s" * 32, ttl_seconds=900)


def upload(store: LocalBlobStore, key: str, *, age: timedelta) -> str:
    """A file at `key`, written `age` before `NOW`."""
    asyncio.run(store.put(key, "image/png", PNG))
    written = (NOW - age).timestamp()
    os.utime(store.root / "data" / key, (written, written))
    return key


def proof(gym: Gym, *, age: timedelta, store: LocalBlobStore) -> str:
    return upload(store, f"proofs/{gym.id}/{gym.person}/{uuid.uuid4()}", age=age)


def receipt(gym: Gym, *, age: timedelta, store: LocalBlobStore) -> str:
    return upload(store, f"receipts/{gym.id}/{uuid.uuid4()}", age=age)


def stored(store: LocalBlobStore, key: str) -> bool:
    return asyncio.run(store.stat(key)) is not None


def claim_proof(gym: Gym, key: str) -> None:
    """A pending transfer pointing at `key`, as `POST /api/me/payments` writes one."""
    membership = gym.member("signup", date(2026, 11, 1))
    gym.bill(membership, date(2026, 11, 1), date(2026, 11, 30), 45_000)
    gym.sql(
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
        " status, method, claimed_by, claimed_at, proof_object_key)"
        " SELECT $1, $2, id, 45000, 'payment', 'pending', 'transfer', $3, now(), $4"
        " FROM billing_period WHERE membership_id = $2",
        gym.id,
        membership,
        gym.person,
        key,
    )


def expense(gym: Gym, receipt_key: str | None) -> uuid.UUID:
    (row,) = gym.sql(
        "INSERT INTO expense (gym_id, spent_on, amount_clp, category_id, created_by,"
        " receipt_object_key)"
        " SELECT $1, DATE '2026-11-20', 1000, id, $2, $3 FROM expense_category"
        " WHERE gym_id = $1 AND is_other RETURNING id",
        gym.id,
        gym.person,
        receipt_key,
    )
    expense_id: uuid.UUID = row[0]
    return expense_id


def changed(gym: Gym, expense_id: uuid.UUID, before: str | None, after: str | None) -> None:
    """The `expense_changed` row an edit of the receipt writes (`app.api.expenses`)."""
    detail = {
        "expense_id": str(expense_id),
        "before": {"receipt_object_key": before},
        "after": {"receipt_object_key": after},
    }
    gym.sql(
        "INSERT INTO audit_event (gym_id, actor_id, action, detail)"
        " VALUES ($1, $2, 'expense_changed', $3)",
        gym.id,
        gym.person,
        json.dumps(detail),
    )


def run_job(db: Database, store: LocalBlobStore) -> Outcome:
    async def go() -> Outcome:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            # Each test runs as a day of its own: the runner does a day once.
            await conn.execute("DELETE FROM job_run WHERE job_name = $1", uploads.NAME)
            report = await run_due(conn, [uploads.job(store, clock=lambda: NOW)], DAY)
            return report.outcome
        finally:
            await conn.close()

    return asyncio.run(go())


# Each a day or more from the 48 hours' grace: CI's midnight run fakes the clock by up
# to a day, and a file's times may be faked with it or not.
OLD = timedelta(days=4)
YOUNG = timedelta(hours=1)


def test_an_old_upload_nobody_claimed_is_deleted(
    db: Database, gym: Gym, store: LocalBlobStore
) -> None:
    lost_proof = proof(gym, age=OLD, store=store)
    lost_receipt = receipt(gym, age=OLD, store=store)

    assert run_job(db, store) is Outcome.SUCCEEDED

    assert not stored(store, lost_proof)
    assert not stored(store, lost_receipt)


def test_an_upload_inside_the_grace_is_kept(db: Database, gym: Gym, store: LocalBlobStore) -> None:
    young_proof = proof(gym, age=YOUNG, store=store)
    young_receipt = receipt(gym, age=YOUNG, store=store)

    run_job(db, store)

    assert stored(store, young_proof)
    assert stored(store, young_receipt)


def test_a_claimed_proof_and_receipt_are_kept(
    db: Database, gym: Gym, store: LocalBlobStore
) -> None:
    claimed_proof = proof(gym, age=OLD, store=store)
    claim_proof(gym, claimed_proof)
    claimed_receipt = receipt(gym, age=OLD, store=store)
    expense_id = expense(gym, claimed_receipt)
    # Voided, it still keeps its receipt.
    gym.sql(
        "UPDATE expense SET voided_at = now(), voided_by = $2, void_reason = 'duplicado'"
        " WHERE id = $1",
        expense_id,
        gym.person,
    )

    run_job(db, store)

    assert stored(store, claimed_proof)
    assert stored(store, claimed_receipt)


def test_a_receipt_kept_only_as_a_corrections_history_is_kept(
    db: Database, gym: Gym, store: LocalBlobStore
) -> None:
    replaced = receipt(gym, age=OLD, store=store)
    removed = receipt(gym, age=OLD, store=store)
    current = receipt(gym, age=OLD, store=store)
    expense_id = expense(gym, current)
    # Replaced by `current`, after `removed` was put on and taken off another.
    changed(gym, expense_id, replaced, current)
    other = expense(gym, None)
    changed(gym, other, None, removed)
    changed(gym, other, removed, None)

    run_job(db, store)

    assert stored(store, replaced)
    assert stored(store, removed)
    assert stored(store, current)


def test_another_gyms_reference_does_not_keep_an_upload(
    db: Database, gym: Gym, store: LocalBlobStore
) -> None:
    other = Gym(db)
    lost = receipt(gym, age=OLD, store=store)
    # Another gym's audit row naming this key, which its expenses could never hold.
    changed(other, expense(other, None), lost, None)

    run_job(db, store)

    assert not stored(store, lost)


def test_an_upload_a_claim_is_checking_is_left_for_the_next_run(
    db: Database, gym: Gym, store: LocalBlobStore
) -> None:
    claiming = proof(gym, age=OLD, store=store)

    async def go() -> bool:
        claim = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            async with claim.transaction():
                # `app.api.proofs.LOCK_PROOF`, as a claim holds it to its commit.
                await claim.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", claiming
                )
                await asyncio.to_thread(run_job, db, store)
                return await store.stat(claiming) is not None
        finally:
            await claim.close()

    assert asyncio.run(go())

    run_job(db, store)

    assert not stored(store, claiming)


def test_the_log_counts_and_names_no_key(
    db: Database, gym: Gym, store: LocalBlobStore, caplog: pytest.LogCaptureFixture
) -> None:
    lost = proof(gym, age=OLD, store=store)
    kept = proof(gym, age=OLD, store=store)
    claim_proof(gym, kept)

    with caplog.at_level(logging.INFO, logger=uploads.__name__):
        run_job(db, store)

    [record] = [
        r
        for r in caplog.records
        if r.name == uploads.__name__ and getattr(r, "gym_id", None) == str(gym.id)
    ]
    assert (record.deleted, record.kept, record.failed) == (1, 1, 0)  # type: ignore[attr-defined]
    for r in caplog.records:
        text = r.getMessage() + repr(r.__dict__)
        assert lost not in text and kept not in text
        assert str(gym.person) not in text


def test_a_store_that_refuses_a_deletion_fails_the_day_without_naming_the_file(
    db: Database,
    gym: Gym,
    store: LocalBlobStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lost = proof(gym, age=OLD, store=store)

    async def refuse(key: str) -> None:
        raise PermissionError(f"cannot remove {store.root / 'data' / key}")

    monkeypatch.setattr(store, "delete", refuse)
    with caplog.at_level(logging.INFO):
        assert run_job(db, store) is Outcome.FAILED

    assert stored(store, lost)
    [failure] = [r for r in caplog.records if r.exc_info and r.name == uploads.__name__]
    assert "1 unclaimed uploads could not be deleted" in str(failure.exc_info[1])  # type: ignore[index]
    for r in caplog.records:
        text = r.getMessage() + repr(r.__dict__)
        assert str(gym.person) not in text
