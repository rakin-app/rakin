"""Sparring opcional (#346): sparring, open mats and Drilling only for a gym that spars.

A gym spars when one of its activities is a combat sport's, or it has none yet; the
owner may turn it on or off in Ajustes, Bloques. Off archives the Sparring and
Drilling block kinds, keeping the time they recorded, and runs an open mat as any class;
on again restores them. The practice takes its sport's word, which names the Sparring
kind: "Randori" in judo.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import gym_today
from app.domain.sparring import PRACTICES, practice_of, spars
from app.domain.vocabulary import PRESETS
from app.main import create_app
from app.seed.build import default_block_kind_id
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import SANTIAGO, join, plan
from tests.test_class_timer import (
    classes,
    local,
    ok,
    open_mat,
    put_plan,
    run_class,
    start,
    technique_and_sparring,
)
from tests.test_class_timer import kinds as kind_rows
from tests.test_guardians import add_person
from tests.test_plans import MONTHLY

# --- the rule, no database --------------------------------------------------------


def test_every_combat_word_is_a_presets() -> None:
    assert set(PRACTICES) <= set(PRESETS)


@pytest.mark.parametrize(
    ("settings", "presets", "expected"),
    [
        ({}, [], True),
        ({}, ["bjj"], True),
        ({}, ["escalada"], False),
        ({}, [None], False),
        ({}, ["escalada", "judo"], True),
        ({"sparring": True}, ["remo"], True),
        ({"sparring": False}, ["bjj"], False),
    ],
    ids=["none-yet", "bjj", "escalada", "free-named", "climbing-and-judo", "on", "off"],
)
def test_whether_a_gym_spars(settings: dict[str, Any], presets: list[str], expected: bool) -> None:
    assert spars(settings, presets) is expected


def test_the_first_combat_activity_names_the_practice() -> None:
    assert practice_of([]) == "sparring"
    assert practice_of(["escalada", "judo", "karate"]) == "randori"
    assert practice_of(["karate"]) == "kumite"


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
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def add(client: TestClient, gym: uuid.UUID, name: str, preset: str | None = None) -> str:
    body: dict[str, Any] = {"name": name}
    if preset is not None:
        body["preset"] = preset
    response = client.post("/api/activities", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def role(client: TestClient, gym: uuid.UUID) -> tuple[bool, str]:
    me = ok(client.get("/api/me/role", headers=as_gym(gym)))
    return me["sparring"], me["practice"]


def switch(client: TestClient, gym: uuid.UUID, on: bool) -> Any:
    return ok(client.patch("/api/gym/settings", json={"sparring": on}, headers=as_gym(gym)))


def kinds(client: TestClient, gym: uuid.UUID) -> dict[str, bool]:
    """Each kind's name, and whether it is archived."""
    listed = ok(client.get("/api/block-kinds", headers=as_gym(gym)))
    return {k["name"]: k["archived"] for k in listed}


ALL_ON = {
    "Calentamiento": False,
    "Técnica": False,
    "Drilling": False,
    "Juegos": False,
    "Sparring": False,
    "Otro": False,
}
OFF = {**ALL_ON, "Drilling": True, "Sparring": True}
RANDORI = {("Randori" if k == "Sparring" else k): v for k, v in ALL_ON.items()}


@pg
def test_a_gym_with_no_activity_yet_spars_as_today(client: TestClient, gym: uuid.UUID) -> None:
    assert role(client, gym) == (True, "sparring")
    assert ok(client.get("/api/gym/settings", headers=as_gym(gym)))["sparring"] is True
    assert kinds(client, gym) == ALL_ON


@pg
def test_a_bjj_gym_keeps_todays_kinds(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "BJJ", "bjj")
    assert role(client, gym) == (True, "sparring")
    assert kinds(client, gym) == ALL_ON


