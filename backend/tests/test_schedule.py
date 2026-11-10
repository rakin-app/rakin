"""The weekly schedule (#167, migration 0035): slots make their classes ahead, a class
lasts a duration, a slot changes from a date on, and closed days have no classes.

A slot's classes are made through `HORIZON_DAYS` days from today in the gym's
timezone, once per slot and date however often generation runs. Changing a slot from a
date never rewrites a class before it, one that has started or one with attendance;
cancelled classes stay cancelled.
"""

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db_bootstrap import to_dsn
from app.domain.dates import gym_today
from app.domain.schedule import HORIZON_DAYS, horizon
from app.jobs import schedule as schedule_job
from app.jobs.runner import run_due
from app.main import create_app
from app.schemas.schedule import SlotCreate, SlotUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_attendance import SANTIAGO, changed, class_type, program
from tests.test_class_timer import ok
from tests.test_plans import add_staff

pg = pytest.mark.postgres

EVERY_DAY = [1, 2, 3, 4, 5, 6, 7]


# --- input rules, no database -----------------------------------------------------


def slot_body(**overrides: Any) -> dict[str, Any]:
    return {
        "class_type_id": str(uuid.uuid4()),
        "weekdays": [1, 3, 5],
        "start_time": "19:00",
        "duration_minutes": 90,
        "coach_id": str(uuid.uuid4()),
        **overrides,
    }


def test_weekdays_are_iso_each_once_monday_first() -> None:
    assert SlotCreate.model_validate(slot_body(weekdays=[5, 1, 5])).weekdays == [1, 5]
    for weekdays in ([], [0], [8]):
        with pytest.raises(ValidationError):
            SlotCreate.model_validate(slot_body(weekdays=weekdays))


def test_a_slot_lasts_a_minute_to_a_day_and_starts_on_the_minute() -> None:
    for minutes in (0, 1441):
        with pytest.raises(ValidationError):
            SlotCreate.model_validate(slot_body(duration_minutes=minutes))
    with pytest.raises(ValidationError):
        SlotCreate.model_validate(slot_body(start_time="19:00:30"))


def test_a_slot_ends_on_or_after_it_starts() -> None:
    with pytest.raises(ValidationError):
        SlotCreate.model_validate(slot_body(valid_from="2026-12-01", valid_to="2026-11-30"))
    with pytest.raises(ValidationError):
        SlotUpdate.model_validate({"from_date": "2026-12-01", "valid_to": "2026-11-30"})


def test_a_change_cannot_null_what_a_slot_must_have() -> None:
    for field in ("weekdays", "start_time", "duration_minutes", "coach_id", "class_type_id"):
        with pytest.raises(ValidationError):
            SlotUpdate.model_validate({field: None})


def test_the_horizon_is_two_weeks_today_included() -> None:
    assert HORIZON_DAYS == 14
    assert horizon(date(2026, 11, 10)) == (date(2026, 11, 10), date(2026, 11, 23))


# --- against the database ----------------------------------------------------------


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


def today() -> date:
    return gym_today(SANTIAGO)


def add_slot(
    client: TestClient, gym: uuid.UUID, class_type_id: str, **overrides: Any
) -> dict[str, Any]:
    body = slot_body(class_type_id=class_type_id, coach_id=str(seeded_owner(gym)), **overrides)
    response = client.post("/api/schedule", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def change_slot(
    client: TestClient, gym: uuid.UUID, slot: str, body: dict[str, Any], by: uuid.UUID | None = None
) -> Any:
    return client.patch(f"/api/schedule/{slot}", json=body, headers=as_gym(gym, by))


def sessions_of(db: Database, gym: uuid.UUID) -> list[asyncpg.Record]:
    """The gym's sessions, by start, with their gym-local date and time."""
    rows: list[asyncpg.Record] = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT id, slot_id, slot_date, starts_at, duration_minutes, class_type_id,"
            " coach_id, topic, cancelled_at,"
            " (starts_at AT TIME ZONE 'America/Santiago')::date AS local_day,"
            " (starts_at AT TIME ZONE 'America/Santiago')::time AS local_time"
            " FROM session ORDER BY starts_at",
        ),
    )
    return rows


