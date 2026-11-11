"""Paying ahead (#196), and paying on the first day.

A membership is billed as it starts, so a member who pays at the desk on their first
day is recorded then, not after the nightly job. An up-to-date member pays the next 1
to 12 periods at once: they are billed on the spot, each paid with a payment of its
own, and the job bills on after them. A plan change waits for them, a freeze moves
them, and a refund of one after a baja is not owed again.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_guardians import add_person
from tests.test_proofs import RecordingMailer

pytestmark = pytest.mark.postgres

MONTHLY = {"kind": "monthly", "name": "Mensual adultos", "price_clp": 45_000, "anchor": "signup"}
CHEAPER = {"kind": "monthly", "name": "Mensual 2x", "price_clp": 30_000, "anchor": "signup"}
PACK = {
    "kind": "credits",
    "name": "Pack 12 clases",
    "price_clp": 60_000,
    "credits": 12,
    "credit_expiry_days": 60,
}


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
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def plan(client: TestClient, gym: uuid.UUID, body: dict[str, Any]) -> str:
    return str(ok(client.post("/api/plans", json=body, headers=as_gym(gym)), 201)["id"])


def enrol(
    client: TestClient, gym: uuid.UUID, body: dict[str, Any] = MONTHLY, **start: Any
) -> tuple[str, str]:
    """A new member started on a new plan of `body`, today unless `start` says; their
    person and membership."""
    person = add_person(client, gym, f"Ana {uuid.uuid4().hex[:6]}")
    created = client.post(
        "/api/memberships",
        json={"person_id": person, "plan_id": plan(client, gym, body), **start},
        headers=as_gym(gym),
    )
    return person, str(ok(created, 201)["id"])


def ledger(client: TestClient, gym: uuid.UUID, membership: str) -> Any:
    return ok(client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym)))


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: dict[str, Any]) -> Any:
    body = {
        "membership_id": membership,
        "billing_period_id": period["id"],
        "amount_clp": period["outstanding_clp"],
        "method": "cash",
    }
    return ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)


def paid_up(client: TestClient, gym: uuid.UUID, **start: Any) -> tuple[str, str]:
    """A member who started today and paid their first month at the desk."""
    person, membership = enrol(client, gym, **start)
    for period in ledger(client, gym, membership)["open_periods"]:
        pay(client, gym, membership, period)
    return person, membership


def quote(client: TestClient, gym: uuid.UUID, membership: str) -> list[dict[str, Any]]:
    url = f"/api/ledger/memberships/{membership}/ahead"
    periods: list[dict[str, Any]] = ok(client.get(url, headers=as_gym(gym)))["periods"]
    return periods


def pay_ahead(
    client: TestClient, gym: uuid.UUID, membership: str, periods: int, **body: Any
) -> Any:
    amount = sum(p["amount_due_clp"] for p in quote(client, gym, membership)[:periods])
    return client.post(
        "/api/ledger/payments/ahead",
        json={
            "membership_id": membership,
            "periods": periods,
            "amount_clp": amount,
            "method": "transfer",
            **body,
        },
        headers=as_gym(gym),
    )


def spans(found: Any) -> list[tuple[str, str, int]]:
    """A ledger's periods, oldest first, with what each still owes."""
    periods = reversed(found["periods"])
    return [(p["period_start"], p["period_end"], p["outstanding_clp"]) for p in periods]


def month_span(start: date, months: int) -> tuple[str, str]:
    return (
        add_months(start, months).isoformat(),
        (add_months(start, months + 1) - timedelta(days=1)).isoformat(),
    )


