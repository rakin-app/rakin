"""Clases pasadas (#407): a class registered after it happened, and marked like any other.

A gym that starts using Rakin mid-month creates the classes it held before, on their own
day and time, and marks them. The class is a class like any other; the gym's log tells
it apart (`class_backfilled`, and `attendance_backfilled` for each mark on another day
than the class's own, migration 0070). Marking it takes what each membership pays with
now and never touches the ledger; a drop-in visit is on the class's day; a trial guest
is refused; and every count reads the class's own date.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
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
    change,
    changed,
    class_type,
    created,
    credits_left,
    guest,
    join,
    plan,
    program,
    roster,
    row,
)
from tests.test_dropin_visits import membership_of, visit
from tests.test_guardians import add_person
from tests.test_plans import CREDITS, DROPIN, MONTHLY, TRIAL, add_staff
from tests.test_schedule import add_slot

pytestmark = pytest.mark.postgres

SANTIAGO = ZoneInfo("America/Santiago")


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


@pytest.fixture
def fundamentals(client: TestClient, gym: uuid.UUID) -> str:
    return class_type(client, gym, program(client, gym, "Adultos"))


def at(day: date, hour: int = 19, minute: int = 0) -> str:
    return datetime.combine(day, time(hour, minute), tzinfo=SANTIAGO).isoformat()


def start(
    client: TestClient, gym: uuid.UUID, body: dict[str, Any], by: uuid.UUID | None = None
) -> Any:
    return client.post("/api/sessions", json=body, headers=as_gym(gym, by))


def past_class(client: TestClient, gym: uuid.UUID, class_type_id: str, day: date) -> str:
    made = created(start(client, gym, {"class_type_id": class_type_id, "starts_at": at(day)}))
    return str(made["id"])


def log(db: Database, gym: uuid.UUID, action: str) -> list[dict[str, Any]]:
    """The gym's log rows of `action`, oldest first, `detail` read."""
    rows: list[asyncpg.Record] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT actor_id, person_id, detail, at FROM audit_event"
            " WHERE gym_id = $1 AND action = $2 ORDER BY at, id",
            gym,
            action,
        ),
    )
    return [{**r, "detail": json.loads(r["detail"])} for r in rows]


def no_attendance_role(db: Database, gym: uuid.UUID) -> uuid.UUID:
    """Someone on the team whose one role does not take attendance."""
    person = add_staff(db, gym, "coach")
    title = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "DELETE FROM staff_title WHERE gym_id = $1 AND person_id = $2", gym, person
        )
        await conn.execute(
            "INSERT INTO gym_title (id, gym_id, name, permissions)"
            " VALUES ($1, $2, 'Tesorera', ARRAY['money_read'])",
            title,
            gym,
        )
        await conn.execute(
            "INSERT INTO staff_title (gym_id, person_id, title_id, title_name, starts_on)"
            " VALUES ($1, $2, $3, 'Tesorera', $4)",
            gym,
            person,
            title,
            seeded_today(),
        )

    run(db.admin_url, query)
    return person


# --- creating one --------------------------------------------------------------------


