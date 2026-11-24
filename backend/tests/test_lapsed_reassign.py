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

from app.domain.billing import GENERATE_AHEAD_DAYS
from app.domain.dates import add_months
from app.jobs import billing, lapse
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
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
    return seed_gym(db, unique_slug("sur"))


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def run_billing(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, day)

    assert run(db.owner_url, go)


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
    period on the 1st.

    In a month's last week the plan comes billed the next month too, ahead, as every plan
    does (#586): its period on the 1st is the one picked, and a plan assigned again starts
    after `billed_through()`."""
    today = seeded_today()
    plan_id = plan(client, gym, "first")
    person = enrolled(
        client,
        gym,
        name="Rosa Vidal",
        membership={"plan_id": plan_id, "started_on": today.replace(day=1).isoformat()},
    )["id"]
    [old] = memberships(client, gym, person)
    first = today.replace(day=1).isoformat()
    [period] = [
        p for p in ledger(client, gym, old["id"])["open_periods"] if p["period_start"] == first
    ]
    assert period["due_date"] == first

    # Grace 5 from the day it was created, not from the 1st it fell due on.
    run_lapse(db, today)
    run_lapse(db, today + timedelta(days=5))
    assert status(client, gym, old["id"]) == "active"
    run_lapse(db, today + timedelta(days=6))
    assert status(client, gym, old["id"]) == "lapsed"
    return person, plan_id, old["id"], period


def billed_through() -> date:
    """The last day `lapsed_member`'s plan billed: its month, and the next one too once
    that one's 1st is within the days billed ahead of today, in a month's last week."""
    today = seeded_today()
    first = today.replace(day=1)
    months = 2 if add_months(first, 1) <= today + timedelta(days=GENERATE_AHEAD_DAYS) else 1
    return add_months(first, months) - timedelta(days=1)


def on_hoy(period_id: str) -> list[str]:
    """`lapsed_member`'s period as Hoy lists it: once past due, so not on the 1st, the
    day it falls due (#586)."""
    return [period_id] if seeded_today().day > 1 else []


def test_a_lapsed_member_assigned_again_is_billed_the_month_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, plan_id, old, period = lapsed_member(client, db, gym)
    first = seeded_today().replace(day=1)
    next_first = add_months(first, 1)
    through = billed_through()
    resumes = through + timedelta(days=1)

    # Step 3: the form warns of the debt and of the day the new plan starts.
    assert quote(client, gym, person, plan_id, first) == {
        "starts_on": resumes.isoformat(),
        "billed_through": through.isoformat(),
        "debt_clp": 45_000,
        "converts": None,
    }
    created = ok(start(client, gym, person, plan_id, first), 201)
    assert (created["started_on"], created["status"]) == (resumes.isoformat(), "active")

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
        p["period_start"] >= resumes.isoformat()
        for p in ledger(client, gym, created["id"])["periods"]
    )

    # Step 4: Hoy lists the one period the member owes, once it is past due.
    assert [
        p["billing_period_id"] for p in overdue(client, gym) if p["person_id"] == person
    ] == on_hoy(period["id"])
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
        "converts": None,
    }
    lapsed, _, _, _ = lapsed_member(client, db, gym)
    pack = plan(client, gym, "credits")
    assert quote(client, gym, lapsed, pack, today) == {
        "starts_on": today.isoformat(),
        "billed_through": None,
        "debt_clp": 45_000,
        "converts": None,
    }
    # A day past what the lapsed plan billed starts on that day.
    later = add_months(today.replace(day=1), 2)
    assert quote(client, gym, lapsed, plan_id, later)["starts_on"] == later.isoformat()


def test_a_quote_for_someone_not_in_the_gym_is_a_404(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan(client, gym, "first")
    elsewhere = enrolled(client, seed_gym(db, unique_slug("norte")), name="Luis Mora")
    for person in (elsewhere["id"], str(uuid.uuid4())):
        params = {"person_id": person, "plan_id": plan_id}
        response = client.get("/api/memberships/start", params=params, headers=as_gym(gym))
        assert response.status_code == 404, response.text


def test_a_moved_start_bills_on_the_day_it_moved_to(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """A plan anchored on the signup day, asked from the 15th of the month the lapsed plan
    billed, starts on the 1st after what it billed, and bills on the 1st, not the 15th."""
    person, _, _, period = lapsed_member(client, db, gym)
    resumes = billed_through() + timedelta(days=1)
    signup = plan(client, gym, "signup")
    asked = seeded_today().replace(day=15)
    assert quote(client, gym, person, signup, asked)["starts_on"] == resumes.isoformat()
    created = ok(start(client, gym, person, signup, asked), 201)
    assert (created["started_on"], created["anchor_day"]) == (resumes.isoformat(), 1)
    run_billing(db, resumes)
    [first] = ledger(client, gym, created["id"])["periods"]
    month_after = add_months(resumes, 1) - timedelta(days=1)
    assert (first["period_start"], first["period_end"]) == (
        resumes.isoformat(),
        month_after.isoformat(),
    )
    assert period["period_end"] < first["period_start"]


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
    assert on_hoy(period["id"]) == [
        p["billing_period_id"] for p in overdue(client, gym) if p["person_id"] == person
    ]
