"""An admin records a payment ("Registrar pago", #37): cash, transfer or other, created
validated by that admin against one billing period.

The period settles as validating a proof does: paid in full closes it, a second
payment for it is a 409, and an overpayment leaves a validated credit adjustment.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.db_bootstrap import to_dsn
from app.main import create_app
from app.schemas.ledger import PaymentRecord
from app.schemas.plans import MAX_PRICE_CLP
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer, sent_notices

IDS = {"membership_id": str(uuid.uuid4()), "billing_period_id": str(uuid.uuid4())}
PAYMENT: dict[str, Any] = {"amount_clp": 45_000, "method": "cash"}
BODY: dict[str, Any] = {**IDS, **PAYMENT}

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize("method", ["cash", "transfer", "other"])
def test_each_method_is_accepted(method: str) -> None:
    assert PaymentRecord.model_validate({**BODY, "method": method}).method == method


def test_a_note_is_trimmed() -> None:
    assert PaymentRecord.model_validate({**BODY, "note": "  en recepción "}).note == (
        "en recepción"
    )


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "method": "card"},
        {**BODY, "method": None},
        {k: v for k, v in BODY.items() if k != "method"},
        {**BODY, "amount_clp": 0},
        {**BODY, "amount_clp": -45_000},
        {**BODY, "amount_clp": MAX_PRICE_CLP + 1},
        {**BODY, "amount_clp": 45_000.5},
        {k: v for k, v in BODY.items() if k != "amount_clp"},
        {k: v for k, v in BODY.items() if k != "billing_period_id"},
        {k: v for k, v in BODY.items() if k != "membership_id"},
        {**BODY, "note": "   "},
        {**BODY, "status": "pending"},
        {**BODY, "validated_by": str(uuid.uuid4())},
    ],
    ids=str,
)
def test_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PaymentRecord.model_validate(body)


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
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def new_period(db: Database, gym: uuid.UUID, due: int = 45_000) -> dict[str, str]:
    """A fresh billing period of the gym's seeded membership, nothing paid on it yet."""

    async def query(conn: asyncpg.Connection) -> Any:
        membership = await conn.fetchval("SELECT id FROM membership WHERE gym_id = $1", gym)
        period = await conn.fetchval(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " SELECT $1, $2, d, d + 29, $3, d FROM (SELECT coalesce(max(period_start) + 30,"
            " '2026-12-01') AS d FROM billing_period WHERE membership_id = $2) s RETURNING id",
            gym,
            membership,
            due,
        )
        return {"membership_id": str(membership), "billing_period_id": str(period)}

    # As the superuser, which skips RLS.
    return dict(run(db.admin_url, query))


def record(client: TestClient, gym: uuid.UUID, body: dict[str, Any], **kw: Any) -> Any:
    return client.post("/api/ledger/payments", json=body, headers=as_gym(gym, **kw))


def entries(db: Database, period: dict[str, str]) -> list[dict[str, Any]]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT * FROM ledger_entry WHERE membership_id = $1"
            " AND (billing_period_id = $2 OR billing_period_id IS NULL) AND kind <> 'charge'"
            " ORDER BY created_at, kind DESC",
            uuid.UUID(period["membership_id"]),
            uuid.UUID(period["billing_period_id"]),
        ),
    )
    return [dict(r) for r in rows]


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


@pg
@pytest.mark.parametrize("method", ["cash", "transfer", "other"])
def test_records_a_payment_validated_by_the_admin(
    client: TestClient, db: Database, sur: uuid.UUID, method: str
) -> None:
    admin = add_staff(db, sur, "admin")
    period = new_period(db, sur)
    response = record(
        client,
        sur,
        {**period, "amount_clp": 45_000, "method": method, "note": "pagó en recepción"},
        person_id=admin,
    )
    assert response.status_code == 201, response.text
    body = response.json()

    payment = body["payment"]
    assert payment["kind"] == "payment"
    assert payment["status"] == "validated"
    assert payment["method"] == method
    assert payment["amount_clp"] == 45_000
    assert payment["billing_period_id"] == period["billing_period_id"]
    assert payment["claimed_by"] == payment["validated_by"] == str(admin)
    assert payment["claimed_at"] == payment["validated_at"]
    assert payment["note"] == "pagó en recepción"
    assert body["credit"] is None
    assert body["period"] == {
        "id": period["billing_period_id"],
        "amount_due_clp": 45_000,
        "paid_clp": 45_000,
        "outstanding_clp": 0,
        "closed": True,
    }

    [row] = entries(db, period)
    assert str(row["id"]) == payment["id"]
    assert row["gym_id"] == sur
    assert (row["status"], row["method"], row["validated_by"]) == ("validated", method, admin)
    assert row["proof_object_key"] is None


@pg
def test_a_recorded_payment_emails_a_receipt(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    period = new_period(db, sur, due=45_000)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_person SET email = 'dueno@example.cl' WHERE person_id = $1",
            seeded_owner(sur),
        ),
    )
    mailer.sent.clear()

    response = record(client, sur, {**period, "amount_clp": 40_000, "method": "cash"})

    assert response.status_code == 201, response.text
    [email] = mailer.sent
    assert email.to == "dueno@example.cl"
    assert email.subject == "Pago validado"
    assert "validó tu pago de $40.000" in email.text
    assert "De este período quedan $5.000 por pagar." in email.text
    assert "Tu página: " in email.text
    [(template, _, outcome)] = [n for n in sent_notices(db, sur) if n[0] == "receipt"]
    assert (template, outcome) == ("receipt", "sent")