def generate(db: Database, gym: uuid.UUID, first: date, last: date, refill: bool = False) -> int:
    (row,) = run(
        db.owner_url,
        in_gym(gym, "SELECT schedule_sessions($1, $2, NULL, $3)", first, last, refill),
    )
    made: int = row[0]
    return made


def slot_rows(db: Database, gym: uuid.UUID) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = run(
        db.owner_url,
        in_gym(gym, "SELECT id, valid_from, valid_to, start_time FROM schedule_slot ORDER BY 2"),
    )
    return rows


def run_job(db: Database, day: date) -> None:
    """The `schedule` job alone, for `day`, as the nightly runner runs it."""

    async def go() -> None:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            await conn.execute("DELETE FROM job_run WHERE job_name = $1", schedule_job.NAME)
            report = await run_due(conn, [schedule_job.JOB], day)
            assert report.outcome == "succeeded"
        finally:
            await conn.close()

    asyncio.run(go())


def first_made(at: time = time(19)) -> date:
    """The first date a slot starting at `at` makes a class for: today if that is still
    ahead in the gym's timezone, else tomorrow, since no class is made already begun."""
    ahead = datetime.combine(today(), at, tzinfo=SANTIAGO) > datetime.now(UTC)
    return today() if ahead else today() + timedelta(days=1)


def dates(rows: list[asyncpg.Record]) -> list[date]:
    return [r["slot_date"] for r in rows]


def every_day(first: date, last: date) -> list[date]:
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


# --- making classes ----------------------------------------------------------------


@pg
def test_a_slot_makes_its_classes_for_the_next_two_weeks_and_never_twice(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=[1, 3, 5], topic="Guardia")
    first, last = horizon(today())
    expected = [d for d in every_day(first_made(), last) if d.isoweekday() in (1, 3, 5)]

    made = sessions_of(db, gym)
    assert dates(made) == expected
    assert {r["slot_id"] for r in made} == {uuid.UUID(slot["id"])}
    assert {(r["local_time"], r["duration_minutes"], r["topic"]) for r in made} == {
        (time(19), 90, "Guardia")
    }
    assert [r["local_day"] for r in made] == expected

    # The job, the API and generation itself again: nothing more.
    assert generate(db, gym, first, last) == 0
    assert generate(db, gym, first, last, refill=True) == 0
    run_job(db, today())
    assert len(sessions_of(db, gym)) == len(expected)


