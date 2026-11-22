"""Anular pago registrado por error (#281): a payment recorded by mistake is undone.

The undoing is a new entry, a refund of what is left of the payment with `purpose =
'mistake'`, naming the payment as `refund_of` and `corrects`. The period owes it again,
as after a refund; "Cobrado" nets it in the month it is made, but "Reembolsos" does not
count it: it reports as "Pagos anulados" (`corrected_clp`). A payment that carried
credit is undone whole, its credit reverted beside it. The student, or their guardian,
is emailed that it was undone, once it has committed. A person whose only payment was
undone counts as having been given it back, so they can still be deleted.
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
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry, Purpose
from app.main import create_app
from app.notices import _dia
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_corrections import audit_rows
from tests.test_extra_charges import create, draft, line_of
from tests.test_guardians import add_person
from tests.test_member_roll import enrolled, forget, memberships, plan
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer
from tests.test_voids import balance, book, ledger, member, ok, pending_proof, void_plan

WHY = "se registró en el alumno equivocado"

# --- the domain, no database ------------------------------------------------------


def period_of(paid: int = 0) -> BillingPeriod:
    return BillingPeriod(
        period_start=seeded_today(),
        period_end=seeded_today() + timedelta(days=29),
        amount_due_clp=45_000,
        due_date=seeded_today(),
        paid_clp=paid,
        closed=paid >= 45_000,
    )


PAID = LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=45_000, status=EntryStatus.VALIDATED)


def test_undoing_a_payment_takes_back_all_that_is_left_of_it() -> None:
    whole = domain.undo_payment(period_of(45_000), PAID, 0, f"  {WHY} ")
    entry = whole.entry
    assert (entry.kind, entry.amount_clp, entry.purpose) == ("refund", 45_000, Purpose.MISTAKE)
    assert entry.note == WHY
    assert (whole.period.outstanding_clp, whole.period.closed) == (45_000, False)

    # After a refund of 10.000, the 35.000 left of it.
    rest = domain.undo_payment(period_of(35_000), PAID, 10_000, WHY)
    assert rest.entry.amount_clp == 35_000
    assert rest.period.outstanding_clp == 45_000


def test_a_payment_with_nothing_left_or_not_validated_is_not_undone() -> None:
    with pytest.raises(InvalidTransition):
        domain.undo_payment(period_of(), PAID, 45_000, WHY)
    pending = dataclasses.replace(PAID, status=EntryStatus.PENDING)
    with pytest.raises(InvalidTransition):
        domain.undo_payment(period_of(), pending, 0, WHY)
    with pytest.raises(ValueError):
        domain.undo_payment(period_of(45_000), PAID, 0, "  ")


def test_a_credit_is_reverted_by_minus_as_much() -> None:
    entry = domain.revert_credit(5_000, WHY)
    assert (entry.kind, entry.amount_clp, entry.purpose) == ("adjustment", -5_000, Purpose.REVERT)
    with pytest.raises(ValueError):
        domain.revert_credit(0, WHY)
    with pytest.raises(ValueError):
        LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=-5, purpose=Purpose.MISTAKE)


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(db: Database, mailer: RecordingMailer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url, public_base_url="http://testserver"))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("sur"))


def undo(client: TestClient, gym: uuid.UUID, payment: str, **kw: Any) -> Any:
    body = {"payment_id": payment, "reason": WHY}
    return client.post("/api/ledger/payment-voids", json=body, headers=as_gym(gym, **kw))


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> Any:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "method": "transfer",
    }
    return ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)


def give_back(client: TestClient, gym: uuid.UUID, payment: str, amount: int) -> Any:
    body = {"payment_id": payment, "amount_clp": amount, "method": "cash"}
    return client.post("/api/ledger/refunds", json=body, headers=as_gym(gym))


def emailed(db: Database, gym: uuid.UUID, person: str, address: str) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_person SET email = $3 WHERE gym_id = $1 AND person_id = $2",
            gym,
            uuid.UUID(person),
            address,
        ),
    )


def kpis(client: TestClient, gym: uuid.UUID) -> Any:
    return book(client, gym)["kpis"]


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_an_undone_payment_is_owed_again_and_reported_as_a_correction(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer, role: str
) -> None:
    person, membership = member(client, gym)
    emailed(db, gym, person, "prueba@example.cl")
    oldest = ledger(client, gym, membership)["open_periods"][0]
    owed_before = balance(db, membership)
    payment = pay(client, gym, membership, oldest["id"], 45_000)["payment"]
    paid_kpis = kpis(client, gym)

    by = None if role == "owner" else add_staff(db, gym, "admin")
    mailer.sent.clear()
    recorded = ok(undo(client, gym, payment["id"], **({"person_id": by} if by else {})), 201)
    entry = recorded["void"]
    assert (entry["kind"], entry["amount_clp"], entry["note"]) == ("refund", 45_000, WHY)
    assert (entry["purpose"], entry["corrects"], entry["refund_of"]) == (
        "mistake",
        payment["id"],
        payment["id"],
    )
    assert entry["method"] is None
    assert recorded["reverted"] is None
    assert recorded["period"]["outstanding_clp"] == 45_000

    # Owed again, as before the payment.
    after = ledger(client, gym, membership)
    assert oldest["id"] in {p["id"] for p in after["open_periods"]}
    assert balance(db, membership) == owed_before
    assert payment["id"] not in {p["id"] for p in after["refundable_payments"]}

    # "Cobrado" drops in the month it is made; "Reembolsos" does not move.
    later = kpis(client, gym)
    assert later["collected_clp"] == paid_kpis["collected_clp"] - 45_000
    assert (later["refunded_clp"], later["refunds"]) == (
        paid_kpis["refunded_clp"],
        paid_kpis["refunds"],
    )
    assert (later["corrected_clp"], later["corrections"]) == (
        paid_kpis["corrected_clp"] + 45_000,
        paid_kpis["corrections"] + 1,
    )
    booked = next(i for i in book(client, gym)["items"] if i["id"] == entry["id"])
    assert (booked["kind"], booked["purpose"], booked["note"]) == ("refund", "mistake", WHY)

    # The audit row says what it undid.
    row = audit_rows(db, gym, person)[-1]
    assert (row["action"], row["reason"]) == ("ledger_corrected", WHY)
    assert row["detail"]["purpose"] == "mistake"
    assert row["detail"]["payment_id"] == payment["id"]
    assert row["detail"]["entry_ids"] == [entry["id"]]
    assert row["detail"]["before"]["outstanding_clp"] == 0
    assert row["detail"]["after"] == {"outstanding_clp": 45_000, "balance_clp": owed_before}

    # The student is told, without the admin's reason.
    [email] = mailer.sent
    assert (email.to, email.subject) == ("prueba@example.cl", "Pago anulado")
    assert (
        f"El pago de $45.000 del {_dia(seeded_today())} se anuló: fue un error de registro."
        in email.text
    )
    assert "Tu saldo es $" in email.text
    assert WHY not in email.text and WHY not in (email.html or "")

    # "Mis pagos" lists it as undone, without the reason.
    mine = ok(client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person))))["payments"]
    [shown] = [p for p in mine if p["id"] == entry["id"]]
    assert (shown["kind"], shown["purpose"], shown["note"]) == ("refund", "mistake", None)

    # Undone once: nothing is left to undo, or to refund.
    again = undo(client, gym, payment["id"])
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "nothing_left"
    assert give_back(client, gym, payment["id"], 1).status_code == 409


@pg
def test_a_partly_refunded_payment_is_undone_for_what_is_left(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    owed_before = balance(db, membership)
    payment = pay(client, gym, membership, oldest["id"], 45_000)["payment"]
    ok(give_back(client, gym, payment["id"], 10_000), 201)
    before = kpis(client, gym)

    recorded = ok(undo(client, gym, payment["id"]), 201)
    assert recorded["void"]["amount_clp"] == 35_000
    assert recorded["period"]["outstanding_clp"] == 45_000
    assert balance(db, membership) == owed_before
    later = kpis(client, gym)
    assert later["collected_clp"] == before["collected_clp"] - 35_000
    assert later["refunded_clp"] == before["refunded_clp"]
    assert later["corrected_clp"] == before["corrected_clp"] + 35_000


@pg
def test_an_overpaid_payment_is_undone_whole_with_its_credit_reverted(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    owed_before = balance(db, membership)
    paid = pay(client, gym, membership, oldest["id"], 50_000)
    credit = paid["credit"]
    assert credit["amount_clp"] == 5_000

    recorded = ok(undo(client, gym, paid["payment"]["id"]), 201)
    assert recorded["void"]["amount_clp"] == 50_000
    reverted = recorded["reverted"]
    assert (reverted["kind"], reverted["amount_clp"], reverted["purpose"]) == (
        "adjustment",
        -5_000,
        "revert",
    )
    assert (reverted["corrects"], reverted["billing_period_id"]) == (credit["id"], None)
    assert recorded["period"]["outstanding_clp"] == 45_000
    assert balance(db, membership) == owed_before
    row = audit_rows(db, gym, person)[-1]
    assert row["detail"]["entry_ids"] == [recorded["void"]["id"], reverted["id"]]
    # The student sees the credit taken back, never why.
    mine = ok(client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person))))["payments"]
    [shown] = [p for p in mine if p["id"] == reverted["id"]]
    assert (shown["purpose"], shown["amount_clp"], shown["note"]) == ("revert", -5_000, None)


@pg
def test_a_cobro_line_payment_is_undone_and_the_line_owed_again(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, gym, "Ana")
    emailed(db, gym, ana, "ana@example.cl")
    charge = create(client, gym, draft([ana], amount_clp=25_000))
    line = line_of(charge, ana)["id"]
    paid = ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/payments",
            json={"amount_clp": 25_000, "method": "cash"},
            headers=as_gym(gym),
        ),
        201,
    )
    before = kpis(client, gym)

    mailer.sent.clear()
    recorded = ok(undo(client, gym, paid["payment"]["id"]), 201)
    entry = recorded["void"]
    assert (entry["extra_line_id"], entry["membership_id"], entry["purpose"]) == (
        line,
        None,
        "mistake",
    )
    assert recorded["period"] == {
        "id": line,
        "amount_due_clp": 25_000,
        "paid_clp": 0,
        "outstanding_clp": 25_000,
        "closed": False,
    }
    owed = line_of(ok(client.get(f"/api/extra-charges/{charge['id']}", headers=as_gym(gym))), ana)
    assert (owed["status"], owed["outstanding_clp"]) == ("open", 25_000)
    later = kpis(client, gym)
    assert later["collected_extra_clp"] == before["collected_extra_clp"] - 25_000
    assert later["refunded_clp"] == before["refunded_clp"]

    row = audit_rows(db, gym, ana)[-1]
    assert (row["detail"]["purpose"], row["detail"]["extra_line_id"]) == ("mistake", line)
    assert row["detail"]["after"]["outstanding_clp"] == 25_000

    [email] = mailer.sent
    assert email.to == "ana@example.cl"
    assert "por Rifa de fin de año se anuló: fue un error de registro." in email.text
    assert "De este cobro quedan $25.000 por pagar." in email.text


@pg
def test_a_dependents_correction_goes_to_their_guardian(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    marta = enrolled(client, gym, name="Marta", email=f"marta-{uuid.uuid4().hex[:6]}@example.cl")
    started_on = (seeded_today() - timedelta(days=10)).isoformat()
    kid = enrolled(
        client,
        gym,
        name="Tomás",
        guardian={"person_id": marta["id"]},
        membership={"plan_id": plan(client, gym), "started_on": started_on},
    )
    [membership] = memberships(client, gym, kid["id"])
    period = ledger(client, gym, membership["id"])["open_periods"][0]
    payment = pay(client, gym, membership["id"], period["id"], 45_000)["payment"]

    mailer.sent.clear()
    ok(undo(client, gym, payment["id"]), 201)
    [email] = mailer.sent
    assert email.to == marta["email"]
    assert "El pago de $45.000 de Tomás del " in email.text


@pg
def test_only_a_validated_payment_of_no_correction_is_undone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    pending_proof(db, gym, person, membership, oldest["id"])
    [proof] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT id FROM ledger_entry WHERE membership_id = $1 AND status = 'pending'",
            uuid.UUID(membership),
        ),
    )
    refused = undo(client, gym, str(proof["id"]))
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_validated"
    assert undo(client, gym, str(uuid.uuid4())).status_code == 404

    # A reason is required.
    payment = pay(client, gym, membership, oldest["id"], 45_000)["payment"]
    blank = client.post(
        "/api/ledger/payment-voids",
        json={"payment_id": payment["id"], "reason": "  "},
        headers=as_gym(gym),
    )
    assert blank.status_code == 422


@pg
def test_a_coach_cannot_undo_a_payment(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    _, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    payment = pay(client, gym, membership, oldest["id"], 45_000)["payment"]
    coach = add_staff(db, gym, "coach")
    assert undo(client, gym, payment["id"], person_id=coach).status_code == 403


@pg
def test_a_person_whose_only_payment_was_undone_can_be_deleted(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    oldest = ledger(client, gym, membership)["open_periods"][0]
    payment = pay(client, gym, membership, oldest["id"], 45_000)["payment"]
    refused = ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym)))
    assert refused == {"refused": "payment", "amount_clp": 45_000}

    ok(undo(client, gym, payment["id"]), 201)
    # What they owe stands in the way, as for anyone; a test person's plan is voided.
    ok(void_plan(client, gym, membership))
    assert forget(client, gym, person, reason="era de prueba").status_code == 204
    assert client.get(f"/api/people/{person}", headers=as_gym(gym)).status_code == 404


@pg
def test_a_payment_validated_with_another_of_its_membership_takes_no_credit(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """The credit is found by the transaction that wrote it (`CARRIED_CREDIT`): paying
    ahead validates several payments in one, and carries none, and a credit beside two
    payments of one instant is matched to neither."""
    _, membership = member(client, gym, days_ago=0)
    ledger_now = ledger(client, gym, membership)
    for period in ledger_now["open_periods"]:
        pay(client, gym, membership, period["id"], period["outstanding_clp"])
    quote = ok(client.get(f"/api/ledger/memberships/{membership}/ahead", headers=as_gym(gym)))
    two = quote["periods"][:2]
    ahead = ok(
        client.post(
            "/api/ledger/payments/ahead",
            json={
                "membership_id": membership,
                "periods": 2,
                "amount_clp": sum(p["amount_due_clp"] for p in two),
                "method": "cash",
            },
            headers=as_gym(gym),
        ),
        201,
    )
    payments = ahead["payments"]
    assert len(payments) == 2 and payments[0]["validated_at"] == payments[1]["validated_at"]
    credits = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM ledger_entry WHERE membership_id = $1 AND kind = 'adjustment'"
            " AND billing_period_id IS NULL"
            " AND created_at = (SELECT validated_at FROM ledger_entry WHERE id = $2)",
            uuid.UUID(membership),
            uuid.UUID(payments[0]["id"]),
        ),
    )
    assert credits == 0

    # A credit written beside both (no path does) is reverted with neither.
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, status,"
            " validated_by, validated_at, created_at, note)"
            " SELECT gym_id, membership_id, 1000, 'adjustment', 'validated', validated_by,"
            " validated_at, validated_at, 'x' FROM ledger_entry WHERE id = $1",
            uuid.UUID(payments[0]["id"]),
        ),
    )
    recorded = ok(undo(client, gym, payments[0]["id"]), 201)
    assert recorded["reverted"] is None


@pg
def test_the_database_holds_a_mistake_to_its_payment_and_to_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    periods = ledger(client, gym, membership)["open_periods"]
    first = pay(client, gym, membership, periods[0]["id"], 45_000)["payment"]
    second = pay(client, gym, membership, periods[1]["id"], 45_000)["payment"]

    def insert(refund_of: str, corrects: str, period: str) -> str:
        return (
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, note, refund_of, corrects, purpose, validated_by, validated_at)"
            f" VALUES (current_setting('app.gym_id')::uuid, '{membership}', '{period}', 1,"
            f" 'refund', 'validated', 'x', '{refund_of}', '{corrects}', 'mistake',"
            " current_setting('app.person_id')::uuid, now())"
        )

    owner = seeded_owner(gym)
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.api_url,
            in_gym(gym, insert(first["id"], second["id"], periods[0]["id"]), person=owner),
        )
    run(db.api_url, in_gym(gym, insert(first["id"], first["id"], periods[0]["id"]), person=owner))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(
            db.api_url,
            in_gym(gym, insert(first["id"], first["id"], periods[0]["id"]), person=owner),
        )


def test_upgrade_and_downgrade_0087() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0086")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0086")
        migrate(scratch)


def test_the_export_lists_a_payment_undone_apart_from_refunds() -> None:
    day = seeded_today()

    def row(kind: str, amount: int) -> ledger_export.Row:
        return ledger_export.Row(
            day=day,
            member="Ana",
            rut=None,
            concept="Mensual",
            period=None,
            kind=kind,
            method=None,
            amount_clp=amount,
            status=ledger_export.STATUSES["validated"],
            bank_ref=None,
            note=None,
        )

    label = ledger_export.kind_label("refund", voids=False, purpose="mistake")
    reverted = ledger_export.kind_label("adjustment", False, "revert", on_period=False)
    assert reverted == "Ajuste por pago anulado"
    # A revert on a period is not a credit's (#282): a plain adjustment here.
    assert ledger_export.kind_label("adjustment", False, "revert", on_period=True) == "Ajuste"
    totals = ledger_export.totals(
        [
            row("Pago", 45_000),
            row("Devolución", 5_000),
            row(label, 40_000),
            row("Ajuste", 3_000),
            row(reverted, -3_000),
        ],
        0,
    )
    lines = dict(ledger_export.total_lines(totals))
    # The revert cancels the credit it reverts in "Total ajustado".
    assert lines["Total ajustado (a favor +, en contra -)"] == 0
    assert lines["Total devuelto"] == 5_000
    assert lines["Total pagos anulados (error de registro)"] == 40_000
    assert lines["Cobrado neto (pagado menos devuelto y anulado)"] == 0
