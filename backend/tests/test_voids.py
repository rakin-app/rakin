"""Fixing a mistake on a member (#256): void a charge, void a plan started by mistake,
and delete a test person, keeping the audit trail.

A void is a new entry, an adjustment of all the period still owes, so the period owes
nothing anywhere the app settles one: the ficha, Hoy, Pagos and its KPIs, the balance.
The charge stays in the ledger, read as voided with who, when and why. Money stands in
the way: a payment is refunded first, a proof waiting is rejected first. A person whose
every charge is voided and from whom the gym kept no money is deleted, ledger and all,
and the gym's log keeps a row saying who deleted, when and why, with nothing about them.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain import billing as domain
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
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
from tests.test_member_roll import count, enrolled, forget, leave, memberships, plan
from tests.test_plans import add_staff

pg = pytest.mark.postgres

REASON = "alumno de prueba"

# --- the domain, no database ------------------------------------------------------


def test_a_void_settles_all_the_period_still_owes() -> None:
    period = BillingPeriod(
        period_start=seeded_today(),
        period_end=seeded_today() + timedelta(days=29),
        amount_due_clp=45_000,
        due_date=seeded_today(),
        # A surcharge of 5.000 is owed on top; a discount of 10.000 counts towards it.
        paid_clp=5_000,
    )
    settlement = domain.void(period, "  cobrado por error ")
    assert (settlement.entry.amount_clp, settlement.entry.voids) == (40_000, True)
    assert settlement.entry.note == "cobrado por error"
    assert (settlement.period.outstanding_clp, settlement.period.closed) == (0, True)
    with pytest.raises(InvalidTransition):
        domain.void(settlement.period, "otra vez")
    with pytest.raises(ValueError):
        domain.void(period, "  ")


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


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def member(client: TestClient, gym: uuid.UUID, days_ago: int = 40) -> tuple[str, str]:
    """A test student on a monthly plan of 45.000 since `days_ago`: billed every period
    from then, the ones before today overdue. Their id and their membership's."""
    started_on = (seeded_today() - timedelta(days=days_ago)).isoformat()
    body = enrolled(
        client,
        gym,
        name="Prueba Test",
        membership={"plan_id": plan(client, gym)} | {"started_on": started_on},
    )
    [membership] = memberships(client, gym, body["id"])
    return body["id"], membership["id"]


def ledger(client: TestClient, gym: uuid.UUID, membership: str) -> Any:
    return ok(client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym)))


def void(client: TestClient, gym: uuid.UUID, membership: str, period: str, **kw: Any) -> Any:
    body = {"membership_id": membership, "billing_period_id": period, "reason": REASON}
    return client.post("/api/ledger/voids", json=body, headers=as_gym(gym, **kw))


def void_plan(client: TestClient, gym: uuid.UUID, membership: str, **kw: Any) -> Any:
    return client.post(
        f"/api/memberships/{membership}/void", json={"reason": REASON}, headers=as_gym(gym, **kw)
    )


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str) -> str:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": 45_000,
        "method": "cash",
    }
    return str(
        ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)["payment"][
            "id"
        ]
    )


def refund(client: TestClient, gym: uuid.UUID, payment: str) -> None:
    body = {"payment_id": payment, "amount_clp": 45_000, "method": "cash"}
    ok(client.post("/api/ledger/refunds", json=body, headers=as_gym(gym)), 201)


def overdue_ids(client: TestClient, gym: uuid.UUID) -> set[str]:
    found = ok(client.get("/api/ledger/overdue", headers=as_gym(gym)))
    return {p["billing_period_id"] for p in found["periods"]}


def book(client: TestClient, gym: uuid.UUID, **params: str) -> Any:
    return ok(client.get("/api/ledger/book", params=params, headers=as_gym(gym)))


def balance(db: Database, membership: str) -> int:
    value: int = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT coalesce(sum(balance_clp), 0) FROM v_balance WHERE membership_id = $1",
            uuid.UUID(membership),
        ),
    )
    return value


