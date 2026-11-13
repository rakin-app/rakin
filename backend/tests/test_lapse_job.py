"""The `lapse` job against the database: Active → Lapsed after grace, packs on expiry.

Each test lapses a gym of its own (`tests.jobgym`): the job works on every gym, so a
test reads back only its own.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import date

import asyncpg
import pytest

from app.db_bootstrap import to_dsn
from app.jobs import daily, lapse, run_due
from tests.conftest import require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, in_gym, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

NOV_1 = date(2026, 11, 1)
# Due Nov 1 with the default 5 days' grace: Nov 2 to 6 are the grace, Nov 7 lapses.
LAST_GRACE_DAY = date(2026, 11, 6)
LAPSES_ON = date(2026, 11, 7)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def gym(db: Database) -> Gym:
    return Gym(db)


def run_lapse(db: Database, day: date) -> bool:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await lapse.lapse_memberships(conn, day)

    complete: bool = run(db.owner_url, go)
    return complete


def period(gym: Gym, member: uuid.UUID, due: date, amount: int = 45_000) -> uuid.UUID:
    (row,) = gym.sql(
        "INSERT INTO billing_period"
        " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
        " VALUES ($1, $2, $3, $3::date + 29, $4, $3) RETURNING id",
        gym.id,
        member,
        due,
        amount,
    )
    period_id: uuid.UUID = row[0]
    return period_id


def entry(
    gym: Gym,
    member: uuid.UUID,
    period_id: uuid.UUID,
    amount: int,
    *,
    kind: str = "payment",
    status: str = "validated",
) -> None:
    gym.sql(
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
        " status) VALUES ($1, $2, $3, $4, $5, $6)",
        gym.id,
        member,
        period_id,
        amount,
        kind,
        status,
    )


def status(gym: Gym, member: uuid.UUID) -> str:
    (row,) = gym.sql("SELECT status FROM membership WHERE id = $1", member)
    value: str = row[0]
    return value


def events(gym: Gym, member: uuid.UUID) -> list[tuple[str, date]]:
    rows = gym.sql(
        "SELECT kind, occurred_on FROM plan_event WHERE membership_id = $1 ORDER BY created_at",
        member,
    )
    return [tuple(r) for r in rows]


def set_grace(gym: Gym, grace: object) -> None:
    gym.sql("UPDATE gym SET settings = $1::jsonb", json.dumps({"grace_days": grace}))


def monthly_due_nov_1(gym: Gym) -> tuple[uuid.UUID, uuid.UUID]:
    member = gym.member("signup", NOV_1)
    return member, period(gym, member, NOV_1)


def test_an_unpaid_monthly_membership_lapses_after_the_grace(gym: Gym) -> None:
    member, _ = monthly_due_nov_1(gym)

    run_lapse(gym.db, LAST_GRACE_DAY)
    assert status(gym, member) == "active"
    assert events(gym, member) == []

    run_lapse(gym.db, LAPSES_ON)
    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", LAPSES_ON)]


def test_a_plan_created_after_its_due_date_has_its_grace_from_then(gym: Gym) -> None:
    """A plan backdated to Nov 1 on Nov 13 lapses on `max(due, created) + grace` (#271):
    not the night it was created, but the night after its grace from Nov 13."""
    created_on = date(2026, 11, 13)
    member = gym.member("signup", NOV_1, created_on=created_on)
    period(gym, member, NOV_1)

    run_lapse(gym.db, created_on)
    run_lapse(gym.db, date(2026, 11, 18))
    assert status(gym, member) == "active"

    run_lapse(gym.db, date(2026, 11, 19))
    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", date(2026, 11, 19))]


def test_a_paid_period_does_not_lapse(gym: Gym) -> None:
    member, period_id = monthly_due_nov_1(gym)
    entry(gym, member, period_id, 45_000)

    run_lapse(gym.db, date(2026, 12, 1))

    assert status(gym, member) == "active"
    assert events(gym, member) == []


def test_a_credit_adjustment_and_a_payment_together_settle_the_period(gym: Gym) -> None:
    member, period_id = monthly_due_nov_1(gym)
    entry(gym, member, period_id, 20_000, kind="adjustment")
    entry(gym, member, period_id, 25_000)

    run_lapse(gym.db, LAPSES_ON)

    assert status(gym, member) == "active"


@pytest.mark.parametrize(
    ("amount", "entry_status"),
    [(45_000, "pending"), (45_000, "rejected"), (44_999, "validated")],
    ids=["pending", "rejected", "short"],
)
def test_only_a_validated_payment_in_full_holds_off_the_lapse(
    gym: Gym, amount: int, entry_status: str
) -> None:
    member, period_id = monthly_due_nov_1(gym)
    entry(gym, member, period_id, amount, status=entry_status)

    run_lapse(gym.db, LAPSES_ON)

    assert status(gym, member) == "lapsed"


def test_the_oldest_unpaid_period_is_the_one_that_counts(gym: Gym) -> None:
    member = gym.member("signup", date(2026, 10, 1))
    october = period(gym, member, date(2026, 10, 1))
    period(gym, member, NOV_1)
    entry(gym, member, october, 45_000)

    run_lapse(gym.db, LAST_GRACE_DAY)
    assert status(gym, member) == "active"

    run_lapse(gym.db, LAPSES_ON)
    assert status(gym, member) == "lapsed"


def test_a_period_not_yet_due_does_not_lapse(gym: Gym) -> None:
    # Billing writes periods 7 days ahead; one due later is unpaid but not owed.
    member = gym.member("signup", date(2026, 11, 15))
    period(gym, member, date(2026, 11, 15))

    run_lapse(gym.db, date(2026, 11, 14))

    assert status(gym, member) == "active"


def test_grace_is_the_gyms(gym: Gym) -> None:
    set_grace(gym, 10)
    member, _ = monthly_due_nov_1(gym)

    run_lapse(gym.db, date(2026, 11, 11))
    assert status(gym, member) == "active"

    run_lapse(gym.db, date(2026, 11, 12))
    assert status(gym, member) == "lapsed"


def test_no_grace_lapses_the_day_after_the_due_date(gym: Gym) -> None:
    set_grace(gym, 0)
    member, _ = monthly_due_nov_1(gym)

    run_lapse(gym.db, NOV_1)
    assert status(gym, member) == "active"

    run_lapse(gym.db, date(2026, 11, 2))
    assert status(gym, member) == "lapsed"


def test_a_prepaid_block_lapses_like_a_monthly_period(gym: Gym) -> None:
    member = gym.member("prepaid", NOV_1)
    period(gym, member, NOV_1, 240_000)

    run_lapse(gym.db, LAPSES_ON)

    assert status(gym, member) == "lapsed"


def test_a_credits_pack_lapses_the_day_after_it_expires(gym: Gym) -> None:
    member = gym.member("credits", NOV_1, current_period_end=date(2026, 11, 30))
    gym.sql("UPDATE membership SET credits_remaining = 5 WHERE id = $1", member)

    run_lapse(gym.db, date(2026, 11, 30))
    assert status(gym, member) == "active"

    run_lapse(gym.db, date(2026, 12, 1))
    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", date(2026, 12, 1))]


def test_a_credits_pack_at_zero_lapses(gym: Gym) -> None:
    member = gym.member("credits", NOV_1, current_period_end=date(2026, 12, 30))
    gym.sql("UPDATE membership SET credits_remaining = 0 WHERE id = $1", member)

    run_lapse(gym.db, date(2026, 11, 20))

    assert status(gym, member) == "lapsed"


def test_a_trial_lapses_after_its_free_days(gym: Gym) -> None:
    member = gym.member("trial", NOV_1, status="trial", current_period_end=date(2026, 11, 14))
    gym.sql("UPDATE membership SET credits_remaining = 2 WHERE id = $1", member)

    run_lapse(gym.db, date(2026, 11, 14))
    assert status(gym, member) == "trial"

    run_lapse(gym.db, date(2026, 11, 15))
    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", date(2026, 11, 15))]


@pytest.mark.parametrize(
    ("plan", "member_status"),
    [("signup", "frozen"), ("signup", "lapsed"), ("signup", "cancelled"), ("dropin", "active")],
)
def test_other_memberships_are_left_alone(gym: Gym, plan: str, member_status: str) -> None:
    member = gym.member(plan, NOV_1, status=member_status)
    period(gym, member, NOV_1)

    run_lapse(gym.db, date(2026, 12, 31))

    assert status(gym, member) == member_status
    assert events(gym, member) == []


def test_running_the_same_date_again_changes_nothing(gym: Gym) -> None:
    member, _ = monthly_due_nov_1(gym)

    run_lapse(gym.db, LAPSES_ON)
    run_lapse(gym.db, LAPSES_ON)

    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", LAPSES_ON)]


def test_a_payment_in_flight_holds_off_the_lapse(gym: Gym) -> None:
    """The payment holds the membership's lock, as `app.api.ledger` takes it, and has
    written its entry but not committed. The job waits for it, then counts it: reading
    "unpaid" in the locking statement itself would use the snapshot from before."""
    member, period_id = monthly_due_nov_1(gym)

    async def go() -> None:
        paying = await asyncpg.connect(to_dsn(gym.db.owner_url))
        nightly = await asyncpg.connect(to_dsn(gym.db.owner_url))
        try:
            await paying.execute("BEGIN")
            await paying.execute("SELECT set_config('app.gym_id', $1, true)", str(gym.id))
            await paying.execute("SELECT FROM membership WHERE id = $1 FOR UPDATE", member)
            await paying.execute(
                "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id,"
                " amount_clp, kind, status) VALUES ($1, $2, $3, 45000, 'payment', 'validated')",
                gym.id,
                member,
                period_id,
            )

            async def lapse_run() -> bool:
                async with nightly.transaction():
                    return await lapse.lapse_memberships(nightly, LAPSES_ON)

            waiting = asyncio.create_task(lapse_run())
            await asyncio.sleep(0.5)
            assert not waiting.done(), "the lapse did not wait for the payment"
            await paying.execute("COMMIT")
            assert await waiting is True
        finally:
            await paying.close()
            await nightly.close()

    asyncio.run(go())

    assert status(gym, member) == "active"
    assert events(gym, member) == []


def test_a_gym_reads_only_its_own_plan_events(db: Database) -> None:
    sur, norte = Gym(db), Gym(db)
    member, _ = monthly_due_nov_1(sur)
    run_lapse(db, LAPSES_ON)

    def seen(gym: Gym) -> list[asyncpg.Record]:
        rows: list[asyncpg.Record] = run(
            db.api_url, in_gym(gym.id, "SELECT membership_id FROM plan_event")
        )
        return rows

    assert [r[0] for r in seen(sur)] == [member]
    assert seen(norte) == []


def test_a_gym_that_fails_is_rolled_back_and_the_others_are_lapsed(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    bad, good = Gym(db), Gym(db)
    unpaid, _ = monthly_due_nov_1(bad)
    other, _ = monthly_due_nov_1(good)
    set_grace(bad, "cinco")
    try:
        with caplog.at_level(logging.INFO, logger="app.jobs.lapse"):
            assert run_lapse(db, LAPSES_ON) is False
    finally:
        # The job lapses every gym in the module's database.
        set_grace(bad, 5)

    assert status(good, other) == "lapsed"
    assert status(bad, unpaid) == "active"
    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "lapsing a gym failed"
    assert failure.__dict__["gym_id"] == str(bad.id)
    assert failure.exc_info is not None


def test_the_nightly_runner_bills_then_lapses(gym: Gym) -> None:
    # Started Oct 30 and never paid: billing writes the period due Oct 30, and the
    # same day's lapse run finds it past the grace on Nov 5.
    member = gym.member("signup", date(2026, 10, 30))

    async def go(conn: asyncpg.Connection) -> None:
        await run_due(conn, daily.JOBS, date(2026, 11, 5))

    run(gym.db.owner_url, go)

    assert len(gym.periods(member)) == 1
    assert status(gym, member) == "lapsed"
    assert events(gym, member) == [("lapsed", date(2026, 11, 5))]
