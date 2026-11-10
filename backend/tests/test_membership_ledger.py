"""One membership's ledger, as the member detail reads it ("Ficha de alumno", #60).

The periods it still owes, oldest first, with what is owed today and how late each is,
and its entries newest first, with who reviewed each.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_guardians import add_person, bill
from tests.test_plans import add_staff

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


def slug(db: Database, gym: uuid.UUID) -> str:
    return str(run(db.admin_url, lambda c: c.fetchval("SELECT slug FROM gym WHERE id = $1", gym)))


def ledger(client: TestClient, gym: uuid.UUID, membership: str, **kw: Any) -> Any:
    return client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym, **kw))


def read(client: TestClient, gym: uuid.UUID, membership: str) -> Any:
    response = ledger(client, gym, membership)
    assert response.status_code == 200, response.text
    return response.json()


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> None:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "method": "cash",
    }
    response = client.post("/api/ledger/payments", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text


@pg
def test_open_periods_are_oldest_first_and_owed_counts_only_what_is_due(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    # Paid, part-paid and 9 days late, due today, and not due for three days.
    membership = bill(
        db,
        sur,
        ana,
        [(-40, 30000, 30000, 0), (-9, 45000, 10000, 5000), (0, 45000, 0, 0), (3, 45000, 0, 0)],
    )

    found = read(client, sur, membership)

    periods = found["open_periods"]
    assert [(p["amount_due_clp"], p["paid_clp"], p["outstanding_clp"]) for p in periods] == [
        (45000, 10000, 35000),
        (45000, 0, 45000),
        (45000, 0, 45000),
    ]
    today = seeded_today()
    dues = [date.fromisoformat(p["due_date"]) for p in periods]
    assert [p["days_overdue"] for p in periods] == [max((today - d).days, 0) for d in dues]
    assert [p["due"] for p in periods] == [d <= today for d in dues]
    # A pending payment settles nothing until it is validated.
    assert found["owed_clp"] == sum(p["outstanding_clp"] for p in periods if p["due"])


@pg
def test_entries_are_newest_first_with_who_reviewed_them(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-5, 30000, 0, 0)])
    [period] = read(client, sur, membership)["open_periods"]

    pay(client, sur, membership, period["id"], 10000)
    # 25.000 against the 20.000 left: the period closes and 5.000 is carried as credit.
    pay(client, sur, membership, period["id"], 25000)

    found = read(client, sur, membership)

    assert found["open_periods"] == []
    assert found["owed_clp"] == 0
    rows = [
        (e["kind"], e["status"], e["amount_clp"], e["method"], e["period_start"])
        for e in found["entries"]
    ]
    start = period["period_start"]
    # The credit and the payment that left it share a transaction, so a time.
    assert sorted(rows[:2], key=str) == sorted(
        [
            ("adjustment", "validated", 5000, None, None),
            ("payment", "validated", 25000, "cash", start),
        ],
        key=str,
    )
    assert rows[2:] == [
        ("payment", "validated", 10000, "cash", start),
        ("charge", "validated", 30000, None, start),
    ]
    payments = [e for e in found["entries"] if e["kind"] == "payment"]
    assert {e["validated_by_name"] for e in payments} == {f"owner of {slug(db, sur)}"}
    assert all(e["validated_at"] for e in payments)


@pg
def test_a_pending_claim_shows_unreviewed(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 0, 30000)])

    entries = read(client, sur, membership)["entries"]

    [claim] = [e for e in entries if e["kind"] == "payment"]
    assert (claim["status"], claim["validated_by_name"], claim["validated_at"]) == (
        "pending",
        None,
        None,
    )


@pg
def test_the_timeline_is_capped(
    client: TestClient, db: Database, sur: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.ledger.TIMELINE_LIMIT", 2)
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-60, 30000, 30000, 0), (-30, 30000, 30000, 0)])

    assert len(read(client, sur, membership)["entries"]) == 2


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_read_it(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    membership = bill(db, sur, add_person(client, sur, "Ana"), [(-1, 30000, 0, 0)])
    person = seeded_owner(sur) if role == "owner" else add_staff(db, sur, role)

    assert ledger(client, sur, membership, person_id=person).status_code == 200


@pg
def test_a_coach_cannot_read_it(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    membership = bill(db, sur, add_person(client, sur, "Ana"), [(-1, 30000, 0, 0)])

    response = ledger(client, sur, membership, person_id=add_staff(db, sur, "coach"))

    assert response.status_code == 403


@pg
def test_another_gyms_membership_is_not_found(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"academia-norte-{uuid.uuid4().hex[:6]}")
    theirs = bill(db, norte, add_person(client, norte, "Bea"), [(-1, 30000, 0, 0)])

    assert ledger(client, sur, theirs).status_code == 404
    assert ledger(client, sur, str(uuid.uuid4())).status_code == 404
