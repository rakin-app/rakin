"""Custom fields over the API: defining them, who sees them, and a person's values.

The value and visibility rules themselves are `tests/domain/test_custom_fields.py`.
"""

import asyncio
import json
import re
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres

FIELDS = "/api/custom-fields"


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


@dataclass(frozen=True)
class Gym:
    id: uuid.UUID
    owner: dict[str, str]
    admin: dict[str, str]
    coach: dict[str, str]
    member: uuid.UUID

    def fields_of(self, person: uuid.UUID) -> str:
        return f"/api/people/{person}/fields"


def staffed(db: Database, slug: str) -> Gym:
    """A gym with an owner, an admin, a coach and a member."""
    gym = seed_gym(db, slug)
    admin, coach, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        for person, role in ((admin, "admin"), (coach, "coach"), (member, None)):
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym,
                person,
            )
            if role:
                await conn.execute(
                    "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)",
                    gym,
                    person,
                    role,
                )

    run(db.admin_url, query)
    return Gym(gym, as_gym(gym), as_gym(gym, admin), as_gym(gym, coach), member)


def define(client: TestClient, gym: Gym, **body: Any) -> dict[str, Any]:
    response = client.post(FIELDS, json=body, headers=gym.owner)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def stored_defs(db: Database, gym: Gym) -> list[dict[str, Any]]:
    settings = run(
        db.admin_url, lambda c: c.fetchval("SELECT settings FROM gym WHERE id = $1", gym.id)
    )
    defs: list[dict[str, Any]] = json.loads(settings)["custom_fields"]
    return defs


def stored_rows(db: Database, gym: Gym) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT person_id, field_key, value, secret FROM person_field_value"
            " WHERE gym_id = $1 ORDER BY field_key",
            gym.id,
        ),
    )
    return rows


def key(client: TestClient, gym: Gym, **body: Any) -> str:
    """The key of a field the owner defines."""
    result: str = define(client, gym, **body)["key"]
    return result


def keys(response: Any) -> list[str]:
    return [f["key"] for f in response.json()]


# --- definitions ------------------------------------------------------------------