def pending_proof(db: Database, gym: uuid.UUID, person: str, membership: str, period: str) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, claimed_by, claimed_at, proof_object_key)"
            " VALUES ($1, $2, $3, 45000, 'payment', 'pending', $4, now(), $5)",
            gym,
            uuid.UUID(membership),
            uuid.UUID(period),
            uuid.UUID(person),
            f"proofs/{uuid.uuid4()}.png",
        ),
    )


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_a_voided_charge_is_owed_nowhere_and_reads_as_voided(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    _, membership = member(client, gym)
    before = ledger(client, gym, membership)
    oldest = before["open_periods"][0]
    assert oldest["days_overdue"] > 0
    assert oldest["id"] in overdue_ids(client, gym)
    kpis = book(client, gym, month=oldest["due_date"])["kpis"]
    owed_before, balance_before = before["owed_clp"], balance(db, membership)

    by = seeded_owner(gym) if role == "owner" else add_staff(db, gym, "admin")
    recorded = ok(void(client, gym, membership, oldest["id"], person_id=by), 201)
    entry = recorded["void"]
    assert (entry["kind"], entry["amount_clp"], entry["voids"]) == ("adjustment", 45_000, True)
    assert (entry["note"], entry["validated_by"]) == (REASON, str(by))
    assert recorded["period"]["outstanding_clp"] == 0

    # Not owed on the ficha, on Hoy, in Pagos, in the balance.
    after = ledger(client, gym, membership)
    assert oldest["id"] not in {p["id"] for p in after["open_periods"]}
    assert after["owed_clp"] == owed_before - 45_000
    assert oldest["id"] not in overdue_ids(client, gym)
    assert balance(db, membership) == balance_before - 45_000
    later = book(client, gym, month=oldest["due_date"])["kpis"]
    assert later["overdue_clp"] == kpis["overdue_clp"] - 45_000
    assert later["expected_clp"] == kpis["expected_clp"] - 45_000
    # Pagos' "Vencidos" leaves it out.
    overdue_book = book(client, gym, filter="overdue")["items"]
    assert not [i for i in overdue_book if i["kind"] == "charge" and i["voided"]]

    # Still in the ledger, struck through with why, who and when; the void beside it.
    charge = next(
        e
        for e in after["entries"]
        if e["kind"] == "charge" and e["billing_period_id"] == oldest["id"]
    )
    assert charge["voided"]["reason"] == REASON
    assert charge["voided"]["by_name"] is not None
    assert charge["voided"]["at"] == entry["created_at"]
    voids = [e for e in after["entries"] if e["voids"]]
    assert [(v["billing_period_id"], v["note"]) for v in voids] == [(oldest["id"], REASON)]
    month = book(client, gym, month=oldest["period_start"])["items"]
    booked = next(i for i in month if i["kind"] == "charge" and i["membership_id"] == membership)
    assert booked["voided"]["reason"] == REASON


@pg
def test_a_coach_cannot_void(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    _, membership = member(client, gym)
    period = ledger(client, gym, membership)["open_periods"][0]["id"]
    coach = add_staff(db, gym, "coach")
    assert void(client, gym, membership, period, person_id=coach).status_code == 403
    assert void_plan(client, gym, membership, person_id=coach).status_code == 403
    assert period in {p["id"] for p in ledger(client, gym, membership)["open_periods"]}


@pg
def test_a_void_needs_a_reason_and_a_period_with_no_money_on_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    first, second = (p["id"] for p in ledger(client, gym, membership)["open_periods"][:2])
    body = {"membership_id": membership, "billing_period_id": first, "reason": "  "}
    assert client.post("/api/ledger/voids", json=body, headers=as_gym(gym)).status_code == 422

    payment = pay(client, gym, membership, first)
    paid = void(client, gym, membership, first)
    assert paid.status_code == 409
    assert paid.json()["detail"] | {"message": None} == {
        "code": "paid",
        "message": None,
        "amount_clp": 45_000,
    }
    # Given back, it is owed again, and voids.
    refund(client, gym, payment)
    ok(void(client, gym, membership, first), 201)
    again = void(client, gym, membership, first)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "nothing_owed")

    pending_proof(db, gym, person, membership, second)
    waiting = void(client, gym, membership, second)
    assert (waiting.status_code, waiting.json()["detail"]["code"]) == (409, "pending")

    elsewhere = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    assert void(client, elsewhere, membership, second).status_code == 404


@pg
def test_a_plan_started_by_mistake_is_voided_and_bills_no_more(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    owing = ledger(client, gym, membership)["open_periods"]
    assert len(owing) >= 2
    admin = add_staff(db, gym, "admin")

    voided = ok(void_plan(client, gym, membership, person_id=admin))
    assert voided["status"] == "cancelled"
    assert (voided["void_reason"], voided["cancel_reason"]) == (REASON, REASON)
    assert voided["voided_at"] is not None
    # Ended as of its start, as if it had never run.
    started = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT started_at, cancelled_at, voided_by FROM membership WHERE id = $1",
            uuid.UUID(membership),
        ),
    )
    assert started["cancelled_at"] == started["started_at"]
    assert started["voided_by"] == admin

    after = ledger(client, gym, membership)
    assert (after["open_periods"], after["owed_clp"]) == ([], 0)
    assert {e["billing_period_id"] for e in after["entries"] if e["voids"]} == {
        p["id"] for p in owing
    }
    assert balance(db, membership) <= 0

    periods = "SELECT count(*) FROM billing_period WHERE membership_id = $1"
    billed = count(db, gym, periods, uuid.UUID(membership))

    async def bill_later(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, seeded_today() + timedelta(40))

    run(db.owner_url, bill_later)
    assert count(db, gym, periods, uuid.UUID(membership)) == billed

    again = void_plan(client, gym, membership)
    assert again.status_code == 409
    # And the person, now owing nothing and holding no money, can be deleted.
    assert ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym)))["refused"] is None


