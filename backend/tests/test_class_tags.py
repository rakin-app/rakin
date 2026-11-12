"""Class tags and hours per tag (#243, migration 0041).

An owner or admin keeps the gym's tags; a class's coach, an admin or the owner puts
them on a class, and a slot's default tags go on the classes it makes. A student reads
what their classes were about, never the coach's notes, and everyone reads hours per
tag: a class's duration, added to each tag it carries, over the classes a person
attended or the gym held. A cancelled class counts nowhere.
"""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.domain.dates import gym_today, start_of_local_day
from app.main import create_app
from app.schemas.class_tags import MAX_TAGS
from app.schemas.sessions import SessionUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import SANTIAGO, changed, class_type, join, plan, program
from tests.test_class_timer import ok
from tests.test_guardians import add_person, new_kid
from tests.test_plans import MONTHLY, add_staff
from tests.test_schedule import EVERY_DAY, add_slot, change_slot, first_made

pg = pytest.mark.postgres


# --- input rules, no database -----------------------------------------------------


def test_a_class_s_tags_are_each_once_and_never_null() -> None:
    one, two = uuid.uuid4(), uuid.uuid4()
    assert SessionUpdate(tag_ids=[one, two, one]).tag_ids == [one, two]
    assert SessionUpdate(tag_ids=[]).tag_ids == []
    with pytest.raises(ValidationError):
        SessionUpdate(tag_ids=None)
    with pytest.raises(ValidationError):
        SessionUpdate(tag_ids=[uuid.uuid4() for _ in range(MAX_TAGS + 1)])


# --- the database ------------------------------------------------------------------


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


def tag(client: TestClient, gym: uuid.UUID, name: str) -> str:
    response = client.post("/api/class-tags", json={"name": name}, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def edit_tag(
    client: TestClient,
    gym: uuid.UUID,
    tag_id: str,
    body: dict[str, Any],
    by: uuid.UUID | None = None,
) -> Any:
    return client.patch(f"/api/class-tags/{tag_id}", json=body, headers=as_gym(gym, by))


def local(day: date, hour: int = 19, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute), tzinfo=SANTIAGO).isoformat()


def today() -> date:
    return gym_today(SANTIAGO)


def early_today() -> str:
    """A minute into today in the gym's timezone: begun, and in this month and year."""
    return (start_of_local_day(today(), SANTIAGO) + timedelta(minutes=1)).isoformat()


