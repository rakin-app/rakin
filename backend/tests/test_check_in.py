"""Check-in at the door (#348, migration 0060): open-access class types, the session of
the day the first check-in makes, credits spent, and what open access is kept out of.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_attendance import (
    at,
    class_type,
    created,
    credits_left,
    join,
    plan,
    program,
    session_of,
)
from tests.test_guardians import add_person
from tests.test_plans import CREDITS, add_staff

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


def ok(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


def error_type(response: Any) -> str:
    assert response.status_code == 422, response.text
    return str(response.json()["detail"][0]["type"])


def open_access(client: TestClient, gym: uuid.UUID, program_id: str, cost: int = 1) -> Any:
    body = {"name": "Acceso libre", "program_id": program_id, "kind": "open_access"}
    return created(
        client.post("/api/class-types", json={**body, "credit_cost": cost}, headers=as_gym(gym))
    )


def check_in(
    client: TestClient, gym: uuid.UUID, door: str, membership: str, by: uuid.UUID | None = None
) -> Any:
    return client.post(
        f"/api/check-in/{door}", json={"membership_id": membership}, headers=as_gym(gym, by)
    )


def search(client: TestClient, gym: uuid.UUID, door: str, q: str) -> Any:
    return ok(client.get(f"/api/check-in/{door}/search", params={"q": q}, headers=as_gym(gym)))


def day_sessions(db: Database, gym: uuid.UUID) -> Any:
    return run(
        db.api_url,
        in_gym(gym, "SELECT id, open_day, coach_id FROM session ORDER BY open_day"),
    )


@pg
def test_an_open_access_type_counts_as_a_class_by_default(
    client: TestClient, gym: uuid.UUID
) -> None:
    door = open_access(client, gym, program(client, gym, "Adultos"))
    assert (door["kind"], door["counts_as_class"]) == ("open_access", True)
    listed = ok(client.get("/api/check-in", headers=as_gym(gym)))
    assert [(d["name"], d["session_id"], d["arrivals"]) for d in listed] == [
        ("Acceso libre", None, [])
    ]


@pg
def test_a_gym_with_no_open_access_has_no_door(client: TestClient, gym: uuid.UUID) -> None:
    class_type(client, gym, program(client, gym, "Adultos"))
    assert ok(client.get("/api/check-in", headers=as_gym(gym))) == []


@pg
def test_two_check_ins_the_same_day_make_one_session_the_next_day_another(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    door = open_access(client, gym, program(client, gym, "Adultos"))["id"]
    pack = plan(client, gym, CREDITS)
    paula = join(client, gym, add_person(client, gym, "Paula Contreras"), pack)
    tomas = join(client, gym, add_person(client, gym, "Tomás Pérez"), pack)

    first = ok(check_in(client, gym, door, paula, coach))
    second = ok(check_in(client, gym, door, tomas))
    assert first["session_id"] == second["session_id"] is not None
    assert [a["name"] for a in second["arrivals"]] == ["Tomás Pérez", "Paula Contreras"]
    assert second["date"] == seeded_today().isoformat()
    made = day_sessions(db, gym)
    # Taught by whoever checked the first one in.
    assert [(r["open_day"], r["coach_id"]) for r in made] == [(seeded_today(), coach)]

    # The day before's session, as yesterday left it.
    yesterday = seeded_today() - timedelta(days=1)
    run(
        db.admin_url,
        in_gym(
            None,
            "UPDATE session SET open_day = $1, starts_at = starts_at - interval '1 day'"
            " WHERE id = $2",
            yesterday,
            uuid.UUID(first["session_id"]),
        ),
    )
    today = ok(check_in(client, gym, door, paula))
    assert today["session_id"] != first["session_id"]
    assert [a["name"] for a in today["arrivals"]] == ["Paula Contreras"]
    assert [r["open_day"] for r in day_sessions(db, gym)] == [yesterday, seeded_today()]


@pg
def test_a_check_in_spends_the_credit_cost_once_and_undo_gives_it_back(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    door = open_access(client, gym, program(client, gym, "Adultos"), cost=2)["id"]
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )

    day = ok(check_in(client, gym, door, paula))
    assert credits_left(db, gym, paula) == 10
    arrival = day["arrivals"][0]
    assert (arrival["credits_consumed"], arrival["credits_remaining"]) == (2, 10)
    assert arrival["marked_at"] is not None
    # A second tap changes nothing.
    ok(check_in(client, gym, door, paula))
    assert credits_left(db, gym, paula) == 10

    undone = ok(client.delete(f"/api/check-in/{door}/{paula}", headers=as_gym(gym)))
    assert undone["arrivals"] == []
    assert credits_left(db, gym, paula) == 12


@pg
def test_a_spent_pack_or_a_lapsed_plan_still_checks_in(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    door = open_access(client, gym, program(client, gym, "Adultos"))["id"]
    paula = join(
        client,
        gym,
        add_person(client, gym, "Paula Contreras"),
        plan(client, gym, {**CREDITS, "credits": 1}),
    )
    run(
        db.admin_url,
        in_gym(None, "UPDATE membership SET credits_remaining = 0 WHERE id = $1", uuid.UUID(paula)),
    )
    found = search(client, gym, door, "paula")
    assert [(c["credits_remaining"], c["checked_in_at"]) for c in found] == [(0, None)]
    day = ok(check_in(client, gym, door, paula))
    assert day["arrivals"][0]["credits_consumed"] == 0
    assert search(client, gym, door, "paula")[0]["checked_in_at"] is not None


@pg
def test_the_search_finds_by_name_or_rut_whom_the_program_admits(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults, kids = program(client, gym, "Adultos"), program(client, gym, "Kids")
    door = open_access(client, gym, adults)["id"]
    paula = add_person(client, gym, "Paula Contreras", rut="12.345.678-5")
    join(client, gym, paula, plan(client, gym, {**CREDITS, "program_id": adults}))
    mateo = add_person(client, gym, "Mateo Contreras")
    join(client, gym, mateo, plan(client, gym, {**CREDITS, "name": "Kids", "program_id": kids}))
    add_person(client, gym, "Sin Plan Contreras")

    assert [c["name"] for c in search(client, gym, door, "contreras")] == ["Paula Contreras"]
    assert [c["name"] for c in search(client, gym, door, "12345678")] == ["Paula Contreras"]
    assert search(client, gym, door, "  ") == []


@pg
def test_an_open_access_session_with_no_visits_is_not_unmarked(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    door = open_access(client, gym, adults)["id"]
    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    ok(check_in(client, gym, door, paula))
    ok(client.delete(f"/api/check-in/{door}/{paula}", headers=as_gym(gym)))
    lesson = session_of(client, gym, class_type(client, gym, adults))

    unmarked = ok(client.get("/api/sessions/unmarked", headers=as_gym(gym)))
    assert [s["id"] for s in unmarked["sessions"]] == [lesson]
    today = ok(client.get("/api/sessions", headers=as_gym(gym)))
    assert sorted(s["class_type_kind"] for s in today["sessions"]) == ["class", "open_access"]


@pg
def test_a_visit_counts_for_attendance_and_inactivity(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    door = open_access(client, gym, program(client, gym, "Adultos"))["id"]
    person = add_person(client, gym, "Paula Contreras")
    paula = join(client, gym, person, plan(client, gym, CREDITS))
    ok(check_in(client, gym, door, paula))

    counts = ok(client.get(f"/api/people/{person}/attendance", headers=as_gym(gym)))
    assert (counts["last_30_days"], counts["total"]) == (1, 1)
    away = run(
        db.api_url,
        in_gym(
            gym, "SELECT last_attended_on FROM v_inactive WHERE person_id = $1", uuid.UUID(person)
        ),
    )
    assert [r["last_attended_on"] for r in away] == [seeded_today()]


@pg
def test_open_access_has_no_classes_to_start_schedule_or_time(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    door = open_access(client, gym, adults)["id"]
    headers = as_gym(gym)
    started = client.post("/api/sessions", json={"class_type_id": door}, headers=headers)
    assert error_type(started) == "open_access"
    slot = {
        "class_type_id": door,
        "weekdays": [1],
        "start_time": "19:00",
        "duration_minutes": 60,
        "coach_id": str(seeded_owner(gym)),
    }
    assert error_type(client.post("/api/schedule", json=slot, headers=headers)) == "open_access"
    lesson = session_of(client, gym, class_type(client, gym, adults))
    moved = client.patch(f"/api/sessions/{lesson}", json={"class_type_id": door}, headers=headers)
    assert error_type(moved) == "open_access"

    paula = join(
        client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, CREDITS)
    )
    day = ok(check_in(client, gym, door, paula))["session_id"]
    later = {"starts_at": at(seeded_today() + timedelta(days=1))}
    assert error_type(client.patch(f"/api/sessions/{day}", json=later, headers=headers)) == (
        "open_access"
    )
    # The rest of it changes as any session's does.
    ok(client.patch(f"/api/sessions/{day}", json={"topic": "Muro nuevo"}, headers=headers))
    kinds = ok(client.get("/api/block-kinds", headers=headers))
    block = {"block_kind_id": kinds[0]["id"], "planned_seconds": 600}
    planned = client.put(f"/api/sessions/{day}/blocks", json={"blocks": [block]}, headers=headers)
    assert error_type(planned) == "open_access_plan"


@pg
def test_a_used_class_type_never_becomes_or_stops_being_open_access(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    headers = as_gym(gym)
    unused = class_type(client, gym, adults, "Libre")
    turned = ok(
        client.patch(f"/api/class-types/{unused}", json={"kind": "open_access"}, headers=headers)
    )
    assert (turned["kind"], turned["counts_as_class"]) == ("open_access", True)

    used = class_type(client, gym, adults)
    session_of(client, gym, used)
    refused = client.patch(
        f"/api/class-types/{used}", json={"kind": "open_access"}, headers=headers
    )
    assert error_type(refused) == "open_access_kind"


@pg
def test_a_cancelled_day_refuses_check_ins_and_a_member_may_not_check_in(
    client: TestClient, gym: uuid.UUID
) -> None:
    door = open_access(client, gym, program(client, gym, "Adultos"))["id"]
    pack = plan(client, gym, CREDITS)
    person = add_person(client, gym, "Paula Contreras")
    paula = join(client, gym, person, pack)
    member = uuid.UUID(person)
    assert check_in(client, gym, door, paula, member).status_code == 403
    assert client.get("/api/check-in", headers=as_gym(gym, member)).status_code == 403
    tomas = join(client, gym, add_person(client, gym, "Tomás Pérez"), pack)
    day = ok(check_in(client, gym, door, paula))["session_id"]
    ok(client.delete(f"/api/check-in/{door}/{paula}", headers=as_gym(gym)))
    ok(client.post(f"/api/sessions/{day}/cancel", headers=as_gym(gym)))

    assert check_in(client, gym, door, tomas).status_code == 409
    assert ok(client.get("/api/check-in", headers=as_gym(gym)))[0]["cancelled"] is True
    missing = client.get(f"/api/check-in/{uuid.uuid4()}/search", headers=as_gym(gym))
    assert missing.status_code == 404
