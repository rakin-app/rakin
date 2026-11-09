"""The `billing_periods` job against the database: periods and charges, once each.

Each test bills a gym of its own, made here with only the plans and memberships it
names: the job bills every gym, so a test reads back only its own.
"""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from app.jobs import Job, Outcome, billing, daily, run_due
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

NOV_8 = date(2026, 11, 8)

PLANS: dict[str, dict[str, Any]] = {
    "signup": {"kind": "monthly", "price_clp": 45_000, "anchor": "signup"},
    "first": {"kind": "monthly", "price_clp": 40_000, "anchor": "first"},
    "prepaid": {"kind": "prepaid", "price_clp": 240_000, "period_months": 6},
    "credits": {"kind": "credits", "price_clp": 45_000, "credits": 12, "credit_expiry_days": 60},
    "dropin": {"kind": "dropin", "price_clp": 10_000},
    "trial": {"kind": "trial", "price_clp": 0, "credits": 2, "credit_expiry_days": 14},
}


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


class Gym:
    """A gym with one member and every plan in `PLANS`, written as the owner."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.id = uuid.uuid4()
        self.person = uuid.uuid4()
        self.plans = {key: uuid.uuid4() for key in PLANS}

        async def query(conn: asyncpg.Connection) -> None:
            async with conn.transaction():
                await self._in_gym(conn)
                await conn.execute(
                    "INSERT INTO gym (id, name, slug) VALUES ($1, $2, $2)", self.id, str(self.id)
                )
                await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'Ana')", self.person)
                await conn.execute(
                    "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Ana')",
                    self.id,
                    self.person,
                )
                for key, plan in PLANS.items():
                    columns = ", ".join(plan)
                    values = ", ".join(f"${i}" for i in range(4, len(plan) + 4))
                    await conn.execute(
                        f"INSERT INTO plan (id, gym_id, name, {columns})"
                        f" VALUES ($1, $2, $3, {values})",
                        self.plans[key],
                        self.id,
                        key,
                        *plan.values(),
                    )

        run(db.owner_url, query)

    async def _in_gym(self, conn: asyncpg.Connection) -> None:
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(self.id))

    def member(
        self,
        plan: str,
        started_on: date,
        *,
        status: str = "active",
        anchor_day: int | None = None,
        current_period_end: date | None = None,
        discount_pct: int = 0,
    ) -> uuid.UUID:
        membership_id = uuid.uuid4()
        if PLANS[plan]["kind"] == "monthly" and anchor_day is None:
            anchor_day = 1 if PLANS[plan]["anchor"] == "first" else started_on.day
        extra = (
            {"cancel_reason": "se mudó", "cancelled_at": datetime.now(UTC)}
            if status == "cancelled"
            else {}
        )
        columns = ", ".join(extra)
        values = ", ".join(f"${i}" for i in range(10, len(extra) + 10))
        self.sql(
            "INSERT INTO membership (id, gym_id, person_id, plan_id, status, anchor_day,"
            " started_at, current_period_end, discount_pct"
            + (f", {columns}) " if extra else ") ")
            + "VALUES ($1, $2, $3, $4, $5, $6,"
            " ($7::date::timestamp AT TIME ZONE 'America/Santiago'), $8, $9"
            + (f", {values})" if extra else ")"),
            membership_id,
            self.id,
            self.person,
            self.plans[plan],
            status,
            anchor_day,
            started_on,
            current_period_end,
            discount_pct,
            *extra.values(),
        )
        return membership_id

    def sql(self, sql: str, *args: object) -> list[asyncpg.Record]:
        rows: list[asyncpg.Record] = run(self.db.owner_url, in_gym(self.id, sql, *args))
        return rows

    def periods(self, membership_id: uuid.UUID) -> list[tuple[date, date, int, date]]:
        rows = self.sql(
            "SELECT period_start, period_end, amount_due_clp, due_date FROM billing_period"
            " WHERE membership_id = $1 ORDER BY period_start",
            membership_id,
        )
        return [tuple(r) for r in rows]

    def charges(self, membership_id: uuid.UUID) -> list[tuple[date, int, str]]:
        rows = self.sql(
            "SELECT b.period_start, e.amount_clp, e.status FROM ledger_entry e"
            " JOIN billing_period b ON b.id = e.billing_period_id"
            " WHERE e.membership_id = $1 AND e.kind = 'charge' ORDER BY b.period_start",
            membership_id,
        )
        return [tuple(r) for r in rows]

    def membership(self, membership_id: uuid.UUID) -> asyncpg.Record:
        (row,) = self.sql(
            "SELECT plan_id, anchor_day, next_plan_id, next_plan_from FROM membership"
            " WHERE id = $1",
            membership_id,
        )
        return row

    def bill(self, membership_id: uuid.UUID, start: date, end: date, amount: int) -> None:
        self.sql(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, $3, $4, $5, $3)",
            self.id,
            membership_id,
            start,
            end,
            amount,
        )


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