def start(
    client: TestClient,
    gym: uuid.UUID,
    class_type_id: str,
    starts_at: str,
    minutes: int | None = 60,
    **more: Any,
) -> str:
    body = {"class_type_id": class_type_id, "starts_at": starts_at, "duration_minutes": minutes}
    response = client.post("/api/sessions", json={**body, **more}, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def set_tags(
    client: TestClient, gym: uuid.UUID, session: str, tags: list[str], by: uuid.UUID | None = None
) -> Any:
    return client.patch(f"/api/sessions/{session}", json={"tag_ids": tags}, headers=as_gym(gym, by))


def tags_on(client: TestClient, gym: uuid.UUID, session: str) -> list[str]:
    got = ok(client.get(f"/api/sessions/{session}", headers=as_gym(gym)))
    return [t["name"] for t in got["tags"]]


def hours(listed: Any) -> dict[str, int]:
    return {row["name"]: row["minutes"] for row in listed["tags"]}


def error_type(response: Any) -> str:
    assert response.status_code == 422, response.text
    return str(response.json()["detail"][0]["type"])


# --- the gym's tags ----------------------------------------------------------------


@pg
def test_an_owner_or_admin_creates_renames_and_archives_tags(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    admin = add_staff(db, gym, "admin")
    renamed = ok(edit_tag(client, gym, guard, {"name": "Pasaje"}, by=admin))
    assert (renamed["name"], renamed["archived"]) == ("Pasaje", False)
    strength = tag(client, gym, "Fuerza")

    assert ok(edit_tag(client, gym, guard, {"archived": True}))["archived"] is True

    listed = ok(client.get("/api/class-tags", headers=as_gym(gym)))
    assert [(t["name"], t["archived"]) for t in listed] == [("Fuerza", False), ("Pasaje", True)]
    active = ok(client.get("/api/class-tags", params={"archived": "false"}, headers=as_gym(gym)))
    assert [t["id"] for t in active] == [strength]
    assert ok(edit_tag(client, gym, guard, {"archived": False}))["archived"] is False


@pg
def test_a_tag_s_name_is_unique_in_its_gym_case_ignored(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    tag(client, gym, "Fuerza")
    again = client.post("/api/class-tags", json={"name": " fuerza "}, headers=as_gym(gym))
    assert again.status_code == 409, again.text
    other = tag(client, gym, "Movilidad")
    assert edit_tag(client, gym, other, {"name": "FUERZA"}).status_code == 409
    # Another gym has its own.
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:6]}")
    tag(client, norte, "Fuerza")
    assert client.post("/api/class-tags", json={"name": ""}, headers=as_gym(gym)).status_code == 422


@pg
def test_a_coach_reads_tags_and_changes_none_and_a_member_reads_none(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    strength = tag(client, gym, "Fuerza")
    coach = add_staff(db, gym, "coach")

    assert len(ok(client.get("/api/class-tags", headers=as_gym(gym, coach)))) == 1
    made = client.post("/api/class-tags", json={"name": "Otro"}, headers=as_gym(gym, coach))
    assert made.status_code == 403
    assert edit_tag(client, gym, strength, {"archived": True}, by=coach).status_code == 403
    member = uuid.UUID(add_person(client, gym, "Ana Rojas"))
    assert client.get("/api/class-tags", headers=as_gym(gym, member)).status_code == 403
    assert client.get("/api/class-tags/hours", headers=as_gym(gym, member)).status_code == 403


@pg
def test_tags_stay_in_their_gym(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    strength = tag(client, gym, "Fuerza")
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:6]}")
    assert ok(client.get("/api/class-tags", headers=as_gym(norte))) == []
    assert edit_tag(client, norte, strength, {"name": "x"}).status_code == 404
    # Nor on another gym's class, even past the API.
    session = start(
        client, norte, class_type(client, norte, program(client, norte, "A")), local(today())
    )
    assert error_type(set_tags(client, norte, session, [strength])) == "unknown_tag"
    rows = run(
        db.api_url,
        in_gym(gym, "SELECT count(*) AS n FROM class_tag WHERE id = $1", uuid.UUID(strength)),
    )
    assert rows[0]["n"] == 1
    hidden = run(
        db.api_url,
        in_gym(norte, "SELECT count(*) AS n FROM class_tag WHERE id = $1", uuid.UUID(strength)),
    )
    assert hidden[0]["n"] == 0


# --- a class's tags ----------------------------------------------------------------


@pg
def test_a_class_s_coach_an_admin_or_the_owner_sets_its_tags(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard, strength = tag(client, gym, "Pasaje de guardia"), tag(client, gym, "Fuerza")
    coach, other, admin = (add_staff(db, gym, role) for role in ("coach", "coach", "admin"))
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    session = start(client, gym, fundamentals, local(today()), coach_id=str(coach))

    tagged = set_tags(client, gym, session, [strength, guard], by=coach)
    assert tagged.status_code == 200, tagged.text
    assert [t["name"] for t in tagged.json()["tags"]] == ["Fuerza", "Pasaje de guardia"]
    assert set_tags(client, gym, session, [guard], by=other).status_code == 403
    assert ok(set_tags(client, gym, session, [guard], by=admin))["tags"][0]["id"] == guard
    assert ok(set_tags(client, gym, session, []))["tags"] == []
    # Listed with the day's classes too.
    tag_on = ok(set_tags(client, gym, session, [strength], by=coach))
    day = ok(client.get("/api/sessions", params={"date": today().isoformat()}, headers=as_gym(gym)))
    assert [t["name"] for t in day["sessions"][0]["tags"]] == ["Fuerza"]
    assert tag_on["topic"] is None


@pg
def test_an_archived_tag_stays_on_a_class_and_goes_on_no_new_one(
    client: TestClient, gym: uuid.UUID
) -> None:
    guard, strength = tag(client, gym, "Pasaje de guardia"), tag(client, gym, "Fuerza")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    old = start(client, gym, fundamentals, local(today() - timedelta(days=3)))
    ok(set_tags(client, gym, old, [guard]))
    ok(edit_tag(client, gym, guard, {"archived": True}))

    assert tags_on(client, gym, old) == ["Pasaje de guardia"]
    # Kept while another is added, ...
    kept = ok(set_tags(client, gym, old, [guard, strength]))
    assert [(t["name"], t["archived"]) for t in kept["tags"]] == [
        ("Fuerza", False),
        ("Pasaje de guardia", True),
    ]
    # ... but not put on a class that lacks it.
    new = start(client, gym, fundamentals, local(today()))
    assert error_type(set_tags(client, gym, new, [guard])) == "archived_tag"
    assert error_type(set_tags(client, gym, new, [str(uuid.uuid4())])) == "unknown_tag"


@pg
def test_deleting_a_tagged_class_takes_its_tags(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    strength = tag(client, gym, "Fuerza")
    session = start(client, gym, class_type(client, gym, program(client, gym, "A")), local(today()))
    ok(set_tags(client, gym, session, [strength]))
    assert client.delete(f"/api/sessions/{session}", headers=as_gym(gym)).status_code == 204
    rows = run(db.api_url, in_gym(gym, "SELECT count(*) AS n FROM session_tag"))
    assert rows[0]["n"] == 0


# --- the schedule's default tags ---------------------------------------------------


def slot_session_tags(db: Database, gym: uuid.UUID) -> dict[date, list[str]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT s.slot_date, coalesce(array_agg(t.name ORDER BY t.name)"
            " FILTER (WHERE t.id IS NOT NULL), '{}') AS tags"
            " FROM session s LEFT JOIN session_tag st ON st.session_id = s.id"
            " LEFT JOIN class_tag t ON t.id = st.tag_id"
            " WHERE s.slot_id IS NOT NULL GROUP BY s.slot_date",
        ),
    )
    return {r["slot_date"]: list(r["tags"]) for r in rows}


@pg
def test_a_slot_s_tags_go_on_each_class_it_makes_and_one_class_changes_alone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard, strength = tag(client, gym, "Pasaje de guardia"), tag(client, gym, "Fuerza")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, tag_ids=[guard])
    assert [t["name"] for t in slot["tags"]] == ["Pasaje de guardia"]

    made = slot_session_tags(db, gym)
    assert made and all(tags == ["Pasaje de guardia"] for tags in made.values())

    # "Solo esta clase": one class's tags, and the slot keeps its own.
    first = first_made()
    [one] = [
        s["id"]
        for s in ok(
            client.get("/api/sessions", params={"date": first.isoformat()}, headers=as_gym(gym))
        )["sessions"]
    ]
    ok(set_tags(client, gym, one, [strength]))
    [listed] = ok(client.get("/api/schedule", headers=as_gym(gym)))
    assert [t["id"] for t in listed["tags"]] == [guard]

    # "Esta y las siguientes": the classes still on the slot's tags take the new ones;
    # the one tagged alone keeps its own.
    changed_slot = ok(change_slot(client, gym, slot["id"], {"tag_ids": [guard, strength]}))
    assert {t["name"] for t in changed_slot["tags"]} == {"Pasaje de guardia", "Fuerza"}
    after = slot_session_tags(db, gym)
    assert after[first] == ["Fuerza"]
    assert all(tags == ["Fuerza", "Pasaje de guardia"] for d, tags in after.items() if d != first)


@pg
def test_a_slot_change_from_a_later_date_carries_its_tags(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, tag_ids=[guard])
    later = first_made() + timedelta(days=3)

    moved = ok(change_slot(client, gym, slot["id"], {"from_date": later.isoformat(), "topic": "x"}))

    assert moved["id"] != slot["id"]
    assert [t["id"] for t in moved["tags"]] == [guard]
    assert all(tags == ["Pasaje de guardia"] for tags in slot_session_tags(db, gym).values())


@pg
def test_an_archived_slot_tag_goes_on_no_class_it_makes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard, gone = tag(client, gym, "Pasaje de guardia"), tag(client, gym, "Viejo")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, tag_ids=[guard, gone])
    ok(edit_tag(client, gym, gone, {"archived": True}))
    # The classes it makes from now on, as the nightly run would.
    run(db.owner_url, in_gym(gym, "DELETE FROM session"))
    last = today() + timedelta(days=13)
    run(db.owner_url, in_gym(gym, "SELECT schedule_sessions($1, $2, NULL, true)", today(), last))

    made = slot_session_tags(db, gym)
    assert made and all(tags == ["Pasaje de guardia"] for tags in made.values())
    # Nor does another slot take it.
    other = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    assert error_type(change_slot(client, gym, other["id"], {"tag_ids": [gone]})) == "archived_tag"


# --- what students read ------------------------------------------------------------


def my_classes(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    response = client.get("/api/me/classes", headers=as_gym(gym, uuid.UUID(person)))
    assert response.status_code == 200, response.text
    return response


@pg
def test_a_student_reads_their_classes_topic_and_tags_and_never_the_notes(
    client: TestClient, gym: uuid.UUID
) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    monthly = plan(client, gym, MONTHLY)
    ana = add_person(client, gym, "Ana Rojas")
    member = join(client, gym, ana, monthly)
    older = start(
        client, gym, fundamentals, local(today() - timedelta(days=400)), topic="Torreando"
    )
    newer = start(
        client,
        gym,
        fundamentals,
        early_today(),
        topic="Pasaje torreando",
        notes="Ana se resintió la rodilla",
    )
    skipped = start(client, gym, fundamentals, early_today(), notes="nadie")
    ok(set_tags(client, gym, newer, [guard]))
    for session in (older, newer):
        changed(client, gym, session, mark=[member])

    response = my_classes(client, gym, ana)

    assert "rodilla" not in response.text and "notes" not in response.text
    [mine] = response.json()["people"]
    assert (mine["person_id"], mine["name"]) == (ana, "Ana Rojas")
    assert [c["session_id"] for c in mine["classes"]] == [newer, older]
    first = mine["classes"][0]
    assert (first["topic"], first["class_type_name"], first["program_name"]) == (
        "Pasaje torreando",
        "Fundamentos",
        "Adultos",
    )
    assert [t["name"] for t in first["tags"]] == ["Pasaje de guardia"]
    assert skipped not in {c["session_id"] for c in mine["classes"]}


@pg
def test_a_guardian_reads_each_dependent_s_classes(client: TestClient, gym: uuid.UUID) -> None:
    strength = tag(client, gym, "Fuerza")
    kids = class_type(client, gym, program(client, gym, "Niños"))
    monthly = plan(client, gym, MONTHLY)
    mother = add_person(client, gym, "Carla Soto")
    tomas = new_kid(client, gym, mother, "Tomás Soto")
    member = join(client, gym, tomas, monthly)
    session = start(client, gym, kids, early_today(), minutes=45, notes="Tomás llegó tarde")
    ok(set_tags(client, gym, session, [strength]))
    changed(client, gym, session, mark=[member])

    response = my_classes(client, gym, mother)

    assert "tarde" not in response.text and "notes" not in response.text
    # She trains nowhere here, so only her son's.
    [son] = response.json()["people"]
    assert (son["name"], [c["session_id"] for c in son["classes"]]) == ("Tomás Soto", [session])
    assert hours(son["this_month"]) == {"Fuerza": 45}
    # The son reads his own, and nobody else's.
    assert [p["name"] for p in my_classes(client, gym, tomas).json()["people"]] == ["Tomás Soto"]


@pg
def test_a_student_s_hours_per_tag_this_month_and_year(client: TestClient, gym: uuid.UUID) -> None:
    guard, strength, gone = (tag(client, gym, n) for n in ("Pasaje de guardia", "Fuerza", "Viejo"))
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    ana = add_person(client, gym, "Ana Rojas")
    member = join(client, gym, ana, plan(client, gym, MONTHLY))
    both = start(client, gym, fundamentals, early_today(), minutes=90)
    alone = start(client, gym, fundamentals, early_today(), minutes=60)
    untagged = start(client, gym, fundamentals, early_today(), minutes=30)
    last_year = start(client, gym, fundamentals, local(date(today().year - 1, 6, 1)), minutes=60)
    missed = start(client, gym, fundamentals, early_today(), minutes=120)
    ok(set_tags(client, gym, both, [guard, strength]))
    ok(set_tags(client, gym, alone, [gone]))
    ok(set_tags(client, gym, last_year, [guard]))
    ok(set_tags(client, gym, missed, [guard]))
    for session in (both, alone, untagged, last_year):
        changed(client, gym, session, mark=[member])
    # Archived after the class: it still counts.
    ok(edit_tag(client, gym, gone, {"archived": True}))

    [mine] = my_classes(client, gym, ana).json()["people"]

    # Each class adds its whole duration to every tag it carries.
    assert hours(mine["this_month"]) == {"Pasaje de guardia": 90, "Fuerza": 90, "Viejo": 60}
    assert hours(mine["this_year"]) == hours(mine["this_month"])
    assert mine["this_month"]["untagged_minutes"] == 30
    assert mine["this_month"]["first_day"] == today().replace(day=1).isoformat()
    assert mine["this_year"]["last_day"] == date(today().year, 12, 31).isoformat()
    viejo = next(r for r in mine["this_month"]["tags"] if r["name"] == "Viejo")
    assert (viejo["archived"], viejo["classes"]) == (True, 1)


# --- what staff read ---------------------------------------------------------------


@pg
def test_the_gym_s_hours_count_held_classes_and_never_cancelled_ones(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    march = date(2025, 3, 10)
    held = start(client, gym, fundamentals, local(march), minutes=90)
    cancelled = start(client, gym, fundamentals, local(march + timedelta(days=1)), minutes=60)
    april = start(client, gym, fundamentals, local(date(2025, 4, 2)), minutes=60)
    no_duration = start(client, gym, fundamentals, local(march), minutes=None)
    for session in (held, cancelled, april, no_duration):
        ok(set_tags(client, gym, session, [guard]))
    ok(client.post(f"/api/sessions/{cancelled}/cancel", headers=as_gym(gym)))
    coach = add_staff(db, gym, "coach")

    def gym_hours(**params: int) -> Any:
        return ok(client.get("/api/class-tags/hours", params=params, headers=as_gym(gym, coach)))

    month = gym_hours(year=2025, month=3)
    assert month["tags"] == [
        {
            "tag_id": guard,
            "name": "Pasaje de guardia",
            "archived": False,
            "classes": 2,
            "minutes": 90,
        }
    ]
    assert (month["first_day"], month["last_day"]) == ("2025-03-01", "2025-03-31")
    assert hours(gym_hours(year=2025)) == {"Pasaje de guardia": 150}
    assert gym_hours()["first_day"] == today().replace(day=1).isoformat()
    refused = client.get("/api/class-tags/hours", params={"month": 3}, headers=as_gym(gym))
    assert refused.status_code == 422
    assert (
        client.get(
            "/api/class-tags/hours", params={"year": 2025, "month": 13}, headers=as_gym(gym)
        ).status_code
        == 422
    )


@pg
def test_a_class_yet_to_begin_has_not_been_held(client: TestClient, gym: uuid.UUID) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    ahead = start(client, gym, fundamentals, local(date(today().year + 1, 1, 5)), minutes=60)
    ok(set_tags(client, gym, ahead, [guard]))
    upcoming = ok(
        client.get("/api/class-tags/hours", params={"year": today().year + 1}, headers=as_gym(gym))
    )
    assert upcoming["tags"] == []


@pg
def test_the_ficha_s_hours_are_the_member_s_attended_classes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    guard = tag(client, gym, "Pasaje de guardia")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    ana = add_person(client, gym, "Ana Rojas")
    member = join(client, gym, ana, plan(client, gym, MONTHLY))
    came = start(client, gym, fundamentals, local(date(2025, 3, 10)), minutes=90)
    missed = start(client, gym, fundamentals, local(date(2025, 3, 12)), minutes=60)
    for session in (came, missed):
        ok(set_tags(client, gym, session, [guard]))
    changed(client, gym, came, mark=[member])
    coach = add_staff(db, gym, "coach")

    ficha = ok(
        client.get(
            f"/api/people/{ana}/tag-hours",
            params={"year": 2025, "month": 3},
            headers=as_gym(gym, coach),
        )
    )

    assert hours(ficha) == {"Pasaje de guardia": 90}
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:6]}")
    assert client.get(f"/api/people/{ana}/tag-hours", headers=as_gym(norte)).status_code == 404


# --- the migration -----------------------------------------------------------------


@pg
def test_downgrade_to_0040_and_back() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0040")
        tables = "SELECT to_regclass('class_tag') IS NULL AND to_regclass('session_tag') IS NULL"
        assert run(scratch.admin_url, lambda c: c.fetchval(tables)) is True
        migrate(scratch)
        assert run(scratch.admin_url, lambda c: c.fetchval(tables)) is False
