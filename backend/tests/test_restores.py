"""Restaurar cargo (#278): a charge voided by mistake is owed again, as if never voided.

A restore is a new entry, an adjustment of minus the void's amount naming it in
`corrects`, so the period owes it again everywhere the app settles one: the ficha, Hoy,
the balance. The charge no longer reads voided, "Esperado" counts it again, and it may
be voided again; the Libro keeps the void and the restore. A void is restored once, and
never one of a plan voided by mistake. The database holds it too: one void without a
restore per period, and a restore only of a void of its own period and amount.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain import billing as domain
from app.domain.billing import BillingPeriod
from app.domain.ledger import Purpose
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_corrections import audit_rows
from tests.test_plans import add_staff
from tests.test_voids import (
    balance,
    book,
    ledger,
    member,
    ok,
    overdue_ids,
    pay,
    refund,
    void,
    void_plan,
)

pg = pytest.mark.postgres

WHY = "se anuló el cargo equivocado"

# --- the domain, no database ------------------------------------------------------


def test_a_restore_puts_the_voids_amount_back_on_the_period() -> None:
    period = BillingPeriod(
        period_start=seeded_today(),
        period_end=seeded_today() + timedelta(days=29),
        amount_due_clp=45_000,
        due_date=seeded_today(),
    )
    voided = domain.void(period, "duplicado")
    settlement = domain.restore(voided.period, voided.entry.amount_clp, f"  {WHY} ")
    entry = settlement.entry
    assert (entry.kind, entry.amount_clp, entry.purpose) == ("adjustment", -45_000, Purpose.RESTORE)
    assert entry.note == WHY
    assert (settlement.period.outstanding_clp, settlement.period.closed) == (45_000, False)
    with pytest.raises(ValueError):
        domain.restore(voided.period, 45_000, "  ")
    with pytest.raises(ValueError):
        domain.restore(voided.period, 0, WHY)


# --- against real Postgres --------------------------------------------------------


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"sur-{uuid.uuid4().hex[:8]}")


def restore(client: TestClient, gym: uuid.UUID, void_id: str, **kw: Any) -> Any:
    body = {"void_id": void_id, "reason": WHY}
    return client.post("/api/ledger/restores", json=body, headers=as_gym(gym, **kw))


def charge_of(entries: list[Any], period: str) -> Any:
    return next(e for e in entries if e["kind"] == "charge" and e["billing_period_id"] == period)


def period_of(read: Any, period: str) -> Any:
    return next(p for p in read["periods"] if p["id"] == period)


def voided_period(client: TestClient, gym: uuid.UUID) -> tuple[str, str, Any, str]:
    """A member's overdue period, voided: their id, their membership's, the period, the
    void's id."""
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    recorded = ok(void(client, gym, membership, oldest["id"]), 201)
    return person, membership, oldest, recorded["void"]["id"]


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_a_restored_charge_is_owed_again_and_reads_as_restored(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    person, membership = member(client, gym)
    before = ledger(client, gym, membership)
    oldest = before["open_periods"][0]
    kpis = book(client, gym, month=oldest["due_date"])["kpis"]
    balance_before = balance(db, membership)
    void_id = ok(void(client, gym, membership, oldest["id"]), 201)["void"]["id"]
    assert period_of(ledger(client, gym, membership), oldest["id"])["void_id"] == void_id

    by = None if role == "owner" else add_staff(db, gym, "admin")
    recorded = ok(restore(client, gym, void_id, **({"person_id": by} if by else {})), 201)
    entry = recorded["restore"]
    assert (entry["kind"], entry["amount_clp"], entry["note"]) == ("adjustment", -45_000, WHY)
    assert (entry["purpose"], entry["corrects"], entry["voids"]) == ("restore", void_id, False)
    assert recorded["period"]["outstanding_clp"] == 45_000

    # Owed again on the ficha, on Hoy, in the balance, and in "Esperado".
    after = ledger(client, gym, membership)
    assert oldest["id"] in {p["id"] for p in after["open_periods"]}
    assert after["owed_clp"] == before["owed_clp"]
    assert oldest["id"] in overdue_ids(client, gym)
    assert balance(db, membership) == balance_before
    later = book(client, gym, month=oldest["due_date"])["kpis"]
    assert (later["expected_clp"], later["overdue_clp"]) == (
        kpis["expected_clp"],
        kpis["overdue_clp"],
    )

    # The charge no longer reads voided, but says it was, and restored; the Libro keeps both.
    charge = charge_of(after["entries"], oldest["id"])
    assert charge["voided"] is None
    assert charge["restored"]["reason"] == WHY
    assert charge["restored"]["by_name"] is not None
    assert charge["restored"]["void"]["reason"] == "alumno de prueba"
    purposes = {e["purpose"] for e in after["entries"] if e["billing_period_id"] == oldest["id"]}
    assert {"void", "restore"} <= purposes
    assert (
        period_of(after, oldest["id"])["voided_clp"],
        period_of(after, oldest["id"])["void_id"],
    ) == (
        0,
        None,
    )
    month = book(client, gym, month=oldest["period_start"])["items"]
    booked = next(i for i in month if i["kind"] == "charge" and i["membership_id"] == membership)
    assert (booked["voided"], booked["restored"]["reason"]) == (None, WHY)

    # The audit row says what it put back.
    row = audit_rows(db, gym, person)[-1]
    assert (row["action"], row["reason"]) == ("ledger_corrected", WHY)
    assert row["detail"]["purpose"] == "restore"
    assert row["detail"]["entry_ids"] == [entry["id"]]
    assert row["detail"]["before"]["outstanding_clp"] == 0
    assert row["detail"]["after"] == {"outstanding_clp": 45_000, "balance_clp": balance_before}


@pg
def test_a_restored_period_can_be_voided_again_and_a_void_is_restored_once(
    client: TestClient, gym: uuid.UUID
) -> None:
    _, membership, oldest, first = voided_period(client, gym)
    ok(restore(client, gym, first), 201)
    again = restore(client, gym, first)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "restored"

    second = ok(void(client, gym, membership, oldest["id"]), 201)["void"]["id"]
    read = ledger(client, gym, membership)
    assert oldest["id"] not in {p["id"] for p in read["open_periods"]}
    assert charge_of(read["entries"], oldest["id"])["voided"]["at"] is not None
    assert period_of(read, oldest["id"])["void_id"] == second
    # And restored again, this time the second void.
    ok(restore(client, gym, second), 201)
    assert oldest["id"] in {p["id"] for p in ledger(client, gym, membership)["open_periods"]}


@pg
def test_only_a_void_of_a_plan_still_assigned_is_restored(
    client: TestClient, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    periods = ledger(client, gym, membership)["open_periods"]
    paid = pay(client, gym, membership, periods[0]["id"])

    refused = restore(client, gym, paid)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_a_void"
    assert restore(client, gym, str(uuid.uuid4())).status_code == 404
    assert (
        client.post(
            "/api/ledger/restores", json={"void_id": paid, "reason": " "}, headers=as_gym(gym)
        ).status_code
        == 422
    )

    # A plan voided by mistake is assigned again, not restored a period at a time.
    refund(client, gym, paid)
    ok(void_plan(client, gym, membership), 200)
    [plan_void, *_] = [e for e in ledger(client, gym, membership)["entries"] if e["voids"]]
    refused = restore(client, gym, plan_void["id"])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "plan_voided"


@pg
def test_a_coach_cannot_restore(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    _, membership, oldest, void_id = voided_period(client, gym)
    coach = add_staff(db, gym, "coach")
    assert restore(client, gym, void_id, person_id=coach).status_code == 403
    assert oldest["id"] not in {p["id"] for p in ledger(client, gym, membership)["open_periods"]}


# --- what the database holds to, whoever writes ---------------------------------------


def write(db: Database, gym: uuid.UUID, sql: str, *args: object) -> Any:
    return run(db.owner_url, in_gym(gym, sql, *args))


ADJUSTMENT = (
    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
    " status, note, purpose, corrects) SELECT gym_id, membership_id, id, $2, 'adjustment',"
    " 'validated', 'a mano', $3, $4 FROM billing_period WHERE id = $1 RETURNING id"
)


@pg
def test_the_database_keeps_one_standing_void_per_period(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, _, oldest, void_id = voided_period(client, gym)
    period = uuid.UUID(oldest["id"])
    with pytest.raises(asyncpg.UniqueViolationError):
        write(db, gym, ADJUSTMENT, period, 1_000, "void", None)
    # A restore of another amount, or of what is not a void, is refused.
    with pytest.raises(asyncpg.CheckViolationError):
        write(db, gym, ADJUSTMENT, period, -1_000, "restore", uuid.UUID(void_id))
    # Each purpose to its sign: a restore is owed, a void in the member's favour.
    with pytest.raises(asyncpg.CheckViolationError):
        write(db, gym, ADJUSTMENT, period, 45_000, "restore", uuid.UUID(void_id))
    with pytest.raises(asyncpg.CheckViolationError):
        write(db, gym, ADJUSTMENT, period, 1_000, "nada", None)

    restored = write(db, gym, ADJUSTMENT, period, -45_000, "restore", uuid.UUID(void_id))
    assert restored is not None
    with pytest.raises(asyncpg.UniqueViolationError):
        write(db, gym, ADJUSTMENT, period, -45_000, "restore", uuid.UUID(void_id))
    # Restored, the period takes a void again.
    write(db, gym, ADJUSTMENT, period, 45_000, "void", None)