@pg
def test_the_nightly_job_adds_the_next_day_and_a_deleted_class_stays_deleted(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    made = sessions_of(db, gym)
    assert dates(made) == every_day(first_made(), horizon(today())[1])
    last = made[-1]
    assert client.delete(f"/api/sessions/{last['id']}", headers=as_gym(gym)).status_code == 204

    run_job(db, today() + timedelta(days=1))

    after = dates(sessions_of(db, gym))
    assert last["slot_date"] not in after
    assert after[-1] == horizon(today() + timedelta(days=1))[1]
    assert len(after) == len(made)  # one deleted, one added


@pg
def test_a_slot_starts_and_ends_when_it_says(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    starts = today() + timedelta(days=3)
    ends = today() + timedelta(days=6)
    add_slot(
        client,
        gym,
        fundamentals,
        weekdays=EVERY_DAY,
        valid_from=starts.isoformat(),
        valid_to=ends.isoformat(),
    )
    assert dates(sessions_of(db, gym)) == every_day(starts, ends)


@pg
def test_a_deactivated_class_type_makes_no_classes(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    starts = today() + timedelta(days=1)
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, valid_from=starts.isoformat())
    client.patch(f"/api/class-types/{fundamentals}", json={"active": False}, headers=as_gym(gym))
    assert generate(db, gym, *horizon(today() + timedelta(days=5)), refill=True) == 0


@pg
def test_classes_land_on_the_gym_s_wall_clock_across_dst_and_midnight(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    # Chile goes back an hour on 2027-04-04 and forward, at midnight, on 2027-09-05.
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, valid_from="2027-04-02")
    add_slot(
        client, gym, fundamentals, weekdays=EVERY_DAY, start_time="23:30", valid_from="2027-04-02"
    )
    generate(db, gym, date(2027, 4, 2), date(2027, 4, 6))
    generate(db, gym, date(2027, 9, 3), date(2027, 9, 7), refill=True)

    made = sessions_of(db, gym)
    for row in made:
        # On its own date at its own time, whatever the offset that day.
        assert row["local_day"] == row["slot_date"]
        assert row["local_time"] in (time(19), time(23, 30))
    offsets = {
        r["starts_at"].astimezone(SANTIAGO).utcoffset()
        for r in made
        if r["slot_date"] in (date(2027, 4, 2), date(2027, 4, 6))
    }
    assert offsets == {timedelta(hours=-3), timedelta(hours=-4)}

    # 23:30 in Santiago is the next day in UTC; the gym's day still lists it.
    late = next(r for r in made if r["local_time"] == time(23, 30))
    assert late["starts_at"].astimezone(UTC).date() == late["slot_date"] + timedelta(days=1)
    listed = ok(
        client.get(
            "/api/sessions", params={"date": late["slot_date"].isoformat()}, headers=as_gym(gym)
        )
    )
    assert str(late["id"]) in [s["id"] for s in listed["sessions"]]


@pg
def test_a_class_at_a_skipped_local_time_keeps_its_date(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    # 00:30 does not exist on 2027-09-05 in Santiago: it takes the offset before the
    # change, as the rest of the app does (`start_of_local_day`), and stays on that date.
    add_slot(client, gym, fundamentals, weekdays=[7], start_time="00:30", valid_from="2027-09-01")
    generate(db, gym, date(2027, 9, 5), date(2027, 9, 5))
    (row,) = sessions_of(db, gym)
    assert row["local_day"] == date(2027, 9, 5)
    # 00:30 at -04, which is 01:30 at -03: compared in UTC, since Python holds a wall
    # time in the gap unequal to every instant (PEP 495).
    assert row["starts_at"] == datetime(2027, 9, 5, 4, 30, tzinfo=UTC)


# --- changing a slot -----------------------------------------------------------------


def backfilled_slot(
    client: TestClient, db: Database, gym: uuid.UUID, class_type_id: str, **overrides: Any
) -> dict[str, Any]:
    """An every-day slot since a week ago, with its past week's classes held too.

    The schedule never makes a class already begun, so those are written as the classes
    it would have made then."""
    since = today() - timedelta(days=7)
    slot = add_slot(
        client, gym, class_type_id, weekdays=EVERY_DAY, valid_from=since.isoformat(), **overrides
    )
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO session (gym_id, class_type_id, starts_at, duration_minutes, coach_id,"
            " topic, slot_id, slot_date)"
            " SELECT gym_id, class_type_id, (d::date + start_time) AT TIME ZONE"
            " 'America/Santiago', duration_minutes, coach_id, topic, id, d::date"
            " FROM schedule_slot, generate_series($2::date, $3::date, interval '1 day') d"
            " WHERE id = $1",
            uuid.UUID(slot["id"]),
            since,
            today() - timedelta(days=1),
        ),
    )
    return slot


@pg
def test_changing_a_slot_from_a_date_leaves_the_classes_before_it(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = backfilled_slot(client, gym=gym, db=db, class_type_id=fundamentals)
    before = {r["slot_date"]: r for r in sessions_of(db, gym)}
    from_date = today() + timedelta(days=2)

    response = change_slot(
        client,
        gym,
        slot["id"],
        {"from_date": from_date.isoformat(), "start_time": "20:00", "duration_minutes": 60},
    )
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["id"] != slot["id"]
    assert (new["valid_from"], new["start_time"], new["duration_minutes"]) == (
        from_date.isoformat(),
        "20:00:00",
        60,
    )
    old, _ = (r for r in slot_rows(db, gym))
    assert (old["id"], old["valid_to"]) == (uuid.UUID(slot["id"]), from_date - timedelta(days=1))

    after = {r["slot_date"]: r for r in sessions_of(db, gym)}
    assert after.keys() == before.keys()
    for day, row in after.items():
        if day < from_date:
            assert row == before[day], day  # past and earlier classes untouched
        else:
            assert (row["local_time"], row["duration_minutes"]) == (time(20), 60)
            assert row["slot_id"] == uuid.UUID(new["id"])
            assert row["id"] == before[day]["id"]  # the same class, moved


@pg
def test_a_change_from_the_past_never_rewrites_a_class_that_happened(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = backfilled_slot(client, gym=gym, db=db, class_type_id=fundamentals)
    before = {r["slot_date"]: r for r in sessions_of(db, gym)}
    from_date = today() - timedelta(days=3)

    response = change_slot(
        client, gym, slot["id"], {"from_date": from_date.isoformat(), "start_time": "07:00"}
    )
    assert response.status_code == 200, response.text
    for day, row in {r["slot_date"]: r for r in sessions_of(db, gym)}.items():
        if day < today():
            assert row["starts_at"] == before[day]["starts_at"], day
        elif day > today():
            assert row["local_time"] == time(7), day


@pg
def test_a_change_from_the_first_date_changes_the_slot_itself(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    response = change_slot(client, gym, slot["id"], {"coach_id": str(add_staff(db, gym, "coach"))})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == slot["id"]
    assert len(slot_rows(db, gym)) == 1
    coaches = {r["coach_id"] for r in sessions_of(db, gym)}
    assert coaches == {uuid.UUID(response.json()["coach_id"])}


@pg
def test_changing_the_weekdays_drops_and_adds_dates_and_cancelled_ones_stay_cancelled(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=[1, 3, 5])
    first, last = horizon(today())
    tomorrow = today() + timedelta(days=1)
    kept = next(r for r in sessions_of(db, gym) if r["slot_date"] > tomorrow)
    cancelled = client.post(f"/api/sessions/{kept['id']}/cancel", headers=as_gym(gym))
    assert cancelled.status_code == 200, cancelled.text
    runs_on = sorted(
        {kept["slot_date"].isoweekday(), (kept["slot_date"] + timedelta(1)).isoweekday()}
    )

    response = change_slot(
        client,
        gym,
        slot["id"],
        {"from_date": tomorrow.isoformat(), "weekdays": runs_on, "start_time": "18:00"},
    )
    assert response.status_code == 200, response.text

    after = [r for r in sessions_of(db, gym) if r["slot_date"] >= tomorrow]
    assert dates(after) == [d for d in every_day(tomorrow, last) if d.isoweekday() in runs_on]
    again = next(r for r in after if r["id"] == kept["id"])
    assert again["cancelled_at"] is not None
    assert again["local_time"] == time(18)
    assert first == today()


@pg
def test_a_class_with_attendance_is_left_alone_by_a_change(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    marked = sessions_of(db, gym)[3]
    roster = ok(client.get(f"/api/sessions/{marked['id']}/roster", headers=as_gym(gym)))
    changed(client, gym, str(marked["id"]), mark=[roster["members"][0]["membership_id"]])

    change_slot(client, gym, slot["id"], {"start_time": "06:00", "weekdays": [1]})
    after = {r["id"]: r for r in sessions_of(db, gym)}
    assert after[marked["id"]]["starts_at"] == marked["starts_at"]


@pg
def test_solo_esta_clase_changes_one_class_and_the_schedule_does_not_remake_it(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    one = sessions_of(db, gym)[5]
    moved = datetime.combine(one["slot_date"], time(10), tzinfo=SANTIAGO).isoformat()
    response = client.patch(
        f"/api/sessions/{one['id']}",
        json={"starts_at": moved, "duration_minutes": 45},
        headers=as_gym(gym),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["duration_minutes"], body["slot_date"]) == (45, one["slot_date"].isoformat())

    generate(db, gym, *horizon(today()), refill=True)
    rows = [r for r in sessions_of(db, gym) if r["slot_date"] == one["slot_date"]]
    assert [(r["local_time"], r["duration_minutes"]) for r in rows] == [(time(10), 45)]
    others = {r["duration_minutes"] for r in sessions_of(db, gym) if r["id"] != one["id"]}
    assert others == {90}


@pg
def test_a_change_moves_the_slot_s_own_topic_and_keeps_a_coach_s(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, topic="Guardia")
    written = sessions_of(db, gym)[4]
    client.patch(f"/api/sessions/{written['id']}", json={"topic": "Pasajes"}, headers=as_gym(gym))
    change_slot(client, gym, slot["id"], {"topic": "Montada"})
    topics = {r["slot_date"]: r["topic"] for r in sessions_of(db, gym)}
    assert topics.pop(written["slot_date"]) == "Pasajes"
    assert set(topics.values()) == {"Montada"}


@pg
def test_shortening_a_slot_deletes_its_classes_after_the_end(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    ends = today() + timedelta(days=4)
    response = change_slot(client, gym, slot["id"], {"valid_to": ends.isoformat()})
    assert response.status_code == 200, response.text
    assert max(dates(sessions_of(db, gym))) == ends


@pg
def test_a_change_from_after_the_end_is_refused(
    client: TestClient, gym: uuid.UUID, fundamentals: str
) -> None:
    ends = today() + timedelta(days=2)
    slot = add_slot(client, gym, fundamentals, valid_to=ends.isoformat())
    response = change_slot(
        client,
        gym,
        slot["id"],
        {"from_date": (ends + timedelta(days=1)).isoformat(), "start_time": "08:00"},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "after_valid_to"


# --- deleting a slot -----------------------------------------------------------------


@pg
def test_deleting_a_slot_deletes_only_its_classes_yet_to_happen(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = backfilled_slot(client, gym=gym, db=db, class_type_id=fundamentals)
    marked = next(r for r in sessions_of(db, gym) if r["slot_date"] > today())
    roster = ok(client.get(f"/api/sessions/{marked['id']}/roster", headers=as_gym(gym)))
    changed(client, gym, str(marked["id"]), mark=[roster["members"][0]["membership_id"]])

    response = client.delete(f"/api/schedule/{slot['id']}", headers=as_gym(gym))
    assert response.status_code == 204, response.text
    left = sessions_of(db, gym)
    assert all(r["slot_id"] is None for r in left)
    assert marked["id"] in {r["id"] for r in left}
    assert all(r["local_day"] <= today() or r["id"] == marked["id"] for r in left)
    assert len([r for r in left if r["local_day"] < today()]) == 7
    assert slot_rows(db, gym) == []


# --- closed days ---------------------------------------------------------------------


@pg
def test_a_closed_day_has_no_classes_and_reopening_makes_them(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    holiday = today() + timedelta(days=5)
    later = today() + timedelta(days=HORIZON_DAYS + 2)

    for day, label in ((holiday, "Feriado"), (later, None)):
        response = client.put(
            f"/api/closed-days/{day.isoformat()}", json={"label": label}, headers=as_gym(gym)
        )
        assert response.status_code == 200, response.text
    assert holiday not in dates(sessions_of(db, gym))
    listed = ok(client.get("/api/closed-days", headers=as_gym(gym)))
    assert listed == [
        {"day": holiday.isoformat(), "label": "Feriado"},
        {"day": later.isoformat(), "label": None},
    ]

    # The job skips it as it reaches it.
    run_job(db, today() + timedelta(days=4))
    assert later not in dates(sessions_of(db, gym))
    assert holiday not in dates(sessions_of(db, gym))

    response = client.delete(f"/api/closed-days/{holiday.isoformat()}", headers=as_gym(gym))
    assert response.status_code == 204
    assert holiday in dates(sessions_of(db, gym))


def set_generated_until(db: Database, gym: uuid.UUID, day: date) -> None:
    run(db.owner_url, in_gym(gym, "UPDATE schedule_slot SET generated_until = $1", day))


def delete_after(db: Database, gym: uuid.UUID, day: date) -> None:
    run(db.owner_url, in_gym(gym, "DELETE FROM session WHERE slot_date > $1", day))


@pg
def test_closing_a_day_goes_by_where_a_class_is_now(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    by_date = {r["slot_date"]: r for r in sessions_of(db, gym)}
    moved_off, landing = today() + timedelta(days=3), today() + timedelta(days=4)
    moved_on, closed = today() + timedelta(days=6), today() + timedelta(days=7)

    def move(day: date, to: date) -> None:
        when = datetime.combine(to, time(10), tzinfo=SANTIAGO).isoformat()
        response = client.patch(
            f"/api/sessions/{by_date[day]['id']}", json={"starts_at": when}, headers=as_gym(gym)
        )
        assert response.status_code == 200, response.text

    move(moved_off, landing)
    move(moved_on, closed)
    for day in (moved_off, closed):
        response = client.put(f"/api/closed-days/{day}", json={}, headers=as_gym(gym))
        assert response.status_code == 200, response.text

    left = {r["id"] for r in sessions_of(db, gym)}
    # Moved off the day it closed: stays. Moved onto one: goes, with the day's own.
    assert by_date[moved_off]["id"] in left
    assert by_date[moved_on]["id"] not in left
    assert by_date[closed]["id"] not in left
    assert by_date[landing]["id"] in left


@pg
def test_no_class_is_made_whose_start_has_passed(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    # 00:01 today has begun at any hour but the first minute of the day.
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY, start_time="00:01")
    made = sessions_of(db, gym)
    assert today() not in dates(made)
    assert dates(made) == every_day(today() + timedelta(days=1), horizon(today())[1])
    assert generate(db, gym, today(), today(), refill=True) == 0
    assert ok(client.get("/api/sessions/unmarked", headers=as_gym(gym)))["sessions"] == []


@pg
def test_reopening_a_day_past_a_gap_does_not_skip_it(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    add_slot(client, gym, fundamentals, weekdays=EVERY_DAY)
    # The nightly run had made classes only through two days from now.
    behind = today() + timedelta(days=2)
    delete_after(db, gym, behind)
    set_generated_until(db, gym, behind)
    reopened = today() + timedelta(days=5)
    client.put(f"/api/closed-days/{reopened}", json={}, headers=as_gym(gym))
    assert client.delete(f"/api/closed-days/{reopened}", headers=as_gym(gym)).status_code == 204
    assert reopened in dates(sessions_of(db, gym))

    run_job(db, today())
    assert dates(sessions_of(db, gym)) == every_day(first_made(), horizon(today())[1])


# --- who may ---------------------------------------------------------------------------


@pg
def test_only_an_owner_or_admin_reads_or_changes_the_schedule(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals)
    coach = add_staff(db, gym, "coach")
    admin = add_staff(db, gym, "admin")
    assert client.get("/api/schedule", headers=as_gym(gym, coach)).status_code == 403
    assert change_slot(client, gym, slot["id"], {"start_time": "08:00"}, coach).status_code == 403
    assert client.get("/api/closed-days", headers=as_gym(gym, coach)).status_code == 403
    assert change_slot(client, gym, slot["id"], {"start_time": "08:00"}, admin).status_code == 200
    listed = ok(client.get("/api/schedule", headers=as_gym(gym, admin)))
    assert [s["start_time"] for s in listed] == ["08:00:00"]


@pg
def test_another_gym_s_schedule_is_invisible(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    slot = add_slot(client, gym, fundamentals)
    holiday = (today() + timedelta(days=1)).isoformat()
    client.put(f"/api/closed-days/{holiday}", json={"label": "Feriado"}, headers=as_gym(gym))
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    assert ok(client.get("/api/schedule", headers=as_gym(other))) == []
    assert ok(client.get("/api/closed-days", headers=as_gym(other))) == []
    assert change_slot(client, other, slot["id"], {"start_time": "08:00"}).status_code == 404
    assert client.delete(f"/api/schedule/{slot['id']}", headers=as_gym(other)).status_code == 404
    assert generate(db, other, *horizon(today()), refill=True) == 0


@pg
def test_a_coach_cannot_change_a_class_s_duration(
    client: TestClient, db: Database, gym: uuid.UUID, fundamentals: str
) -> None:
    coach = add_staff(db, gym, "coach")
    started = client.post(
        "/api/sessions",
        json={"class_type_id": fundamentals, "duration_minutes": 60, "coach_id": str(coach)},
        headers=as_gym(gym),
    )
    assert started.status_code == 201, started.text
    one = started.json()
    assert (one["duration_minutes"], one["slot_id"], one["slot_date"]) == (60, None, None)
    path = f"/api/sessions/{one['id']}"
    assert (
        client.patch(path, json={"duration_minutes": 30}, headers=as_gym(gym, coach)).status_code
        == 403
    )
    cleared = client.patch(path, json={"duration_minutes": None}, headers=as_gym(gym))
    assert cleared.json()["duration_minutes"] is None
