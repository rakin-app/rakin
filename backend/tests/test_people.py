"""People: create and edit by phone, and what one gym can learn about another's members.

Identity is global by phone, so the cross-tenant tests ask the question a curious
admin would: having typed a phone that another gym already has, can they tell? The
answer, the record they then read, and the database grants must all say no.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.domain.rut import check_digit, format_rut
from app.main import create_app
from app.schemas.people import PersonCreate, PersonUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

# --- input rules, no database -----------------------------------------------------


def test_create_normalises_phone_and_rut() -> None:
    body = PersonCreate(
        phone="9 8765 4321", name="  Camila Rojas ", email=" camila@example.com", rut="7.654.321-6"
    )
    assert (body.phone, body.name, body.email, body.rut) == (
        "+56987654321",
        "Camila Rojas",
        "camila@example.com",
        "7654321-6",
    )


@pytest.mark.parametrize(
    "field",
    [
        {"phone": "22 345 6789"},  # a landline
        {"phone": "+54 9 11 2345 6789"},
        {"name": "   "},
        {"email": "camila"},
        {"email": "+56912345678"},
        {"rut": "7.654.321-5"},
        # system date: pydantic's `PastDate` checks against the host's today.
        {"dob": (date.today() + timedelta(days=1)).isoformat()},
        {"gym_id": str(uuid.uuid4())},
    ],
    ids=str,
)
def test_create_refuses(field: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        PersonCreate.model_validate({"phone": "+56912345678", "name": "Camila", **field})


def test_create_needs_a_phone_and_a_name() -> None:
    with pytest.raises(ValidationError):
        PersonCreate.model_validate({"name": "Camila"})
    with pytest.raises(ValidationError):
        PersonCreate.model_validate({"phone": "+56912345678"})


def test_update_takes_only_the_fields_sent() -> None:
    body = PersonUpdate.model_validate({"email": None, "rut": "76.123.456-0"})
    assert body.model_dump(exclude_unset=True) == {"email": None, "rut": "76123456-0"}


@pytest.mark.parametrize("field", [{"phone": "+56912345678"}, {"name": None}], ids=str)
def test_update_refuses(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PersonUpdate.model_validate(field)


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres

# The fields a gym enters, in the normalised form it gets back.
CAMILA = {
    "phone": "+56987654321",
    "name": "Camila Rojas",
    "email": "camila@example.com",
    "rut": "7654321-6",
    "dob": "1994-03-12",
}


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def norte(db: Database) -> uuid.UUID:
    return seed_gym(db, "dojo-norte")


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


_phones = iter(range(10_000_000, 100_000_000, 7_919))


def new_phone() -> str:
    return f"+569{next(_phones):08d}"


_ruts = iter(range(10_000_000, 30_000_000, 7_919))


def new_rut() -> str:
    """A RUT no one in these tests has yet, normalised: a gym holds each RUT once."""
    body = next(_ruts)
    return f"{body}-{check_digit(body)}"


def create(client: TestClient, gym: uuid.UUID, **fields: Any) -> Any:
    return client.post("/api/people", json=fields, headers=as_gym(gym))


def entered(body: dict[str, Any]) -> dict[str, Any]:
    """A response without the fields the gym did not type."""
    return {k: v for k, v in body.items() if k not in ("id", "left_on", "created_at", "updated_at")}


def people_with_phone(db: Database, phone: str) -> list[asyncpg.Record]:
    return list(
        run(db.admin_url, lambda c: c.fetch("SELECT * FROM person WHERE phone = $1", phone))
    )


@pg
def test_create_then_read(client: TestClient, sur: uuid.UUID) -> None:
    phone = new_phone()
    response = create(client, sur, **{**CAMILA, "phone": phone[3:]})  # typed as 9XXXXXXXX
    assert response.status_code == 201
    body = response.json()
    assert entered(body) == {**CAMILA, "phone": phone}

    read = client.get(f"/api/people/{body['id']}", headers=as_gym(sur))
    assert read.status_code == 200
    assert read.json() == body


@pg
def test_optional_fields_may_be_left_out(client: TestClient, sur: uuid.UUID) -> None:
    phone = new_phone()
    response = create(client, sur, phone=phone, name="Diego")
    assert response.status_code == 201
    assert entered(response.json()) == {
        "phone": phone,
        "name": "Diego",
        "email": None,
        "rut": None,
        "dob": None,
    }


@pg
def test_a_phone_already_in_this_gym_names_that_person(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    phone = new_phone()
    first = create(client, sur, **{**CAMILA, "phone": phone, "rut": new_rut()}).json()

    again = create(client, sur, phone=phone, name="Someone else")
    assert again.status_code == 409
    assert again.json() == {"detail": {"code": "phone_in_gym", "person_id": first["id"]}}
    # Offered, not applied: the record is as it was.
    assert client.get(f"/api/people/{first['id']}", headers=as_gym(sur)).json() == first
    assert len(people_with_phone(db, phone)) == 1


@pg
def test_a_phone_known_elsewhere_answers_like_a_new_one(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    known = new_phone()
    norte_body = create(
        client, norte, phone=known, name="Camila R.", email="cr@norte.cl", rut="76.123.456-0"
    ).json()

    before = datetime.now(UTC)
    fresh = create(client, sur, **{**CAMILA, "phone": new_phone(), "rut": new_rut()})
    camila = {**CAMILA, "phone": known, "rut": new_rut()}
    attached = create(client, sur, **camila)

    # Same status, same shape, and only what sur typed: nothing of norte's record.
    assert attached.status_code == fresh.status_code == 201
    assert set(attached.json()) == set(fresh.json())
    assert entered(attached.json()) == camila
    assert {k: v for k, v in entered(fresh.json()).items() if k not in ("phone", "rut")} == {
        k: v for k, v in entered(attached.json()).items() if k not in ("phone", "rut")
    }
    # This gym's timestamps, not the identity's.
    for field in ("created_at", "updated_at"):
        assert datetime.fromisoformat(attached.json()[field]) >= before

    # One person, now in both gyms, each with its own record.
    [person] = people_with_phone(db, known)
    assert str(person["id"]) == attached.json()["id"] == norte_body["id"]
    sur_view = client.get(f"/api/people/{person['id']}", headers=as_gym(sur)).json()
    norte_view = client.get(f"/api/people/{person['id']}", headers=as_gym(norte)).json()
    assert sur_view == attached.json()
    assert norte_view == norte_body


@pg
def test_attaching_does_not_reveal_the_other_gyms_memberships(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    phone = new_phone()
    person_id = uuid.UUID(create(client, norte, phone=phone, name="Ana").json()["id"])

    async def join_norte_plan(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(norte))
            await conn.execute(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " SELECT gym_id, $1, id, 'active' FROM plan",
                person_id,
            )

    run(db.owner_url, join_norte_plan)
    assert create(client, sur, phone=phone, name="Ana").status_code == 201

    memberships = "SELECT gym_id FROM membership WHERE person_id = $1"
    records = "SELECT gym_id FROM gym_person WHERE person_id = $1"
    for query in (memberships, records):
        found = run(db.api_url, in_gym(sur, query, person_id))
        assert {r["gym_id"] for r in found} <= {sur}


@pg
def test_an_edit_stays_in_its_gym(client: TestClient, sur: uuid.UUID, norte: uuid.UUID) -> None:
    phone = new_phone()
    norte_body = create(client, norte, phone=phone, name="Pedro", email="p@norte.cl").json()
    create(client, sur, phone=phone, name="Pedro", email="p@sur.cl")
    person = norte_body["id"]

    rut = new_rut()
    edit = {"name": "Pedro Soto", "email": None, "rut": format_rut(rut), "dob": "2001-07-30"}
    response = client.patch(f"/api/people/{person}", json=edit, headers=as_gym(sur))
    assert response.status_code == 200
    assert entered(response.json()) == {**edit, "phone": phone, "rut": rut}
    assert response.json()["updated_at"] > response.json()["created_at"]

    assert client.get(f"/api/people/{person}", headers=as_gym(norte)).json() == norte_body


@pg
def test_an_edit_changes_only_the_fields_sent(client: TestClient, sur: uuid.UUID) -> None:
    body = create(client, sur, **{**CAMILA, "phone": new_phone(), "rut": new_rut()}).json()
    response = client.patch(f"/api/people/{body['id']}", json={"dob": None}, headers=as_gym(sur))
    assert entered(response.json()) == {**entered(body), "dob": None}


@pg
@pytest.mark.parametrize("edit", [{"phone": "+56911112222"}, {"name": None}, {"rut": "1-1"}])
def test_an_invalid_edit_is_refused(
    client: TestClient, sur: uuid.UUID, edit: dict[str, Any]
) -> None:
    body = create(client, sur, **{**CAMILA, "phone": new_phone(), "rut": new_rut()}).json()
    response = client.patch(f"/api/people/{body['id']}", json=edit, headers=as_gym(sur))
    assert response.status_code == 422
    assert client.get(f"/api/people/{body['id']}", headers=as_gym(sur)).json() == body


@pg
def test_another_gyms_member_is_not_found_like_nobody(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    theirs = create(client, norte, phone=new_phone(), name="Luis").json()["id"]
    nobody = str(uuid.uuid4())
    for person in (theirs, nobody):
        assert client.get(f"/api/people/{person}", headers=as_gym(sur)).status_code == 404
        patch = client.patch(f"/api/people/{person}", json={"name": "x"}, headers=as_gym(sur))
        assert patch.status_code == 404
        assert (
            client.patch(f"/api/people/{person}", json={}, headers=as_gym(sur)).status_code == 404
        )
    assert client.get(f"/api/people/{theirs}", headers=as_gym(norte)).json()["name"] == "Luis"


# --- join_gym_by_phone, query by query (migration 0004) ----------------------------

JOIN = "SELECT * FROM join_gym_by_phone($1, 'x', NULL, NULL, NULL)"


@pg
def test_joining_needs_a_gym(db: Database) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match=r"app\.gym_id"):
        run(db.api_url, in_gym(None, JOIN, new_phone()))


@pg
def test_the_lookup_ends_with_the_function(db: Database, sur: uuid.UUID) -> None:
    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await conn.fetch(JOIN, new_phone())
            return await conn.fetchval("SELECT current_setting('app.person_lookup', true)")

    for url in (db.api_url, db.owner_url):
        assert run(url, query) == "off"


@pg
@pytest.mark.parametrize("user", ["api", "owner"])
def test_outside_the_function_the_lookup_opens_nothing_to_the_api(
    db: Database, sur: uuid.UUID, norte: uuid.UUID, user: str
) -> None:
    async def visible(conn: asyncpg.Connection, lookup: str) -> set[uuid.UUID]:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await conn.execute("SELECT set_config('app.person_lookup', $1, true)", lookup)
            return {r["id"] for r in await conn.fetch("SELECT id FROM person")}

    async def compare(conn: asyncpg.Connection) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
        return await visible(conn, "off"), await visible(conn, "on")

    off, on = run(db.api_url if user == "api" else db.owner_url, compare)
    if user == "api":
        assert on == off
    else:
        # The owner's deliberate override, which is what the function relies on.
        assert on > off


@pg
@pytest.mark.parametrize("table", ["membership", "staff"])
def test_a_gym_holds_rows_only_for_people_it_has_a_record_of(
    db: Database, sur: uuid.UUID, norte: uuid.UUID, table: str
) -> None:
    insert = {
        "membership": "INSERT INTO membership (gym_id, person_id, plan_id, status)"
        " SELECT $1, $2, id, 'active' FROM plan WHERE gym_id = $1",
        "staff": "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')",
    }[table]

    # As the owner, in the gym, so RLS allows the row and only the foreign key refuses.
    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(norte))
            person = uuid.uuid4()
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                norte,
                person,
            )
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await conn.execute(insert, sur, person)

    with pytest.raises(asyncpg.ForeignKeyViolationError, match=f"{table}_gym_person_fkey"):
        run(db.owner_url, query)


@pg
def test_backfill_gives_every_member_and_staff_a_record() -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0003")
        gym, owner, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        async def seed(conn: asyncpg.Connection) -> None:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
                await conn.execute("INSERT INTO gym (id, name, slug) VALUES ($1, 'g', 'g')", gym)
                await conn.execute(
                    "INSERT INTO person (id, name, phone, rut)"
                    " VALUES ($1, 'Owner', NULL, NULL), ($2, 'Member', '+56912345678', '1-9')",
                    owner,
                    member,
                )
                await conn.execute(
                    "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'owner')",
                    gym,
                    owner,
                )
                plan = await conn.fetchval(
                    "INSERT INTO plan (gym_id, name, kind, price_clp)"
                    " VALUES ($1, 'M', 'monthly', 1) RETURNING id",
                    gym,
                )
                for person in (owner, member):
                    await conn.execute(
                        "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                        " VALUES ($1, $2, $3, 'active')",
                        gym,
                        person,
                        plan,
                    )

        run(db.owner_url, seed)
        migrate(db)

        rows = run(
            db.api_url,
            in_gym(gym, "SELECT person_id, name, rut FROM gym_person ORDER BY name"),
        )
        assert [tuple(r) for r in rows] == [(member, "Member", "1-9"), (owner, "Owner", None)]
        command.downgrade(db.alembic(), "0003")
