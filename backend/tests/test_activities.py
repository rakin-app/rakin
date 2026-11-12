"""Gym activities (#245, migration 0043).

An owner or admin keeps what the gym teaches, each activity with whether it grades;
any staff role reads them. A class type may belong to one. `/api/me/role` says
whether any activity grades, which is what decides every belt on the gym's screens.
The migration gives a gym that grades today a graded "BJJ", and every other gym none.
"""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import class_type, program
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
def gym(db: Database) -> uuid.UUID:
    return another_gym(db)


def another_gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def add(client: TestClient, gym: uuid.UUID, name: str, uses_grades: bool = False) -> dict[str, Any]:
    body = {"name": name, "uses_grades": uses_grades}
    response = client.post("/api/activities", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    made: dict[str, Any] = response.json()
    return made


def listed(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> Any:
    response = client.get("/api/activities", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def uses_grades(client: TestClient, gym: uuid.UUID) -> bool:
    response = client.get("/api/me/role", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return bool(response.json()["uses_grades"])


@pg
def test_a_new_gym_teaches_nothing_and_does_not_grade(client: TestClient, gym: uuid.UUID) -> None:
    assert listed(client, gym) == []
    assert not uses_grades(client, gym)


@pg
def test_an_admin_adds_renames_and_removes_activities(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    admin = add_staff(db, gym, "admin")
    response = client.post(
        "/api/activities", json={"name": "  Ballet "}, headers=as_gym(gym, admin)
    )
    assert response.status_code == 201, response.text
    ballet = response.json()
    assert (ballet["name"], ballet["uses_grades"], ballet["class_types"]) == ("Ballet", False, 0)
    bjj = add(client, gym, "BJJ", uses_grades=True)

    assert [a["name"] for a in listed(client, gym)] == ["Ballet", "BJJ"]

    renamed = client.patch(
        f"/api/activities/{ballet['id']}", json={"name": "Danza"}, headers=as_gym(gym, admin)
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["uses_grades"]) == ("Danza", False)

    gone = client.delete(f"/api/activities/{bjj['id']}", headers=as_gym(gym, admin))
    assert gone.status_code == 204, gone.text
    assert [a["name"] for a in listed(client, gym)] == ["Danza"]
    again = client.delete(f"/api/activities/{bjj['id']}", headers=as_gym(gym, admin))
    assert again.status_code == 404


@pg
def test_a_name_is_unique_in_the_gym_case_ignored(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    add(client, gym, "Judo")
    taken = client.post("/api/activities", json={"name": "JUDO"}, headers=as_gym(gym))
    assert taken.status_code == 409
    karate = add(client, gym, "Karate")
    renamed = client.patch(
        f"/api/activities/{karate['id']}", json={"name": "judo"}, headers=as_gym(gym)
    )
    assert renamed.status_code == 409
    # Another gym may have its own.
    add(client, another_gym(db), "Judo")


@pytest.mark.parametrize("body", [{"name": ""}, {"name": None}, {"uses_grades": None}])
@pg
def test_nothing_is_cleared(client: TestClient, gym: uuid.UUID, body: dict[str, Any]) -> None:
    judo = add(client, gym, "Judo")
    response = client.patch(f"/api/activities/{judo['id']}", json=body, headers=as_gym(gym))
    assert response.status_code == 422


@pg
def test_a_coach_reads_them_and_changes_none(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    judo = add(client, gym, "Judo", uses_grades=True)
    coach = add_staff(db, gym, "coach")
    assert [a["name"] for a in listed(client, gym, coach)] == ["Judo"]
    for method, path, body in [
        ("POST", "/api/activities", {"name": "Karate"}),
        ("PATCH", f"/api/activities/{judo['id']}", {"uses_grades": False}),
        ("DELETE", f"/api/activities/{judo['id']}", None),
    ]:
        response = client.request(method, path, json=body, headers=as_gym(gym, coach))
        assert response.status_code == 403, (method, response.text)


@pg
def test_a_member_reads_none(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    member = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", member)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, member
        )

    run(db.admin_url, query)
    response = client.get("/api/activities", headers=as_gym(gym, member))
    assert response.status_code == 403
    # But their role says whether the gym grades, for the belt on their own page.
    me = client.get("/api/me/role", headers=as_gym(gym, member))
    assert me.status_code == 200 and me.json()["uses_grades"] is False


@pg
def test_another_gym_neither_sees_nor_changes_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    judo = add(client, gym, "Judo", uses_grades=True)
    other = another_gym(db)
    assert listed(client, other) == []
    assert not uses_grades(client, other)
    path = f"/api/activities/{judo['id']}"
    assert client.patch(path, json={"name": "x"}, headers=as_gym(other)).status_code == 404
    assert client.delete(path, headers=as_gym(other)).status_code == 404
    assert [a["name"] for a in listed(client, gym)] == ["Judo"]


@pg
def test_the_gym_grades_while_any_activity_does(client: TestClient, gym: uuid.UUID) -> None:
    ballet = add(client, gym, "Ballet")
    assert not uses_grades(client, gym)
    bjj = add(client, gym, "BJJ", uses_grades=True)
    judo = add(client, gym, "Judo", uses_grades=True)
    assert uses_grades(client, gym)

    client.patch(f"/api/activities/{bjj['id']}", json={"uses_grades": False}, headers=as_gym(gym))
    assert uses_grades(client, gym)
    client.delete(f"/api/activities/{judo['id']}", headers=as_gym(gym))
    assert not uses_grades(client, gym)
    client.patch(f"/api/activities/{ballet['id']}", json={"uses_grades": True}, headers=as_gym(gym))
    assert uses_grades(client, gym)


@pg
def test_the_api_keeps_grading_with_no_graded_activity(client: TestClient, gym: uuid.UUID) -> None:
    assert not uses_grades(client, gym)
    scheme = client.get("/api/gym/grading-scheme", headers=as_gym(gym))
    assert scheme.status_code == 200, scheme.text


# --- class types ------------------------------------------------------------------


@pg
def test_a_class_type_belongs_to_an_activity_or_none(client: TestClient, gym: uuid.UUID) -> None:
    bjj = add(client, gym, "BJJ", uses_grades=True)
    adults = program(client, gym, "Adultos")

    plain = client.get(f"/api/class-types/{class_type(client, gym, adults)}", headers=as_gym(gym))
    assert (plain.json()["activity_id"], plain.json()["activity_name"]) == (None, None)

    body = {"name": "Avanzado", "program_id": adults, "activity_id": bjj["id"]}
    made = client.post("/api/class-types", json=body, headers=as_gym(gym))
    assert made.status_code == 201, made.text
    assert (made.json()["activity_id"], made.json()["activity_name"]) == (bjj["id"], "BJJ")
    assert listed(client, gym)[0]["class_types"] == 1

    unlinked = client.patch(
        f"/api/class-types/{made.json()['id']}", json={"activity_id": None}, headers=as_gym(gym)
    )
    assert unlinked.status_code == 200, unlinked.text
    assert unlinked.json()["activity_id"] is None

    linked = client.patch(
        f"/api/class-types/{plain.json()['id']}",
        json={"activity_id": bjj["id"]},
        headers=as_gym(gym),
    )
    assert linked.json()["activity_name"] == "BJJ"
    # A change to something else leaves it where it is.
    renamed = client.patch(
        f"/api/class-types/{plain.json()['id']}", json={"name": "Básico"}, headers=as_gym(gym)
    )
    assert renamed.json()["activity_id"] == bjj["id"]


@pg
def test_removing_an_activity_leaves_its_class_types_with_none(
    client: TestClient, gym: uuid.UUID
) -> None:
    judo = add(client, gym, "Judo", uses_grades=True)
    adults = program(client, gym, "Adultos")
    body = {"name": "Randori", "program_id": adults, "activity_id": judo["id"]}
    made = client.post("/api/class-types", json=body, headers=as_gym(gym)).json()

    client.delete(f"/api/activities/{judo['id']}", headers=as_gym(gym))

    after = client.get(f"/api/class-types/{made['id']}", headers=as_gym(gym)).json()
    assert (after["activity_id"], after["program_id"], after["active"]) == (None, adults, True)


@pg
def test_a_class_type_takes_no_other_gyms_activity(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    theirs = add(client, another_gym(db), "BJJ")
    adults = program(client, gym, "Adultos")
    for activity in (theirs["id"], str(uuid.uuid4())):
        body = {"name": "Fundamentos", "program_id": adults, "activity_id": activity}
        response = client.post("/api/class-types", json=body, headers=as_gym(gym))
        assert response.status_code == 422, response.text
        assert response.json()["detail"][0]["type"] == "unknown_activity"
    mine = class_type(client, gym, adults)
    response = client.patch(
        f"/api/class-types/{mine}", json={"activity_id": theirs["id"]}, headers=as_gym(gym)
    )
    assert response.status_code == 422


# --- the migration ----------------------------------------------------------------


@pytest.fixture
def old_db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0042")
        yield database


def store_grading(db: Database, gym: uuid.UUID, grading: Any) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym SET settings = settings || jsonb_build_object('grading', $1::jsonb)"
            " WHERE id = $2",
            json.dumps(grading),
            gym,
        ),
    )


def record_rank(db: Database, gym: uuid.UUID) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO grade_event (gym_id, membership_id, rank_key, awarded_on)"
            " SELECT gym_id, id, 'blue', current_date FROM membership WHERE gym_id = $1",
            gym,
        ),
    )


def activities_of(db: Database, gym: uuid.UUID) -> list[tuple[str, bool]]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch("SELECT name, uses_grades FROM gym_activity WHERE gym_id = $1", gym),
    )
    return [(r["name"], r["uses_grades"]) for r in rows]


RANK = {"key": "blue", "label": "Azul", "sub_ranks": []}


@pg
def test_the_migration_gives_a_gym_that_grades_a_graded_bjj(old_db: Database) -> None:
    schemed = seed_gym(old_db, "con-esquema")
    store_grading(old_db, schemed, {"ranks": [RANK], "kids_ladder": [], "goal_metric": None})
    kids_only = seed_gym(old_db, "solo-kids")
    store_grading(old_db, kids_only, {"ranks": [], "kids_ladder": [RANK]})
    ranked = seed_gym(old_db, "con-grados")
    record_rank(old_db, ranked)
    empty = seed_gym(old_db, "esquema-vacio")
    store_grading(old_db, empty, {"ranks": [], "kids_ladder": [], "goal_metric": None})
    malformed = seed_gym(old_db, "esquema-roto")
    store_grading(old_db, malformed, {"ranks": "rotas"})
    bare = seed_gym(old_db, "sin-grados")

    migrate(old_db, "0043")

    for gym in (schemed, kids_only, ranked):
        assert activities_of(old_db, gym) == [("BJJ", True)]
    for gym in (empty, malformed, bare):
        assert activities_of(old_db, gym) == []
    forced = run(
        old_db.admin_url,
        lambda c: c.fetch(
            "SELECT relname, relforcerowsecurity FROM pg_class"
            " WHERE relname IN ('gym', 'grade_event', 'gym_activity')"
        ),
    )
    assert {r["relname"]: r["relforcerowsecurity"] for r in forced} == {
        "gym": True,
        "grade_event": True,
        "gym_activity": True,
    }

    command.downgrade(old_db.alembic(), "0042")
    gone = run(
        old_db.admin_url,
        lambda c: c.fetchval("SELECT to_regclass('gym_activity') IS NULL"),
    )
    assert gone
