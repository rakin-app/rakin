"""The gym's overdue periods, as the owner's dashboard reads them ("Hoy", #58).

`v_overdue` decides what is overdue (`tests/test_reporting_views.py`); this is what
the endpoint adds: only Active memberships, who owes it and on which plan, the total,
and the longest overdue first.
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
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_guardians import add_person, bill
from tests.test_membership_ledger import gym_today
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


def overdue(client: TestClient, gym: uuid.UUID, **kw: Any) -> Any:
    return client.get("/api/ledger/overdue", headers=as_gym(gym, **kw))


def read(client: TestClient, gym: uuid.UUID) -> Any:
    response = overdue(client, gym)
    assert response.status_code == 200, response.text
    return response.json()


def set_status(db: Database, membership: str, status: str) -> None:
    # A cancelled membership carries its reason and time (migration 0009).
    cancelled = status == "cancelled"
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET status = $1,"
            " cancel_reason = CASE WHEN $2 THEN 'other' END,"
            " cancelled_at = CASE WHEN $2 THEN now() END WHERE id = $3",
            status,
            cancelled,
            uuid.UUID(membership),
        ),
    )


@pg
def test_lists_active_overdue_periods_longest_first_with_the_total(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana Rojas")
    beto = add_person(client, sur, "Beto Soto")
    # Ana: paid 20 days ago, 9 days late with 10.000 paid and 5.000 pending, not due yet.
    anas = bill(db, sur, ana, [(-20, 30000, 30000, 0), (-9, 45000, 10000, 5000), (3, 45000, 0, 0)])
    betos = bill(db, sur, beto, [(-3, 30000, 0, 0)])

    found = read(client, sur)

    today = gym_today()
    rows = [
        (p["membership_id"], p["person_name"], p["plan_name"], p["outstanding_clp"])
        for p in found["periods"]
    ]
    # A pending payment settles nothing until it is validated.
    assert rows == [(anas, "Ana Rojas", "Mensual", 35000), (betos, "Beto Soto", "Mensual", 30000)]
    assert found["total_clp"] == 65000
    for p in found["periods"]:
        assert p["days_overdue"] == (today - date.fromisoformat(p["due_date"])).days
    assert {p["person_id"] for p in found["periods"]} == {ana, beto}


@pg
@pytest.mark.parametrize("status", ["lapsed", "cancelled"])
def test_leaves_out_memberships_that_are_not_active(
    client: TestClient, db: Database, sur: uuid.UUID, status: str
) -> None:
    membership = bill(db, sur, add_person(client, sur, "Ana"), [(-30, 30000, 0, 0)])
    set_status(db, membership, status)

    assert read(client, sur) == {"total_clp": 0, "periods": []}


@pg
def test_another_gyms_periods_are_not_listed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"academia-norte-{uuid.uuid4().hex[:6]}")
    bill(db, norte, add_person(client, norte, "Bea"), [(-5, 30000, 0, 0)])

    assert read(client, sur)["periods"] == []


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_read_it(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    person = seeded_owner(sur) if role == "owner" else add_staff(db, sur, role)

    assert overdue(client, sur, person_id=person).status_code == 200


@pg
def test_a_coach_cannot_read_it(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    assert overdue(client, sur, person_id=add_staff(db, sur, "coach")).status_code == 403
