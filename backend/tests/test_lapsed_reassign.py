"""A plan assigned again to a member whose plan lapsed unpaid (#271).

On staging a plan backdated to the 1st lapsed the night after it was created, before
the owner could record the payment; "Asignar plan" then started a second one on the
1st, billing the month again; Hoy listed the member twice, and the ficha's current plan
was down to the memberships' ids. Here: the backdated plan has its grace from the day it
was created, the plan assigned again starts after what the lapsed one billed, the
current plan is the live one, and the lapsed plan's charge can be voided, and put back
with a "Recargo" when voided by mistake.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.jobs import lapse
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_member_roll import enrolled, memberships, plan

pytestmark = pytest.mark.postgres


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


def run_lapse(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await lapse.lapse_memberships(conn, day)

    assert run(db.owner_url, go)


def status(client: TestClient, gym: uuid.UUID, membership: str) -> str:
    found = ok(client.get(f"/api/memberships/{membership}", headers=as_gym(gym)))
    return str(found["status"])


def ledger(client: TestClient, gym: uuid.UUID, membership: str) -> Any:
    return ok(client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym)))


def overdue(client: TestClient, gym: uuid.UUID) -> list[dict[str, Any]]:
    return list(ok(client.get("/api/ledger/overdue", headers=as_gym(gym)))["periods"])


def shown(client: TestClient, gym: uuid.UUID, person: str) -> str:
    """The membership Alumnos shows for `person`."""
    rows = ok(client.get("/api/people", headers=as_gym(gym)))["items"]
    [row] = [r for r in rows if r["id"] == person]
    return str(row["membership"]["id"])


def start(client: TestClient, gym: uuid.UUID, person: str, plan_id: str, on: date) -> Any:
    body = {"person_id": person, "plan_id": plan_id, "started_on": on.isoformat()}
    return client.post("/api/memberships", json=body | {"send_welcome": False}, headers=as_gym(gym))


def quote(client: TestClient, gym: uuid.UUID, person: str, plan_id: str, on: date) -> Any:
    params = {"person_id": person, "plan_id": plan_id, "started_on": on.isoformat()}
    return ok(client.get("/api/memberships/start", params=params, headers=as_gym(gym)))


def lapsed_member(
    client: TestClient, db: Database, gym: uuid.UUID
) -> tuple[str, str, str, dict[str, Any]]:
    """Steps 1 and 2: a plan backdated to the 1st, created today, unpaid until it lapses
    once its grace from today is past. The person, the plan, the membership and its
    period."""
    today = seeded_today()
    plan_id = plan(client, gym, "first")
    person = enrolled(
        client,
        gym,
        name="Rosa Vidal",
        membership={"plan_id": plan_id, "started_on": today.replace(day=1).isoformat()},
    )["id"]
    [old] = memberships(client, gym, person)
    [period] = ledger(client, gym, old["id"])["open_periods"]
    assert period["due_date"] == today.replace(day=1).isoformat()

    # Grace 5 from the day it was created, not from the 1st it fell due on.
    run_lapse(db, today)
    run_lapse(db, today + timedelta(days=5))
    assert status(client, gym, old["id"]) == "active"
    run_lapse(db, today + timedelta(days=6))
    assert status(client, gym, old["id"]) == "lapsed"
    return person, plan_id, old["id"], period


def test_a_lapsed_member_assigned_again_is_billed_the_month_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, plan_id, old, period = lapsed_member(client, db, gym)
    first = seeded_today().replace(day=1)
    next_first = add_months(first, 1)

    # Step 3: the form warns of the debt and of the day the new plan starts.
    assert quote(client, gym, person, plan_id, first) == {
        "starts_on": next_first.isoformat(),
        "billed_through": period["period_end"],
        "debt_clp": 45_000,
    }
    created = ok(start(client, gym, person, plan_id, first), 201)
    assert (created["started_on"], created["status"]) == (next_first.isoformat(), "active")

    # The month is billed once, on the lapsed plan, and owed there.
    month = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT count(*) FROM billing_period bp JOIN membership m ON m.id = bp.membership_id"
            " WHERE m.person_id = $1 AND bp.period_start >= $2 AND bp.period_start < $3",
            uuid.UUID(person),
            first,
            next_first,
        ),
    )
    assert month[0][0] == 1
    assert ledger(client, gym, old)["owed_clp"] == 45_000
    assert all(
        p["period_start"] >= next_first.isoformat()
        for p in ledger(client, gym, created["id"])["periods"]
    )

    # Step 4: Hoy lists the one period the member owes.
    assert [p["billing_period_id"] for p in overdue(client, gym) if p["person_id"] == person] == [
        period["id"]
    ]
    # Step 6: the ficha and Alumnos show the active plan as current.
    assert memberships(client, gym, person)[0]["id"] == created["id"]
    assert shown(client, gym, person) == created["id"]


def test_a_quote_moves_nothing_without_a_lapsed_plan_or_for_a_pack(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    plan_id = plan(client, gym, "first")
    person = enrolled(client, gym, name="Ana Soto")["id"]
    assert quote(client, gym, person, plan_id, today) == {
        "starts_on": today.isoformat(),
        "billed_through": None,
        "debt_clp": 0,
    }
    lapsed, _, _, _ = lapsed_member(client, db, gym)
    pack = plan(client, gym, "credits")
    assert quote(client, gym, lapsed, pack, today) == {
        "starts_on": today.isoformat(),
        "billed_through": None,
        "debt_clp": 45_000,
    }
    # A day past what the lapsed plan billed starts on that day.
    later = add_months(today.replace(day=1), 2)
    assert quote(client, gym, lapsed, plan_id, later)["starts_on"] == later.isoformat()


def test_the_current_plan_is_the_live_one_then_the_latest_created(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """Step 6: two memberships started on the same day, as staging had."""
    first = seeded_today().replace(day=1)
    plan_id = plan(client, gym, "first")
    person = enrolled(
        client,
        gym,
        name="Rosa Vidal",
        membership={"plan_id": plan_id, "started_on": first.isoformat()},
    )["id"]
    [live] = memberships(client, gym, person)

    def another(status: str, created_hours: int) -> str:
        rows = run(
            db.owner_url,
            in_gym(
                gym,
                "INSERT INTO membership (gym_id, person_id, plan_id, status, anchor_day,"
                " started_at, created_at, current_period_end)"
                " SELECT gym_id, person_id, plan_id, $2, anchor_day, started_at,"
                " now() + make_interval(hours => $3), current_period_end"
                " FROM membership WHERE id = $1 RETURNING id",
                uuid.UUID(live["id"]),
                status,
                created_hours,
            ),
        )
        return str(rows[0][0])

    # Created after it, and the same day started: still not the current one.
    lapsed = another("lapsed", 1)
    assert memberships(client, gym, person)[0]["id"] == live["id"]
    assert shown(client, gym, person) == live["id"]

    # Neither live: the latest created.
    run(
        db.owner_url,
        in_gym(gym, "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(live["id"])),
    )
    assert memberships(client, gym, person)[0]["id"] == lapsed
    assert shown(client, gym, person) == lapsed


def test_the_lapsed_plans_charge_is_voided_and_put_back_with_a_recargo(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, _, old, period = lapsed_member(client, db, gym)
    body = {"membership_id": old, "billing_period_id": period["id"], "reason": "duplicado"}
    ok(client.post("/api/ledger/voids", json=body, headers=as_gym(gym)), 201)
    after = ledger(client, gym, old)
    assert after["owed_clp"] == 0
    [voided] = [p for p in after["periods"] if p["id"] == period["id"]]
    assert (voided["outstanding_clp"], voided["voided_clp"]) == (0, 45_000)
    assert person not in {p["person_id"] for p in overdue(client, gym)}

    # Voided by mistake: a "Recargo" of as much puts it back, owed and overdue again.
    surcharge = {
        "membership_id": old,
        "billing_period_id": period["id"],
        "amount_clp": -voided["voided_clp"],
        "note": "restaurar cargo anulado por error",
    }
    ok(client.post("/api/ledger/adjustments", json=surcharge, headers=as_gym(gym)), 201)
    assert ledger(client, gym, old)["owed_clp"] == 45_000
    assert period["id"] in {p["billing_period_id"] for p in overdue(client, gym)}
