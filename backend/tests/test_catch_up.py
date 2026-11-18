"""A gym suspended from the panel gets nothing from the nightly jobs, and once resumed
its ledger is what it would have been had it never been suspended (#439,
`app.jobs.catch_up`).

Two gyms alike, one suspended for five weeks, run every night through three months.
In the suspension one plan lapses for want of payment and another's booked freeze
starts and ends: without the catch-up, the resumed gym would bill the lapsed plan for
the whole suspension and start the freeze on the day it came back.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest

from app.jobs import catch_up, daily
from app.jobs.runner import Outcome, run_due
from tests.conftest import require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

DAY = timedelta(days=1)
START = date(2026, 9, 1)
SUSPENDED = date(2026, 10, 2)
RESUMED = date(2026, 11, 10)
END = date(2026, 12, 1)


@pytest.fixture
def db() -> Iterator[Database]:
    # Its own: the runner's days are the database's, for every gym in it.
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def run_day(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> Any:
        return await run_due(conn, daily.JOBS, day)

    report = run(db.owner_url, go)
    assert report.outcome is Outcome.SUCCEEDED, report


def suspend(db: Database, gym: Gym, on: date) -> None:
    """As `platform_suspend_gym` does, at noon of `on` in the gym's timezone."""
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym SET suspended_at = ($2::date + time '12:00') AT TIME ZONE timezone,"
            " suspended_reason = 'Impago' WHERE id = $1",
            gym.id,
            on,
        ),
    )


def resume(db: Database, gym: Gym) -> None:
    """As `platform_resume_gym` does."""
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym SET jobs_owed_since = coalesce(jobs_owed_since, suspended_at),"
            " suspended_at = NULL, suspended_reason = NULL WHERE id = $1",
            gym.id,
        ),
    )


def pay_first_period(gym: Gym, membership: uuid.UUID) -> None:
    [(period_id, amount)] = gym.sql(
        "SELECT id, amount_due_clp FROM billing_period WHERE membership_id = $1",
        membership,
    )
    gym.sql(
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
        " status) VALUES ($1, $2, $3, $4, 'payment', 'validated')",
        gym.id,
        membership,
        period_id,
        amount,
    )


def book_freeze(gym: Gym, membership: uuid.UUID, start: date, end: date) -> None:
    gym.sql(
        "INSERT INTO membership_freeze"
        " (gym_id, membership_id, from_date, to_date, reason, started)"
        " VALUES ($1, $2, $3, $4, 'Viaje', false)",
        gym.id,
        membership,
        start,
        end,
    )


def ledger(gym: Gym, memberships: list[uuid.UUID]) -> list[Any]:
    """Each membership's status, periods, charges and plan events: what the jobs wrote."""
    return [
        (
            gym.sql("SELECT status FROM membership WHERE id = $1", m)[0][0],
            gym.periods(m),
            gym.charges(m),
            [
                tuple(r)
                for r in gym.sql(
                    "SELECT kind, occurred_on FROM plan_event WHERE membership_id = $1"
                    " ORDER BY occurred_on, kind",
                    m,
                )
            ],
        )
        for m in memberships
    ]


def rows(gym: Gym) -> int:
    return int(
        gym.sql(
            "SELECT (SELECT count(*) FROM billing_period) + (SELECT count(*) FROM ledger_entry)"
            " + (SELECT count(*) FROM plan_event) + (SELECT count(*) FROM session)"
        )[0][0]
    )


def test_a_resumed_gyms_ledger_is_as_if_it_had_never_been_suspended(db: Database) -> None:
    gyms = [Gym(db), Gym(db)]
    kept, suspended = gyms
    members: dict[uuid.UUID, list[uuid.UUID]] = {}
    for gym in gyms:
        # Pays its first month only, so it lapses in October, in the suspension.
        lapsing = gym.member("signup", START)
        # Owes nothing, and is frozen from Oct 20 to Nov 5, in the suspension too.
        freezing = gym.member("signup", date(2026, 9, 15), discount_pct=100)
        book_freeze(gym, freezing, date(2026, 10, 20), date(2026, 11, 5))
        members[gym.id] = [lapsing, freezing]

    before = 0
    day = START
    while day <= END:
        run_day(db, day)
        if day == START:
            for gym in gyms:
                pay_first_period(gym, members[gym.id][0])
        if day == SUSPENDED:
            suspend(db, suspended, day)
            before = rows(suspended)
        if day == RESUMED:
            # A night in the suspension did nothing for it: no rows.
            assert rows(suspended) == before
            assert suspended.sql("SELECT jobs_owed_since FROM gym")[0][0] is None
            resume(db, suspended)
        day += DAY

    expected = ledger(kept, members[kept.id])
    assert ledger(suspended, members[suspended.id]) == expected
    # What it would have lost or gained without the catch-up.
    (lapsed_status, _, charges, events), (_, _, _, freeze_events) = expected
    assert lapsed_status == "lapsed"
    assert [kind for kind, _ in events] == ["lapsed"]
    assert SUSPENDED < events[0][1] < RESUMED
    assert [start for start, _, _ in charges] == [START, date(2026, 10, 1)]
    assert freeze_events == [("frozen", date(2026, 10, 20)), ("unfrozen", date(2026, 11, 5))]
    # Caught up once: the gym is the other jobs' again.
    assert suspended.sql("SELECT jobs_owed_since FROM gym")[0][0] is None


def test_a_suspended_gym_and_one_not_caught_up_are_left_out_of_the_jobs(db: Database) -> None:
    active, suspended, resumed = Gym(db), Gym(db), Gym(db)
    suspend(db, suspended, START)
    suspend(db, resumed, START)
    resume(db, resumed)

    def ids(sql: str) -> set[uuid.UUID]:
        return {r[0] for r in run(db.owner_url, lambda c: c.fetch(sql))}

    assert ids("SELECT jobs_gym_ids()") >= {active.id}
    assert not ids("SELECT jobs_gym_ids()") & {suspended.id, resumed.id}
    assert ids(catch_up.RESUMED) == {resumed.id}


def test_a_gym_resumed_the_day_it_was_suspended_replays_nothing(db: Database) -> None:
    gym = Gym(db)
    membership = gym.member("signup", START)
    run_day(db, START)
    periods = gym.periods(membership)
    suspend(db, gym, START + DAY)
    resume(db, gym)
    run_day(db, START + DAY)
    assert gym.sql("SELECT jobs_owed_since FROM gym")[0][0] is None
    # Billed as any day: nothing new owed the next day.
    assert gym.periods(membership) == periods
