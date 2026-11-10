"""The member list (Alumnos): search by name, phone or RUT, filter by status, plan and
program.

Each test seeds its own gym, so the list it reads holds exactly what it put there:
the seeded owner (active on "Mensual") plus the people it adds.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

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
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


_phones = iter(range(20_000_000, 100_000_000, 6_997))


def new_phone() -> str:
    return f"+569{next(_phones):08d}"


def as_owner(db: Database, gym: uuid.UUID, sql: str, *args: object) -> Any:
    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            return await conn.fetchval(sql, *args)

    return run(db.owner_url, query)


def add_plan(db: Database, gym: uuid.UUID, name: str) -> uuid.UUID:
    plan: uuid.UUID = as_owner(
        db,
        gym,
        "INSERT INTO plan (gym_id, name, kind, price_clp, anchor)"
        " VALUES ($1, $2, 'monthly', 1, 'signup')"
        " RETURNING id",
        gym,
        name,
    )
    return plan


def mensual(db: Database, gym: uuid.UUID) -> uuid.UUID:
    """The plan `seed_gym` gave the gym."""
    plan: uuid.UUID = as_owner(db, gym, "SELECT id FROM plan WHERE name = 'Mensual'")
    return plan


def join(
    db: Database, gym: uuid.UUID, person: str, plan: uuid.UUID, status: str, days_ago: int = 0
) -> str:
    started = datetime.now(UTC) - timedelta(days=days_ago)
    # A cancelled membership carries its reason and when (migration 0009).
    cancelled = status == "cancelled"
    membership = as_owner(
        db,
        gym,
        "INSERT INTO membership"
        " (gym_id, person_id, plan_id, status, started_at, cancel_reason, cancelled_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
        gym,
        uuid.UUID(person),
        plan,
        status,
        started,
        "se mudó" if cancelled else None,
        started if cancelled else None,
    )
    return str(membership)


def add_person(client: TestClient, gym: uuid.UUID, name: str, **fields: Any) -> str:
    body = {"phone": new_phone(), "name": name, **fields}
    response = client.post("/api/people", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    person: str = response.json()["id"]
    return person


def listing(client: TestClient, gym: uuid.UUID, **params: Any) -> Any:
    response = client.get("/api/people", params=params, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def names(client: TestClient, gym: uuid.UUID, **params: Any) -> list[str]:
    return [row["name"] for row in listing(client, gym, **params)["items"]]


def test_everyone_by_name_with_the_membership_shown(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan = add_plan(db, gym, "Mensual kids")
    tomas = add_person(client, gym, "Tomás Vera", rut="7.654.321-6")
    membership = join(db, gym, tomas, plan, "trial")
    add_person(client, gym, "ana Díaz")  # no membership yet: still listed

    body = listing(client, gym)
    owner = f"owner of {as_owner(db, gym, 'SELECT slug FROM gym')}"
    assert [row["name"] for row in body["items"]] == ["ana Díaz", owner, "Tomás Vera"]
    assert body["total"] == 3
    ana, _, row = body["items"]
    assert ana["membership"] is None
    assert row == {
        "id": tomas,
        "name": "Tomás Vera",
        "phone": row["phone"],
        "rut": "7654321-6",
        "membership": {
            "id": membership,
            "status": "trial",
            "plan_id": str(plan),
            "plan_name": "Mensual kids",
        },
        "guardian": None,
        "dependents": 0,
        "left_on": None,
    }


def test_staff_without_a_membership_are_not_members(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_person(client, gym, "Coach Rivas")
    as_owner(
        db,
        gym,
        "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')",
        gym,
        uuid.UUID(coach),
    )
    assert "Coach Rivas" not in names(client, gym)

    join(db, gym, coach, mensual(db, gym), "active")
    assert "Coach Rivas" in names(client, gym)


@pytest.mark.parametrize("q", ["martin", "MARTÍN", "nunez", "núñ", "  tín Nú  "])
def test_name_search_ignores_case_and_accents(client: TestClient, gym: uuid.UUID, q: str) -> None:
    add_person(client, gym, "Martín Núñez")
    add_person(client, gym, "Camila Rojas")
    assert names(client, gym, q=q) == ["Martín Núñez"]


@pytest.mark.parametrize("q", ["%", "_", "\\"])
def test_like_wildcards_are_matched_literally(client: TestClient, gym: uuid.UUID, q: str) -> None:
    add_person(client, gym, "Camila Rojas")
    add_person(client, gym, "100% Fuerza")
    assert names(client, gym, q=q) == (["100% Fuerza"] if q == "%" else [])


def test_phone_search_takes_any_format(client: TestClient, gym: uuid.UUID) -> None:
    phone = new_phone()  # +569XXXXXXXX
    add_person(client, gym, "Camila Rojas", phone=phone)
    add_person(client, gym, "Diego Soto")
    local = phone[4:]
    for q in (phone, phone[3:], f"9 {local[:4]} {local[4:]}", f"+56 9 {local}", local[-4:]):
        assert names(client, gym, q=q) == ["Camila Rojas"], q


def test_rut_search_takes_any_format(client: TestClient, gym: uuid.UUID) -> None:
    add_person(client, gym, "Camila Rojas", rut="7.654.321-6")
    add_person(client, gym, "Diego Soto", rut="76.123.456-0")
    for q in ("7.654.321-6", "7654321-6", "76543216", "7.654.321"):
        assert names(client, gym, q=q) == ["Camila Rojas"], q
    assert names(client, gym, q="123.456") == ["Diego Soto"]


def test_filters_by_status_and_plan(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    kids = add_plan(db, gym, "Mensual kids")
    monthly = mensual(db, gym)
    for name, plan, status in [
        ("Ana", kids, "active"),
        ("Bruno", kids, "lapsed"),
        ("Carla", monthly, "frozen"),
        ("Diego", monthly, "trial"),
    ]:
        join(db, gym, add_person(client, gym, name), plan, status)
    add_person(client, gym, "Elisa")  # no membership: matches no status or plan

    assert names(client, gym, status="lapsed") == ["Bruno"]
    assert names(client, gym, status=["frozen", "trial"]) == ["Carla", "Diego"]
    assert names(client, gym, plan_id=str(kids)) == ["Ana", "Bruno"]
    assert names(client, gym, plan_id=str(kids), status="active") == ["Ana"]
    assert names(client, gym, plan_id=str(kids), status="active", q="bru") == []
    assert names(client, gym, plan_id=str(monthly), q="di") == ["Diego"]
    assert listing(client, gym, plan_id=str(kids))["total"] == 2


def test_filters_by_program_through_the_plan(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    kids, adults = (
        as_owner(db, gym, "INSERT INTO program (gym_id, name) VALUES ($1, $2) RETURNING id", gym, n)
        for n in ("Kids", "Adultos")
    )
    kids_monthly, kids_pack = add_plan(db, gym, "Kids mensual"), add_plan(db, gym, "Kids pack")
    for plan in (kids_monthly, kids_pack):
        as_owner(db, gym, "UPDATE plan SET program_id = $1 WHERE id = $2", kids, plan)
    for name, plan in [("Ana", kids_monthly), ("Bruno", kids_pack), ("Carla", mensual(db, gym))]:
        join(db, gym, add_person(client, gym, name), plan, "active")

    assert names(client, gym, program_id=str(kids)) == ["Ana", "Bruno"]
    assert names(client, gym, program_id=str(kids), q="bru") == ["Bruno"]
    assert names(client, gym, program_id=[str(kids), str(adults)]) == ["Ana", "Bruno"]
    # "Mensual" names no program, so its members are in none.
    assert names(client, gym, program_id=str(adults)) == []


def test_the_row_shows_the_latest_membership_not_cancelled(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    kids = add_plan(db, gym, "Mensual kids")
    monthly = mensual(db, gym)
    ana = add_person(client, gym, "Ana")
    join(db, gym, ana, kids, "lapsed", days_ago=60)
    current = join(db, gym, ana, monthly, "active", days_ago=30)
    join(db, gym, ana, kids, "cancelled", days_ago=1)
    bruno = add_person(client, gym, "Bruno")
    join(db, gym, bruno, kids, "cancelled", days_ago=90)
    last = join(db, gym, bruno, monthly, "cancelled", days_ago=10)

    rows = {row["name"]: row["membership"] for row in listing(client, gym)["items"]}
    assert rows["Ana"]["id"] == current
    assert rows["Bruno"]["id"] == last
    # The filters read the row's membership, not any of the person's.
    assert names(client, gym, status="lapsed") == []
    assert names(client, gym, status="cancelled") == ["Bruno"]


def test_pages(client: TestClient, gym: uuid.UUID) -> None:
    for name in ("Carla Paz", "Ana Paz", "Diego Soto", "Bruno Paz"):
        add_person(client, gym, name)
    first = listing(client, gym, q="paz", limit=2)
    second = listing(client, gym, q="paz", limit=2, offset=2)
    beyond = listing(client, gym, q="paz", limit=2, offset=10)
    assert [r["name"] for r in first["items"]] == ["Ana Paz", "Bruno Paz"]
    assert [r["name"] for r in second["items"]] == ["Carla Paz"]
    assert beyond["items"] == []
    assert first["total"] == second["total"] == beyond["total"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {"status": "gone"},
        {"plan_id": "not-a-uuid"},
        {"program_id": "not-a-uuid"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"q": "x" * 101},
    ],
    ids=str,
)
def test_bad_parameters_are_refused(
    client: TestClient, gym: uuid.UUID, params: dict[str, Any]
) -> None:
    response = client.get("/api/people", params=params, headers=as_gym(gym))
    assert response.status_code == 422


def test_another_gyms_members_are_not_listed(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"other-{uuid.uuid4().hex[:8]}")
    phone = new_phone()
    shared = add_person(client, other, "Pedro de Norte", phone=phone, rut="7.654.321-6")
    join(db, other, shared, mensual(db, other), "active")
    add_person(client, other, "Luis")

    assert names(client, gym, q="pedro") == []
    assert names(client, gym, q=phone) == []
    assert names(client, gym, q="7654321") == []
    assert names(client, gym, plan_id=str(mensual(db, other))) == []
    assert listing(client, gym)["total"] == 1  # the owner

    # The same phone in this gym lists this gym's record only, without other's membership.
    add_person(client, gym, "Pedro", phone=phone)
    [row] = listing(client, gym, q=phone)["items"]
    assert (row["name"], row["rut"], row["membership"]) == ("Pedro", None, None)


def test_coaches_may_list_and_members_may_not(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = uuid.UUID(add_person(client, gym, "Coach"))
    as_owner(
        db, gym, "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')", gym, coach
    )
    member = uuid.UUID(add_person(client, gym, "Member"))
    assert client.get("/api/people", headers=as_gym(gym, coach)).status_code == 200
    assert client.get("/api/people", headers=as_gym(gym, member)).status_code == 403
    assert client.get("/api/people").status_code == 401
