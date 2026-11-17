"""Fixed-period plans against the database (#351): billed by the nightly job with the
same dates for every member, copied for the next period with their members moved
across, and refused once their period has ended.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_memberships import start

pytestmark = pytest.mark.postgres

MAR_1, DEC_31 = date(2027, 3, 1), date(2027, 12, 31)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def generate(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, day)

    assert run(db.owner_url, go)


# --- the nightly job ----------------------------------------------------------------


def test_members_starting_on_different_days_owe_the_same_period(db: Database) -> None:
    gym = Gym(db)
    early = gym.member("season", date(2027, 2, 20), current_period_end=date(2027, 2, 19))
    late = gym.member("season", date(2027, 6, 10), current_period_end=date(2027, 6, 9))

    generate(db, date(2027, 6, 3))

    assert gym.periods(early) == [(MAR_1, DEC_31, 300_000, MAR_1)]
    assert gym.periods(late) == [(MAR_1, DEC_31, 300_000, date(2027, 6, 10))]
    assert gym.charges(late) == [(MAR_1, 300_000, "validated")]


def test_nothing_is_billed_after_the_period_until_moved_to_the_next_plan(db: Database) -> None:
    gym = Gym(db)
    member = gym.member("season", MAR_1, current_period_end=MAR_1 - timedelta(days=1))
    generate(db, MAR_1)

    generate(db, date(2028, 3, 1))
    generate(db, date(2028, 12, 31))

    assert gym.periods(member) == [(MAR_1, DEC_31, 300_000, MAR_1)]


def test_moved_to_the_next_season_it_bills_that_season_when_due(db: Database) -> None:
    gym = Gym(db)
    member = gym.member("season", MAR_1, current_period_end=MAR_1 - timedelta(days=1))
    generate(db, MAR_1)
    (row,) = gym.sql(
        "INSERT INTO plan (gym_id, name, kind, price_clp, period_start, period_end)"
        " VALUES ($1, 'Temporada 2028', 'fixed_period', 320000, '2028-03-01', '2028-12-31')"
        " RETURNING id",
        gym.id,
    )
    gym.sql(
        "UPDATE membership SET next_plan_id = $2, next_plan_from = '2028-01-01' WHERE id = $1",
        member,
        row["id"],
    )

    generate(db, date(2028, 2, 22))
    assert len(gym.periods(member)) == 1
    generate(db, date(2028, 2, 23))

    mar_1_2028 = date(2028, 3, 1)
    assert gym.periods(member)[1] == (mar_1_2028, date(2028, 12, 31), 320_000, mar_1_2028)
    moved = gym.membership(member)
    assert (moved["plan_id"], moved["next_plan_id"]) == (row["id"], None)


# --- the API ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def season(client: TestClient, gym: uuid.UUID, start: date, end: date, **fields: Any) -> str:
    body = {
        "kind": "fixed_period",
        "name": "Temporada",
        "price_clp": 300_000,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        **fields,
    }
    response = client.post("/api/plans", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def current_season(client: TestClient, gym: uuid.UUID) -> str:
    today = seeded_today()
    return season(client, gym, today - timedelta(days=30), today + timedelta(days=200))


def on(client: TestClient, gym: uuid.UUID, plan_id: str) -> dict[str, Any]:
    response = start(client, gym, plan_id)
    assert response.status_code == 201, response.text
    return dict(response.json())


def next_period(client: TestClient, gym: uuid.UUID, plan_id: str, **body: Any) -> Any:
    return client.post(f"/api/plans/{plan_id}/next-period", json=body, headers=as_gym(gym))


def test_a_member_starting_mid_season_owes_it_from_today_at_the_full_price(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan = current_season(client, sur)
    membership = on(client, sur, plan)

    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT period_start, period_end, amount_due_clp, due_date FROM billing_period"
            " WHERE membership_id = $1",
            uuid.UUID(membership["id"]),
        ),
    )
    today = seeded_today()
    assert [tuple(r) for r in rows] == [
        (today - timedelta(days=30), today + timedelta(days=200), 300_000, today)
    ]


def test_a_plan_whose_period_ended_does_not_start(client: TestClient, sur: uuid.UUID) -> None:
    today = seeded_today()
    ended = season(client, sur, today - timedelta(days=300), today - timedelta(days=1))

    response = start(client, sur, ended)

    assert response.status_code == 422
    assert "ended" in response.text


def test_the_plans_list_and_the_next_period_moves_the_members_chosen(
    client: TestClient, sur: uuid.UUID
) -> None:
    program = client.post("/api/programs", json={"name": "Remo"}, headers=as_gym(sur)).json()["id"]
    today = seeded_today()
    end = today + timedelta(days=200)
    plan = season(client, sur, today - timedelta(days=30), end, program_id=program)
    staying, leaving = on(client, sur, plan), on(client, sur, plan)

    listed = client.get(f"/api/plans/{plan}/memberships", headers=as_gym(sur))
    assert listed.status_code == 200
    assert {m["membership_id"] for m in listed.json()} == {staying["id"], leaving["id"]}

    start_next = end + timedelta(days=60)
    response = next_period(
        client,
        sur,
        plan,
        name="Temporada siguiente",
        price_clp=320_000,
        period_start=start_next.isoformat(),
        period_end=(start_next + timedelta(days=300)).isoformat(),
        membership_ids=[staying["id"]],
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["moved"] == 1
    assert copy["plan"]["kind"] == "fixed_period"
    assert copy["plan"]["program_id"] == program
    assert copy["plan"]["period_start"] == start_next.isoformat()
    moved = client.get(f"/api/memberships/{staying['id']}", headers=as_gym(sur)).json()
    assert moved["next_plan"]["plan_id"] == copy["plan"]["id"]
    assert moved["next_plan"]["starts_on"] == (end + timedelta(days=1)).isoformat()
    kept = client.get(f"/api/memberships/{leaving['id']}", headers=as_gym(sur)).json()
    assert kept["next_plan"] is None


def test_the_next_period_starts_after_the_current_one(client: TestClient, sur: uuid.UUID) -> None:
    today = seeded_today()
    plan = season(client, sur, today, today + timedelta(days=100))

    response = next_period(
        client,
        sur,
        plan,
        name="Otra",
        price_clp=1,
        period_start=(today + timedelta(days=100)).isoformat(),
        period_end=(today + timedelta(days=200)).isoformat(),
    )

    assert response.status_code == 422
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [
        (["body", "period_start"], "after_period")
    ]


def test_only_a_fixed_period_plan_and_its_own_members_move(
    client: TestClient, sur: uuid.UUID
) -> None:
    today = seeded_today()
    later = {
        "name": "Otra",
        "price_clp": 1,
        "period_start": (today + timedelta(days=400)).isoformat(),
        "period_end": (today + timedelta(days=500)).isoformat(),
    }
    monthly = client.post(
        "/api/plans",
        json={"kind": "monthly", "name": "Mensual", "price_clp": 1, "anchor": "signup"},
        headers=as_gym(sur),
    ).json()["id"]
    assert next_period(client, sur, monthly, **later).status_code == 409

    plan = current_season(client, sur)
    elsewhere = on(client, sur, current_season(client, sur))
    refused = next_period(client, sur, plan, **later, membership_ids=[elsewhere["id"]])
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_on_plan"
    names = [p["name"] for p in client.get("/api/plans", headers=as_gym(sur)).json()]
    assert "Otra" not in names  # the copy went with the refusal


def test_a_plan_change_to_a_period_that_ended_is_refused(
    client: TestClient, sur: uuid.UUID
) -> None:
    today = seeded_today()
    membership = on(client, sur, current_season(client, sur))
    ended = season(client, sur, today - timedelta(days=60), today + timedelta(days=10))

    response = client.post(
        f"/api/memberships/{membership['id']}/plan-change",
        json={"plan_id": ended},
        headers=as_gym(sur),
    )

    assert response.status_code == 422
    assert "ended" in response.text


# --- the migration ------------------------------------------------------------------


def test_a_downgrade_makes_a_fixed_period_plan_prepaid() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        gym = uuid.uuid4()

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute("INSERT INTO gym (id, name, slug) VALUES ($1, 'g', 'g')", gym)
            await conn.execute(
                "INSERT INTO plan (gym_id, name, kind, price_clp, period_start, period_end)"
                " VALUES ($1, 'T', 'fixed_period', 1, '2027-03-01', '2027-12-31'),"
                " ($1, 'S', 'fixed_period', 1, '2027-03-01', '2027-03-15')",
                gym,
            )

        run(scratch.admin_url, seed)
        command.downgrade(scratch.alembic(), "0063")
        rows = run(
            scratch.admin_url,
            lambda c: c.fetch("SELECT name, kind, period_months FROM plan ORDER BY name"),
        )
        assert [tuple(r) for r in rows] == [("S", "prepaid", 1), ("T", "prepaid", 10)]
        migrate(scratch)
