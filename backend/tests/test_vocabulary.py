"""Vocabulario del gimnasio (#344): what the gym calls itself, its members and its coach.

A gym that never set its words reads today's, academia / alumnos / profe. Its first
activity from a preset brings that sport's words, a free-named one the neutral words;
an activity added later changes nothing, and once the owner picks the words in Ajustes
no activity changes them again. Every screen reads them: `/api/me/role` signed in,
`/api/host`, the join form and the privacy notice before.
"""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.vocabulary import DEFAULT_GRADING, GRADING_PRESETS, PRESETS, PresetKey
from app.main import create_app
from app.schemas.grading import PRESETS as grading_presets
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

pg = pytest.mark.postgres

TODAY = {"place": "academia", "members": "alumnos", "coach": "profe"}
CLUB = {"place": "club", "members": "socios", "coach": "entrenador"}
FRONTEND = Path(__file__).parents[2] / "frontend" / "src" / "api"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url, public_base_url="https://rakin.cl", base_domain="rakin.cl"
        )
    )
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def words(client: TestClient, gym: uuid.UUID) -> Any:
    response = client.get("/api/me/role", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()["vocabulary"]


def add(client: TestClient, gym: uuid.UUID, name: str, preset: str | None = None) -> Any:
    body: dict[str, Any] = {"name": name}
    if preset is not None:
        body["preset"] = preset
    response = client.post("/api/activities", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return response.json()


def pick(client: TestClient, gym: uuid.UUID, vocabulary: Any) -> Any:
    return client.patch("/api/gym/settings", json={"vocabulary": vocabulary}, headers=as_gym(gym))


def test_every_preset_key_is_one_the_api_takes() -> None:
    assert set(get_args(PresetKey)) == set(PRESETS)


def test_every_graded_activity_reads_by_a_belt_preset() -> None:
    # A graded art's empty scheme reads as belts, not levels (#353, #411).
    belts = {p.key: p.scheme.belts for p in grading_presets}
    graded = {key for key, preset in PRESETS.items() if preset.uses_grades}
    assert set(DEFAULT_GRADING) == graded
    assert all(belts[DEFAULT_GRADING[key]] for key in graded)
    # Each grading preset with ranks starts its own art's activity, and back again.
    assert all(GRADING_PRESETS[DEFAULT_GRADING[key]] == key for key in graded)
    assert set(GRADING_PRESETS) == {key for key, has in belts.items() if has}


def test_the_spa_lists_the_same_activities_and_their_grading() -> None:
    activities = (FRONTEND / "activities.ts").read_text()
    keys = re.findall(r"\{ key: '(\w+)', name: '([^']+)', usesGrades: (true|false) \}", activities)
    assert {k: (name, graded == "true") for k, name, graded in keys} == {
        key: (p.name, p.uses_grades) for key, p in PRESETS.items()
    }
    of = (FRONTEND / "grading.ts").read_text()
    body = of[of.index("GRADING_PRESET_OF") :].split("}", 1)[0]
    assert dict(re.findall(r"(\w+): '([\w-]+)'", body)) == DEFAULT_GRADING


@pg
def test_a_gym_that_never_set_its_words_reads_todays(client: TestClient, gym: uuid.UUID) -> None:
    assert words(client, gym) == TODAY
    settings = client.get("/api/gym/settings", headers=as_gym(gym)).json()
    assert settings["vocabulary"] == TODAY


@pg
@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("bjj", TODAY),
        ("judo", {"place": "dojo", "members": "alumnos", "coach": "sensei"}),
        ("escalada", {"place": "gimnasio", "members": "socios", "coach": "instructor"}),
        ("remo", {"place": "club", "members": "socios", "coach": "entrenador"}),
    ],
)
def test_the_first_activity_brings_its_sports_words(
    client: TestClient, gym: uuid.UUID, preset: str, expected: Any
) -> None:
    activity = add(client, gym, PRESETS[preset].name, preset)

    assert activity["preset"] == preset
    assert activity["words"] == expected
    assert words(client, gym) == expected


@pg
def test_a_free_named_first_activity_brings_the_neutral_words(
    client: TestClient, gym: uuid.UUID
) -> None:
    activity = add(client, gym, "Parkour")

    assert (activity["preset"], activity["words"]) == (None, None)
    assert words(client, gym) == {"place": "gimnasio", "members": "miembros", "coach": "coach"}


