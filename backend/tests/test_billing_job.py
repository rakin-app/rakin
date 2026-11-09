"""The `billing_periods` job against the database: periods and charges, once each.

Each test bills a gym of its own (`tests.jobgym`), with only the plans and memberships it
names: the job bills every gym, so a test reads back only its own.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import date

import asyncpg
import pytest

from app.jobs import Job, Outcome, billing, daily, run_due
from tests.conftest import require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

NOV_8 = date(2026, 11, 8)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def generate(db: Database, day: date) -> bool:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, day)

    complete: bool = run(db.owner_url, go)
    return complete


@pytest.fixture
def gym(db: Database) -> Gym:
    return Gym(db)


def test_a_monthly_period_and_its_charge_are_generated_seven_days_ahead(gym: Gym) -> None:
    member = gym.member("signup", date(2026, 11, 15), discount_pct=10)

    generate(gym.db, date(2026, 11, 7))
    assert gym.periods(member) == []

    generate(gym.db, NOV_8)
    nov_15, dec_14 = date(2026, 11, 15), date(2026, 12, 14)
    assert gym.periods(member) == [(nov_15, dec_14, 40_500, nov_15)]
    assert gym.charges(member) == [(nov_15, 40_500, "validated")]


def test_running_the_same_date_again_creates_nothing(gym: Gym) -> None:
    members = [
        gym.member("signup", date(2026, 11, 15)),
        gym.member("prepaid", date(2026, 11, 10)),
        gym.member("credits", date(2026, 11, 9)),
    ]
    generate(gym.db, NOV_8)
    before = [(gym.periods(m), gym.charges(m)) for m in members]

    generate(gym.db, NOV_8)

    assert [(gym.periods(m), gym.charges(m)) for m in members] == before
    assert all(len(periods) == 1 for periods, _ in before)


def test_monthly_catches_up_one_period_per_cycle(gym: Gym) -> None:
    member = gym.member("signup", date(2026, 11, 15))

    generate(gym.db, date(2027, 1, 8))

    assert [p[:2] for p in gym.periods(member)] == [
        (date(2026, 11, 15), date(2026, 12, 14)),
        (date(2026, 12, 15), date(2027, 1, 14)),
        (date(2027, 1, 15), date(2027, 2, 14)),
    ]
    assert len(gym.charges(member)) == 3


@pytest.mark.parametrize(
    ("plan", "end", "amount"),
    [
        ("prepaid", date(2027, 5, 14), 240_000),
        ("credits", date(2027, 1, 13), 45_000),
        ("dropin", date(2026, 11, 15), 10_000),
    ],
)
def test_prepaid_credits_and_dropin_are_one_charge(
    gym: Gym, plan: str, end: date, amount: int
) -> None:
    member = gym.member(plan, date(2026, 11, 15))

    generate(gym.db, NOV_8)
    generate(gym.db, date(2027, 4, 1))

    nov_15 = date(2026, 11, 15)
    assert gym.periods(member) == [(nov_15, end, amount, nov_15)]
    assert gym.charges(member) == [(nov_15, amount, "validated")]


@pytest.mark.parametrize(
    ("plan", "status"),
    [("trial", "trial"), ("signup", "frozen"), ("signup", "lapsed"), ("signup", "cancelled")],
)
def test_trials_and_inactive_memberships_are_not_billed(gym: Gym, plan: str, status: str) -> None:
    member = gym.member(plan, date(2026, 11, 10), status=status)

    generate(gym.db, NOV_8)

    assert gym.periods(member) == []


def test_a_full_scholarship_has_a_period_but_no_charge(gym: Gym) -> None:
    member = gym.member("signup", date(2026, 11, 15), discount_pct=100)

    generate(gym.db, NOV_8)

    assert [p[2] for p in gym.periods(member)] == [0]
    assert gym.charges(member) == []


def change_plan(gym: Gym, to: str) -> uuid.UUID:
    """A member on the signup plan since Oct 15, billed through Nov 14, moving to `to`."""
    member = gym.member("signup", date(2026, 10, 15), current_period_end=date(2026, 11, 14))
    gym.bill(member, date(2026, 10, 15), date(2026, 11, 14), 45_000)
    gym.sql(
        "UPDATE membership SET next_plan_id = $2, next_plan_from = '2026-11-15' WHERE id = $1",
        member,
        gym.plans[to],
    )
    return member


def test_a_change_to_a_first_anchor_moves_the_plan_and_the_anchor_day(gym: Gym) -> None:
    member = change_plan(gym, "first")

    generate(gym.db, date(2026, 11, 7))
    assert gym.membership(member)["next_plan_id"] == gym.plans["first"]

    generate(gym.db, NOV_8)

    nov_15 = date(2026, 11, 15)
    assert gym.periods(member)[1:] == [(nov_15, date(2026, 11, 30), 40_000, nov_15)]
    assert tuple(gym.membership(member)) == (gym.plans["first"], 1, None, None)

    generate(gym.db, date(2026, 11, 24))
    assert gym.periods(member)[-1][:2] == (date(2026, 12, 1), date(2026, 12, 31))


def test_a_change_to_prepaid_clears_the_anchor_day(gym: Gym) -> None:
    member = change_plan(gym, "prepaid")

    generate(gym.db, NOV_8)

    assert gym.periods(member)[1:2] == [
        (date(2026, 11, 15), date(2027, 5, 14), 240_000, date(2026, 11, 15))
    ]
    assert tuple(gym.membership(member)) == (gym.plans["prepaid"], None, None, None)


def test_every_gym_is_billed_in_one_run(db: Database) -> None:
    sur, norte = Gym(db), Gym(db)
    members = [g.member("signup", date(2026, 11, 12)) for g in (sur, norte)]

    generate(db, NOV_8)

    assert [len(g.periods(m)) for g, m in zip((sur, norte), members, strict=True)] == [1, 1]


def test_only_the_owner_may_list_every_gym(db: Database) -> None:
    Gym(db)
    assert run(db.owner_url, lambda c: c.fetchval("SELECT count(*) FROM jobs_gym_ids()")) > 0

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, lambda c: c.fetch("SELECT jobs_gym_ids()"))


def test_the_nightly_runner_runs_it(gym: Gym) -> None:
    member = gym.member("signup", date(2026, 11, 15))

    async def go(conn: asyncpg.Connection) -> None:
        await run_due(conn, daily.JOBS, NOV_8)

    run(gym.db.owner_url, go)

    assert len(gym.periods(member)) == 1


@pytest.fixture
def broken(db: Database) -> Iterator[tuple[Gym, uuid.UUID, uuid.UUID]]:
    """A gym with a membership billed fine and one the schedule refuses: a pending change
    to a credits plan, which only a hand edit could leave. Repaired afterwards, since
    the job bills every gym in the module's database."""
    gym = Gym(db)
    fine = gym.member("signup", date(2026, 11, 12))
    bad = gym.member("signup", date(2026, 11, 13))
    gym.sql(
        "UPDATE membership SET next_plan_id = $2, next_plan_from = '2026-11-13' WHERE id = $1",
        bad,
        gym.plans["credits"],
    )
    yield gym, fine, bad
    gym.sql("UPDATE membership SET next_plan_id = NULL, next_plan_from = NULL WHERE id = $1", bad)


