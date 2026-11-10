"""An admin corrects the ledger with new entries (#38): an adjustment (+/-) to what a
billing period owes, with a note saying why, and a refund of a validated payment.

An adjustment in the member's favour counts towards its period as a payment does, up
to what the period still owes; one against them is owed on top, and opens a period
that was paid. A refund names its payment, gives back no more than is left of it, and
no longer counts towards the payment's period, which opens again if it falls short.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.main import create_app
from app.schemas.ledger import AdjustmentRecord, RefundRecord
from app.schemas.plans import MAX_PRICE_CLP
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_ledger_payments import entries, new_period, record
from tests.test_plans import add_staff

IDS = {"membership_id": str(uuid.uuid4()), "billing_period_id": str(uuid.uuid4())}
ADJUSTMENT: dict[str, Any] = {**IDS, "amount_clp": -5_000, "note": "matrícula"}
REFUND: dict[str, Any] = {"payment_id": str(uuid.uuid4()), "amount_clp": 5_000, "method": "cash"}

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize("amount", [-MAX_PRICE_CLP, -1, 1, MAX_PRICE_CLP])
def test_an_adjustment_goes_either_way(amount: int) -> None:
    assert AdjustmentRecord.model_validate({**ADJUSTMENT, "amount_clp": amount}).amount_clp == (
        amount
    )


@pytest.mark.parametrize(
    "body",
    [
        {**ADJUSTMENT, "amount_clp": 0},
        {**ADJUSTMENT, "amount_clp": MAX_PRICE_CLP + 1},
        {**ADJUSTMENT, "amount_clp": -MAX_PRICE_CLP - 1},
        {**ADJUSTMENT, "note": "   "},
        {**ADJUSTMENT, "note": None},
        {k: v for k, v in ADJUSTMENT.items() if k != "note"},
        {k: v for k, v in ADJUSTMENT.items() if k != "billing_period_id"},
        {**ADJUSTMENT, "method": "cash"},
    ],
    ids=str,
)
def test_an_adjustment_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AdjustmentRecord.model_validate(body)


@pytest.mark.parametrize(
    "body",
    [
        {**REFUND, "amount_clp": 0},
        {**REFUND, "amount_clp": -5_000},
        {**REFUND, "amount_clp": MAX_PRICE_CLP + 1},
        {**REFUND, "method": "card"},
        {k: v for k, v in REFUND.items() if k != "method"},
        {k: v for k, v in REFUND.items() if k != "payment_id"},
        {**REFUND, "note": "  "},
        {**REFUND, "billing_period_id": str(uuid.uuid4())},
    ],
    ids=str,
)
def test_a_refund_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RefundRecord.model_validate(body)


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


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
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def adjust(client: TestClient, gym: uuid.UUID, body: dict[str, Any], **kw: Any) -> Any:
    return client.post("/api/ledger/adjustments", json=body, headers=as_gym(gym, **kw))


def refund(client: TestClient, gym: uuid.UUID, body: dict[str, Any], **kw: Any) -> Any:
    return client.post("/api/ledger/refunds", json=body, headers=as_gym(gym, **kw))


def pay(client: TestClient, gym: uuid.UUID, period: dict[str, str], amount: int) -> str:
    response = record(client, gym, {**period, "amount_clp": amount, "method": "transfer"})
    assert response.status_code == 201, response.text
    payment_id: str = response.json()["payment"]["id"]
    return payment_id


def charged(db: Database, gym: uuid.UUID, due: int = 45_000) -> dict[str, str]:
    """`new_period`, with the validated charge the billing job writes for it."""
    period = new_period(db, gym, due=due)
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, validated_at) VALUES ($1, $2, $3, $4, 'charge', 'validated', now())",
            gym,
            uuid.UUID(period["membership_id"]),
            uuid.UUID(period["billing_period_id"]),
            due,
        ),
    )
    return period


def balance(db: Database, period: dict[str, str]) -> int:
    """The membership's `v_balance`: owed if positive, credit if not."""
    value: int = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT coalesce(sum(balance_clp), 0) FROM v_balance WHERE membership_id = $1",
            uuid.UUID(period["membership_id"]),
        ),
    )
    return value