def run_billing(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            assert await billing.generate_billing_periods(conn, day)

    run(db.owner_url, go)


# --- the first day ----------------------------------------------------------------


def test_a_new_member_owes_their_first_month_on_their_first_day(
    client: TestClient, sur: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership = enrol(client, sur)

    [period] = ledger(client, sur, membership)["open_periods"]

    assert (period["period_start"], period["period_end"]) == month_span(today, 0)
    assert (period["due_date"], period["outstanding_clp"], period["due"]) == (
        today.isoformat(),
        45_000,
        True,
    )
    pay(client, sur, membership, period)
    found = ledger(client, sur, membership)
    assert found["open_periods"] == []
    assert found["paid_through"] == month_span(today, 0)[1]


def test_the_nightly_job_finds_the_first_period_already_billed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    _, membership = enrol(client, sur)

    run_billing(db, seeded_today())

    assert len(ledger(client, sur, membership)["periods"]) == 1


def test_a_pack_is_charged_as_it_starts(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = enrol(client, sur, PACK)

    [period] = ledger(client, sur, membership)["open_periods"]

    assert period["outstanding_clp"] == 60_000


def test_reactivating_on_a_plan_charges_it_at_once(client: TestClient, sur: uuid.UUID) -> None:
    person = add_person(client, sur, "Bruno")
    ok(client.post(f"/api/people/{person}/leave", json={}, headers=as_gym(sur)))
    returned = client.post(
        f"/api/people/{person}/return",
        json={"membership": {"plan_id": plan(client, sur, PACK)}},
        headers=as_gym(sur),
    )
    ok(returned)
    memberships = ok(client.get(f"/api/memberships?person_id={person}", headers=as_gym(sur)))

    [period] = ledger(client, sur, memberships[0]["id"])["open_periods"]

    assert period["outstanding_clp"] == 60_000


def test_a_membership_starting_later_is_billed_when_it_comes_due(
    client: TestClient, sur: uuid.UUID
) -> None:
    later = seeded_today() + timedelta(days=20)

    _, membership = enrol(client, sur, started_on=later.isoformat())

    assert ledger(client, sur, membership)["periods"] == []


# --- paying ahead -----------------------------------------------------------------


def test_the_quote_is_the_next_year_of_periods(client: TestClient, sur: uuid.UUID) -> None:
    today = seeded_today()
    _, membership = paid_up(client, sur)

    periods = quote(client, sur, membership)

    assert [(p["period_start"], p["period_end"]) for p in periods] == [
        month_span(today, n) for n in range(1, 13)
    ]
    assert {p["amount_due_clp"] for p in periods} == {45_000}


def test_paying_three_months_ahead_bills_and_pays_them(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership = paid_up(client, sur)

    recorded = ok(pay_ahead(client, sur, membership, 3, note="en recepción"), 201)

    assert [(p["amount_clp"], p["method"], p["note"]) for p in recorded["payments"]] == [
        (45_000, "transfer", "en recepción")
    ] * 3
    assert all(p["closed"] for p in recorded["periods"])
    assert recorded["paid_through"] == month_span(today, 3)[1]
    found = ledger(client, sur, membership)
    assert found["open_periods"] == []
    assert found["owed_clp"] == 0
    assert found["paid_through"] == month_span(today, 3)[1]
    assert spans(found) == [(*month_span(today, n), 0) for n in range(4)]
    # Nothing left to bill until the lead time reaches the month after.
    run_billing(db, add_months(today, 4) - timedelta(days=8))
    assert len(ledger(client, sur, membership)["periods"]) == 4


def test_the_job_bills_on_after_the_months_paid_ahead(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership = paid_up(client, sur)
    ok(pay_ahead(client, sur, membership, 2), 201)

    run_billing(db, add_months(today, 3) - timedelta(days=7))

    found = ledger(client, sur, membership)
    assert spans(found) == [(*month_span(today, n), 0) for n in range(3)] + [
        (*month_span(today, 3), 45_000)
    ]
    assert found["paid_through"] == month_span(today, 2)[1]


def test_paid_ahead_is_collected_once_on_the_day_it_is_received(
    client: TestClient, sur: uuid.UUID
) -> None:
    month = seeded_today().replace(day=1).isoformat()

    def kpis() -> Any:
        url = f"/api/ledger/book?month={month}"
        return ok(client.get(url, headers=as_gym(sur)))["kpis"]

    _, membership = paid_up(client, sur)
    before = kpis()

    ok(pay_ahead(client, sur, membership, 3), 201)

    after = kpis()
    assert after["collected_clp"] - before["collected_clp"] == 3 * 45_000
    assert after["collected_payments"] - before["collected_payments"] == 3
    # The months ahead fall due in later months: none is this month's.
    assert after["expected_clp"] == before["expected_clp"]


def test_paying_ahead_emails_one_receipt_for_the_whole(
    client: TestClient, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    _, membership = paid_up(client, sur)
    mailer.sent.clear()

    ok(pay_ahead(client, sur, membership, 3), 201)

    [email] = mailer.sent
    assert "validó tu pago de $135.000" in email.text


def test_paying_ahead_waits_for_an_open_period(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = enrol(client, sur)

    assert quote(client, sur, membership) == []
    refused = client.post(
        "/api/ledger/payments/ahead",
        json={"membership_id": membership, "periods": 1, "amount_clp": 45_000, "method": "cash"},
        headers=as_gym(sur),
    )
    assert refused.status_code == 409, refused.text


def test_an_amount_other_than_the_quote_is_refused(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = paid_up(client, sur)

    refused = pay_ahead(client, sur, membership, 2, amount_clp=45_000)

    assert refused.status_code == 409, refused.text
    assert len(ledger(client, sur, membership)["periods"]) == 1


def test_a_pack_does_not_pay_ahead(client: TestClient, sur: uuid.UUID) -> None:
    _, membership = enrol(client, sur, PACK)
    for period in ledger(client, sur, membership)["open_periods"]:
        pay(client, sur, membership, period)

    assert quote(client, sur, membership) == []


def test_another_gyms_membership_is_not_found(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    _, membership = paid_up(client, sur)

    url = f"/api/ledger/memberships/{membership}/ahead"
    assert client.get(url, headers=as_gym(norte)).status_code == 404
    assert pay_ahead_as(client, norte, membership).status_code == 404


def pay_ahead_as(client: TestClient, gym: uuid.UUID, membership: str) -> Any:
    return client.post(
        "/api/ledger/payments/ahead",
        json={"membership_id": membership, "periods": 1, "amount_clp": 45_000, "method": "cash"},
        headers=as_gym(gym),
    )


# --- boundaries -------------------------------------------------------------------


def test_a_plan_change_after_paying_ahead_starts_after_the_months_paid(
    client: TestClient, sur: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership = paid_up(client, sur)
    ok(pay_ahead(client, sur, membership, 2), 201)

    changed = client.post(
        f"/api/memberships/{membership}/plan-change",
        json={"plan_id": plan(client, sur, CHEAPER)},
        headers=as_gym(sur),
    )

    assert ok(changed)["next_plan"]["starts_on"] == month_span(today, 3)[0]
    # What is paid stays paid at the old price; the change prices the next one.
    assert {p[2] for p in spans(ledger(client, sur, membership))} == {0}
    assert quote(client, sur, membership)[0]["amount_due_clp"] == 30_000


def test_a_freeze_from_today_after_paying_ahead_moves_every_month_paid(
    client: TestClient, sur: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership = paid_up(client, sur)
    ok(pay_ahead(client, sur, membership, 2), 201)

    frozen = client.post(
        f"/api/memberships/{membership}/freeze",
        json={"to_date": (today + timedelta(days=10)).isoformat(), "reason": "lesión"},
        headers=as_gym(sur),
    )

    assert ok(frozen)["status"] == "frozen"
    found = ledger(client, sur, membership)
    assert [p[2] for p in spans(found)] == [0, 0, 0]
    assert (
        found["paid_through"]
        == (date.fromisoformat(month_span(today, 2)[1]) + timedelta(days=10)).isoformat()
    )
    assert found["open_periods"] == []


def test_after_a_baja_the_months_paid_ahead_stay_paid_and_nothing_more_is_billed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    today = seeded_today()
    person, membership = paid_up(client, sur)
    ok(pay_ahead(client, sur, membership, 2), 201)

    ok(client.post(f"/api/people/{person}/leave", json={}, headers=as_gym(sur)))
    run_billing(db, add_months(today, 3))

    found = ledger(client, sur, membership)
    assert spans(found) == [(*month_span(today, n), 0) for n in range(3)]
    overdue = ok(client.get("/api/ledger/overdue", headers=as_gym(sur)))
    assert membership not in {p["membership_id"] for p in overdue["periods"]}


def test_refunding_a_month_paid_ahead_after_a_baja_leaves_it_not_owed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    person, membership = paid_up(client, sur)
    paid = ok(pay_ahead(client, sur, membership, 2), 201)
    ok(client.post(f"/api/people/{person}/leave", json={}, headers=as_gym(sur)))
    last = paid["payments"][-1]

    refunded = client.post(
        "/api/ledger/refunds",
        json={"payment_id": last["id"], "amount_clp": 45_000, "method": "transfer"},
        headers=as_gym(sur),
    )

    body = ok(refunded, 201)
    assert body["period"]["closed"]
    assert (body["waived"]["kind"], body["waived"]["amount_clp"]) == ("adjustment", 45_000)
    # Not a debt even once its due date has passed.
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE billing_period SET due_date = due_date - 400 WHERE id = $1",
            uuid.UUID(last["billing_period_id"]),
        ),
    )
    overdue = ok(client.get("/api/ledger/overdue", headers=as_gym(sur)))
    assert membership not in {p["membership_id"] for p in overdue["periods"]}


def test_refunding_a_month_paid_ahead_while_still_a_member_opens_it_again(
    client: TestClient, sur: uuid.UUID
) -> None:
    _, membership = paid_up(client, sur)
    paid = ok(pay_ahead(client, sur, membership, 2), 201)

    refunded = client.post(
        "/api/ledger/refunds",
        json={"payment_id": paid["payments"][-1]["id"], "amount_clp": 45_000, "method": "cash"},
        headers=as_gym(sur),
    )

    body = ok(refunded, 201)
    assert not body["period"]["closed"]
    assert body["waived"] is None
    assert len(ledger(client, sur, membership)["open_periods"]) == 1


# --- the student page -------------------------------------------------------------


def test_the_student_page_says_how_far_they_have_paid(client: TestClient, sur: uuid.UUID) -> None:
    today = seeded_today()
    person, membership = paid_up(client, sur)
    ok(pay_ahead(client, sur, membership, 3), 201)

    page = ok(client.get("/api/me/page", headers=as_gym(sur, uuid.UUID(person))))

    assert page["next_payment"] is None
    assert page["paid_through"] == month_span(today, 3)[1]
