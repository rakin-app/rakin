"""Revertir ajuste and Condonar deuda (#282).

A revert undoes an adjustment made by mistake with an adjustment of minus as much,
naming it in `corrects`, so its period settles as if it never was: a discount reverted
is owed again, a Recargo reverted is not, capped at what the period still owes. A void
is restored instead, a correction's own entry is undone by its inverse, a carried credit
follows its payment, and an adjustment is reverted once.

A write-off forgives a real debt: an adjustment in the member's favour of all the
period owes. Nothing is owed on it, so it leaves Hoy and the balance, but "Esperado"
keeps it, unlike a void, and the book reports it as "Condonado". A proof waiting on the
period is reviewed first.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app import ledger_export
from app.domain import billing as domain
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import Purpose
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_corrections import adjust, audit_rows
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer
from tests.test_voids import (
    balance,
    book,
    ledger,
    member,
    ok,
    overdue_ids,
    pay,
    pending_proof,
    void,
)

pg = pytest.mark.postgres

WHY = "se aplicó al alumno equivocado"
FORGIVEN = "se fue del país, no se cobrará"

# --- the domain, no database ------------------------------------------------------


def period(paid: int = 0) -> BillingPeriod:
    return BillingPeriod(
        period_start=seeded_today(),
        period_end=seeded_today() + timedelta(days=29),
        amount_due_clp=45_000,
        due_date=seeded_today(),
        paid_clp=paid,
    )


def test_a_revert_undoes_an_adjustment_either_way() -> None:
    discounted = domain.adjust(period(), 5_000, "hermano")
    settlement = domain.revert(discounted.period, 5_000, f"  {WHY} ")
    entry = settlement.entry
    assert (entry.kind, entry.amount_clp, entry.purpose) == ("adjustment", -5_000, Purpose.REVERT)
    assert entry.note == WHY
    assert settlement.period.outstanding_clp == 45_000

    surcharged = domain.adjust(period(), -5_000, "recargo")
    assert surcharged.period.outstanding_clp == 50_000
    assert domain.revert(surcharged.period, -5_000, WHY).period.outstanding_clp == 45_000
    # A Recargo's revert is in the member's favour: no more than the period still owes.
    paid = domain.adjust(period(paid=45_000), -5_000, "recargo").period
    assert paid.outstanding_clp == 5_000
    with pytest.raises(InvalidTransition):
        domain.revert(domain.adjust(period(paid=47_000), -5_000, "recargo").period, -5_000, WHY)
    assert domain.revert(paid, -5_000, WHY).period.closed
    with pytest.raises(ValueError):
        domain.revert(discounted.period, 5_000, "  ")


def test_a_write_off_forgives_all_the_period_still_owes() -> None:
    settlement = domain.write_off(period(paid=20_000), f" {FORGIVEN} ")
    entry = settlement.entry
    assert (entry.kind, entry.amount_clp, entry.purpose) == ("adjustment", 25_000, "write_off")
    assert entry.note == FORGIVEN
    assert (settlement.period.outstanding_clp, settlement.period.closed) == (0, True)
    with pytest.raises(InvalidTransition):
        domain.write_off(settlement.period, FORGIVEN)
    with pytest.raises(ValueError):
        domain.write_off(period(), " ")


def test_the_export_labels_a_revert_and_a_write_off_as_adjustments() -> None:
    assert ledger_export.kind_label("adjustment", False, "revert") == "Ajuste revertido"
    assert ledger_export.kind_label("adjustment", False, "revert", on_period=False) == (
        "Ajuste por pago anulado"
    )
    assert ledger_export.kind_label("adjustment", False, "write_off") == "Deuda condonada"


# --- against real Postgres --------------------------------------------------------


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url, public_base_url="http://testserver"))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=RecordingMailer())
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("sur"))


def revert(client: TestClient, gym: uuid.UUID, adjustment: str, **kw: Any) -> Any:
    body = {"adjustment_id": adjustment, "reason": WHY}
    return client.post("/api/ledger/reverts", json=body, headers=as_gym(gym, **kw))


def write_off(client: TestClient, gym: uuid.UUID, membership: str, period: str, **kw: Any) -> Any:
    body = {"membership_id": membership, "billing_period_id": period, "reason": FORGIVEN}
    return client.post("/api/ledger/write-offs", json=body, headers=as_gym(gym, **kw))


def refused(response: Any, code: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == code


def outstanding(client: TestClient, gym: uuid.UUID, membership: str, period: str) -> int:
    read = ledger(client, gym, membership)
    return int(next(p for p in read["periods"] if p["id"] == period)["outstanding_clp"])


def entry_of(client: TestClient, gym: uuid.UUID, membership: str, entry: str) -> Any:
    return next(e for e in ledger(client, gym, membership)["entries"] if e["id"] == entry)


@pg
@pytest.mark.parametrize(("role", "amount"), [("owner", 5_000), ("admin", -5_000)])
def test_a_reverted_discount_or_recargo_leaves_the_period_as_before_it(
    client: TestClient, db: Database, gym: uuid.UUID, role: str, amount: int
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    balance_before = balance(db, membership)
    adjusted = adjust(client, gym, membership, oldest["id"], amount)["adjustment"]
    assert outstanding(client, gym, membership, oldest["id"]) == 45_000 - amount

    by = None if role == "owner" else add_staff(db, gym, "admin")
    recorded = ok(revert(client, gym, adjusted["id"], **({"person_id": by} if by else {})), 201)
    entry = recorded["revert"]
    assert (entry["kind"], entry["amount_clp"], entry["note"]) == ("adjustment", -amount, WHY)
    assert (entry["purpose"], entry["corrects"]) == ("revert", adjusted["id"])
    assert recorded["period"]["outstanding_clp"] == 45_000

    # As before the adjustment: on the ficha, on Hoy, in the balance.
    assert outstanding(client, gym, membership, oldest["id"]) == 45_000
    assert oldest["id"] in overdue_ids(client, gym)
    assert balance(db, membership) == balance_before
    # The Libro keeps both, the adjustment reading reverted.
    reverted = entry_of(client, gym, membership, adjusted["id"])["reverted"]
    assert (reverted["reason"], reverted["by_name"] is not None) == (WHY, True)

    row = audit_rows(db, gym, person)[-1]
    assert (row["action"], row["reason"]) == ("ledger_corrected", WHY)
    assert row["detail"]["purpose"] == "revert"
    assert row["detail"]["entry_ids"] == [entry["id"]]
    assert row["detail"]["adjustment_id"] == adjusted["id"]
    assert row["detail"]["before"]["outstanding_clp"] == 45_000 - amount
    assert row["detail"]["after"] == {"outstanding_clp": 45_000, "balance_clp": balance_before}

    # An adjustment is reverted once, and a revert is not reverted.
    refused(revert(client, gym, adjusted["id"]), "reverted")
    refused(revert(client, gym, entry["id"]), "correction")


@pg
def test_a_recargo_paid_is_not_reverted_past_what_the_period_owes(
    client: TestClient, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    surcharge = adjust(client, gym, membership, oldest["id"], -5_000)["adjustment"]
    body = {
        "membership_id": membership,
        "billing_period_id": oldest["id"],
        "amount_clp": 50_000,
        "method": "cash",
    }
    ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)
    refused(revert(client, gym, surcharge["id"]), "exceeds")
    assert outstanding(client, gym, membership, oldest["id"]) == 0


@pg
def test_only_a_plain_adjustment_on_a_period_is_reverted(
    client: TestClient, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]

    # A payment is no adjustment, and an unknown id is not found.
    paid = pay(client, gym, membership, first["id"])
    refused(revert(client, gym, paid), "not_an_adjustment")
    assert revert(client, gym, str(uuid.uuid4())).status_code == 404
    reason = {"adjustment_id": paid, "reason": " "}
    assert client.post("/api/ledger/reverts", json=reason, headers=as_gym(gym)).status_code == 422

    # A void is restored instead, and its restore undone by voiding again.
    discount = adjust(client, gym, membership, second["id"], 5_000)["adjustment"]
    voided = ok(void(client, gym, membership, second["id"]), 201)["void"]
    refused(revert(client, gym, voided["id"]), "void")
    # Nor a discount under a void: restore the charge first.
    refused(revert(client, gym, discount["id"]), "voided")
    restore = {"void_id": voided["id"], "reason": WHY}
    restored = ok(client.post("/api/ledger/restores", json=restore, headers=as_gym(gym)), 201)
    refused(revert(client, gym, restored["restore"]["id"]), "correction")
    ok(revert(client, gym, discount["id"]), 201)
    assert outstanding(client, gym, membership, second["id"]) == 45_000


@pg
def test_a_carried_credit_and_its_revert_follow_their_payment(
    client: TestClient, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    body = {
        "membership_id": membership,
        "billing_period_id": oldest["id"],
        "amount_clp": 50_000,
        "method": "cash",
    }
    paid = ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)
    refused(revert(client, gym, paid["credit"]["id"]), "credit")
    undo = {"payment_id": paid["payment"]["id"], "reason": WHY}
    undone = ok(client.post("/api/ledger/payment-voids", json=undo, headers=as_gym(gym)), 201)
    refused(revert(client, gym, undone["reverted"]["id"]), "correction")


@pg
def test_a_coach_cannot_revert_or_write_off(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    adjusted = adjust(client, gym, membership, oldest["id"], 5_000)["adjustment"]
    coach = add_staff(db, gym, "coach")
    assert revert(client, gym, adjusted["id"], person_id=coach).status_code == 403
    assert write_off(client, gym, membership, oldest["id"], person_id=coach).status_code == 403
    assert outstanding(client, gym, membership, oldest["id"]) == 40_000


@pg
def test_a_written_off_debt_is_owed_nowhere_but_still_expected_and_condoned(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    # Part of it was paid, and stays paid.
    body = {
        "membership_id": membership,
        "billing_period_id": oldest["id"],
        "amount_clp": 20_000,
        "method": "cash",
    }
    ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)
    expected = book(client, gym, month=oldest["due_date"])["kpis"]["expected_clp"]
    condoned = book(client, gym)["kpis"]["written_off_clp"]
    balance_before = balance(db, membership)

    recorded = ok(write_off(client, gym, membership, oldest["id"]), 201)
    entry = recorded["write_off"]
    assert (entry["kind"], entry["amount_clp"], entry["note"]) == ("adjustment", 25_000, FORGIVEN)
    assert (entry["purpose"], entry["corrects"], entry["voids"]) == ("write_off", None, False)
    assert (recorded["period"]["outstanding_clp"], recorded["period"]["closed"]) == (0, True)

    # Nothing owed, off Hoy, out of the balance; the charge does not read voided.
    read = ledger(client, gym, membership)
    assert oldest["id"] not in {p["id"] for p in read["open_periods"]}
    assert oldest["id"] not in overdue_ids(client, gym)
    assert balance(db, membership) == balance_before - 25_000
    charge = next(
        e
        for e in read["entries"]
        if e["kind"] == "charge" and e["billing_period_id"] == oldest["id"]
    )
    assert charge["voided"] is None
    # Still in "Esperado", and in the month's "Condonado".
    assert book(client, gym, month=oldest["due_date"])["kpis"]["expected_clp"] == expected
    assert book(client, gym)["kpis"]["written_off_clp"] == condoned + 25_000

    row = audit_rows(db, gym, person)[-1]
    assert (row["action"], row["reason"]) == ("ledger_corrected", FORGIVEN)
    assert row["detail"]["purpose"] == "write_off"
    assert row["detail"]["entry_ids"] == [entry["id"]]
    assert row["detail"]["before"] == {"outstanding_clp": 25_000, "balance_clp": balance_before}
    assert row["detail"]["after"]["outstanding_clp"] == 0

    # Nothing is left to forgive; reverted, the debt is owed again and no longer condoned.
    refused(write_off(client, gym, membership, oldest["id"]), "nothing_owed")
    ok(revert(client, gym, entry["id"]), 201)
    assert outstanding(client, gym, membership, oldest["id"]) == 25_000
    assert oldest["id"] in overdue_ids(client, gym)
    assert book(client, gym)["kpis"]["written_off_clp"] == condoned


@pg
def test_a_write_off_waits_for_a_proof_on_the_period(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    pending_proof(db, gym, person, membership, oldest["id"])
    refused(write_off(client, gym, membership, oldest["id"]), "pending")
    assert outstanding(client, gym, membership, oldest["id"]) == 45_000
    assert write_off(client, gym, membership, str(uuid.uuid4())).status_code == 404


# --- what the database holds to, whoever writes ---------------------------------------


REVERT = (
    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
    " status, note, purpose, corrects) SELECT gym_id, membership_id, id, $2, 'adjustment',"
    " 'validated', 'a mano', 'revert', $3 FROM billing_period WHERE id = $1 RETURNING id"
)


@pg
def test_the_database_holds_a_revert_to_its_adjustment(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    adjusted = uuid.UUID(adjust(client, gym, membership, first["id"], 5_000)["adjustment"]["id"])
    voided = uuid.UUID(ok(void(client, gym, membership, second["id"]), 201)["void"]["id"])

    def write(period: str, amount: int, corrects: uuid.UUID) -> Any:
        return run(db.owner_url, in_gym(gym, REVERT, uuid.UUID(period), amount, corrects))

    # Another amount, another period, or a void: refused.
    with pytest.raises(asyncpg.CheckViolationError):
        write(first["id"], -4_000, adjusted)
    with pytest.raises(asyncpg.CheckViolationError):
        write(second["id"], -5_000, adjusted)
    with pytest.raises(asyncpg.CheckViolationError):
        write(second["id"], -45_000, voided)
    assert write(first["id"], -5_000, adjusted) is not None
    # Once.
    with pytest.raises(asyncpg.UniqueViolationError):
        write(first["id"], -5_000, adjusted)


def test_upgrade_and_downgrade_0091() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0090")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0090")
        migrate(scratch)