def test_a_gym_that_fails_is_rolled_back_and_the_others_are_billed(
    db: Database, broken: tuple[Gym, uuid.UUID, uuid.UUID], caplog: pytest.LogCaptureFixture
) -> None:
    bad_gym, fine, bad = broken
    other = Gym(db)
    member = other.member("signup", date(2026, 11, 12))

    with caplog.at_level(logging.INFO, logger="app.jobs.billing"):
        assert generate(db, NOV_8) is False

    assert len(other.periods(member)) == 1
    # The whole failing gym is rolled back, its sound membership with it.
    assert bad_gym.periods(fine) == []
    assert bad_gym.periods(bad) == []
    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "billing a gym failed"
    assert failure.__dict__["gym_id"] == str(bad_gym.id)
    assert failure.__dict__["membership_id"] == str(bad)
    assert failure.exc_info is not None


def test_the_runner_fails_the_day_keeps_the_billed_gyms_and_retries(
    db: Database, broken: tuple[Gym, uuid.UUID, uuid.UUID]
) -> None:
    bad_gym, fine, bad = broken
    other = Gym(db)
    member = other.member("signup", date(2026, 11, 12))
    # A name of its own: `job_run` is shared with the other runner test in this module.
    job = Job(f"billing-{uuid.uuid4().hex[:8]}", billing.generate_billing_periods)

    async def go(conn: asyncpg.Connection) -> Outcome:
        return (await run_due(conn, [job], NOV_8)).outcome

    assert run(db.owner_url, go) is Outcome.FAILED
    assert len(other.periods(member)) == 1

    bad_gym.sql(
        "UPDATE membership SET next_plan_id = NULL, next_plan_from = NULL WHERE id = $1", bad
    )
    assert run(db.owner_url, go) is Outcome.SUCCEEDED
    assert len(other.periods(member)) == 1
    assert len(bad_gym.periods(fine)) == 1
