"""Requisitos over the API: the gym's list, a person's records, and the student page
(#349, migration 0061). The states themselves are `tests/domain/test_requirements.py`.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_custom_fields import Gym, staffed

pytestmark = pytest.mark.postgres

LIST = "/api/requirements"


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


def define(client: TestClient, gym: Gym, **body: Any) -> dict[str, Any]:
    response = client.post(LIST, json=body, headers=gym.owner)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def of(person: uuid.UUID) -> str:
    return f"/api/people/{person}/requirements"


def record(
    client: TestClient,
    gym: Gym,
    requirement: str,
    done_on: date,
    note: str | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    return client.post(
        f"{of(gym.member)}/{requirement}",
        json={"done_on": done_on.isoformat(), "note": note},
        headers=headers or gym.owner,
    )


def by_name(response: Any) -> dict[str, dict[str, Any]]:
    assert response.status_code == 200, response.text
    return {r["name"]: r for r in response.json()}


def stored(db: Database, gym: Gym) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT done_on, note, note_secret FROM person_requirement WHERE gym_id = $1"
            " ORDER BY recorded_at",
            gym.id,
        ),
    )
    return rows


# --- the list ----------------------------------------------------------------------


def test_the_owner_defines_requirements_with_their_defaults(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-define")
    waiver = define(client, gym, name="Declaración de riesgos firmada")
    assert waiver.pop("id")
    assert waiver == {
        "name": "Declaración de riesgos firmada",
        "valid_months": None,
        "sensitive": False,
        "visible_to": "staff",
        "active": True,
    }
    medical = define(client, gym, name="Certificado médico", valid_months=12, sensitive=True)
    assert (medical["valid_months"], medical["visible_to"]) == (12, "owner")

    listed = client.get(LIST, headers=gym.owner).json()
    assert [r["name"] for r in listed] == ["Declaración de riesgos firmada", "Certificado médico"]


@pytest.mark.parametrize("body", [{"name": " "}, {"name": "x", "valid_months": 0}])
def test_a_requirement_needs_a_name_and_a_length(
    client: TestClient, db: Database, body: Any
) -> None:
    gym = staffed(db, f"rq-bad-{uuid.uuid4().hex[:6]}")
    assert client.post(LIST, json=body, headers=gym.owner).status_code == 422


def test_an_admin_defines_but_never_says_who_sees_it(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-admin")
    assert client.post(LIST, json={"name": "Inducción"}, headers=gym.admin).status_code == 201
    for extra in ({"sensitive": True}, {"visible_to": "admin"}):
        body = {"name": "Otro", **extra}
        assert client.post(LIST, json=body, headers=gym.admin).status_code == 403
    # Nor does a coach define any.
    assert client.post(LIST, json={"name": "x"}, headers=gym.coach).status_code == 403


def test_a_requirement_is_renamed_reordered_and_deactivated(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-edit")
    first = define(client, gym, name="Inducción")
    second = define(client, gym, name="Prueba de natación", valid_months=24)

    renamed = client.patch(
        f"{LIST}/{first['id']}",
        json={"name": "Inducción de seguridad", "valid_months": 6},
        headers=gym.admin,
    )
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["valid_months"]) == ("Inducción de seguridad", 6)
    once = client.patch(f"{LIST}/{first['id']}", json={"valid_months": None}, headers=gym.admin)
    assert once.json()["valid_months"] is None
    assert (
        client.patch(f"{LIST}/{first['id']}", json={"name": None}, headers=gym.admin).status_code
        == 422
    )

    order = client.put(
        f"{LIST}/order", json={"ids": [second["id"], first["id"]]}, headers=gym.admin
    )
    assert [r["id"] for r in order.json()] == [second["id"], first["id"]]
    assert (
        client.put(f"{LIST}/order", json={"ids": [first["id"]]}, headers=gym.admin).status_code
        == 422
    )

    off = client.patch(f"{LIST}/{second['id']}", json={"active": False}, headers=gym.admin)
    assert off.json()["active"] is False
    # Still listed in Ajustes, and no more on the ficha.
    assert len(client.get(LIST, headers=gym.owner).json()) == 2
    assert list(by_name(client.get(of(gym.member), headers=gym.owner))) == [
        "Inducción de seguridad"
    ]
    gone = record(client, gym, second["id"], seeded_today())
    assert gone.status_code == 404


def test_an_admin_reorders_around_what_only_the_owner_sees(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-order-hidden")
    a = define(client, gym, name="A")["id"]
    hidden = define(client, gym, name="Oculto", visible_to="owner")["id"]
    b = define(client, gym, name="B")["id"]

    response = client.put(f"{LIST}/order", json={"ids": [b, a]}, headers=gym.admin)

    assert response.status_code == 200, response.text
    assert [r["id"] for r in response.json()] == [b, a]
    assert [r["id"] for r in client.get(LIST, headers=gym.owner).json()] == [b, hidden, a]


# --- a person's records ------------------------------------------------------------


def test_a_gym_with_no_requirements_answers_none(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-none")
    assert client.get(of(gym.member), headers=gym.owner).json() == []
    assert client.get("/api/me/requirements", headers=as_gym(gym.id, gym.member)).json() == []


def test_recording_a_requirement_sets_its_state(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-record")
    medical = define(client, gym, name="Certificado médico", valid_months=12)["id"]
    waiver = define(client, gym, name="Declaración de riesgos firmada")["id"]
    today = seeded_today()

    before = by_name(client.get(of(gym.member), headers=gym.coach))
    assert before["Certificado médico"]["state"] == "pending"
    assert before["Certificado médico"]["done_on"] is None

    # A coach records too, and may back-date it.
    stale = record(client, gym, medical, add_months(today, -13), headers=gym.coach)
    assert by_name(stale)["Certificado médico"]["state"] == "expired"
    fresh = by_name(record(client, gym, medical, today, note="  Dr. Pérez  "))["Certificado médico"]
    assert fresh["state"] == "ok"
    assert (fresh["done_on"], fresh["expires_on"]) == (
        today.isoformat(),
        add_months(today, 12).isoformat(),
    )
    assert fresh["note"] == "Dr. Pérez"
    signed = by_name(record(client, gym, waiver, today, note=""))["Declaración de riesgos firmada"]
    assert (signed["state"], signed["expires_on"], signed["note"]) == ("ok", None, None)
    # The earlier record is kept.
    assert len(stored(db, gym)) == 3


def test_a_record_is_today_at_the_latest(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-future")
    waiver = define(client, gym, name="Declaración de riesgos firmada")["id"]
    tomorrow = date.fromordinal(seeded_today().toordinal() + 1)
    assert record(client, gym, waiver, tomorrow).status_code == 422
    assert record(client, gym, waiver, date(1900, 1, 1)).status_code == 422
    other = uuid.uuid4()
    missing = client.post(
        f"{of(other)}/{waiver}", json={"done_on": seeded_today().isoformat()}, headers=gym.owner
    )
    assert missing.status_code == 404


def test_a_sensitive_note_is_sealed_and_kept_from_who_may_not_see_it(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-sensitive")
    medical = define(client, gym, name="Certificado médico", valid_months=12, sensitive=True)["id"]
    today = seeded_today()

    answered = by_name(record(client, gym, medical, today, note="Apto sin restricciones"))
    assert answered["Certificado médico"]["note"] == "Apto sin restricciones"
    [row] = stored(db, gym)
    assert row["note"] is None
    assert b"Apto" not in row["note_secret"]

    # Owner only: neither an admin nor a coach is told it is there.
    for role in (gym.admin, gym.coach):
        assert by_name(client.get(of(gym.member), headers=role)) == {}
        assert record(client, gym, medical, today, headers=role).status_code == 404
        assert client.get(LIST, headers=role).json() == []
    # Widened to admins, an admin reads the note and a coach still does not.
    widened = client.patch(f"{LIST}/{medical}", json={"visible_to": "admin"}, headers=gym.owner)
    assert widened.status_code == 200, widened.text
    admin_view = by_name(client.get(of(gym.member), headers=gym.admin))
    assert admin_view["Certificado médico"]["note"] == "Apto sin restricciones"
    assert by_name(client.get(of(gym.member), headers=gym.coach)) == {}


def test_marking_a_requirement_sensitive_seals_its_notes_and_unmarking_opens_them(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-reseal")
    swim = define(client, gym, name="Prueba de natación", valid_months=24)["id"]
    record(client, gym, swim, seeded_today(), note="200 m")

    marked = client.patch(f"{LIST}/{swim}", json={"sensitive": True}, headers=gym.owner)
    assert marked.json()["visible_to"] == "owner"
    [row] = stored(db, gym)
    assert (row["note"], row["note_secret"] is not None) == (None, True)
    assert (
        by_name(client.get(of(gym.member), headers=gym.owner))["Prueba de natación"]["note"]
        == "200 m"
    )

    client.patch(f"{LIST}/{swim}", json={"sensitive": False}, headers=gym.owner)
    [row] = stored(db, gym)
    assert (row["note"], row["note_secret"]) == ("200 m", None)
    # An admin may change neither, on one they see; one they do not is not there.
    waiver = define(client, gym, name="Declaración de riesgos firmada")["id"]
    for body in ({"sensitive": True}, {"visible_to": "owner"}):
        refused = client.patch(f"{LIST}/{waiver}", json=body, headers=gym.admin)
        assert refused.status_code == 403
    hidden = client.patch(f"{LIST}/{swim}", json={"name": "x"}, headers=gym.admin)
    assert hidden.status_code == 404


# --- the student page --------------------------------------------------------------


def test_the_student_page_shows_their_own_and_their_dependents_without_notes(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "rq-me")
    waiver = define(client, gym, name="Declaración de riesgos firmada")["id"]
    define(client, gym, name="Certificado médico", valid_months=12, sensitive=True)
    record(client, gym, waiver, seeded_today(), note="firmado en papel")

    [mine] = client.get("/api/me/requirements", headers=as_gym(gym.id, gym.member)).json()
    assert mine["person_id"] == str(gym.member)
    assert [(r["name"], r["state"]) for r in mine["requirements"]] == [
        ("Declaración de riesgos firmada", "ok"),
        ("Certificado médico", "pending"),
    ]
    assert all("note" not in r for r in mine["requirements"])

    # A guardian with no plan of their own sees their dependent's, not their own.
    guardian = uuid.uuid4()

    async def link(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", guardian)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Madre')",
            gym.id,
            guardian,
        )
        await conn.execute(
            "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
            " VALUES ($1, $2, $3)",
            gym.id,
            guardian,
            gym.member,
        )

    run(db.admin_url, link)
    theirs = client.get("/api/me/requirements", headers=as_gym(gym.id, guardian)).json()
    assert [p["person_id"] for p in theirs] == [str(gym.member)]


# --- the database ------------------------------------------------------------------


def test_the_database_keeps_records_as_recorded(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-db")
    waiver = uuid.UUID(define(client, gym, name="Declaración de riesgos firmada")["id"])
    insert = (
        "INSERT INTO person_requirement (gym_id, person_id, requirement_id, done_on, recorded_by)"
        " VALUES ($1, $2, $3, $4, $5)"
    )
    row = (gym.id, gym.member, waiver, seeded_today(), gym.member)
    # Recorded as someone other than who is acting.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym.id, insert, *row, person=uuid.uuid4()))
    run(db.api_url, in_gym(gym.id, insert, *row, person=gym.member))
    for statement in (
        "UPDATE person_requirement SET done_on = done_on - 1",
        "DELETE FROM person_requirement",
        "DELETE FROM requirement",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(gym.id, statement))

    other = seed_gym(db, "rq-db-other")
    assert client.get(of(gym.member), headers=as_gym(other)).status_code == 404
    for table in ("requirement", "person_requirement"):
        seen = run(db.api_url, in_gym(other, f"SELECT count(*) FROM {table}"))
        assert seen[0]["count"] == 0


def test_deleting_a_person_deletes_their_records(client: TestClient, db: Database) -> None:
    gym = staffed(db, "rq-forget")
    waiver = define(client, gym, name="Declaración de riesgos firmada")["id"]
    assert record(client, gym, waiver, seeded_today()).status_code == 200

    response = client.request(
        "DELETE",
        f"/api/people/{gym.member}",
        json={"reason": "agregado por error"},
        headers=gym.owner,
    )

    assert response.status_code == 204, response.text
    assert stored(db, gym) == []