@pg
def test_a_plan_cancelled_before_is_still_voided_and_keeps_how_it_ended(
    client: TestClient, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    leave(client, gym, person)
    # Dado de baja keeps the debt; voiding the plan clears it.
    assert ledger(client, gym, membership)["owed_clp"] > 0
    voided = ok(void_plan(client, gym, membership))
    assert (voided["status"], voided["cancel_reason"]) == ("cancelled", "dado de baja")
    assert voided["void_reason"] == REASON
    assert ledger(client, gym, membership)["owed_clp"] == 0


@pg
def test_a_plan_with_a_payment_on_it_is_not_voided(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    periods = ledger(client, gym, membership)["open_periods"]
    pay(client, gym, membership, periods[-1]["id"])
    refused = void_plan(client, gym, membership)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "paid"
    # Nothing was written: every period still owes as it did.
    after = ledger(client, gym, membership)
    assert [p["id"] for p in after["open_periods"]] == [p["id"] for p in periods[:-1]]
    assert not [e for e in after["entries"] if e["voids"]]
    status = ok(client.get(f"/api/memberships/{membership}", headers=as_gym(gym)))["status"]
    assert status == "active"


@pg
def test_a_test_person_with_only_voided_charges_is_deleted_and_logged(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    periods = ledger(client, gym, membership)["open_periods"]
    # A payment received blocks it, and says how much: the money is real.
    payment = pay(client, gym, membership, periods[0]["id"])
    asked = ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym)))
    assert asked == {"refused": "payment", "amount_clp": 45_000}
    refused = forget(client, gym, person)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "payment", "amount_clp": 45_000}

    refund(client, gym, payment)
    owed = sum(p["outstanding_clp"] for p in periods)
    asked = ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym)))
    assert asked == {"refused": "owes", "amount_clp": owed}

    ok(void_plan(client, gym, membership))
    entries = count(
        db, gym, "SELECT count(*) FROM ledger_entry WHERE membership_id = $1", uuid.UUID(membership)
    )
    assert entries > 0
    assert forget(client, gym, person, reason="era de prueba").status_code == 204

    assert client.get(f"/api/people/{person}", headers=as_gym(gym)).status_code == 404
    for sql in (
        "SELECT count(*) FROM ledger_entry WHERE membership_id = $1",
        "SELECT count(*) FROM membership WHERE id = $1",
    ):
        assert count(db, gym, sql, uuid.UUID(membership)) == 0

    [row] = run(
        db.admin_url,
        lambda c: c.fetch("SELECT * FROM audit_event WHERE gym_id = $1", gym),
    )
    assert (row["action"], row["actor_id"], row["reason"]) == (
        "person_deleted",
        seeded_owner(gym),
        "era de prueba",
    )
    detail = row["detail"]
    assert '"memberships": 1' in detail and '"voided_memberships": 1' in detail
    assert f'"ledger_entries": {entries}' in detail
    # Nothing about them: no id, no name.
    assert person not in detail and "Prueba" not in detail

    # The gym's owner and admins read the log; a coach does not.
    admin = add_staff(db, gym, "admin")
    coach = add_staff(db, gym, "coach")
    log = "SELECT count(*) FROM audit_event"
    assert int(run(db.api_url, in_gym(gym, log, person=admin))[0][0]) == 1
    assert int(run(db.api_url, in_gym(gym, log, person=coach))[0][0]) == 0


@pg
def test_a_proof_waiting_blocks_deleting(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership = member(client, gym, days_ago=0)
    [period] = ledger(client, gym, membership)["open_periods"]
    pending_proof(db, gym, person, membership, period["id"])
    asked = ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym)))
    assert asked == {"refused": "pending", "amount_clp": None}


@pg
def test_the_ledger_is_still_append_only_outside_forget(db: Database, gym: uuid.UUID) -> None:
    other = uuid.uuid4()

    async def delete(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            # Naming someone the entries are not of lets nothing through.
            await conn.execute("SELECT set_config('app.forget_person', $1, true)", str(other))
            await conn.execute("DELETE FROM ledger_entry")

    with pytest.raises(asyncpg.RestrictViolationError, match="cannot be deleted"):
        run(db.owner_url, delete)


@pg
def test_a_cancelled_membership_changes_only_to_be_voided(db: Database, gym: uuid.UUID) -> None:
    async def change(conn: asyncpg.Connection, sql: str) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "UPDATE membership SET status = 'cancelled', cancel_reason = 'x',"
                " cancelled_at = now() WHERE gym_id = $1",
                gym,
            )
            await conn.execute(sql)

    with pytest.raises(asyncpg.RestrictViolationError):
        run(db.owner_url, lambda c: change(c, "UPDATE membership SET discount_pct = 10"))
    with pytest.raises(asyncpg.RestrictViolationError):
        run(
            db.owner_url,
            lambda c: change(
                c, "UPDATE membership SET voided_at = now(), void_reason = 'y', discount_pct = 10"
            ),
        )
    run(
        db.owner_url,
        lambda c: change(c, "UPDATE membership SET voided_at = now(), void_reason = 'y'"),
    )


@pg
def test_upgrade_and_downgrade_0044() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0043")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0043")
        migrate(scratch)
