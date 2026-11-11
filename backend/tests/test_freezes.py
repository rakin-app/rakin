"""Freezes (#26): `POST /api/memberships/{id}/freeze`, the nightly `freezes` job, and
the freeze lines the member detail and the ledger book list.

A freeze starts today in the gym's timezone, so the API tests date everything from
that day. The job tests run a gym of their own (`tests.jobgym`) on fixed dates.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import gym_today
from app.domain.membership import MAX_FREEZE_DAYS
from app.jobs import daily, freezes, run_due
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_memberships import add_staff, cancel, plan, start, unbilled
from tests.test_proofs import RecordingMailer

pytestmark = pytest.mark.postgres

DAY = timedelta(days=1)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=RecordingMailer())
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"sur-{uuid.uuid4()}")


def today(db: Database, gym: uuid.UUID) -> date:
    (row,) = run(db.owner_url, in_gym(gym, "SELECT timezone FROM gym"))
    return gym_today(row["timezone"])


def member(client: TestClient, gym: uuid.UUID, key: str, started_on: date) -> dict[str, Any]:
    response = start(client, gym, plan(client, gym, key), started_on=started_on.isoformat())
    assert response.status_code == 201, response.text
    return dict(response.json())


def bill(db: Database, gym: uuid.UUID, membership: str, start: date, end: date) -> None:
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, $3, $4, 45000, $3)",
            gym,
            uuid.UUID(membership),
            start,
            end,
        ),
    )


def periods(db: Database, gym: uuid.UUID, membership: str) -> list[tuple[date, date, date]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT period_start, period_end, due_date FROM billing_period"
            " WHERE membership_id = $1 ORDER BY period_start",
            uuid.UUID(membership),
        ),
    )
    return [tuple(r) for r in rows]


def freeze(
    client: TestClient,
    gym: uuid.UUID,
    membership: str,
    to_date: date,
    reason: str = "Lesión de rodilla",
    person: uuid.UUID | None = None,
) -> Any:
    return client.post(
        f"/api/memberships/{membership}/freeze",
        json={"to_date": to_date.isoformat(), "reason": reason},
        headers=as_gym(gym, person),
    )


# --- POST /api/memberships/{id}/freeze ---------------------------------------------------


def test_a_freeze_moves_the_due_date_and_the_periods_not_yet_started(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    # One period under way, one billed ahead that starts in three days.
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    bill(db, sur, started["id"], now + 3 * DAY, now + 32 * DAY)

    response = freeze(client, sur, started["id"], now + 14 * DAY, "  Lesión de rodilla  ")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "frozen"
    assert body["freeze"]["from_date"] == now.isoformat()
    assert body["freeze"]["to_date"] == (now + 14 * DAY).isoformat()
    assert body["freeze"]["reason"] == "Lesión de rodilla"
    # Paid through the end of the period under way, 14 days later; due the day after.
    assert body["current_period_end"] == (now + 16 * DAY).isoformat()
    assert body["anchor_day"] == (now + 17 * DAY).day
    assert periods(db, sur, started["id"]) == [
        (now - 27 * DAY, now + 2 * DAY, now - 27 * DAY),
        (now + 17 * DAY, now + 46 * DAY, now + 17 * DAY),
    ]
    rows = run(
        db.owner_url,
        in_gym(
            sur,
            "SELECT kind, occurred_on FROM plan_event WHERE membership_id = $1",
            uuid.UUID(started["id"]),
        ),
    )
    assert [tuple(r) for r in rows] == [("frozen", now)]
    (row,) = run(db.owner_url, in_gym(sur, "SELECT created_by FROM membership_freeze"))
    assert row["created_by"] == seeded_owner(sur)

    # Read back, it is in its freeze; the list says so too.
    read = client.get(f"/api/memberships/{started['id']}", headers=as_gym(sur))
    assert read.json()["freeze"] == body["freeze"]


def test_a_freeze_moves_a_pending_plan_change(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    other = plan(client, sur, "first")
    changed = client.post(
        f"/api/memberships/{started['id']}/plan-change",
        json={"plan_id": other},
        headers=as_gym(sur),
    )
    assert changed.json()["next_plan"]["starts_on"] == (now + 3 * DAY).isoformat()

    body = freeze(client, sur, started["id"], now + 10 * DAY).json()

    assert body["next_plan"]["starts_on"] == (now + 13 * DAY).isoformat()


def test_a_credits_pack_expires_later(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    now = today(db, sur)
    started = member(client, sur, "credits", now - 10 * DAY)

    body = freeze(client, sur, started["id"], now + 7 * DAY).json()

    assert body["current_period_end"] == (now - 10 * DAY + 59 * DAY + 7 * DAY).isoformat()
    assert body["anchor_day"] is None


def test_only_an_active_membership_freezes(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    frozen = member(client, sur, "signup", now)
    assert freeze(client, sur, frozen["id"], now + 7 * DAY).status_code == 200
    cancelled = member(client, sur, "signup", now)
    assert cancel(client, sur, cancelled["id"]).status_code == 200
    trial = member(client, sur, "trial", now)

    for membership in (frozen, cancelled, trial):
        assert freeze(client, sur, membership["id"], now + 7 * DAY).status_code == 409


@pytest.mark.parametrize(
    ("days", "reason"), [(0, "viaje"), (-1, "viaje"), (MAX_FREEZE_DAYS + 1, "viaje"), (7, "  ")]
)
def test_a_freeze_needs_an_end_ahead_and_a_reason(
    client: TestClient, db: Database, sur: uuid.UUID, days: int, reason: str
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)

    response = freeze(client, sur, started["id"], now + days * DAY, reason)

    assert response.status_code == 422, response.text
    assert (
        client.get(f"/api/memberships/{started['id']}", headers=as_gym(sur)).json()["status"]
        == "active"
    )


def test_a_coach_cannot_freeze_and_another_gym_finds_nothing(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    coach = add_staff(db, sur, "coach")
    norte = seed_gym(db, f"norte-{uuid.uuid4()}")

    assert freeze(client, sur, started["id"], now + 7 * DAY, person=coach).status_code == 403
    assert freeze(client, norte, started["id"], now + 7 * DAY).status_code == 404


def test_freezes_are_isolated_and_only_their_end_and_reason_change(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200
    norte = seed_gym(db, f"norte-{uuid.uuid4()}")

    seen = run(db.api_url, in_gym(norte, "SELECT count(*) AS n FROM membership_freeze"))
    assert seen[0]["n"] == 0
    for sql in (
        "UPDATE membership_freeze SET from_date = from_date - 1",
        "UPDATE membership_freeze SET created_by = NULL",
        "DELETE FROM membership_freeze",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(sur, sql))
    run(db.api_url, in_gym(sur, "UPDATE membership_freeze SET reason = 'x', started = true"))


# --- ending, editing and booking a freeze (#115) -----------------------------------------


def end(
    client: TestClient, gym: uuid.UUID, membership: str, person: uuid.UUID | None = None
) -> Any:
    return client.post(f"/api/memberships/{membership}/freeze/end", headers=as_gym(gym, person))


def edit(client: TestClient, gym: uuid.UUID, membership: str, **body: Any) -> Any:
    json = {k: v.isoformat() if isinstance(v, date) else v for k, v in body.items()}
    return client.patch(f"/api/memberships/{membership}/freeze", json=json, headers=as_gym(gym))


def began(db: Database, gym: uuid.UUID, membership: str, days: int) -> None:
    """The freeze running began `days` ago: its first day and end move back by them,
    as if it had been written then."""
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership_freeze SET from_date = from_date - $2::integer,"
            " to_date = to_date - $2::integer"
            " WHERE membership_id = $1",
            uuid.UUID(membership),
            days,
        ),
    )


def events(db: Database, gym: uuid.UUID, membership: str) -> list[tuple[str, date, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT kind, occurred_on, created_by FROM plan_event WHERE membership_id = $1"
            " ORDER BY kind",
            uuid.UUID(membership),
        ),
    )
    return [tuple(r) for r in rows]


def read(client: TestClient, gym: uuid.UUID, membership: str) -> dict[str, Any]:
    response = client.get(f"/api/memberships/{membership}", headers=as_gym(gym))
    return dict(response.json())


def ledger_lines(client: TestClient, gym: uuid.UUID, membership: str) -> list[tuple[str, str]]:
    response = client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym))
    return [(f["edge"], f["day"]) for f in response.json()["freezes"]]


def test_ending_a_freeze_early_moves_the_due_date_back_by_the_days_left(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    bill(db, sur, started["id"], now + 3 * DAY, now + 32 * DAY)
    other = plan(client, sur, "first")
    client.post(
        f"/api/memberships/{started['id']}/plan-change",
        json={"plan_id": other},
        headers=as_gym(sur),
    )
    # Frozen for 14 days from 5 days ago: the due date moved by 14 then.
    assert freeze(client, sur, started["id"], now + 14 * DAY).status_code == 200
    began(db, sur, started["id"], 5)

    response = end(client, sur, started["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["freeze"] is None
    # 5 days frozen of the 14: paid through the period's end plus 5, due the day after.
    assert body["current_period_end"] == (now + 7 * DAY).isoformat()
    assert body["anchor_day"] == (now + 8 * DAY).day
    # The change waited for the period billed ahead: from the day after it, plus 5.
    assert body["next_plan"]["starts_on"] == (now + 38 * DAY).isoformat()
    assert periods(db, sur, started["id"]) == [
        (now - 27 * DAY, now + 2 * DAY, now - 27 * DAY),
        (now + 8 * DAY, now + 37 * DAY, now + 8 * DAY),
    ]
    (row,) = run(db.owner_url, in_gym(sur, "SELECT to_date FROM membership_freeze"))
    assert row["to_date"] == now
    # Who ended it, and when.
    assert events(db, sur, started["id"]) == [
        ("frozen", now, seeded_owner(sur)),
        ("unfrozen", now, seeded_owner(sur)),
    ]
    assert ledger_lines(client, sur, started["id"]) == [
        ("end", now.isoformat()),
        ("start", (now - 5 * DAY).isoformat()),
    ]


def test_a_freeze_ended_on_its_first_day_moves_no_date(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    bill(db, sur, started["id"], now + 3 * DAY, now + 32 * DAY)
    assert freeze(client, sur, started["id"], now + 14 * DAY).status_code == 200

    body = end(client, sur, started["id"]).json()

    # Billing resumes where it would have with no freeze: after the period under way.
    assert (body["status"], body["current_period_end"], body["anchor_day"]) == (
        "active",
        (now + 2 * DAY).isoformat(),
        (now + 3 * DAY).day,
    )
    assert periods(db, sur, started["id"])[1] == (now + 3 * DAY, now + 32 * DAY, now + 3 * DAY)
    # No day frozen, so no lines; and it may freeze again the same day.
    assert ledger_lines(client, sur, started["id"]) == []
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200


def test_editing_a_running_freeze_end_moves_the_due_date_by_the_difference(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    bill(db, sur, started["id"], now + 3 * DAY, now + 32 * DAY)
    assert freeze(client, sur, started["id"], now + 14 * DAY).status_code == 200

    longer = edit(client, sur, started["id"], to_date=now + 21 * DAY)
    assert longer.status_code == 200, longer.text
    assert longer.json()["current_period_end"] == (now + 23 * DAY).isoformat()
    assert longer.json()["freeze"]["to_date"] == (now + 21 * DAY).isoformat()
    shorter = edit(client, sur, started["id"], to_date=now + 4 * DAY).json()

    assert shorter["status"] == "frozen"
    assert shorter["current_period_end"] == (now + 6 * DAY).isoformat()
    assert shorter["anchor_day"] == (now + 7 * DAY).day
    assert periods(db, sur, started["id"])[1] == (now + 7 * DAY, now + 36 * DAY, now + 7 * DAY)

    reworded = edit(client, sur, started["id"], reason="  Viaje  ").json()
    assert reworded["freeze"]["reason"] == "Viaje"
    assert reworded["current_period_end"] == shorter["current_period_end"]


@pytest.mark.parametrize(("days", "body"), [(0, None), (-1, None), (MAX_FREEZE_DAYS + 1, None)])
def test_a_running_freeze_ends_after_today_and_within_a_year(
    client: TestClient, db: Database, sur: uuid.UUID, days: int, body: None
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200

    response = edit(client, sur, started["id"], to_date=now + days * DAY)

    assert response.status_code == 422, response.text
    assert read(client, sur, started["id"])["freeze"]["to_date"] == (now + 7 * DAY).isoformat()


def test_an_edit_needs_something_to_change(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200

    assert edit(client, sur, started["id"]).status_code == 422
    assert edit(client, sur, started["id"], reason=" ").status_code == 422


def test_a_freeze_booked_ahead_waits_for_its_first_day(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = unbilled(client, db, sur, "signup", now - 27 * DAY)
    bill(db, sur, started["id"], now - 27 * DAY, now + 2 * DAY)
    before = read(client, sur, started["id"])

    response = client.post(
        f"/api/memberships/{started['id']}/freeze",
        json={
            "from_date": (now + 5 * DAY).isoformat(),
            "to_date": (now + 15 * DAY).isoformat(),
            "reason": "Viaje",
        },
        headers=as_gym(sur),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["freeze"]["started"] is False
    assert body["freeze"]["from_date"] == (now + 5 * DAY).isoformat()
    assert body["current_period_end"] == before["current_period_end"]
    assert events(db, sur, started["id"]) == []
    assert ledger_lines(client, sur, started["id"]) == []
    # One at a time.
    assert freeze(client, sur, started["id"], now + 3 * DAY).status_code == 409

    edited = edit(client, sur, started["id"], to_date=now + 20 * DAY).json()
    assert edited["freeze"]["to_date"] == (now + 20 * DAY).isoformat()
    assert edited["current_period_end"] == before["current_period_end"]
    assert edit(client, sur, started["id"], to_date=now + 5 * DAY).status_code == 422

    called_off = end(client, sur, started["id"]).json()
    assert (called_off["status"], called_off["freeze"]) == ("active", None)
    assert end(client, sur, started["id"]).status_code == 409
    assert freeze(client, sur, started["id"], now + 3 * DAY).status_code == 200


@pytest.mark.parametrize("days", [-1, MAX_FREEZE_DAYS + 1])
def test_a_freeze_starts_from_today_to_a_year_ahead(
    client: TestClient, db: Database, sur: uuid.UUID, days: int
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)

    response = client.post(
        f"/api/memberships/{started['id']}/freeze",
        json={
            "from_date": (now + days * DAY).isoformat(),
            "to_date": (now + (days + 7) * DAY).isoformat(),
            "reason": "Viaje",
        },
        headers=as_gym(sur),
    )

    assert response.status_code == 422, response.text


def test_cancelling_calls_off_a_booked_freeze(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    client.post(
        f"/api/memberships/{started['id']}/freeze",
        json={
            "from_date": (now + 5 * DAY).isoformat(),
            "to_date": (now + 9 * DAY).isoformat(),
            "reason": "Viaje",
        },
        headers=as_gym(sur),
    )

    assert cancel(client, sur, started["id"]).status_code == 200

    (row,) = run(db.owner_url, in_gym(sur, "SELECT from_date, to_date FROM membership_freeze"))
    assert row["to_date"] == row["from_date"]


def test_no_freeze_to_end_or_edit_and_a_coach_cannot(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert end(client, sur, started["id"]).status_code == 409
    assert edit(client, sur, started["id"], reason="x").status_code == 409

    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200
    coach = add_staff(db, sur, "coach")
    norte = seed_gym(db, f"norte-{uuid.uuid4()}")
    assert end(client, sur, started["id"], person=coach).status_code == 403
    assert end(client, norte, started["id"]).status_code == 404


# --- freeze lines -----------------------------------------------------------------------


def past_freeze(db: Database, gym: uuid.UUID, membership: str, start: date, end: date) -> None:
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason)"
            " VALUES ($1, $2, $3, $4, 'Viaje')",
            gym,
            uuid.UUID(membership),
            start,
            end,
        ),
    )


def test_the_member_ledger_lists_each_freeze_start_and_end_so_far(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now - 60 * DAY)
    past_freeze(db, sur, started["id"], now - 40 * DAY, now - 20 * DAY)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200

    ledger = client.get(f"/api/ledger/memberships/{started['id']}", headers=as_gym(sur))

    assert ledger.status_code == 200, ledger.text
    lines = [(f["edge"], f["day"], f["reason"]) for f in ledger.json()["freezes"]]
    # The current one has not ended yet.
    assert lines == [
        ("start", now.isoformat(), "Lesión de rodilla"),
        ("end", (now - 20 * DAY).isoformat(), "Viaje"),
        ("start", (now - 40 * DAY).isoformat(), "Viaje"),
    ]


def test_the_book_lists_the_months_freeze_lines_beside_its_entries(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200

    def book(filter: str, month: date = now) -> list[dict[str, Any]]:
        response = client.get(
            f"/api/ledger/book?filter={filter}&month={month.isoformat()}", headers=as_gym(sur)
        )
        assert response.status_code == 200, response.text
        return list(response.json()["freezes"])

    [line] = book("all")
    assert (line["edge"], line["day"], line["membership_id"]) == (
        "start",
        now.isoformat(),
        started["id"],
    )
    assert line["person"]["id"] == started["person_id"]
    assert line["guardian"] is None
    assert line["plan_name"] == "Mensual"
    # Not a dependent's, and not money owed.
    assert book("kids") == book("pending") == book("overdue") == []
    # Another month's book has none.
    assert book("all", now.replace(day=1) - DAY) == []


def test_the_books_search_keeps_the_freeze_lines_of_the_members_it_finds(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    started = member(client, sur, "signup", now)
    assert freeze(client, sur, started["id"], now + 7 * DAY).status_code == 200
    name = client.get(f"/api/people/{started['person_id']}", headers=as_gym(sur)).json()["name"]

    def freeze_lines(q: str) -> list[dict[str, Any]]:
        response = client.get(
            "/api/ledger/book", params={"month": now.isoformat(), "q": q}, headers=as_gym(sur)
        )
        assert response.status_code == 200, response.text
        return list(response.json()["freezes"])

    [line] = freeze_lines(name)
    assert line["membership_id"] == started["id"]
    assert freeze_lines("nadie se llama así") == []


# --- the `freezes` job -------------------------------------------------------------------

NOV_10 = date(2026, 11, 10)
NOV_24 = date(2026, 11, 24)
NOV_30 = date(2026, 11, 30)


@pytest.fixture
def gym(db: Database) -> Gym:
    return Gym(db)


def frozen(gym: Gym, start: date, end: date, **member: Any) -> uuid.UUID:
    membership = gym.member("signup", start - 30 * DAY, status="frozen", **member)
    gym.sql(
        "INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason)"
        " VALUES ($1, $2, $3, $4, 'Viaje')",
        gym.id,
        membership,
        start,
        end,
    )
    return membership


def run_freezes(db: Database, day: date) -> bool:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await freezes.run_freezes(conn, day)

    complete: bool = run(db.owner_url, go)
    return complete


def state(gym: Gym, membership: uuid.UUID) -> tuple[str, list[tuple[str, date]]]:
    (row,) = gym.sql("SELECT status FROM membership WHERE id = $1", membership)
    events = gym.sql(
        "SELECT kind, occurred_on FROM plan_event WHERE membership_id = $1", membership
    )
    return row["status"], [tuple(e) for e in events]


def test_a_freeze_ends_on_its_to_date_with_an_unfrozen_event(db: Database, gym: Gym) -> None:
    membership = frozen(gym, NOV_10, NOV_24)

    assert run_freezes(db, NOV_24 - DAY)
    assert state(gym, membership) == ("frozen", [])

    assert run_freezes(db, NOV_24)
    assert state(gym, membership) == ("active", [("unfrozen", NOV_24)])

    # Run again, it finds nothing more to do.
    assert run_freezes(db, NOV_24)
    assert state(gym, membership) == ("active", [("unfrozen", NOV_24)])


def test_a_run_after_downtime_unfreezes_on_the_day_it_runs(db: Database, gym: Gym) -> None:
    membership = frozen(gym, NOV_10, NOV_24)

    assert run_freezes(db, NOV_24 + 3 * DAY)

    assert state(gym, membership) == ("active", [("unfrozen", NOV_24 + 3 * DAY)])


def test_only_the_latest_freeze_counts(db: Database, gym: Gym) -> None:
    membership = frozen(gym, NOV_10, NOV_24)
    gym.sql(
        "INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason)"
        " VALUES ($1, $2, $3, $4, 'Antes')",
        gym.id,
        membership,
        NOV_10 - 40 * DAY,
        NOV_10 - 20 * DAY,
    )

    assert run_freezes(db, NOV_24 - DAY)

    assert state(gym, membership) == ("frozen", [])


def test_a_membership_unfrozen_is_billed_the_same_day(db: Database, gym: Gym) -> None:
    # The freeze moved the due date to Nov 28, past its end on Nov 24.
    membership = frozen(gym, NOV_10, NOV_24, anchor_day=28, current_period_end=date(2026, 11, 27))

    async def go(conn: asyncpg.Connection) -> None:
        await run_due(conn, daily.JOBS, NOV_24)

    run(db.owner_url, go)

    assert state(gym, membership)[0] == "active"
    assert gym.periods(membership) == [
        (date(2026, 11, 28), date(2026, 12, 27), 45_000, date(2026, 11, 28))
    ]


def booked(gym: Gym, membership: uuid.UUID, start: date, end: date) -> None:
    gym.sql(
        "INSERT INTO membership_freeze"
        " (gym_id, membership_id, from_date, to_date, reason, started)"
        " VALUES ($1, $2, $3, $4, 'Viaje', false)",
        gym.id,
        membership,
        start,
        end,
    )


def test_a_booked_freeze_starts_on_its_first_day_and_moves_the_due_date(
    db: Database, gym: Gym
) -> None:
    membership = gym.member("signup", date(2026, 10, 1), current_period_end=NOV_30)
    gym.bill(membership, date(2026, 12, 1), date(2026, 12, 31), 45_000)
    booked(gym, membership, NOV_10, NOV_24)

    assert run_freezes(db, NOV_10 - DAY)
    assert state(gym, membership) == ("active", [])

    assert run_freezes(db, NOV_10)
    assert state(gym, membership) == ("frozen", [("frozen", NOV_10)])
    (row,) = gym.sql(
        "SELECT current_period_end, anchor_day FROM membership WHERE id = $1", membership
    )
    assert (row["current_period_end"], row["anchor_day"]) == (date(2026, 12, 14), 15)
    assert gym.periods(membership) == [
        (date(2026, 12, 15), date(2027, 1, 14), 45_000, date(2026, 12, 15))
    ]
    (fz,) = gym.sql("SELECT started FROM membership_freeze")
    assert fz["started"] is True

    # Run again, it starts nothing more; then the freeze ends on its day.
    assert run_freezes(db, NOV_10)
    assert run_freezes(db, NOV_24)
    assert state(gym, membership) == ("active", [("frozen", NOV_10), ("unfrozen", NOV_24)])


def test_a_booked_freeze_of_a_lapsed_membership_is_called_off(db: Database, gym: Gym) -> None:
    membership = gym.member("signup", date(2026, 10, 1), status="lapsed")
    booked(gym, membership, NOV_10, NOV_24)

    assert run_freezes(db, NOV_10)

    assert state(gym, membership) == ("lapsed", [])
    (fz,) = gym.sql("SELECT from_date, to_date, started FROM membership_freeze")
    assert tuple(fz) == (NOV_10, NOV_10, False)


def test_a_run_after_a_whole_booked_freeze_starts_and_ends_it(db: Database, gym: Gym) -> None:
    membership = gym.member("signup", date(2026, 10, 1), current_period_end=NOV_30)
    booked(gym, membership, NOV_10, NOV_24)

    assert run_freezes(db, NOV_24 + DAY)

    status, kinds = state(gym, membership)
    assert (status, sorted(kinds)) == (
        "active",
        [("frozen", NOV_24 + DAY), ("unfrozen", NOV_24 + DAY)],
    )
    (row,) = gym.sql("SELECT current_period_end FROM membership WHERE id = $1", membership)
    assert row["current_period_end"] == NOV_30 + 14 * DAY


def test_a_freeze_called_off_after_another_does_not_hold_it(db: Database, gym: Gym) -> None:
    membership = frozen(gym, NOV_10, NOV_24)
    # Booked and called off before this one: it ends on its first day.
    booked(gym, membership, NOV_24 + 5 * DAY, NOV_24 + 5 * DAY)

    assert run_freezes(db, NOV_24)

    assert state(gym, membership) == ("active", [("unfrozen", NOV_24)])
