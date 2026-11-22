"""Pagado hasta… (#286): the payments or gifts up to a date, for a member who paid
before the gym used Rakin.

Every period starting on or before the date is settled, those billed first, then those
it bills as paying ahead does, each with a payment ("Pagado antes de Rakin") or a gift
("Bonificación"), in one transaction with an audit row each. "Pagado hasta" then reads
the date, the payments count in this month's Cobrado, and no receipt is emailed.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import ledger_export
from app.domain.billing import (
    Billable,
    Plan,
    periods_through,
)
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, seed_gym, seeded_today, throwaway_database
from tests.test_corrections import corrections
from tests.test_finances import cobrado
from tests.test_pay_ahead import (
    PACK,
    enrol,
    ledger,
    month_span,
    ok,
    pay,
    run_billing,
    spans,
)
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer
from tests.test_voids import pending_proof

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
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("academia-sur"))


# --- the domain, no database ------------------------------------------------------

MONTHLY_PLAN = Plan(PlanTerms(PlanKind.MONTHLY, None, None, None, None, None), 45_000)


def billable(started_on: date, billed_through: date | None = None) -> Billable:
    return Billable(
        plan=MONTHLY_PLAN,
        status=MembershipStatus.ACTIVE,
        started_on=started_on,
        billed_through=billed_through,
        anchor_day=started_on.day,
    )


def test_the_periods_through_a_date_include_the_one_it_falls_in() -> None:
    owed = periods_through(billable(date(2026, 1, 5)), date(2026, 3, 10), 12)

    assert [(p.period_start, p.period_end) for p in owed.periods] == [
        (date(2026, 1, 5), date(2026, 2, 4)),
        (date(2026, 2, 5), date(2026, 3, 4)),
        (date(2026, 3, 5), date(2026, 4, 4)),
    ]


def test_the_periods_through_a_date_start_after_the_last_one_billed() -> None:
    owed = periods_through(billable(date(2026, 1, 5), date(2026, 2, 4)), date(2026, 2, 5), 12)

    assert [p.period_start for p in owed.periods] == [date(2026, 2, 5)]


def test_the_periods_through_a_date_stop_at_the_limit() -> None:
    owed = periods_through(billable(date(2026, 1, 5)), date(2027, 12, 31), 3)

    assert len(owed.periods) == 3


def test_a_pack_has_no_periods_through_a_date() -> None:
    pack = Plan(PlanTerms(PlanKind.CREDITS, None, 12, 60, None, None), 60_000)
    owed = periods_through(
        Billable(plan=pack, status=MembershipStatus.ACTIVE, started_on=date(2026, 1, 5)),
        date(2026, 6, 1),
        12,
    )

    assert owed.periods == ()


# --- the API ----------------------------------------------------------------------


def url(membership: str) -> str:
    return f"/api/ledger/memberships/{membership}/paid-through"


def quote(client: TestClient, gym: uuid.UUID, membership: str, through: str) -> Any:
    return client.get(url(membership), params={"through": through}, headers=as_gym(gym))


def settle(
    client: TestClient,
    gym: uuid.UUID,
    membership: str,
    through: str,
    mode: str = "paid",
    **body: Any,
) -> Any:
    total = ok(quote(client, gym, membership, through))["total_clp"]
    payload = {"through": through, "mode": mode, "total_clp": total, **body}
    if mode == "paid":
        payload.setdefault("method", "transfer")
    return client.post(url(membership), json=payload, headers=as_gym(gym))


def this_month(client: TestClient, gym: uuid.UUID) -> Any:
    """Resumen del mes for the current month."""
    return ok(client.get("/api/summary", headers=as_gym(gym)))


def refused(response: Any, code: str) -> Any:
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    return detail


def back_dated(client: TestClient, gym: uuid.UUID, months: int = 3) -> tuple[str, str, date]:
    """A member whose plan started `months` months ago, every period since billed and
    owing; their person, membership, and the start."""
    start = seeded_today() - timedelta(days=31 * months)
    person, membership = enrol(client, gym, started_on=start.isoformat())
    return person, membership, start


@pg
def test_paid_up_to_a_date_reads_that_date_and_is_no_income_of_the_month(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    person, membership, start = back_dated(client, sur)
    billed = ledger(client, sur, membership)["open_periods"]
    assert len(billed) >= 3
    # Every period billed, and two more not billed yet.
    through = month_span(start, len(billed) + 1)[1]
    before = cobrado(client, sur)
    month_before = this_month(client, sur)
    sent = len(mailer.sent)

    found = ok(quote(client, sur, membership, through))
    assert [p["billed"] for p in found["periods"]] == [True] * len(billed) + [False, False]
    assert found["total_clp"] == 45_000 * (len(billed) + 2)
    assert found["paid_through"] == through

    recorded = ok(settle(client, sur, membership, through, method="cash"), 201)

    assert recorded["paid_through"] == through
    assert {(e["kind"], e["amount_clp"], e["note"], e["purpose"]) for e in recorded["entries"]} == {
        ("payment", 45_000, "Pagado antes de Rakin", "paid_before")
    }
    after = ledger(client, sur, membership)
    assert after["paid_through"] == through
    assert after["open_periods"] == []
    # The period reads paid, but that money was not received this month (0093).
    assert all(p["outstanding_clp"] == 0 and p["closed"] for p in recorded["periods"])
    assert after["balance_clp"] == 0
    kpis = cobrado(client, sur)
    assert (kpis["collected_clp"], kpis["collected_payments"]) == (
        before["collected_clp"],
        before["collected_payments"],
    )
    month = this_month(client, sur)
    assert (month["income_clp"], month["income_payments"]) == (
        month_before["income_clp"],
        month_before["income_payments"],
    )
    # The money arrived long ago: no receipt.
    assert len(mailer.sent) == sent
    rows = ok(corrections(client, sur, person))["items"]
    assert len(rows) == len(billed) + 2
    assert {(r["action"], r["purpose"], r["paid_through"], r["reason"]) for r in rows} == {
        ("ledger_corrected", "paid_before", "paid", "Pagado antes de Rakin")
    }
    assert all(r["after"]["outstanding_clp"] == 0 for r in rows)


@pg
def test_a_month_paid_before_rakin_undone_is_still_no_income(
    client: TestClient, sur: uuid.UUID
) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    recorded = ok(settle(client, sur, membership, month_span(start, 0)[1]), 201)
    before = cobrado(client, sur)

    undone = client.post(
        "/api/ledger/payment-voids",
        json={"payment_id": recorded["entries"][0]["id"], "reason": "no era de este alumno"},
        headers=as_gym(sur),
    )

    ok(undone, 201)
    kpis = cobrado(client, sur)
    assert (kpis["collected_clp"], kpis["corrected_clp"], kpis["refunded_clp"]) == (
        before["collected_clp"],
        before["corrected_clp"],
        before["refunded_clp"],
    )
    assert ledger(client, sur, membership)["open_periods"] != []


@pg
def test_given_up_to_a_date_is_a_bonificacion_and_no_income(
    client: TestClient, sur: uuid.UUID
) -> None:
    person, membership, start = back_dated(client, sur, months=1)
    through = month_span(start, 2)[1]
    before = cobrado(client, sur)["collected_clp"]

    recorded = ok(settle(client, sur, membership, through, mode="gift"), 201)

    assert {(e["kind"], e["note"]) for e in recorded["entries"]} == {("adjustment", "Bonificación")}
    assert ledger(client, sur, membership)["paid_through"] == through
    assert cobrado(client, sur)["collected_clp"] == before
    rows = ok(corrections(client, sur, person))["items"]
    assert {r["paid_through"] for r in rows} == {"gift"}


@pg
def test_a_date_inside_a_period_settles_all_of_it(client: TestClient, sur: uuid.UUID) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    inside = (date.fromisoformat(month_span(start, 2)[0]) + timedelta(days=3)).isoformat()

    recorded = ok(settle(client, sur, membership, inside), 201)

    assert recorded["paid_through"] == month_span(start, 2)[1]


@pg
def test_a_period_paid_in_part_is_settled_for_the_rest(client: TestClient, sur: uuid.UUID) -> None:
    _, membership, _ = back_dated(client, sur, months=1)
    oldest = ledger(client, sur, membership)["open_periods"][0]
    pay(client, sur, membership, {**oldest, "outstanding_clp": 20_000})

    found = ok(quote(client, sur, membership, oldest["period_end"]))

    assert [p["amount_clp"] for p in found["periods"]] == [25_000]
    recorded = ok(settle(client, sur, membership, oldest["period_end"]), 201)
    assert [e["amount_clp"] for e in recorded["entries"]] == [25_000]


@pg
def test_the_nightly_job_bills_on_after_them(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    through = month_span(start, 3)[1]
    ok(settle(client, sur, membership, through), 201)

    run_billing(db, date.fromisoformat(through))

    periods = spans(ledger(client, sur, membership))
    assert periods[-1][:2] == month_span(start, 4)
    assert periods[-1][2] == 45_000
    assert ledger(client, sur, membership)["paid_through"] == through


@pg
def test_a_date_before_the_plan_started_belongs_in_the_history(
    client: TestClient, sur: uuid.UUID
) -> None:
    _, membership, start = back_dated(client, sur, months=1)

    detail = refused(
        quote(client, sur, membership, (start - timedelta(days=1)).isoformat()), "before_plan"
    )

    assert detail["started_on"] == start.isoformat()


@pg
def test_a_date_paid_through_already_is_refused(client: TestClient, sur: uuid.UUID) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    through = month_span(start, 2)[1]
    ok(settle(client, sur, membership, through), 201)

    detail = refused(quote(client, sur, membership, month_span(start, 1)[1]), "already_paid")

    assert detail["paid_through"] == through


@pg
def test_a_date_too_far_ahead_is_refused(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = enrol(client, sur)

    far = month_span(seeded_today(), 13)[1]
    refused(quote(client, sur, membership, far), "too_far")


@pg
def test_a_total_not_the_quoted_one_is_refused(client: TestClient, sur: uuid.UUID) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    body = {"through": month_span(start, 1)[1], "mode": "paid", "method": "cash", "total_clp": 1}

    refused(client.post(url(membership), json=body, headers=as_gym(sur)), "amount_changed")

    assert ledger(client, sur, membership)["paid_through"] is None


@pg
def test_a_payment_needs_its_method(client: TestClient, sur: uuid.UUID) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    body = {"through": month_span(start, 0)[1], "mode": "paid", "total_clp": 45_000}

    assert client.post(url(membership), json=body, headers=as_gym(sur)).status_code == 422


@pg
def test_a_proof_waiting_on_a_period_is_reviewed_first(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    person, membership, start = back_dated(client, sur, months=1)
    oldest = ledger(client, sur, membership)["open_periods"][0]
    pending_proof(db, sur, person, membership, oldest["id"])

    refused(quote(client, sur, membership, month_span(start, 1)[1]), "pending")


@pg
def test_a_pack_is_not_paid_up_to_a_date(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = enrol(client, sur, PACK)

    refused(quote(client, sur, membership, month_span(seeded_today(), 1)[1]), "cannot")


@pg
def test_a_coach_cannot_settle_up_to_a_date(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    _, membership, start = back_dated(client, sur, months=1)
    body = {"through": month_span(start, 1)[1], "mode": "gift", "total_clp": 90_000}
    coach = add_staff(db, sur, "coach")

    response = client.post(url(membership), json=body, headers=as_gym(sur, coach))

    assert response.status_code == 403


def test_the_export_labels_a_month_paid_before_rakin_apart_from_the_payments() -> None:
    label = ledger_export.kind_label("payment", False, "paid_before")
    assert label == "Pagado antes de Rakin"
    row = ledger_export.Row(
        day=date(2026, 11, 22),
        member="Socia Ejemplo",
        rut=None,
        concept="Mensual",
        period=(date(2026, 9, 1), date(2026, 9, 30)),
        kind=label,
        method="Efectivo",
        amount_clp=45_000,
        status="Validado",
        bank_ref=None,
        note="Pagado antes de Rakin",
    )
    # Not money received in the month: in no total, as a payment moved is in none.
    assert ledger_export.totals([row], 0).paid_clp == 0