def test_a_class_on_an_earlier_day_is_on_that_day_and_in_the_log(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    day = seeded_today() - timedelta(days=3)
    coach = add_staff(db, gym, "coach")
    made = created(
        start(
            client,
            gym,
            {"class_type_id": fundamentals, "starts_at": at(day, 7, 30), "coach_id": str(coach)},
        )
    )
    assert datetime.fromisoformat(made["starts_at"]) == datetime.fromisoformat(at(day, 7, 30))
    assert made["coach_id"] == str(coach)

    listed = client.get("/api/sessions", params={"date": day.isoformat()}, headers=as_gym(gym))
    assert [s["id"] for s in listed.json()["sessions"]] == [made["id"]]
    today = client.get("/api/sessions", headers=as_gym(gym)).json()
    assert made["id"] not in [s["id"] for s in today["sessions"]]

    [entry] = log(db, gym, "class_backfilled")
    assert entry["actor_id"] == seeded_owner(gym)
    assert entry["person_id"] is None
    assert entry["detail"] == {
        "session_id": made["id"],
        "class_type_id": fundamentals,
        "day": day.isoformat(),
    }


def test_a_class_made_today_is_unchanged_and_not_in_the_log(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    now = created(start(client, gym, {"class_type_id": fundamentals}))
    later_today = created(
        start(client, gym, {"class_type_id": fundamentals, "starts_at": at(seeded_today(), 23)})
    )
    listed = client.get("/api/sessions", headers=as_gym(gym)).json()
    assert {now["id"], later_today["id"]} <= {s["id"] for s in listed["sessions"]}
    assert log(db, gym, "class_backfilled") == []


def test_a_later_day_is_the_schedules_and_refused(
    client: TestClient, gym: uuid.UUID, fundamentals: str
) -> None:
    tomorrow = seeded_today() + timedelta(days=1)
    response = start(client, gym, {"class_type_id": fundamentals, "starts_at": at(tomorrow, 0)})
    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["type"] == "future_day"


def test_a_coach_registers_an_earlier_class_and_a_role_without_attendance_may_not(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    day = seeded_today() - timedelta(days=1)
    body = {"class_type_id": fundamentals, "starts_at": at(day)}
    coach = add_staff(db, gym, "coach")
    made = created(start(client, gym, body, coach))
    assert made["coach_id"] == str(coach)

    treasurer = no_attendance_role(db, gym)
    assert start(client, gym, body, treasurer).status_code == 403
    # Nor today's: running a class is `attendance`'s on any day.
    assert start(client, gym, {"class_type_id": fundamentals}, treasurer).status_code == 403


def move(client: TestClient, gym: uuid.UUID, session: str, starts_at: str) -> Any:
    return client.patch(
        f"/api/sessions/{session}", json={"starts_at": starts_at}, headers=as_gym(gym)
    )


def test_a_class_moved_to_an_earlier_day_is_in_the_log(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    today = seeded_today()
    made = created(start(client, gym, {"class_type_id": fundamentals}))["id"]
    day = today - timedelta(days=5)
    assert move(client, gym, made, at(day, 8)).status_code == 200
    [entry] = log(db, gym, "class_backfilled")
    assert entry["person_id"] is None
    assert entry["detail"] == {
        "session_id": made,
        "class_type_id": fundamentals,
        "day": day.isoformat(),
        "moved_from": today.isoformat(),
    }
    # Another time on the same day, or back to today, is no new back-filled class.
    assert move(client, gym, made, at(day, 10)).status_code == 200
    assert move(client, gym, made, at(today, 10)).status_code == 200
    assert len(log(db, gym, "class_backfilled")) == 1


def test_a_past_class_lasts_its_types_duration_as_of_its_day(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    today = seeded_today()
    day = today - timedelta(days=10)
    add_slot(
        client,
        gym,
        fundamentals,
        duration_minutes=45,
        valid_from=(today - timedelta(days=60)).isoformat(),
        valid_to=(today - timedelta(days=5)).isoformat(),
    )
    add_slot(client, gym, fundamentals, duration_minutes=90, valid_from=today.isoformat())

    assert created(start(client, gym, {"class_type_id": fundamentals}))["duration_minutes"] == 90
    past = created(start(client, gym, {"class_type_id": fundamentals, "starts_at": at(day)}))
    assert past["duration_minutes"] == 45
    asked = client.get(
        "/api/sessions/duration",
        params={"class_type_id": fundamentals, "date": day.isoformat()},
        headers=as_gym(gym),
    )
    assert asked.json()["duration_minutes"] == 45


def test_a_past_class_takes_tags_topic_and_coach_like_any_other(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    session = past_class(client, gym, fundamentals, seeded_today() - timedelta(days=2))
    tag = created(client.post("/api/class-tags", json={"name": "Guardia"}, headers=as_gym(gym)))
    coach = add_staff(db, gym, "coach")
    response = client.patch(
        f"/api/sessions/{session}",
        json={"topic": "Pasajes", "tag_ids": [tag["id"]], "coach_id": str(coach)},
        headers=as_gym(gym),
    )
    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["topic"], edited["coach_id"]) == ("Pasajes", str(coach))
    assert [t["id"] for t in edited["tags"]] == [tag["id"]]


# --- marking one ---------------------------------------------------------------------


def test_marking_a_past_class_spends_a_pack_counts_unlimited_and_is_logged(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    day = seeded_today() - timedelta(days=4)
    session = past_class(client, gym, fundamentals, day)
    paula = add_person(client, gym, "Paula Pack")
    marta = add_person(client, gym, "Marta Mensual")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    monthly = join(client, gym, marta, plan(client, gym, MONTHLY))
    before = credits_left(db, gym, pack)

    marked = changed(client, gym, session, mark=[pack, monthly])
    assert row(marked, "Paula Pack")["present"] and row(marked, "Marta Mensual")["present"]
    assert credits_left(db, gym, pack) == before - 1

    for person in (paula, marta):
        counts = client.get(f"/api/people/{person}/attendance", headers=as_gym(gym)).json()
        assert (counts["last_30_days"], counts["total"]) == (1, 1)

    entries = log(db, gym, "attendance_backfilled")
    assert {(e["person_id"], e["detail"]["membership_id"]) for e in entries} == {
        (uuid.UUID(paula), pack),
        (uuid.UUID(marta), monthly),
    }
    assert {e["detail"]["day"] for e in entries} == {day.isoformat()}
    assert {e["detail"]["session_id"] for e in entries} == {session}

    # Marking again is no new mark, and no new row; nor is it a correction of billing.
    changed(client, gym, session, mark=[pack])
    assert len(log(db, gym, "attendance_backfilled")) == 2
    corrections = client.get(f"/api/ledger/people/{paula}/corrections", headers=as_gym(gym))
    assert corrections.status_code == 200, corrections.text
    assert corrections.json()["items"] == []

    # Unmarking gives the credit back, as on the day.
    changed(client, gym, session, unmark=[pack])
    assert credits_left(db, gym, pack) == before


def test_marking_todays_class_writes_no_log_row(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    session = created(start(client, gym, {"class_type_id": fundamentals}))["id"]
    paula = add_person(client, gym, "Paula Hoy")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    changed(client, gym, session, mark=[pack])
    assert log(db, gym, "attendance_backfilled") == []


def test_a_membership_started_after_the_class_is_still_marked_at_it(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    # Joined today, the day the gym moved to Rakin: last week's classes are filled in
    # on the membership they have.
    session = past_class(client, gym, fundamentals, seeded_today() - timedelta(days=6))
    paula = add_person(client, gym, "Paula Nueva")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    assert row(roster(client, gym, session), "Paula Nueva")["present"] is False
    before = credits_left(db, gym, pack)
    changed(client, gym, session, mark=[pack])
    assert credits_left(db, gym, pack) == before - 1


def ledger_state(db: Database, membership: str) -> tuple[list[tuple[Any, ...]], ...]:
    """Every billing period and ledger entry of the membership, as they stand."""

    async def query(conn: asyncpg.Connection) -> tuple[list[tuple[Any, ...]], ...]:
        periods = await conn.fetch(
            "SELECT * FROM billing_period WHERE membership_id = $1 ORDER BY period_start",
            uuid.UUID(membership),
        )
        entries = await conn.fetch(
            "SELECT * FROM ledger_entry WHERE membership_id = $1 ORDER BY created_at, id",
            uuid.UUID(membership),
        )
        return [tuple(r) for r in periods], [tuple(r) for r in entries]

    result: tuple[list[tuple[Any, ...]], ...] = run(db.admin_url, query)
    return result


def test_marking_a_class_in_a_paid_period_leaves_the_ledger_as_it_was(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    marta = add_person(client, gym, "Marta Pagada")
    monthly = join(client, gym, marta, plan(client, gym, MONTHLY))
    [period] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT id, amount_due_clp FROM billing_period WHERE membership_id = $1",
            uuid.UUID(monthly),
        ),
    )
    paid = client.post(
        "/api/ledger/payments",
        json={
            "membership_id": monthly,
            "billing_period_id": str(period["id"]),
            "amount_clp": period["amount_due_clp"],
            "method": "cash",
        },
        headers=as_gym(gym),
    )
    assert paid.status_code == 201, paid.text
    before = ledger_state(db, monthly)

    session = past_class(client, gym, fundamentals, seeded_today() - timedelta(days=2))
    changed(client, gym, session, mark=[monthly])
    changed(client, gym, session, unmark=[monthly])
    changed(client, gym, session, mark=[monthly])
    assert ledger_state(db, monthly) == before


def test_a_drop_in_visitor_at_a_past_class_visits_on_its_day(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    day = seeded_today() - timedelta(days=3)
    session = past_class(client, gym, fundamentals, day)
    response = visit(client, gym, session, plan(client, gym, DROPIN))
    assert response.status_code == 201, response.text
    visitor = next(m for m in response.json()["members"] if m["name"] == "Visita Uno")
    membership = membership_of(db, visitor["membership_id"])
    assert (membership["period_start"], membership["period_end"]) == (day, day)
    [entry] = log(db, gym, "attendance_backfilled")
    assert entry["person_id"] == membership["person_id"]
    assert entry["detail"]["membership_id"] == visitor["membership_id"]


def test_a_trial_guest_at_a_past_class_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    session = past_class(client, gym, fundamentals, seeded_today() - timedelta(days=1))
    newcomer = add_person(client, gym, "Tomás Prueba")
    response = guest(client, gym, session, newcomer, plan(client, gym, TRIAL))
    assert response.status_code == 409, response.text
    assert "trial" in response.json()["detail"]
    held = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM membership WHERE person_id = $1", uuid.UUID(newcomer)
        ),
    )
    assert held == 0


def test_a_coach_marks_a_past_class_and_a_role_without_attendance_may_not(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    coach = add_staff(db, gym, "coach")
    session = created(
        start(
            client,
            gym,
            {"class_type_id": fundamentals, "starts_at": at(seeded_today() - timedelta(days=1))},
            coach,
        )
    )["id"]
    paula = add_person(client, gym, "Paula Coach")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    assert change(client, gym, session, coach, mark=[pack]).status_code == 200
    [entry] = log(db, gym, "attendance_backfilled")
    assert entry["actor_id"] == coach

    treasurer = no_attendance_role(db, gym)
    refused = change(client, gym, session, treasurer, unmark=[], mark=[pack])
    assert refused.status_code == 403
    # Unmarking writes no log row and asks for nothing new.
    assert change(client, gym, session, coach, unmark=[pack]).status_code == 200


# --- what it counts for --------------------------------------------------------------


def test_a_past_class_counts_by_its_own_day(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    today = seeded_today()
    day = today - timedelta(days=1)
    paula = add_person(client, gym, "Paula Mes")
    pack = join(client, gym, paula, plan(client, gym, CREDITS))
    changed(client, gym, past_class(client, gym, fundamentals, day), mark=[pack])
    old = past_class(client, gym, fundamentals, today - timedelta(days=45))
    changed(client, gym, old, mark=[pack])

    page = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(paula)))
    assert page.status_code == 200, page.text
    this_month = 1 if day.month == today.month else 0
    assert page.json()["attendance"] == {"this_month": this_month, "total": 2}
    counts = client.get(f"/api/people/{paula}/attendance", headers=as_gym(gym)).json()
    assert (counts["last_30_days"], counts["total"]) == (1, 2)


# --- the migration ---------------------------------------------------------------------


def test_the_migration_goes_down_and_up_again() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        gym = seed_gym(database, "gym-down")

        async def write(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, action) VALUES ($1, $2, $3)",
                gym,
                seeded_owner(gym),
                "class_backfilled",
            )

        run(database.admin_url, write)
        command.downgrade(database.alembic(), "0068")
        left = run(
            database.admin_url,
            lambda c: c.fetchval(
                "SELECT count(*) FROM audit_event WHERE action LIKE '%backfilled'"
            ),
        )
        assert left == 0
        migrate(database)
        assert (
            run(
                database.admin_url,
                in_gym(
                    gym, "SELECT count(*) AS n FROM audit_event WHERE action = 'class_backfilled'"
                ),
            )[0]["n"]
            == 0
        )
