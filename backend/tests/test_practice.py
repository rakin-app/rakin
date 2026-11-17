"""A gym's free practice (#346): sparring, randori, escalada libre.

The gym's first activity with a preset names its free practice and the open mat made of
it; with none yet, or none with a preset, it is "Práctica libre". The name lands on the practice's
block kind, unless the gym renamed that, and `/api/me/role` answers it as the gym has it
now, for every screen that names the practice.
"""

import uuid
from collections.abc import Iterator
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.practice import NEUTRAL, PRACTICES, practice_of
from app.domain.vocabulary import PRESETS, PresetKey
from app.main import create_app
from app.seed.build import default_block_kind_id
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import join, plan
from tests.test_class_timer import classes, ok
from tests.test_guardians import add_person
from tests.test_plans import MONTHLY

# --- the names, no database -------------------------------------------------------


def test_every_preset_names_its_practice() -> None:
    assert set(PRACTICES) == set(PRESETS) == set(get_args(PresetKey))


def test_the_first_activity_names_the_practice() -> None:
    assert practice_of([]) == NEUTRAL
    assert practice_of([None]) == NEUTRAL
    assert practice_of([None, "judo"]).block == "Randori"
    assert practice_of(["escalada", "judo"]).block == "Escalada libre"
    assert practice_of(["judo"]).block == "Randori"
    bjj = practice_of(["bjj"])
    assert (bjj.block, bjj.open_mat) == ("Sparring", "Open mat")


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


RENAME = "UPDATE block_kind SET name = $2 WHERE id = block_kind_default_id($1, 'sparring')"


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    """A gym as `app.gyms create` makes one with no activity: its practice neutral."""
    gym_id = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    run(db.admin_url, in_gym(gym_id, RENAME, gym_id, NEUTRAL.block))
    return gym_id


def add(client: TestClient, gym: uuid.UUID, name: str, preset: str | None = None) -> str:
    body: dict[str, Any] = {"name": name}
    if preset is not None:
        body["preset"] = preset
    response = client.post("/api/activities", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def names(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> tuple[str, str]:
    practice = ok(client.get("/api/me/role", headers=as_gym(gym, by)))["practice"]
    return practice["block"], practice["open_mat"]


def kinds(client: TestClient, gym: uuid.UUID) -> list[str]:
    return [k["name"] for k in ok(client.get("/api/block-kinds", headers=as_gym(gym)))]


@pg
def test_a_gym_with_no_activity_practises_freely(client: TestClient, gym: uuid.UUID) -> None:
    assert names(client, gym) == ("Práctica libre", "Práctica libre")
    assert "Práctica libre" in kinds(client, gym)


@pg
def test_bjj_spars_in_open_mats(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "BJJ", "bjj")
    assert names(client, gym) == ("Sparring", "Open mat")
    assert "Sparring" in kinds(client, gym)


@pg
def test_a_climbing_gym_climbs_freely(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Escalada", "escalada")
    assert names(client, gym) == ("Escalada libre", "Escalada libre")
    listed = kinds(client, gym)
    assert "Escalada libre" in listed and "Sparring" not in listed


@pg
def test_only_the_first_activity_names_it(client: TestClient, gym: uuid.UUID) -> None:
    judo = add(client, gym, "Judo", "judo")
    add(client, gym, "Escalada", "escalada")
    assert names(client, gym)[0] == "Randori"
    # Taken away, the next oldest names it.
    assert client.delete(f"/api/activities/{judo}", headers=as_gym(gym)).status_code == 204
    assert names(client, gym)[0] == "Escalada libre"
    assert "Escalada libre" in kinds(client, gym)


@pg
def test_the_first_activity_with_a_preset_names_it(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Parkour")
    assert names(client, gym)[0] == "Práctica libre"
    add(client, gym, "BJJ", "bjj")
    assert names(client, gym) == ("Sparring", "Open mat")
    assert "Sparring" in kinds(client, gym)


@pg
def test_a_name_the_gym_gave_stays(client: TestClient, gym: uuid.UUID) -> None:
    practice = default_block_kind_id(gym, "sparring")
    renamed = {"name": "Rolar"}
    ok(client.patch(f"/api/block-kinds/{practice}", json=renamed, headers=as_gym(gym)))
    add(client, gym, "BJJ", "bjj")
    # The screens read the kind's name as the gym has it; the open mat keeps BJJ's own.
    assert names(client, gym) == ("Rolar", "Open mat")
    assert "Rolar" in kinds(client, gym)


@pg
def test_a_name_another_kind_has_is_not_taken(client: TestClient, gym: uuid.UUID) -> None:
    created = {"name": "Randori", "is_sparring": True}
    response = client.post("/api/block-kinds", json=created, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    add(client, gym, "Judo", "judo")
    assert kinds(client, gym).count("Randori") == 1
    assert "Práctica libre" in kinds(client, gym)


@pg
def test_a_student_reads_the_gyms_practice(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Karate", "karate")
    adults, _ = classes(client, gym)
    monthly = plan(client, gym, {**MONTHLY, "program_id": adults})
    ana = add_person(client, gym, "Ana Rojas")
    join(client, gym, ana, monthly)
    assert names(client, gym, uuid.UUID(ana)) == ("Kumite", "Kumite")


# --- the migration ------------------------------------------------------------------

ACTIVITY = "INSERT INTO gym_activity (gym_id, name, preset) VALUES ($1, $2, $3)"
PRACTICE_KIND = "SELECT name FROM block_kind WHERE id = block_kind_default_id($1, 'sparring')"


@pg
def test_the_migration_names_the_practice_of_the_gyms_already_there() -> None:
    with throwaway_database(require_test_database_url()) as fresh:
        migrate(fresh, "0060")
        gyms = {
            name: seed_gym(fresh, name)
            for name in ("bjj", "climbing", "judo", "empty", "free", "late", "renamed")
        }
        for name, label, preset in (
            ("bjj", "BJJ", "bjj"),
            ("climbing", "Escalada", "escalada"),
            ("judo", "Judo", "judo"),
            ("judo", "Escalada", "escalada"),
            ("free", "Parkour", None),
            ("late", "Parkour", None),
            ("late", "BJJ", "bjj"),
            ("renamed", "Judo", "judo"),
        ):
            run(fresh.admin_url, in_gym(gyms[name], ACTIVITY, gyms[name], label, preset))
        run(fresh.admin_url, in_gym(gyms["renamed"], RENAME, gyms["renamed"], "Rolar"))
        migrate(fresh)

        def practice(name: str) -> str:
            return str(run(fresh.admin_url, in_gym(gyms[name], PRACTICE_KIND, gyms[name]))[0][0])

        assert practice("bjj") == "Sparring"
        assert practice("climbing") == "Escalada libre"
        assert practice("judo") == "Randori"
        assert practice("empty") == "Práctica libre"
        assert practice("free") == "Práctica libre"
        assert practice("late") == "Sparring"
        assert practice("renamed") == "Rolar"

        command.downgrade(fresh.alembic(), "0060")
        assert [practice(n) for n in ("climbing", "judo", "empty", "renamed")] == [
            "Sparring",
            "Sparring",
            "Sparring",
            "Rolar",
        ]