@pg
def test_a_partial_payment_leaves_the_rest_open_and_a_second_one_closes_it(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    first = record(client, sur, {**period, "amount_clp": 20_000, "method": "cash"})
    assert first.status_code == 201, first.text
    assert first.json()["period"] | {"id": None} == {
        "id": None,
        "amount_due_clp": 45_000,
        "paid_clp": 20_000,
        "outstanding_clp": 25_000,
        "closed": False,
    }

    second = record(client, sur, {**period, "amount_clp": 25_000, "method": "transfer"})
    assert second.status_code == 201, second.text
    assert second.json()["period"]["closed"] is True
    assert second.json()["credit"] is None


@pg
def test_an_overpayment_leaves_a_credit_for_a_later_period(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    response = record(client, sur, {**period, "amount_clp": 50_000, "method": "cash"})
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["payment"]["amount_clp"] == 50_000
    assert body["period"]["paid_clp"] == 45_000
    assert body["period"]["closed"] is True
    credit = body["credit"]
    assert credit["kind"] == "adjustment"
    assert credit["status"] == "validated"
    assert credit["amount_clp"] == 5_000
    assert credit["billing_period_id"] is None
    assert credit["method"] is None
    assert credit["note"] == "Pagó $50.000, quedan $5.000 a favor"
    assert credit["validated_by"] == str(seeded_owner(sur))
    assert credit["validated_at"] == body["payment"]["validated_at"]
    assert [r["kind"] for r in entries(db, period)] == ["payment", "adjustment"]


@pg
def test_a_period_already_paid_in_full_is_a_conflict(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    assert (
        record(client, sur, {**period, "amount_clp": 45_000, "method": "cash"}).status_code == 201
    )

    again = record(client, sur, {**period, "amount_clp": 45_000, "method": "cash"})
    assert again.status_code == 409
    assert len(entries(db, period)) == 1


@pg
def test_another_gyms_period_is_not_found(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    theirs = new_period(db, norte)

    response = record(client, sur, {**theirs, "amount_clp": 45_000, "method": "cash"})
    assert response.status_code == 404
    assert entries(db, theirs) == []


@pg
def test_a_period_of_another_membership_is_not_found(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    period = new_period(db, sur)
    body = {**period, "membership_id": str(uuid.uuid4()), "amount_clp": 45_000, "method": "cash"}
    assert record(client, sur, body).status_code == 404
    assert entries(db, period) == []


@pg
@pytest.mark.parametrize("role", ["coach", "member"])
def test_only_an_owner_or_admin_records_a_payment(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    period = new_period(db, sur)
    person = add_staff(db, sur, "coach") if role == "coach" else uuid.uuid4()
    body = {**period, "amount_clp": 45_000, "method": "cash"}
    assert record(client, sur, body, person_id=person).status_code == 403
    assert entries(db, period) == []


@pg
def test_an_unauthenticated_request_is_refused(client: TestClient) -> None:
    assert client.post("/api/ledger/payments", json=BODY).status_code == 401


# --- the table on its own (migration 0008) ----------------------------------------


@pg
def test_the_table_refuses_an_unknown_method(db: Database, sur: uuid.UUID) -> None:
    period = new_period(db, sur)
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.admin_url,
            lambda c: c.execute(
                "INSERT INTO ledger_entry"
                " (gym_id, membership_id, billing_period_id, amount_clp, kind, method)"
                " VALUES ($1, $2, $3, 45000, 'payment', 'efectivo')",
                sur,
                uuid.UUID(period["membership_id"]),
                uuid.UUID(period["billing_period_id"]),
            ),
        )


@pg
def test_upgrade_and_downgrade_0008() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0007")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0007")
        migrate(scratch)


@pg
def test_a_payment_waits_for_a_lapse_run_holding_the_membership(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    """The nightly `lapse` job holds every membership it may lapse until it commits
    (`app.jobs.lapse`); a payment locks its membership before it reads its period, so
    it waits for the run instead of settling a period the job is deciding on.

    Held here `FOR NO KEY UPDATE`, which only the handler's own `FOR UPDATE` waits on:
    the job's `FOR UPDATE` would also stop the entry's foreign-key check, but only at
    the insert, after the handler has read the period."""
    period = new_period(db, sur)

    async def go() -> None:
        nightly = await asyncpg.connect(to_dsn(db.admin_url))
        try:
            await nightly.execute("BEGIN")
            await nightly.execute(
                "SELECT FROM membership WHERE id = $1 FOR NO KEY UPDATE",
                uuid.UUID(period["membership_id"]),
            )
            with ThreadPoolExecutor(1) as pool:
                paying = asyncio.wrap_future(
                    pool.submit(record, client, sur, {**period, **PAYMENT})
                )
                await asyncio.sleep(0.5)
                assert not paying.done(), "the payment did not wait for the lapse run"
                await nightly.execute("COMMIT")
                response = await paying
            assert response.status_code == 201, response.text
        finally:
            await nightly.close()

    asyncio.run(go())