@pg
def test_a_climbing_gym_does_not_spar(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Escalada", "escalada")
    assert role(client, gym) == (False, "sparring")
    assert ok(client.get("/api/gym/settings", headers=as_gym(gym)))["sparring"] is False
    assert kinds(client, gym) == OFF


@pg
def test_a_combat_activity_added_later_turns_it_on(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Escalada", "escalada")
    judo = add(client, gym, "Judo", "judo")
    assert role(client, gym) == (True, "randori")
    assert kinds(client, gym) == RANDORI
    # Taken away again, the gym is back to not sparring, and the kind to its own name.
    assert client.delete(f"/api/activities/{judo}", headers=as_gym(gym)).status_code == 204
    assert role(client, gym) == (False, "sparring")
    assert kinds(client, gym) == OFF


@pg
def test_judo_names_the_sparring_kind_unless_the_gym_renamed_it(
    client: TestClient, gym: uuid.UUID
) -> None:
    sparring = default_block_kind_id(gym, "sparring")
    renamed = {"name": "Combates"}
    ok(client.patch(f"/api/block-kinds/{sparring}", json=renamed, headers=as_gym(gym)))
    add(client, gym, "Judo", "judo")
    assert role(client, gym) == (True, "randori")
    assert "Combates" in kinds(client, gym)


@pg
def test_the_owners_pick_holds_whatever_the_activities(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Escalada", "escalada")
    assert switch(client, gym, True)["sparring"] is True
    assert kinds(client, gym) == ALL_ON
    add(client, gym, "Remo", "remo")
    assert role(client, gym)[0] is True
    assert switch(client, gym, False)["sparring"] is False
    add(client, gym, "BJJ", "bjj")
    assert role(client, gym)[0] is False
    assert kinds(client, gym) == OFF


@pg
def test_a_kind_archived_by_hand_stays_so_while_nothing_turns(
    client: TestClient, gym: uuid.UUID
) -> None:
    drilling = default_block_kind_id(gym, "drilling")
    archive = {"archived": True}
    ok(client.patch(f"/api/block-kinds/{drilling}", json=archive, headers=as_gym(gym)))
    add(client, gym, "BJJ", "bjj")
    add(client, gym, "MMA", "mma")
    assert kinds(client, gym)["Drilling"] is True


@pg
def test_turning_it_off_and_on_loses_no_recorded_time(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "BJJ", "bjj")
    adults, fundamentals = classes(client, gym)
    monthly = plan(client, gym, {**MONTHLY, "program_id": adults})
    ana = add_person(client, gym, "Ana Rojas")
    membership = join(client, gym, ana, monthly)
    month_start = gym_today(SANTIAGO).replace(day=1)
    run_class(
        client,
        gym,
        fundamentals,
        local(month_start, 0, 30),
        technique_and_sparring(kind_rows(client, gym)),
        [{"actual_seconds": 1000}, {"actual_seconds": 900, "rounds_completed": 3}],
        [membership],
    )

    def seconds() -> dict[str, int]:
        time_ = ok(client.get(f"/api/people/{ana}/time", headers=as_gym(gym)))["all_time"]
        return {t["name"]: t["seconds"] for t in time_["by_kind"]}

    assert seconds() == {"Técnica": 1000, "Sparring": 900}
    switch(client, gym, False)
    assert kinds(client, gym) == OFF
    assert seconds() == {"Técnica": 1000, "Sparring": 900}
    switch(client, gym, True)
    assert kinds(client, gym) == ALL_ON
    assert seconds() == {"Técnica": 1000, "Sparring": 900}


@pg
def test_an_open_mat_runs_as_a_class_in_a_gym_that_does_not_spar(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults, _ = classes(client, gym)
    # Made while the gym spars, as the pilot's are; the API still takes one after.
    mat = open_mat(client, gym, adults)
    add(client, gym, "Escalada", "escalada")
    listed = ok(client.get("/api/class-types", headers=as_gym(gym)))
    assert [c["kind"] for c in listed if c["id"] == mat] == ["open_mat"]
    session = start(client, gym, mat, local(gym_today(SANTIAGO), 9) - timedelta(days=1))
    technique = kind_rows(client, gym)["Técnica"]["id"]
    planned = ok(
        put_plan(client, gym, session, [{"block_kind_id": technique, "planned_seconds": 600}])
    )
    assert planned["class_kind"] == "class"
    assert (
        ok(client.get(f"/api/sessions/{session}/blocks", headers=as_gym(gym)))["class_kind"]
        == "class"
    )


@pg
def test_a_student_reads_whether_the_gym_spars(client: TestClient, gym: uuid.UUID) -> None:
    add(client, gym, "Karate", "karate")
    adults, _ = classes(client, gym)
    monthly = plan(client, gym, {**MONTHLY, "program_id": adults})
    ana = add_person(client, gym, "Ana Rojas")
    join(client, gym, ana, monthly)
    me = ok(client.get("/api/me/role", headers=as_gym(gym, uuid.UUID(ana))))
    assert (me["role"], me["sparring"], me["practice"]) == (None, True, "kumite")


# --- the migration ------------------------------------------------------------------

ACTIVITY = "INSERT INTO gym_activity (gym_id, name, preset) VALUES ($1, $2, $3)"
KINDS = "SELECT name, archived FROM block_kind WHERE gym_id = $1 ORDER BY position"


@pg
def test_the_migration_brings_the_gyms_already_there_in_line() -> None:
    with throwaway_database(require_test_database_url()) as fresh:
        migrate(fresh, "0060")
        gyms = {name: seed_gym(fresh, name) for name in ("bjj", "climbing", "judo", "empty")}
        for name, preset, label in (
            ("bjj", "bjj", "BJJ"),
            ("climbing", "escalada", "Escalada"),
            ("judo", "escalada", "Escalada"),
            ("judo", "judo", "Judo"),
        ):
            run(fresh.admin_url, in_gym(gyms[name], ACTIVITY, gyms[name], label, preset))
        migrate(fresh)

        def after(name: str) -> dict[str, bool]:
            rows = run(fresh.admin_url, in_gym(gyms[name], KINDS, gyms[name]))
            return {r["name"]: r["archived"] for r in rows}

        assert after("bjj") == ALL_ON
        assert after("empty") == ALL_ON
        assert after("climbing") == OFF
        assert after("judo") == RANDORI

        command.downgrade(fresh.alembic(), "0060")
        assert after("climbing") == ALL_ON
        assert after("judo") == ALL_ON
