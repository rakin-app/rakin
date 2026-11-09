"""Sessions (migration 0019): the day's classes, started ad hoc, topic and notes after.

A session is one class actually held, of one of the gym's class types, taught by one of
its staff. The day's sessions are those starting on that day in the gym's timezone.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.main import create_app
from app.schemas.sessions import MAX_NOTES, MAX_TOPIC, SessionCreate, SessionUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_plans import add_staff

SANTIAGO = ZoneInfo("America/Santiago")
CLASS_TYPE = str(uuid.uuid4())

# --- input rules, no database -----------------------------------------------------


def test_a_session_starts_now_by_whoever_starts_it_unless_told() -> None:
    body = SessionCreate.model_validate({"class_type_id": CLASS_TYPE})
    assert (body.starts_at, body.coach_id, body.topic, body.notes) == (None, None, None, None)


def test_a_blank_topic_or_notes_is_none() -> None:
    body = SessionUpdate.model_validate({"topic": "  ", "notes": "\n"})
    assert (body.topic, body.notes) == (None, None)
    assert body.model_fields_set == {"topic", "notes"}
    assert SessionUpdate.model_validate({"topic": " Guardia "}).topic == "Guardia"


@pytest.mark.parametrize(
    "body",
    [
        {},  # no class type
        {"class_type_id": "fundamentos"},
        {"class_type_id": CLASS_TYPE, "starts_at": "2026-11-09T19:00:00"},  # no offset
        {"class_type_id": CLASS_TYPE, "topic": "x" * (MAX_TOPIC + 1)},
        {"class_type_id": CLASS_TYPE, "notes": "x" * (MAX_NOTES + 1)},
        {"class_type_id": CLASS_TYPE, "gym_id": CLASS_TYPE},
    ],
    ids=str,
)
def test_create_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SessionCreate.model_validate(body)


@pytest.mark.parametrize(
    "body", [{"coach_id": None}, {"class_type_id": CLASS_TYPE}, {"starts_at": None}], ids=str
)
def test_update_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SessionUpdate.model_validate(body)


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
    """A gym of its own per test, so a day holds exactly what the test started."""
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def class_type(client: TestClient, gym: uuid.UUID, name: str = "Fundamentos") -> dict[str, Any]:
    headers = as_gym(gym)
    programs = client.get("/api/programs", headers=headers).json()
    if programs:
        program = programs[0]
    else:
        program = client.post("/api/programs", json={"name": "Adultos"}, headers=headers).json()
    response = client.post(
        "/api/class-types", json={"name": name, "program_id": program["id"]}, headers=headers
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def start(
    client: TestClient, gym: uuid.UUID, body: dict[str, Any], person: uuid.UUID | None = None
) -> Any:
    return client.post("/api/sessions", json=body, headers=as_gym(gym, person))


def started(
    client: TestClient, gym: uuid.UUID, body: dict[str, Any], person: uuid.UUID | None = None
) -> dict[str, Any]:
    response = start(client, gym, body, person)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def day(client: TestClient, gym: uuid.UUID, **params: Any) -> Any:
    response = client.get("/api/sessions", params=params, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def at(local: str) -> str:
    """A Santiago wall time, `2026-11-09 19:00`, as an ISO instant."""
    return datetime.fromisoformat(local).replace(tzinfo=SANTIAGO).isoformat()


@pg
def test_a_coach_starts_a_session_now_and_sees_it_today(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym)
    coach = add_staff(db, gym, "coach")
    before = datetime.now(UTC)
    session = started(client, gym, {"class_type_id": fundamentals["id"]}, coach)

    assert {
        k: session[k]
        for k in ("class_type_id", "class_type_name", "program_name", "coach_id", "coach_name")
    } == {
        "class_type_id": fundamentals["id"],
        "class_type_name": "Fundamentos",
        "program_name": "Adultos",
        "coach_id": str(coach),
        "coach_name": "x",
    }
    assert (session["topic"], session["notes"]) == (None, None)
    starts_at = datetime.fromisoformat(session["starts_at"])
    assert before - timedelta(seconds=5) <= starts_at <= datetime.now(UTC) + timedelta(seconds=5)

    today = client.get("/api/sessions", headers=as_gym(gym, coach)).json()
    assert today["timezone"] == "America/Santiago"
    assert today["date"] == datetime.now(SANTIAGO).date().isoformat()
    assert today["sessions"] == [session]
    read = client.get(f"/api/sessions/{session['id']}", headers=as_gym(gym, coach))
    assert read.json() == session


@pg
def test_a_day_is_the_gyms_calendar_day_earliest_first(client: TestClient, gym: uuid.UUID) -> None:
    fundamentals, advanced = class_type(client, gym), class_type(client, gym, "Avanzado")
    evening = started(
        client, gym, {"class_type_id": fundamentals["id"], "starts_at": at("2026-11-09 19:00")}
    )
    morning = started(
        client, gym, {"class_type_id": advanced["id"], "starts_at": at("2026-11-09 07:00")}
    )
    # 23:30 in Santiago is already the 10th in UTC, and 00:30 on the 10th is not the 9th.
    late = started(
        client, gym, {"class_type_id": advanced["id"], "starts_at": at("2026-11-09 23:30")}
    )
    started(client, gym, {"class_type_id": advanced["id"], "starts_at": at("2026-11-10 00:30")})
    started(client, gym, {"class_type_id": advanced["id"], "starts_at": at("2026-11-08 23:59")})

    ninth = day(client, gym, date="2026-11-09")
    assert ninth["date"] == "2026-11-09"
    assert [s["id"] for s in ninth["sessions"]] == [morning["id"], evening["id"], late["id"]]
    assert len(day(client, gym, date="2026-11-10")["sessions"]) == 1
    assert day(client, gym, date="2026-11-11")["sessions"] == []


@pg
def test_the_day_follows_the_gyms_timezone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    run(db.admin_url, lambda c: c.execute("UPDATE gym SET timezone = 'UTC' WHERE id = $1", gym))
    fundamentals = class_type(client, gym)
    # 22:00 in Santiago on the 9th is 01:00 UTC on the 10th.
    started(client, gym, {"class_type_id": fundamentals["id"], "starts_at": at("2026-11-09 22:00")})
    assert day(client, gym, date="2026-11-09")["sessions"] == []
    assert day(client, gym, date="2026-11-10")["timezone"] == "UTC"
    assert len(day(client, gym, date="2026-11-10")["sessions"]) == 1


@pg
def test_topic_and_notes_are_written_after_class_and_cleared(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym)
    session = started(
        client, gym, {"class_type_id": fundamentals["id"], "topic": "Guardia cerrada"}
    )
    coach = add_staff(db, gym, "coach")
    path = f"/api/sessions/{session['id']}"

    written = client.patch(
        path,
        json={"topic": " Pasaje de rodilla ", "notes": "Faltó calentamiento."},
        headers=as_gym(gym, coach),
    )
    assert written.status_code == 200, written.text
    after = written.json()
    assert (after["topic"], after["notes"]) == ("Pasaje de rodilla", "Faltó calentamiento.")
    assert after["updated_at"] > session["updated_at"]
    assert {k: v for k, v in after.items() if k not in ("topic", "notes", "updated_at")} == {
        k: v for k, v in session.items() if k not in ("topic", "notes", "updated_at")
    }

    # Only what is sent changes; null or blank clears it.
    notes_only = client.patch(path, json={"notes": "  "}, headers=as_gym(gym)).json()
    assert (notes_only["topic"], notes_only["notes"]) == ("Pasaje de rodilla", None)
    cleared = client.patch(path, json={"topic": None}, headers=as_gym(gym)).json()
    assert cleared["topic"] is None


@pg
def test_the_coach_may_be_someone_else_on_staff(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym)
    coach, admin = add_staff(db, gym, "coach"), add_staff(db, gym, "admin")
    session = started(client, gym, {"class_type_id": fundamentals["id"], "coach_id": str(coach)})
    assert session["coach_id"] == str(coach)
    moved = client.patch(
        f"/api/sessions/{session['id']}", json={"coach_id": str(admin)}, headers=as_gym(gym)
    )
    assert moved.json()["coach_id"] == str(admin)

    # Someone the gym knows who is not staff, another gym's staff, or no one.
    member = uuid.uuid4()

    async def add_member(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'm')", member)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'm')", gym, member
        )

    run(db.admin_url, add_member)
    elsewhere = add_staff(db, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"), "coach")
    for person in (member, elsewhere, uuid.uuid4()):
        refused = start(client, gym, {"class_type_id": fundamentals["id"], "coach_id": str(person)})
        assert refused.status_code == 422, refused.text
        assert [(e["type"], e["loc"]) for e in refused.json()["detail"]] == [
            ("unknown_coach", ["body", "coach_id"])
        ]
        assert (
            client.patch(
                f"/api/sessions/{session['id']}",
                json={"coach_id": str(person)},
                headers=as_gym(gym),
            ).status_code
            == 422
        )


@pg
def test_a_coach_who_left_stays_the_coach_of_their_sessions(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym)
    coach = add_staff(db, gym, "coach")
    session = started(client, gym, {"class_type_id": fundamentals["id"]}, coach)
    run(
        db.admin_url,
        lambda c: c.execute("DELETE FROM staff WHERE gym_id = $1 AND person_id = $2", gym, coach),
    )
    path = f"/api/sessions/{session['id']}"
    assert client.get(path, headers=as_gym(gym)).json()["coach_name"] == "x"
    # Editing what it covered leaves its coach alone, sent again or not.
    edited = client.patch(path, json={"topic": "t", "coach_id": str(coach)}, headers=as_gym(gym))
    assert (edited.status_code, edited.json()["coach_id"]) == (200, str(coach))


@pg
def test_a_session_needs_one_of_the_gyms_active_class_types(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    theirs = class_type(client, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"))
    old = class_type(client, gym, "Viejo")
    client.patch(f"/api/class-types/{old['id']}", json={"active": False}, headers=as_gym(gym))

    for class_type_id, kind in (
        (theirs["id"], "unknown_class_type"),
        (str(uuid.uuid4()), "unknown_class_type"),
        (old["id"], "inactive_class_type"),
    ):
        refused = start(client, gym, {"class_type_id": class_type_id})
        assert refused.status_code == 422, refused.text
        assert [(e["type"], e["loc"]) for e in refused.json()["detail"]] == [
            (kind, ["body", "class_type_id"])
        ]


@pg
def test_another_gyms_sessions_are_not_found(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    session = started(client, gym, {"class_type_id": class_type(client, gym)["id"]})
    path = f"/api/sessions/{session['id']}"
    assert client.get(path, headers=as_gym(other)).status_code == 404
    assert client.patch(path, json={"topic": "x"}, headers=as_gym(other)).status_code == 404
    assert day(client, other)["sessions"] == []
    assert client.get(path, headers=as_gym(gym)).json()["topic"] is None


@pg
@pytest.mark.parametrize("role", ["owner", "admin", "coach"])
def test_every_staff_role_starts_and_writes_sessions(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    fundamentals = class_type(client, gym)
    person = seeded_owner(gym) if role == "owner" else add_staff(db, gym, role)
    session = started(client, gym, {"class_type_id": fundamentals["id"]}, person)
    assert session["coach_id"] == str(person)
    path = f"/api/sessions/{session['id']}"
    edited = client.patch(path, json={"topic": role}, headers=as_gym(gym, person))
    assert edited.status_code == 200


@pg
def test_members_may_not_use_them(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    member = uuid.uuid4()
    run(db.admin_url, lambda c: c.execute("INSERT INTO person (id, name) VALUES ($1, 'm')", member))
    assert client.get("/api/sessions", headers=as_gym(gym, member)).status_code == 403
    body = {"class_type_id": class_type(client, gym)["id"]}
    assert start(client, gym, body, member).status_code == 403


@pg
def test_there_is_no_delete(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    session = started(client, gym, {"class_type_id": class_type(client, gym)["id"]})
    path = f"/api/sessions/{session['id']}"
    assert client.delete(path, headers=as_gym(gym)).status_code == 405
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, "DELETE FROM session WHERE id = $1", uuid.UUID(session["id"])))


# --- the table on its own (migration 0019) ----------------------------------------


@pg
def test_a_row_cannot_name_another_gyms_class_type_or_coach(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    ours, theirs = class_type(client, gym), class_type(client, other)
    insert = (
        "INSERT INTO session (gym_id, class_type_id, starts_at, coach_id)"
        " VALUES ($1, $2, now(), $3)"
    )
    # As the superuser, past RLS: the foreign keys alone hold it to the gym.
    for class_type_id, coach in (
        (theirs["id"], seeded_owner(gym)),
        (ours["id"], seeded_owner(other)),
    ):
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            run(db.admin_url, in_gym(gym, insert, gym, uuid.UUID(class_type_id), coach))


@pg
def test_the_table_refuses_a_blank_topic_or_notes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = uuid.UUID(class_type(client, gym)["id"])
    for column in ("topic", "notes"):
        insert = (
            f"INSERT INTO session (gym_id, class_type_id, starts_at, coach_id, {column})"
            " VALUES ($1, $2, now(), $3, ' ')"
        )
        with pytest.raises(asyncpg.CheckViolationError):
            run(db.owner_url, in_gym(gym, insert, gym, fundamentals, seeded_owner(gym)))


@pg
def test_upgrade_and_downgrade() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0018")
        gone = "SELECT to_regclass('session') IS NULL"
        assert run(scratch.admin_url, lambda c: c.fetchval(gone)) is True
        migrate(scratch)