@pg
def test_a_second_activity_changes_nothing(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "BJJ", "bjj")
    judo = add(client, gym, "Judo", "judo")

    # Its words are there for Ajustes' suggestion, not applied.
    assert judo["words"]["place"] == "dojo"
    assert words(client, gym) == TODAY


@pg
def test_the_owners_words_survive_another_activity(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Escalada", "escalada")
    response = pick(client, gym, CLUB)
    assert response.status_code == 200, response.text
    assert response.json()["vocabulary"] == CLUB

    add(client, gym, "Yoga", "yoga")
    assert words(client, gym) == CLUB


@pg
def test_words_picked_before_any_activity_are_kept(client: TestClient, gym: uuid.UUID) -> None:
    assert pick(client, gym, CLUB).status_code == 200

    add(client, gym, "Judo", "judo")
    assert words(client, gym) == CLUB


@pg
def test_removing_the_only_activity_and_adding_another_keeps_the_owners_words(
    client: TestClient, gym: uuid.UUID
) -> None:
    first = add(client, gym, "Remo", "remo")
    assert pick(client, gym, TODAY).status_code == 200
    gone = client.delete(f"/api/activities/{first['id']}", headers=as_gym(gym))
    assert gone.status_code == 204

    add(client, gym, "Escalada", "escalada")
    assert words(client, gym) == TODAY


@pg
def test_a_rename_keeps_the_preset(client: TestClient, gym: uuid.UUID) -> None:
    activity = add(client, gym, "Judo", "judo")
    response = client.patch(
        f"/api/activities/{activity['id']}", json={"name": "Judo infantil"}, headers=as_gym(gym)
    )
    assert response.status_code == 200, response.text
    assert response.json()["preset"] == "judo"


@pg
@pytest.mark.parametrize(
    "vocabulary",
    [
        None,
        {"place": "club", "members": "socios"},
        {"place": "estadio", "members": "socios", "coach": "profe"},
        {**CLUB, "by_hand": False},
    ],
)
def test_words_off_the_lists_are_refused(
    client: TestClient, gym: uuid.UUID, vocabulary: Any
) -> None:
    assert pick(client, gym, vocabulary).status_code == 422
    assert words(client, gym) == TODAY


@pg
def test_a_preset_off_the_list_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    response = client.post(
        "/api/activities", json={"name": "Polo", "preset": "polo"}, headers=as_gym(gym)
    )
    assert response.status_code == 422


@pg
def test_the_gyms_host_carries_its_words(client: TestClient, gym: uuid.UUID) -> None:
    assert pick(client, gym, CLUB).status_code == 200
    slug = client.get("/api/gym/settings", headers=as_gym(gym)).json()["slug"]

    host = client.get("/api/host", headers={"host": f"{slug}.rakin.cl"})
    assert host.status_code == 200, host.text
    assert host.json()["gym"]["vocabulary"] == CLUB


# --- migration 0059 -------------------------------------------------------------------


@pytest.fixture
def before() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0058")
        yield database


@pg
def test_stored_activities_named_as_a_preset_get_its_key(before: Database) -> None:
    gym = seed_gym(before, "sur")

    async def insert(conn: asyncpg.Connection) -> None:
        await conn.executemany(
            "INSERT INTO gym_activity (gym_id, name, uses_grades) VALUES ($1, $2, true)",
            [(gym, "bjj"), (gym, "Muay Thai"), (gym, "Capoeira")],
        )

    run(before.admin_url, insert)
    command.upgrade(before.alembic(), "0059")

    async def presets(conn: asyncpg.Connection) -> Any:
        rows = await conn.fetch("SELECT name, preset FROM gym_activity ORDER BY name")
        return [tuple(r) for r in rows]

    assert run(before.admin_url, presets) == [
        ("bjj", "bjj"),
        ("Capoeira", None),
        ("Muay Thai", "muay_thai"),
    ]

    async def settings(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval("SELECT settings ? 'vocabulary' FROM gym WHERE id = $1", gym)

    # Nobody's words change: the pilot keeps reading today's.
    assert run(before.admin_url, settings) is False
