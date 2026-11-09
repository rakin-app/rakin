"""Programs and class types (migration 0016): per-gym CRUD, unique names, no delete.

A program is the gym's own (adults, kids, competition); a class type belongs to one of
them and costs credits per attendance. A plan may name a program, which is how a member
is in it.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.main import create_app
from app.schemas.classes import MAX_CREDIT_COST, ClassTypeCreate, ClassTypeUpdate, ProgramUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_plans import DROPIN, MONTHLY, add_staff

# --- input rules, no database -----------------------------------------------------

PROGRAM = str(uuid.uuid4())


def test_a_class_type_costs_one_credit_unless_told() -> None:
    body = ClassTypeCreate.model_validate({"name": " Fundamentos ", "program_id": PROGRAM})
    assert (body.name, body.credit_cost) == ("Fundamentos", 1)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x"},  # no program
        {"name": " ", "program_id": PROGRAM},
        {"name": "x", "program_id": PROGRAM, "credit_cost": -1},
        {"name": "x", "program_id": PROGRAM, "credit_cost": MAX_CREDIT_COST + 1},
        {"name": "x", "program_id": PROGRAM, "active": False},
        {"name": "x", "program_id": "kids"},
    ],
    ids=str,
)
def test_create_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ClassTypeCreate.model_validate(body)


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (ProgramUpdate, {"name": None}),
        (ProgramUpdate, {"active": None}),
        (ProgramUpdate, {"gym_id": PROGRAM}),
        (ClassTypeUpdate, {"program_id": None}),
        (ClassTypeUpdate, {"credit_cost": None}),
        (ClassTypeUpdate, {"name": None}),
    ],
    ids=str,
)
def test_update_refuses_a_null(model: type[Any], body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(body)


# --- against real Postgres --------------------------------------------------------

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
def gym(db: Database) -> uuid.UUID:
    """A gym of its own per test, so a list holds exactly what the test made."""
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def program(client: TestClient, gym: uuid.UUID, name: str = "Kids") -> dict[str, Any]:
    response = client.post("/api/programs", json={"name": name}, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def class_type(client: TestClient, gym: uuid.UUID, body: dict[str, Any]) -> Any:
    return client.post("/api/class-types", json=body, headers=as_gym(gym))


def patch(client: TestClient, gym: uuid.UUID, path: str, body: dict[str, Any]) -> Any:
    return client.patch(path, json=body, headers=as_gym(gym))


@pg
def test_programs_are_created_listed_renamed_and_deactivated(
    client: TestClient, gym: uuid.UUID
) -> None:
    kids = program(client, gym, " Kids ")
    assert (kids["name"], kids["active"]) == ("Kids", True)
    adults = program(client, gym, "adultos")
    competition = program(client, gym, "Competición")

    off = patch(client, gym, f"/api/programs/{competition['id']}", {"active": False})
    assert off.json() == {**competition, "active": False}
    renamed = patch(client, gym, f"/api/programs/{adults['id']}", {"name": "Adultos"})
    assert renamed.json() == {**adults, "name": "Adultos"}

    listed = client.get("/api/programs", headers=as_gym(gym)).json()
    assert [p["name"] for p in listed] == ["Adultos", "Kids", "Competición"]
    active = client.get("/api/programs?active=true", headers=as_gym(gym)).json()
    assert [p["name"] for p in active] == ["Adultos", "Kids"]
    read = client.get(f"/api/programs/{kids['id']}", headers=as_gym(gym))
    assert read.json() == kids


@pg
def test_a_program_name_is_unique_in_the_gym_case_ignored(
    client: TestClient, gym: uuid.UUID, db: Database
) -> None:
    program(client, gym, "Kids")
    adults = program(client, gym, "Adultos")
    again = client.post("/api/programs", json={"name": "KIDS"}, headers=as_gym(gym))
    assert again.status_code == 409
    renamed = patch(client, gym, f"/api/programs/{adults['id']}", {"name": "kids"})
    assert renamed.status_code == 409
    # Another gym may have its own "Kids".
    program(client, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"), "Kids")


@pg
def test_class_types_are_created_read_edited_and_deactivated(
    client: TestClient, gym: uuid.UUID
) -> None:
    kids, adults = program(client, gym, "Kids"), program(client, gym, "Adultos")
    created = class_type(
        client, gym, {"name": "Open mat", "program_id": adults["id"], "credit_cost": 0}
    )
    assert created.status_code == 201, created.text
    open_mat = created.json()
    assert {k: open_mat[k] for k in ("name", "program_id", "program_name", "credit_cost")} == {
        "name": "Open mat",
        "program_id": adults["id"],
        "program_name": "Adultos",
        "credit_cost": 0,
    }
    assert open_mat["active"] is True

    moved = patch(
        client,
        gym,
        f"/api/class-types/{open_mat['id']}",
        {"program_id": kids["id"], "credit_cost": 2},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json() == {
        **open_mat,
        "program_id": kids["id"],
        "program_name": "Kids",
        "credit_cost": 2,
    }
    off = patch(client, gym, f"/api/class-types/{open_mat['id']}", {"active": False})
    assert off.json()["active"] is False
    read = client.get(f"/api/class-types/{open_mat['id']}", headers=as_gym(gym))
    assert read.json() == off.json()


@pg
def test_class_types_list_by_program_and_filter(client: TestClient, gym: uuid.UUID) -> None:
    kids, adults = program(client, gym, "Kids"), program(client, gym, "Adultos")
    for name, prog in [("Kids 8 a 12", kids), ("Avanzado", adults), ("Fundamentos", adults)]:
        class_type(client, gym, {"name": name, "program_id": prog["id"]})
    old = class_type(client, gym, {"name": "Viejo", "program_id": adults["id"]}).json()
    patch(client, gym, f"/api/class-types/{old['id']}", {"active": False})

    def listed(**params: Any) -> list[str]:
        response = client.get("/api/class-types", params=params, headers=as_gym(gym))
        assert response.status_code == 200, response.text
        return [c["name"] for c in response.json()]

    assert listed() == ["Avanzado", "Fundamentos", "Kids 8 a 12", "Viejo"]
    assert listed(active="true") == ["Avanzado", "Fundamentos", "Kids 8 a 12"]
    assert listed(program_id=kids["id"]) == ["Kids 8 a 12"]
    assert listed(program_id=adults["id"], active="false") == ["Viejo"]


@pg
def test_a_class_type_name_is_unique_within_its_program(client: TestClient, gym: uuid.UUID) -> None:
    kids, adults = program(client, gym, "Kids"), program(client, gym, "Adultos")
    assert (
        class_type(client, gym, {"name": "Fundamentos", "program_id": kids["id"]}).status_code
        == 201
    )
    other = class_type(client, gym, {"name": "Fundamentos", "program_id": adults["id"]})
    assert other.status_code == 201
    again = class_type(client, gym, {"name": "fundamentos", "program_id": kids["id"]})
    assert again.status_code == 409
    moved = patch(client, gym, f"/api/class-types/{other.json()['id']}", {"program_id": kids["id"]})
    assert moved.status_code == 409


@pg
def test_a_class_type_needs_one_of_the_gyms_programs(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other_gym = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    theirs = program(client, other_gym, "Kids")
    ours = program(client, gym, "Kids")
    mine = class_type(client, gym, {"name": "Fundamentos", "program_id": ours["id"]}).json()

    for program_id in (theirs["id"], str(uuid.uuid4())):
        created = class_type(client, gym, {"name": "x", "program_id": program_id})
        assert created.status_code == 422
        assert [e["loc"] for e in created.json()["detail"]] == [["body", "program_id"]]
        moved = patch(client, gym, f"/api/class-types/{mine['id']}", {"program_id": program_id})
        assert moved.status_code == 422


@pg
def test_another_gyms_programs_and_class_types_are_not_found(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other_gym = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    kids = program(client, gym, "Kids")
    fundamentals = class_type(client, gym, {"name": "F", "program_id": kids["id"]}).json()
    for path in (f"/api/programs/{kids['id']}", f"/api/class-types/{fundamentals['id']}"):
        assert client.get(path, headers=as_gym(other_gym)).status_code == 404
        assert patch(client, other_gym, path, {"active": False}).status_code == 404
        assert client.get(path, headers=as_gym(gym)).json()["active"] is True
    assert client.get("/api/programs", headers=as_gym(other_gym)).json() == []
    assert client.get("/api/class-types", headers=as_gym(other_gym)).json() == []


@pg
def test_there_is_no_delete(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    kids = program(client, gym, "Kids")
    fundamentals = class_type(client, gym, {"name": "F", "program_id": kids["id"]}).json()
    for path in (f"/api/programs/{kids['id']}", f"/api/class-types/{fundamentals['id']}"):
        assert client.delete(path, headers=as_gym(gym)).status_code == 405
    for table, row in (("class_type", fundamentals), ("program", kids)):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(gym, f"DELETE FROM {table} WHERE id = $1", uuid.UUID(row["id"])))


@pg
@pytest.mark.parametrize(("role", "writes"), [("admin", True), ("coach", False)])
def test_coaches_read_and_only_owner_or_admin_change(
    client: TestClient, db: Database, gym: uuid.UUID, role: str, writes: bool
) -> None:
    kids = program(client, gym, "Kids")
    fundamentals = class_type(client, gym, {"name": "F", "program_id": kids["id"]}).json()
    headers = as_gym(gym, add_staff(db, gym, role))

    for path in ("/api/programs", "/api/class-types"):
        assert client.get(path, headers=headers).status_code == 200
    assert client.get(f"/api/programs/{kids['id']}", headers=headers).status_code == 200
    assert client.get(f"/api/class-types/{fundamentals['id']}", headers=headers).status_code == 200

    statuses = (
        client.post("/api/programs", json={"name": f"P {role}"}, headers=headers).status_code,
        client.patch(
            f"/api/programs/{kids['id']}", json={"active": True}, headers=headers
        ).status_code,
        client.post(
            "/api/class-types",
            json={"name": f"C {role}", "program_id": kids["id"]},
            headers=headers,
        ).status_code,
        client.patch(
            f"/api/class-types/{fundamentals['id']}", json={"credit_cost": 2}, headers=headers
        ).status_code,
    )
    assert statuses == ((201, 200, 201, 200) if writes else (403, 403, 403, 403))


@pg
def test_members_may_not_use_them(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    member = uuid.uuid4()
    run(
        db.admin_url,
        lambda c: c.execute("INSERT INTO person (id, name) VALUES ($1, 'm')", member),
    )
    for path in ("/api/programs", "/api/class-types"):
        assert client.get(path, headers=as_gym(gym, member)).status_code == 403


# --- a plan's program --------------------------------------------------------------


@pg
def test_a_plan_names_its_program_and_can_leave_it(client: TestClient, gym: uuid.UUID) -> None:
    kids = program(client, gym, "Kids")
    created = client.post(
        "/api/plans", json={**MONTHLY, "program_id": kids["id"]}, headers=as_gym(gym)
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["program_id"] == kids["id"]

    dropin = client.post("/api/plans", json=DROPIN, headers=as_gym(gym)).json()
    assert dropin["program_id"] is None
    joined = patch(client, gym, f"/api/plans/{dropin['id']}", {"program_id": kids["id"]})
    assert joined.json()["program_id"] == kids["id"]

    left = patch(client, gym, f"/api/plans/{plan['id']}", {"program_id": None})
    assert left.status_code == 200
    assert left.json() == {**plan, "program_id": None}


@pg
def test_a_plan_needs_one_of_the_gyms_programs(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    theirs = program(client, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"), "Kids")
    plan = client.post("/api/plans", json=DROPIN, headers=as_gym(gym)).json()
    for program_id in (theirs["id"], str(uuid.uuid4())):
        body = {**DROPIN, "program_id": program_id}
        created = client.post("/api/plans", json=body, headers=as_gym(gym))
        assert created.status_code == 422
        assert [e["loc"] for e in created.json()["detail"]] == [["body", "program_id"]]
        edited = patch(client, gym, f"/api/plans/{plan['id']}", {"program_id": program_id})
        assert edited.status_code == 422


# --- the tables on their own (migration 0016) --------------------------------------


@pg
@pytest.mark.parametrize("table", ["class_type", "plan"])
def test_a_row_cannot_name_another_gyms_program(
    client: TestClient, db: Database, gym: uuid.UUID, table: str
) -> None:
    # As the superuser, past RLS: the foreign key alone holds it to the gym.
    theirs = uuid.UUID(program(client, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"))["id"])
    insert = {
        "class_type": "INSERT INTO class_type (gym_id, program_id, name) VALUES ($1, $2, 'x')",
        "plan": "INSERT INTO plan (gym_id, program_id, name, kind, price_clp)"
        " VALUES ($1, $2, 'x', 'dropin', 1)",
    }[table]
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        run(db.admin_url, lambda c: c.execute(insert, gym, theirs))


@pg
def test_the_table_refuses_a_negative_cost_or_blank_name(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    kids = uuid.UUID(program(client, gym)["id"])
    insert = (
        "INSERT INTO class_type (gym_id, program_id, name, credit_cost) VALUES ($1, $2, $3, $4)"
    )
    for name, cost in (("x", -1), (" ", 1)):
        with pytest.raises(asyncpg.CheckViolationError):
            run(db.owner_url, in_gym(gym, insert, gym, kids, name, cost))


@pg
def test_upgrade_and_downgrade() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0015")
        tables = "SELECT to_regclass('program') IS NULL AND to_regclass('class_type') IS NULL"
        assert run(scratch.admin_url, lambda c: c.fetchval(tables)) is True
        column = (
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'plan' AND column_name = 'program_id'"
        )
        assert run(scratch.admin_url, lambda c: c.fetchval(column)) == 0
        migrate(scratch)


@pg
def test_nothing_newly_names_a_deactivated_program(client: TestClient, gym: uuid.UUID) -> None:
    kids, old = program(client, gym, "Kids"), program(client, gym, "Antiguo")
    fundamentals = class_type(client, gym, {"name": "F", "program_id": old["id"]}).json()
    plan = client.post(
        "/api/plans", json={**MONTHLY, "program_id": old["id"]}, headers=as_gym(gym)
    ).json()
    dropin = client.post("/api/plans", json=DROPIN, headers=as_gym(gym)).json()
    patch(client, gym, f"/api/programs/{old['id']}", {"active": False})

    def refused(response: Any) -> None:
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert [(e["type"], e["loc"]) for e in detail] == [
            ("inactive_program", ["body", "program_id"])
        ]

    refused(class_type(client, gym, {"name": "x", "program_id": old["id"]}))
    refused(
        client.post("/api/plans", json={**DROPIN, "program_id": old["id"]}, headers=as_gym(gym))
    )
    moved = patch(client, gym, f"/api/class-types/{fundamentals['id']}", {"program_id": kids["id"]})
    refused(patch(client, gym, f"/api/class-types/{moved.json()['id']}", {"program_id": old["id"]}))
    refused(patch(client, gym, f"/api/plans/{dropin['id']}", {"program_id": old["id"]}))

    # What already names it keeps it, and may be edited, naming it again or not.
    kept = patch(client, gym, f"/api/plans/{plan['id']}", {"program_id": old["id"], "price_clp": 1})
    assert (kept.status_code, kept.json()["program_id"]) == (200, old["id"])
    other = class_type(client, gym, {"name": "G", "program_id": kids["id"]}).json()
    patch(client, gym, f"/api/programs/{old['id']}", {"active": True})
    patch(client, gym, f"/api/class-types/{other['id']}", {"program_id": old["id"]})
    patch(client, gym, f"/api/programs/{old['id']}", {"active": False})
    renamed = patch(
        client, gym, f"/api/class-types/{other['id']}", {"program_id": old["id"], "name": "H"}
    )
    assert (renamed.status_code, renamed.json()["program_name"]) == (200, "Antiguo")


@pg
def test_an_unknown_program_says_so(client: TestClient, gym: uuid.UUID) -> None:
    response = class_type(client, gym, {"name": "x", "program_id": str(uuid.uuid4())})
    assert [e["type"] for e in response.json()["detail"]] == ["unknown_program"]