def ledger(client: TestClient, gym: uuid.UUID, period: dict[str, str]) -> dict[str, Any]:
    response = client.get(f"/api/ledger/memberships/{period['membership_id']}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def open_period(client: TestClient, gym: uuid.UUID, period: dict[str, str]) -> Any:
    found = [p for p in ledger(client, gym, period)["open_periods"]]
    return next((p for p in found if p["id"] == period["billing_period_id"]), None)


# --- adjustments ------------------------------------------------------------------


@pg
def test_an_adjustment_in_the_members_favour_counts_towards_the_period(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    admin = add_staff(db, sur, "admin")
    period = charged(db, sur)
    response = adjust(
        client, sur, {**period, "amount_clp": 5_000, "note": "descuento hermano"}, person_id=admin
    )
    assert response.status_code == 201, response.text
    body = response.json()

    entry = body["adjustment"]
    assert (entry["kind"], entry["status"], entry["amount_clp"]) == (
        "adjustment",
        "validated",
        5_000,
    )
    assert entry["note"] == "descuento hermano"
    assert entry["billing_period_id"] == period["billing_period_id"]
    assert entry["method"] is None and entry["refund_of"] is None
    assert entry["claimed_by"] == entry["validated_by"] == str(admin)
    assert body["period"] == {
        "id": period["billing_period_id"],
        "amount_due_clp": 45_000,
        "paid_clp": 5_000,
        "outstanding_clp": 40_000,
        "closed": False,
    }
    assert open_period(client, sur, period)["outstanding_clp"] == 40_000
    assert balance(db, period) == 40_000

    # The rest is paid as usual, and the period closes.
    pay(client, sur, period, 40_000)
    assert open_period(client, sur, period) is None


@pg
def test_an_adjustment_in_the_members_favour_closes_what_it_covers_and_no_more(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur, due=45_000)
    pay(client, sur, period, 30_000)

    over = adjust(client, sur, {**period, "amount_clp": 15_001, "note": "beca"})
    assert over.status_code == 409
    exact = adjust(client, sur, {**period, "amount_clp": 15_000, "note": "beca"})
    assert exact.status_code == 201, exact.text
    assert exact.json()["period"]["closed"] is True
    assert adjust(client, sur, {**period, "amount_clp": 1, "note": "beca"}).status_code == 409
    assert [r["kind"] for r in entries(db, period)] == ["payment", "adjustment"]


@pg
def test_an_adjustment_against_the_member_is_owed_on_top_and_opens_a_paid_period(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = charged(db, sur)
    pay(client, sur, period, 45_000)
    assert open_period(client, sur, period) is None

    response = adjust(client, sur, {**period, "amount_clp": -5_000, "note": "matrícula"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["adjustment"]["amount_clp"] == -5_000
    assert body["period"] | {"id": None} == {
        "id": None,
        "amount_due_clp": 45_000,
        "paid_clp": 40_000,
        "outstanding_clp": 5_000,
        "closed": False,
    }
    assert open_period(client, sur, period)["outstanding_clp"] == 5_000
    assert balance(db, period) == 5_000

    # A payment of what it adds closes the period again, with no credit.
    paid = record(client, sur, {**period, "amount_clp": 5_000, "method": "cash"})
    assert paid.status_code == 201, paid.text
    assert paid.json()["period"]["closed"] is True
    assert paid.json()["credit"] is None


@pg
def test_an_adjustment_against_the_member_can_exceed_the_amount_due(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur, due=45_000)
    response = adjust(client, sur, {**period, "amount_clp": -10_000, "note": "uniforme"})
    assert response.status_code == 201, response.text
    assert response.json()["period"]["outstanding_clp"] == 55_000
    assert open_period(client, sur, period)["outstanding_clp"] == 55_000

    # A payment of the amount due leaves the adjustment owed.
    paid = record(client, sur, {**period, "amount_clp": 45_000, "method": "cash"})
    assert paid.json()["period"]["outstanding_clp"] == 10_000


@pg
def test_an_adjustment_needs_a_note(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    period = new_period(db, sur)
    assert adjust(client, sur, {**period, "amount_clp": -5_000}).status_code == 422
    assert adjust(client, sur, {**period, "amount_clp": -5_000, "note": " "}).status_code == 422
    assert entries(db, period) == []


@pg
def test_an_adjustment_to_another_gyms_period_is_not_found(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    theirs = new_period(db, norte)
    assert adjust(client, sur, {**theirs, "amount_clp": -5_000, "note": "x"}).status_code == 404
    assert entries(db, theirs) == []


@pg
@pytest.mark.parametrize("role", ["coach", "member"])
def test_only_an_owner_or_admin_adjusts_or_refunds(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    period = new_period(db, sur)
    payment = pay(client, sur, period, 45_000)
    person = add_staff(db, sur, "coach") if role == "coach" else uuid.uuid4()

    body = {**period, "amount_clp": -5_000, "note": "x"}
    assert adjust(client, sur, body, person_id=person).status_code == 403
    body = {"payment_id": payment, "amount_clp": 5_000, "method": "cash"}
    assert refund(client, sur, body, person_id=person).status_code == 403
    assert [r["kind"] for r in entries(db, period)] == ["payment"]


# --- refunds ----------------------------------------------------------------------


@pg
def test_a_refund_references_its_payment_and_opens_the_period_again(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    admin = add_staff(db, sur, "admin")
    period = charged(db, sur)
    payment = pay(client, sur, period, 45_000)

    response = refund(
        client,
        sur,
        {"payment_id": payment, "amount_clp": 15_000, "method": "transfer", "note": "se lesionó"},
        person_id=admin,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    entry = body["refund"]
    assert (entry["kind"], entry["status"], entry["amount_clp"]) == ("refund", "validated", 15_000)
    assert entry["refund_of"] == payment
    assert entry["billing_period_id"] == period["billing_period_id"]
    assert (entry["method"], entry["note"]) == ("transfer", "se lesionó")
    assert entry["validated_by"] == str(admin)
    assert body["period"] | {"id": None} == {
        "id": None,
        "amount_due_clp": 45_000,
        "paid_clp": 30_000,
        "outstanding_clp": 15_000,
        "closed": False,
    }
    assert open_period(client, sur, period)["outstanding_clp"] == 15_000
    assert balance(db, period) == 15_000

    # The member detail lists it with its payment, and what is left to give back.
    read = ledger(client, sur, period)
    lines = {e["id"]: e for e in read["entries"]}
    assert lines[entry["id"]]["refund_of"] == payment
    assert [(p["id"], p["refundable_clp"]) for p in read["refundable_payments"]] == [
        (payment, 30_000)
    ]


@pg
def test_a_refund_of_an_overpayment_leaves_the_period_paid(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = charged(db, sur)
    payment = pay(client, sur, period, 50_000)
    assert balance(db, period) == -5_000

    response = refund(client, sur, {"payment_id": payment, "amount_clp": 5_000, "method": "cash"})
    assert response.status_code == 201, response.text
    assert response.json()["period"]["closed"] is True
    assert open_period(client, sur, period) is None
    assert balance(db, period) == 0


@pg
def test_a_refund_gives_back_no_more_than_is_left_of_its_payment(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = charged(db, sur)
    payment = pay(client, sur, period, 45_000)
    body = {"payment_id": payment, "method": "cash"}

    assert refund(client, sur, {**body, "amount_clp": 45_001}).status_code == 409
    assert refund(client, sur, {**body, "amount_clp": 40_000}).status_code == 201
    assert refund(client, sur, {**body, "amount_clp": 5_001}).status_code == 409
    assert refund(client, sur, {**body, "amount_clp": 5_000}).status_code == 201
    assert refund(client, sur, {**body, "amount_clp": 1}).status_code == 409
    assert open_period(client, sur, period)["outstanding_clp"] == 45_000
    assert balance(db, period) == 45_000
    # Given back in full, it is no longer offered.
    assert ledger(client, sur, period)["refundable_payments"] == []


@pg
def test_the_ledger_offers_every_period_and_refundable_payment_however_old(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # The timeline lists the latest 100 entries; what Ajuste and Devolver offer is not
    # cut to them.
    old = charged(db, sur)
    payment = pay(client, sur, old, 45_000)
    for _ in range(55):
        later = charged(db, sur)
        pay(client, sur, later, 45_000)
    owing = charged(db, sur)

    read = ledger(client, sur, old)
    assert len(read["entries"]) == 100
    assert payment not in {e["id"] for e in read["entries"]}

    # Newest first, with the seeded gym's own period among them.
    periods = read["periods"]
    assert len(periods) == 58
    assert [p["period_start"] for p in periods] == sorted(
        (p["period_start"] for p in periods), reverse=True
    )
    assert periods[0] == {
        "id": owing["billing_period_id"],
        "period_start": periods[0]["period_start"],
        "period_end": periods[0]["period_end"],
        "outstanding_clp": 45_000,
    }
    [first] = [p for p in periods if p["id"] == old["billing_period_id"]]
    assert first["outstanding_clp"] == 0
    assert len(read["refundable_payments"]) == 56
    oldest = read["refundable_payments"][-1]
    assert oldest | {"validated_at": None} == {
        "id": payment,
        "billing_period_id": old["billing_period_id"],
        "period_start": first["period_start"],
        "amount_clp": 45_000,
        "method": "transfer",
        "validated_at": None,
        "refundable_clp": 45_000,
    }


@pg
def test_only_a_validated_payment_is_refunded(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur, due=45_000)

    async def pending(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, method) VALUES ($1, $2, $3, 45000, 'payment', 'pending', 'transfer')"
            " RETURNING id",
            sur,
            uuid.UUID(period["membership_id"]),
            uuid.UUID(period["billing_period_id"]),
        )

    claim = str(run(db.admin_url, pending))
    body = {"payment_id": claim, "amount_clp": 5_000, "method": "cash"}
    assert refund(client, sur, body).status_code == 409

    credit = adjust(client, sur, {**period, "amount_clp": 5_000, "note": "beca"}).json()
    body = {"payment_id": credit["adjustment"]["id"], "amount_clp": 5_000, "method": "cash"}
    assert refund(client, sur, body).status_code == 404
    body = {"payment_id": str(uuid.uuid4()), "amount_clp": 5_000, "method": "cash"}
    assert refund(client, sur, body).status_code == 404
    assert [r["kind"] for r in entries(db, period)] == ["payment", "adjustment"]


@pg
def test_another_gyms_payment_is_not_refunded(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    theirs = new_period(db, norte)
    payment = pay(client, norte, theirs, 45_000)
    body = {"payment_id": payment, "amount_clp": 5_000, "method": "cash"}
    assert refund(client, sur, body).status_code == 404
    assert [r["kind"] for r in entries(db, theirs)] == ["payment"]


@pg
def test_the_book_lists_adjustments_and_refunds(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur, due=45_000)
    payment = pay(client, sur, period, 45_000)
    adjust(client, sur, {**period, "amount_clp": -5_000, "note": "matrícula"})
    refund(client, sur, {"payment_id": payment, "amount_clp": 10_000, "method": "cash"})

    response = client.get("/api/ledger/book", headers=as_gym(sur))
    assert response.status_code == 200, response.text
    items = {i["kind"]: i for i in response.json()["items"]}
    assert items["adjustment"]["amount_clp"] == -5_000
    assert items["adjustment"]["note"] == "matrícula"
    assert items["refund"]["refund_of"] == payment
    assert items["payment"]["refund_of"] is None
    # The period owes the adjustment and what was given back.
    assert items["refund"]["period"]["outstanding_clp"] == 15_000


# --- the table on its own (migration 0019) ----------------------------------------


def insert(db: Database, gym: uuid.UUID, period: dict[str, str], **columns: Any) -> Any:
    names = ", ".join(columns)
    values = ", ".join(f"${i + 4}" for i in range(len(columns)))

    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, status,"
            f" {names}) VALUES ($1, $2, $3, 'validated', {values}) RETURNING id",
            gym,
            uuid.UUID(period["membership_id"]),
            uuid.UUID(period["billing_period_id"]),
            *columns.values(),
        )

    return run(db.admin_url, query)


@pg
@pytest.mark.parametrize(
    "columns",
    [
        {"kind": "payment", "amount_clp": -1},
        {"kind": "charge", "amount_clp": 0},
        {"kind": "refund", "amount_clp": -1},
        {"kind": "adjustment", "amount_clp": 0},
        {"kind": "refund", "amount_clp": 1},
    ],
    ids=str,
)
def test_the_table_refuses(db: Database, sur: uuid.UUID, columns: dict[str, Any]) -> None:
    period = new_period(db, sur)
    with pytest.raises(asyncpg.CheckViolationError):
        insert(db, sur, period, **columns)


@pg
def test_the_table_keeps_refund_of_to_refunds_of_the_same_membership(
    db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    payment = insert(db, sur, period, kind="payment", amount_clp=45_000)
    with pytest.raises(asyncpg.CheckViolationError):
        insert(db, sur, period, kind="payment", amount_clp=1, refund_of=payment)

    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    theirs = new_period(db, norte)
    # `ledger_entry_refund_target` runs before the foreign key, and finds no payment on
    # the refund's period.
    with pytest.raises(asyncpg.CheckViolationError, match="validated payment on its period"):
        insert(db, norte, theirs, kind="refund", amount_clp=1, refund_of=payment)

    assert insert(db, sur, period, kind="refund", amount_clp=1, refund_of=payment)


@pg
def test_the_table_refunds_only_a_validated_payment_on_the_refunds_period(
    db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    other = new_period(db, sur)
    payment = insert(db, sur, period, kind="payment", amount_clp=45_000)
    charge = insert(db, sur, period, kind="charge", amount_clp=45_000)
    credit = insert(db, sur, period, kind="adjustment", amount_clp=5_000, note="beca")

    async def pending(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, method) VALUES ($1, $2, $3, 45000, 'payment', 'pending', 'transfer')"
            " RETURNING id",
            sur,
            uuid.UUID(period["membership_id"]),
            uuid.UUID(period["billing_period_id"]),
        )

    claim = run(db.admin_url, pending)
    for target in (charge, credit, claim):
        with pytest.raises(asyncpg.CheckViolationError, match="validated payment"):
            insert(db, sur, period, kind="refund", amount_clp=1, refund_of=target)
    with pytest.raises(asyncpg.CheckViolationError, match="validated payment on its period"):
        insert(db, sur, other, kind="refund", amount_clp=1, refund_of=payment)
    assert insert(db, sur, period, kind="refund", amount_clp=1, refund_of=payment)


@pg
def test_an_overdue_period_counts_a_refund_against_it(db: Database, sur: uuid.UUID) -> None:
    async def past(conn: asyncpg.Connection) -> Any:
        membership = await conn.fetchval("SELECT id FROM membership WHERE gym_id = $1", sur)
        period = await conn.fetchval(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, '2026-01-01', '2026-01-31', 45000, '2026-01-01') RETURNING id",
            sur,
            membership,
        )
        return {"membership_id": str(membership), "billing_period_id": str(period)}

    period = dict(run(db.admin_url, past))
    insert(db, sur, period, kind="charge", amount_clp=45_000)
    payment = insert(db, sur, period, kind="payment", amount_clp=45_000)

    def overdue() -> list[Any]:
        rows = run(
            db.admin_url,
            lambda c: c.fetch(
                "SELECT paid_clp, outstanding_clp FROM v_overdue WHERE billing_period_id = $1",
                uuid.UUID(period["billing_period_id"]),
            ),
        )
        return [tuple(r) for r in rows]

    assert overdue() == []
    insert(db, sur, period, kind="refund", amount_clp=20_000, refund_of=payment)
    assert overdue() == [(25_000, 20_000)]
    insert(db, sur, period, kind="adjustment", amount_clp=-5_000, note="x")
    assert overdue() == [(20_000, 25_000)]


@pg
def test_upgrade_and_downgrade_0019() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0018")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0018")
        migrate(scratch)
