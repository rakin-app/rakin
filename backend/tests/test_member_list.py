"""The member list (Alumnos): search by name, phone or RUT, filter by status, plan,
program and belt.

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
from app.schemas.grading import PRESETS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
from tests.pg import Database, migrate, run, seed_gym, seeded_today, throwaway_database

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
    # Someone is their RUT, or an email (0036): a made-up RUT unless either is given.
    key = {} if fields.keys() & {"rut", "email"} else {"rut": random_rut()}
    body = {"phone": new_phone(), "name": name, **key, **fields}
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
        "no_whatsapp": False,
        "missing_phone": False,
        "missing_rut": False,
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
        "owes": False,
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


def use_scheme(client: TestClient, gym: uuid.UUID, preset: str) -> None:
    scheme = next(p.scheme.model_dump() for p in PRESETS if p.key == preset)
    response = client.put("/api/gym/grading-scheme", json=scheme, headers=as_gym(gym))
    assert response.status_code == 200, response.text


def promote(client: TestClient, gym: uuid.UUID, person: str, rank_key: str) -> None:
    rank = client.get("/api/gym/grading-scheme", headers=as_gym(gym)).json()
    sub_ranks = next(
        r["sub_ranks"] for r in rank["ranks"] + rank["kids_ladder"] if r["key"] == rank_key
    )
    body = {"rank_key": rank_key, "sub_rank": sub_ranks[0]["key"] if sub_ranks else None}
    response = client.post(f"/api/people/{person}/grades", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text


def test_filters_by_belt_exactly_and_at_least(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    use_scheme(client, gym, "bjj")
    monthly = mensual(db, gym)
    people = {}
    for name in ("Ana", "Bruno", "Carla", "Diego", "Elisa", "Felipe"):
        people[name] = add_person(client, gym, name)
        join(db, gym, people[name], monthly, "active")
    promote(client, gym, people["Ana"], "white")
    promote(client, gym, people["Bruno"], "blue")
    promote(client, gym, people["Carla"], "purple")
    promote(client, gym, people["Diego"], "black")
    promote(client, gym, people["Elisa"], "grey")  # a kids belt, on its own ladder
    # Felipe was blue, and is purple now: his latest promotion is his belt.
    promote(client, gym, people["Felipe"], "blue")
    promote(client, gym, people["Felipe"], "purple")

    assert names(client, gym, rank="blue") == ["Bruno"]
    assert names(client, gym, rank=["purple", "white"]) == ["Ana", "Carla", "Felipe"]
    assert names(client, gym, rank_min="blue") == ["Bruno", "Carla", "Diego", "Felipe"]
    assert names(client, gym, rank_min="purple", q="fel") == ["Felipe"]
    assert names(client, gym, rank_min="black") == ["Diego"]
    # "Blanca o superior" is every adult belt, not the kids' ladder, nor the unranked.
    assert names(client, gym, rank_min="white") == ["Ana", "Bruno", "Carla", "Diego", "Felipe"]
    assert names(client, gym, rank_min="grey") == ["Elisa"]
    assert names(client, gym, rank="purple", rank_min="blue") == ["Carla", "Felipe"]
    assert listing(client, gym, rank_min="blue")["total"] == 4
    assert names(client, gym, rank="red") == []


def test_belt_order_is_the_schemes_for_any_sport(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    use_scheme(client, gym, "judo-karate")
    monthly = mensual(db, gym)
    for name, rank in [
        ("Ana", "kyu-10"),
        ("Bruno", "kyu-1"),
        ("Carla", "dan-1"),
        ("Diego", "dan-3"),
    ]:
        person = add_person(client, gym, name)
        join(db, gym, person, monthly, "active")
        promote(client, gym, person, rank)

    # Kyu count down and dan up: "1.º kyu o superior" is by the scheme's order, not the key's.
    assert names(client, gym, rank_min="kyu-1") == ["Bruno", "Carla", "Diego"]
    assert names(client, gym, rank_min="dan-2") == ["Diego"]
    assert names(client, gym, rank="kyu-10") == ["Ana"]


def test_an_unknown_rank_min_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    # The seeded gym has no scheme: no rank to be above.
    response = client.get("/api/people", params={"rank_min": "blue"}, headers=as_gym(gym))
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "unknown_rank"}
    use_scheme(client, gym, "bjj")
    response = client.get("/api/people", params={"rank_min": "red"}, headers=as_gym(gym))
    assert response.json()["detail"] == {"code": "unknown_rank"}


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
        {"rank_min": "x" * 41},
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

    # The same person in this gym lists this gym's record only, without other's membership.
    add_person(client, gym, "Pedro", phone=phone, rut="7.654.321-6")
    [row] = listing(client, gym, q=phone)["items"]
    assert (row["name"], row["membership"]) == ("Pedro", None)


def open_period(db: Database, gym: uuid.UUID, membership: str, due: str) -> str:
    """A month of 45.000 for `membership`, falling due on `due`, with its charge."""

    async def query(conn: asyncpg.Connection) -> str:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            period = await conn.fetchval(
                "INSERT INTO billing_period"
                " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
                " VALUES ($1, $2, $3::date, $3::date + 29, 45000, $3::date) RETURNING id",
                gym,
                uuid.UUID(membership),
                datetime.fromisoformat(due).date(),
            )
            await conn.execute(
                "INSERT INTO ledger_entry"
                " (gym_id, membership_id, billing_period_id, amount_clp, kind)"
                " VALUES ($1, $2, $3, 45000, 'charge')",
                gym,
                uuid.UUID(membership),
                period,
            )
            return str(period)

    return str(run(db.owner_url, query))


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> None:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "method": "cash",
    }
    response = client.post("/api/ledger/payments", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text


def owing(client: TestClient, gym: uuid.UUID, **headers: Any) -> dict[str, bool]:
    response = client.get("/api/people", headers=as_gym(gym, **headers))
    assert response.status_code == 200, response.text
    return {row["name"]: row["owes"] for row in response.json()["items"]}


def test_owes_is_a_period_not_settled_due_or_not(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan = mensual(db, gym)
    today = seeded_today()
    late = join(db, gym, add_person(client, gym, "Ana"), plan, "lapsed")
    open_period(db, gym, late, (today - timedelta(days=10)).isoformat())
    soon = join(db, gym, add_person(client, gym, "Bruno"), plan, "active")
    open_period(db, gym, soon, (today + timedelta(days=5)).isoformat())
    part = join(db, gym, add_person(client, gym, "Carla"), plan, "active")
    pay(client, gym, part, open_period(db, gym, part, today.isoformat()), 20_000)
    paid = join(db, gym, add_person(client, gym, "Diego"), plan, "active")
    pay(client, gym, paid, open_period(db, gym, paid, today.isoformat()), 45_000)
    join(db, gym, add_person(client, gym, "Elisa"), plan, "active")  # no period yet
    add_person(client, gym, "Fabián")  # no membership

    rows = owing(client, gym)
    assert {name: owes for name, owes in rows.items() if not name.startswith("owner")} == {
        "Ana": True,
        "Bruno": True,
        "Carla": True,
        "Diego": False,
        "Elisa": False,
        "Fabián": False,
    }

    # A coach never sees money: nobody owes on their list.
    coach = uuid.UUID(add_person(client, gym, "Coach"))
    as_owner(
        db, gym, "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')", gym, coach
    )
    assert not any(owing(client, gym, person_id=coach).values())


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