def test_the_owner_defines_fields_with_their_defaults(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-define")
    contact = define(client, gym, label="Contacto de emergencia", type="text")
    contact_key = contact.pop("key")
    assert re.fullmatch(r"contacto_de_emergencia_[0-9a-f]{4}", contact_key)
    assert contact == {
        "label": "Contacto de emergencia",
        "type": "text",
        "options": None,
        "sensitive": False,
        "visible_to": "staff",
        "archived": False,
    }
    health = define(client, gym, label="Notas médicas", type="text", sensitive=True)
    assert health["key"].startswith("notas_medicas_")
    assert health["visible_to"] == "owner"
    weight = define(client, gym, label="Categoría", type="enum", options=["Gallo", "Pluma"])
    assert weight["options"] == ["Gallo", "Pluma"]
    # The same label again gets a key of its own.
    again = key(client, gym, label="Categoría", type="number")
    assert again != weight["key"]

    order = [contact_key, health["key"], weight["key"], again]
    assert keys(client.get(FIELDS, headers=gym.owner)) == order
    assert [d["key"] for d in stored_defs(db, gym)] == order


def test_a_new_key_says_nothing_of_a_field_the_admin_cannot_see(
    client: TestClient, db: Database
) -> None:
    hidden, plain = staffed(db, "cf-key-hidden"), staffed(db, "cf-key-plain")
    define(client, hidden, label="Notas médicas", type="text", sensitive=True)

    def admin_defines(gym: Gym) -> str:
        body = {"label": "Notas médicas", "type": "text"}
        response = client.post(FIELDS, json=body, headers=gym.admin)
        assert response.status_code == 201
        result: str = response.json()["key"]
        return result

    # Shaped the same whether or not an owner-only field took the plain key.
    for made in (admin_defines(hidden), admin_defines(plain)):
        assert re.fullmatch(r"notas_medicas_[0-9a-f]{4}", made)


@pytest.mark.parametrize(
    "body",
    [
        {"label": "x", "type": "enum"},
        {"label": "x", "type": "text", "options": ["a"]},
        {"label": "x", "type": "enum", "options": ["a", "a"]},
        {"label": "x", "type": "enum", "options": []},
        {"label": " ", "type": "text"},
        {"label": "x", "type": "boolean"},
        {"label": "x", "type": "text", "visible_to": "member"},
        {"label": "x", "type": "text", "key": "mine"},
    ],
    ids=str,
)
def test_an_invalid_definition_is_a_422(client: TestClient, db: Database, body: Any) -> None:
    gym = staffed(db, f"cf-bad-{uuid.uuid4().hex[:8]}")
    assert client.post(FIELDS, json=body, headers=gym.owner).status_code == 422


def test_an_admin_defines_fields_but_never_who_sees_them(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-admin")
    response = client.post(FIELDS, json={"label": "Peso", "type": "number"}, headers=gym.admin)
    assert response.status_code == 201
    assert response.json()["visible_to"] == "staff"
    peso = response.json()["key"]

    for extra in ({"sensitive": True}, {"sensitive": False}, {"visible_to": "owner"}):
        body = {"label": "Otro", "type": "text", **extra}
        assert client.post(FIELDS, json=body, headers=gym.admin).status_code == 403
    for change in ({"sensitive": True}, {"visible_to": "admin"}):
        assert client.patch(f"{FIELDS}/{peso}", json=change, headers=gym.admin).status_code == 403
    # Renaming is theirs.
    renamed = client.patch(f"{FIELDS}/{peso}", json={"label": "Peso (kg)"}, headers=gym.admin)
    assert renamed.json()["label"] == "Peso (kg)"
    assert [d["key"] for d in stored_defs(db, gym)] == [peso]


def test_a_coach_reads_definitions_but_cannot_change_them(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-coach")
    peso = key(client, gym, label="Peso", type="number")
    assert keys(client.get(FIELDS, headers=gym.coach)) == [peso]
    body = {"label": "x", "type": "text"}
    assert client.post(FIELDS, json=body, headers=gym.coach).status_code == 403
    response = client.patch(f"{FIELDS}/{peso}", json={"label": "y"}, headers=gym.coach)
    assert response.status_code == 403
    member = as_gym(gym.id, gym.member)
    assert client.get(FIELDS, headers=member).status_code == 403


def test_each_role_sees_only_the_fields_open_to_it(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-visibility")
    todos = key(client, gym, label="Todos", type="text")
    gestion = key(client, gym, label="Gestión", type="text", visible_to="admin")
    dueno = key(client, gym, label="Dueño", type="text", visible_to="owner")

    assert keys(client.get(FIELDS, headers=gym.owner)) == [todos, gestion, dueno]
    assert keys(client.get(FIELDS, headers=gym.admin)) == [todos, gestion]
    assert keys(client.get(FIELDS, headers=gym.coach)) == [todos]
    # A field one cannot see answers as one that does not exist.
    for path in (dueno, "nada"):
        response = client.patch(f"{FIELDS}/{path}", json={"label": "z"}, headers=gym.admin)
        assert (response.status_code, response.json()) == (404, {"detail": "field not found"})


def test_the_owner_widens_and_narrows_a_field(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-widen")
    salud = key(client, gym, label="Salud", type="text", sensitive=True)
    assert keys(client.get(FIELDS, headers=gym.coach)) == []
    widened = client.patch(f"{FIELDS}/{salud}", json={"visible_to": "staff"}, headers=gym.owner)
    assert widened.json()["visible_to"] == "staff"
    assert keys(client.get(FIELDS, headers=gym.coach)) == [salud]

    peso = key(client, gym, label="Peso", type="number")
    # Marking a field sensitive narrows it to the owner, unless they say otherwise.
    flagged = client.patch(f"{FIELDS}/{peso}", json={"sensitive": True}, headers=gym.owner)
    assert (flagged.json()["sensitive"], flagged.json()["visible_to"]) == (True, "owner")
    body = {"sensitive": False, "visible_to": "admin"}
    both = client.patch(f"{FIELDS}/{peso}", json=body, headers=gym.owner)
    assert (both.json()["sensitive"], both.json()["visible_to"]) == (False, "admin")


def test_options_change_only_on_an_enum(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-options")
    categoria = key(client, gym, label="Categoría", type="enum", options=["Gallo"])
    peso = key(client, gym, label="Peso", type="number")
    body = {"options": ["Gallo", "Pluma"]}
    response = client.patch(f"{FIELDS}/{categoria}", json=body, headers=gym.admin)
    assert response.json()["options"] == ["Gallo", "Pluma"]
    assert client.patch(f"{FIELDS}/{peso}", json=body, headers=gym.admin).status_code == 422
    for bad in ({"type": "text"}, {"key": "otro"}, {"label": None}):
        assert client.patch(f"{FIELDS}/{peso}", json=bad, headers=gym.owner).status_code == 422


def test_an_option_people_hold_cannot_be_removed(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-option-in-use")
    options = ["Gallo", "Pluma", "Pesado"]
    plain = key(client, gym, label="Categoría", type="enum", options=options)
    sealed = key(client, gym, label="Lesión", type="enum", options=options, sensitive=True)
    owner_view = as_gym(gym.id)
    for field in (plain, sealed):
        for person, value in ((gym.member, "Pluma"), (seeded_owner(gym.id), "Pluma")):
            response = client.patch(
                gym.fields_of(person), json={"values": {field: value}}, headers=owner_view
            )
            assert response.status_code == 200

    for field in (plain, sealed):
        url = f"{FIELDS}/{field}"
        refused = client.patch(url, json={"options": ["Gallo", "Pesado"]}, headers=gym.owner)
        assert refused.status_code == 409
        assert refused.json() == {"detail": {"code": "option_in_use", "options": {"Pluma": 2}}}
        # One nobody holds goes; so does a reorder or an addition.
        kept = client.patch(url, json={"options": ["Pluma", "Gallo", "Leve"]}, headers=gym.owner)
        assert kept.json()["options"] == ["Pluma", "Gallo", "Leve"]


def test_reordering_keeps_fields_the_caller_cannot_see_in_place(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "cf-order")
    a, b, c = (key(client, gym, label=label, type="text") for label in ("A", "B", "C"))
    secreto = key(client, gym, label="Secreto", type="text", visible_to="owner")
    d = key(client, gym, label="D", type="text")

    response = client.put(f"{FIELDS}/order", json={"keys": [d, c, b, a]}, headers=gym.admin)
    assert keys(response) == [d, c, b, a]
    assert keys(client.get(FIELDS, headers=gym.owner)) == [d, c, b, secreto, a]

    for wrong in ([d, c, b], [d, c, b, a, secreto], [d, c, b, b]):
        response = client.put(f"{FIELDS}/order", json={"keys": wrong}, headers=gym.admin)
        assert response.status_code == 422
    assert client.put(f"{FIELDS}/order", json={"keys": []}, headers=gym.coach).status_code == 403


# --- a person's values ------------------------------------------------------------


def test_values_are_written_read_and_cleared(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-values")
    contacto = key(client, gym, label="Contacto", type="text")
    peso = key(client, gym, label="Peso", type="number")
    ingreso = key(client, gym, label="Ingreso", type="date")
    categoria = key(client, gym, label="Categoría", type="enum", options=["Gallo", "Pluma"])
    url = gym.fields_of(gym.member)

    empty = client.get(url, headers=gym.coach).json()
    assert [(f["key"], f["value"]) for f in empty] == [
        (contacto, None),
        (peso, None),
        (ingreso, None),
        (categoria, None),
    ]
    values = {contacto: " Ana 9 1234 5678 ", peso: 72.5, ingreso: "2026-03-01", categoria: "Pluma"}
    response = client.patch(url, json={"values": values}, headers=gym.coach)
    assert response.status_code == 200
    assert {f["key"]: f["value"] for f in response.json()} == {
        **values,
        contacto: "Ana 9 1234 5678",
    }
    assert client.get(url, headers=gym.owner).json() == response.json()

    cleared = client.patch(url, json={"values": {peso: None, contacto: ""}}, headers=gym.admin)
    assert {f["key"]: f["value"] for f in cleared.json()}[peso] is None
    assert sorted(r["field_key"] for r in stored_rows(db, gym)) == sorted([categoria, ingreso])


def test_an_invalid_value_writes_nothing(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-invalid")
    peso = key(client, gym, label="Peso", type="number")
    categoria = key(client, gym, label="Categoría", type="enum", options=["Gallo"])
    url = gym.fields_of(gym.member)
    body = {"values": {peso: "setenta", categoria: "Gallo", "nada": 1}}
    response = client.patch(url, json=body, headers=gym.owner)
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "fields": {peso: "must be a number", "nada": "unknown field"}
    }
    assert stored_rows(db, gym) == []


def test_a_field_one_cannot_see_is_neither_read_nor_written(
    client: TestClient, db: Database
) -> None:
    gym = staffed(db, "cf-hidden-values")
    todos = key(client, gym, label="Todos", type="text")
    gestion = key(client, gym, label="Gestión", type="text", visible_to="admin")
    salud = key(client, gym, label="Salud", type="text", sensitive=True)
    url = gym.fields_of(gym.member)
    body = {"values": {todos: "a", gestion: "b", salud: "c"}}
    assert client.patch(url, json=body, headers=gym.owner).status_code == 200

    assert [(f["key"], f["value"]) for f in client.get(url, headers=gym.coach).json()] == [
        (todos, "a")
    ]
    assert keys(client.get(url, headers=gym.admin)) == [todos, gestion]
    for hidden in (gestion, salud):
        response = client.patch(url, json={"values": {hidden: "x"}}, headers=gym.coach)
        assert response.json()["detail"] == {"fields": {hidden: "unknown field"}}
    response = client.patch(url, json={"values": {salud: "x"}}, headers=gym.admin)
    assert response.status_code == 422
    owner_view = {f["key"]: f["value"] for f in client.get(url, headers=gym.owner).json()}
    assert owner_view == {todos: "a", gestion: "b", salud: "c"}


def test_an_archived_field_keeps_its_values_out_of_sight(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-archive")
    peso = key(client, gym, label="Peso", type="number")
    url = gym.fields_of(gym.member)
    client.patch(url, json={"values": {peso: 70}}, headers=gym.owner)

    archived = client.patch(f"{FIELDS}/{peso}", json={"archived": True}, headers=gym.admin)
    assert archived.json()["archived"] is True
    assert keys(client.get(FIELDS, headers=gym.coach)) == [peso]
    assert client.get(url, headers=gym.owner).json() == []
    response = client.patch(url, json={"values": {peso: 71}}, headers=gym.owner)
    assert response.json()["detail"] == {"fields": {peso: "unknown field"}}

    client.patch(f"{FIELDS}/{peso}", json={"archived": False}, headers=gym.admin)
    assert [f["value"] for f in client.get(url, headers=gym.owner).json()] == [70]


def test_a_sensitive_value_is_encrypted_at_rest(client: TestClient, db: Database) -> None:
    gym = staffed(db, "cf-sealed")
    salud = key(client, gym, label="Salud", type="text", sensitive=True)
    peso = key(client, gym, label="Peso", type="number")
    url = gym.fields_of(gym.member)
    client.patch(url, json={"values": {salud: "asma severa", peso: 70}}, headers=gym.owner)

    rows = {r["field_key"]: r for r in stored_rows(db, gym)}
    assert rows[salud]["value"] is None
    assert b"asma" not in rows[salud]["secret"]
    assert (json.loads(rows[peso]["value"]), rows[peso]["secret"]) == (70, None)

    # Flagging a field later seals what it holds; unflagging opens it again.
    client.patch(f"{FIELDS}/{peso}", json={"sensitive": True}, headers=gym.owner)
    client.patch(f"{FIELDS}/{salud}", json={"sensitive": False}, headers=gym.owner)
    rows = {r["field_key"]: r for r in stored_rows(db, gym)}
    assert (rows[peso]["value"], rows[salud]["secret"]) == (None, None)
    assert json.loads(rows[salud]["value"]) == "asma severa"
    values = {f["key"]: f["value"] for f in client.get(url, headers=gym.owner).json()}
    assert values == {salud: "asma severa", peso: 70}


def test_a_value_written_while_the_field_turns_sensitive_is_sealed(
    client: TestClient, db: Database
) -> None:
    """The flip holds the gym row; a value write waits for it and then seals."""
    gym = staffed(db, "cf-race")
    peso = key(client, gym, label="Peso", type="number")
    locked, release = threading.Event(), threading.Event()

    async def flip(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT 1 FROM gym WHERE id = $1 FOR UPDATE", gym.id)
            await conn.execute(
                "UPDATE gym SET settings = jsonb_set(settings, '{custom_fields,0,sensitive}',"
                " 'true') WHERE id = $1",
                gym.id,
            )
            locked.set()
            # Held until the test lets go: the write must be waiting by then.
            await asyncio.to_thread(release.wait, 10)

    flipper = threading.Thread(target=run, args=(db.admin_url, flip))
    flipper.start()
    assert locked.wait(5)
    answers: list[int] = []
    writer = threading.Thread(
        target=lambda: answers.append(
            client.patch(
                gym.fields_of(gym.member), json={"values": {peso: 70}}, headers=gym.owner
            ).status_code
        )
    )
    writer.start()
    try:
        writer.join(0.5)
        waited = writer.is_alive()
    finally:
        release.set()
        flipper.join(5)
        writer.join(5)
    assert waited, "the value write did not wait for the flip"

    assert answers == [200]
    [row] = stored_rows(db, gym)
    assert (row["value"], row["secret"] is not None) == (None, True)


def test_values_stay_in_their_gym(client: TestClient, db: Database) -> None:
    sur, norte = staffed(db, "cf-sur"), staffed(db, "cf-norte")
    peso = key(client, sur, label="Peso", type="number")
    client.patch(sur.fields_of(sur.member), json={"values": {peso: 70}}, headers=sur.owner)
    norte_peso = key(client, norte, label="Peso", type="number")

    assert client.get(norte.fields_of(sur.member), headers=norte.owner).status_code == 404
    response = client.patch(
        norte.fields_of(sur.member), json={"values": {norte_peso: 1}}, headers=norte.owner
    )
    assert response.status_code == 404
    assert client.get(sur.fields_of(seeded_owner(norte.id)), headers=sur.owner).status_code == 404
    assert [r["value"] for r in stored_rows(db, sur)] == ["70"]
    assert stored_rows(db, norte) == []
