"""The nightly jobs over 90 simulated days of the demo gym, its invariants checked daily.

The demo gym (`app.seed`) is loaded as of a window's first day into a database of its
own. Then each day, with the clock frozen (freezegun) at the first instant of that day
in `JOBS_TIMEZONE`:

1. members pay the periods due that they planned to pay by then, each plan drawn from
   a fixed random sequence: on a day around the due date, some past the grace, some
   never;
2. `app.jobs.daily` runs, on the date its own `today` reads off the frozen clock;
3. the invariants are checked against what it wrote;
4. it runs again at the last instant of the same day, and must find nothing owed.

The invariants:

- no duplicate periods: a membership's periods follow on from each other with no
  overlap or gap, a monthly one starts on its anchor day, each carries one charge for
  its amount, none is billed more than 7 days ahead, and every Active
  recurring membership is billed that far;
- balances equal ledger sums: `v_balance` is each membership's validated entries summed
  by kind, and its charges are its periods' amounts;
- lapses match grace rules: a membership lapses on exactly the first day the rules say
  it should, stated here independently of `app.domain`, with one `lapsed` event that
  day, and nothing else changes status;
- freezes end on time: a frozen membership is Active again on the day its freeze ends,
  with one `unfrozen` event that day, and from then on lapses as any Active one does;
- DST dates are correct: each window crosses a Santiago clock change, both runs of a
  day read that same date, and `job_run` ends with one succeeded row per job for each
  day of the window, none missing or doubled.

No API runs during the simulation, so the jobs are the only thing that changes a
membership; payments are written straight to the ledger, validated, as an admin would.
"""

import asyncio
import calendar
import itertools
import random
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from freezegun import freeze_time

from app.domain.dates import start_of_local_day
from app.jobs import billing, daily, freezes, join_requests, lapse, schedule
from app.jobs.runner import Outcome
from app.seed import load
from app.seed.build import GYM_ID, build, seed_id
from app.seed.data import GRACE_DAYS, VALIDATOR
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pytestmark = pytest.mark.postgres

DAYS = 90
# Santiago springs forward on 6 Sep 2026 (midnight is skipped) and falls back on
# 4 Apr 2027 (the last hour of 3 Apr repeats).
WINDOWS = [date(2026, 8, 1), date(2027, 2, 1)]
JOBS = [freezes.NAME, billing.NAME, lapse.NAME, join_requests.NAME, schedule.NAME]
# Periods are generated this many days before they fall due (docs/technical.md); not
# `app.domain.billing.GENERATE_AHEAD_DAYS`, which is what is being checked.
AHEAD_DAYS = 7
RECURRING = {"monthly", "prepaid"}
# Of the periods a member plans to pay, the share they never pay.
NEVER_PAID = 0.2


@dataclass(frozen=True)
class Member:
    status: str
    kind: str
    anchor_day: int | None
    current_period_end: date | None
    credits_remaining: int | None


@dataclass(frozen=True)
class Period:
    id: uuid.UUID
    membership_id: uuid.UUID
    start: date
    end: date
    amount_due: int
    due: date


@dataclass(frozen=True)
class Entry:
    membership_id: uuid.UUID
    period_id: uuid.UUID | None
    kind: str
    status: str
    amount: int


@dataclass(frozen=True)
class State:
    members: dict[uuid.UUID, Member]
    periods: list[Period]
    entries: list[Entry]
    lapsed_on: dict[uuid.UUID, list[date]]
    unfrozen_on: dict[uuid.UUID, list[date]]
    # Each membership's latest freeze's end.
    frozen_until: dict[uuid.UUID, date]
    balances: dict[uuid.UUID, int]
    grace: int

    def settled(self, period: Period) -> int:
        """What validated payments and adjustments put towards `period`."""
        return sum(
            e.amount
            for e in self.entries
            if e.period_id == period.id
            and e.status == "validated"
            and e.kind in ("payment", "adjustment")
        )


@dataclass
class Simulation:
    db: Database
    zone: ZoneInfo
    start: date
    rng_key: str
    # Each period's planned payment day, `None` for never; drawn when first seen.
    plans: dict[uuid.UUID, date | None]

    def plan(self, period: Period) -> date | None:
        if period.id not in self.plans:
            rng = random.Random(f"{self.rng_key}/{period.id}")
            if rng.random() < NEVER_PAID:
                self.plans[period.id] = None
            else:
                # From a few days early to a few past the grace (GRACE_DAYS + 1 still
                # beats the lapse: payments come in before the jobs run).
                offset = rng.randrange(-5, GRACE_DAYS + 4)
                self.plans[period.id] = period.due + timedelta(days=offset)
        return self.plans[period.id]


def fetch_state(db: Database) -> State:
    async def go(conn: asyncpg.Connection) -> State:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(GYM_ID))
            members = {
                r["id"]: Member(
                    r["status"],
                    r["kind"],
                    r["anchor_day"],
                    r["current_period_end"],
                    r["credits_remaining"],
                )
                for r in await conn.fetch(
                    "SELECT m.id, m.status, p.kind, m.anchor_day, m.current_period_end,"
                    " m.credits_remaining FROM membership m JOIN plan p ON p.id = m.plan_id"
                )
            }
            periods = [
                Period(*r)
                for r in await conn.fetch(
                    "SELECT id, membership_id, period_start, period_end, amount_due_clp,"
                    " due_date FROM billing_period ORDER BY membership_id, period_start"
                )
            ]
            entries = [
                Entry(*r)
                for r in await conn.fetch(
                    "SELECT membership_id, billing_period_id, kind, status, amount_clp"
                    " FROM ledger_entry"
                )
            ]
            events: dict[str, dict[uuid.UUID, list[date]]] = defaultdict(lambda: defaultdict(list))
            for r in await conn.fetch(
                "SELECT kind, membership_id, occurred_on FROM plan_event ORDER BY occurred_on"
            ):
                events[r[0]][r[1]].append(r[2])
            frozen_until = {
                r[0]: r[1]
                for r in await conn.fetch(
                    "SELECT DISTINCT ON (membership_id) membership_id, to_date"
                    " FROM membership_freeze ORDER BY membership_id, from_date DESC"
                )
            }
            balances = {
                r[0]: r[1]
                for r in await conn.fetch("SELECT membership_id, balance_clp FROM v_balance")
            }
            grace = await conn.fetchval("SELECT (settings ->> 'grace_days')::int FROM gym")
        return State(
            members,
            periods,
            entries,
            dict(events["lapsed"]),
            dict(events["unfrozen"]),
            frozen_until,
            balances,
            grace,
        )

    state: State = run(db.owner_url, go)
    return state


def pay(sim: Simulation, state: State, day: date) -> int:
    """Pay in full each open period of an Active membership planned for `day` or before."""
    owed = [
        (p, p.amount_due - state.settled(p))
        for p in state.periods
        if state.members[p.membership_id].status == "active"
        and p.amount_due > state.settled(p)
        and (planned := sim.plan(p)) is not None
        and planned <= day
    ]
    if not owed:
        return 0
    admin = seed_id("person", VALIDATOR)

    async def go(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(GYM_ID))
            await conn.executemany(
                "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id,"
                " amount_clp, kind, status, method, claimed_by, claimed_at, validated_by,"
                " validated_at) VALUES ($1, $2, $3, $4, 'payment', 'validated', 'cash',"
                " $5, $6, $5, $6)",
                [
                    (GYM_ID, p.membership_id, p.id, amount, admin, sim_now(sim, day))
                    for p, amount in owed
                ],
            )

    run(sim.db.owner_url, go)
    return len(owed)


def sim_now(sim: Simulation, day: date) -> datetime:
    return start_of_local_day(day, sim.zone)


def run_jobs_at(sim: Simulation, instant: datetime) -> tuple[date, list[tuple[str, date]]]:
    """Run the nightly jobs as `python -m app.jobs.daily` would at `instant`."""
    # `real_asyncio` leaves the event loop its own clock.
    with freeze_time(instant, real_asyncio=True):
        today = daily.today(sim.db.settings)
        report = asyncio.run(daily.run_once(sim.db.settings, today, daily.JOBS))
    assert report.outcome is Outcome.SUCCEEDED, report
    return today, report.ran


def check_periods(state: State, day: date) -> None:
    horizon = day + timedelta(days=AHEAD_DAYS)
    by_member: dict[uuid.UUID, list[Period]] = defaultdict(list)
    for p in state.periods:
        by_member[p.membership_id].append(p)
    charges = Counter((e.period_id, e.amount) for e in state.entries if e.kind == "charge")
    charged_periods = Counter(e.period_id for e in state.entries if e.kind == "charge")

    for member_id, periods in by_member.items():
        member = state.members[member_id]
        for before, after in itertools.pairwise(periods):
            assert after.start == before.end + timedelta(days=1), (member_id, before, after)
        for p in periods:
            assert p.start <= p.end and p.due == p.start, p
            assert p.start <= horizon, f"{p} billed past {horizon}"
            if p.amount_due > 0:
                assert charged_periods[p.id] == 1, p
                assert charges[(p.id, p.amount_due)] == 1, p
            else:
                assert charged_periods[p.id] == 0, p
            if member.kind == "monthly":
                assert member.anchor_day is not None
                last = calendar.monthrange(p.start.year, p.start.month)[1]
                assert p.start.day == min(member.anchor_day, last), (member, p)
        if member.kind not in RECURRING:
            assert len(periods) == 1, periods
        elif member.status == "active":
            assert periods[-1].end >= horizon, f"{member_id} billed only to {periods[-1].end}"
    for member_id, member in state.members.items():
        if member.status == "active" and member.kind in RECURRING:
            assert member_id in by_member, f"active {member_id} has no periods"


def check_balances(state: State) -> None:
    sums: dict[uuid.UUID, int] = defaultdict(int)
    charged: dict[uuid.UUID, int] = defaultdict(int)
    for e in state.entries:
        if e.status != "validated":
            continue
        sign = {"charge": 1, "refund": 1, "payment": -1}.get(e.kind)
        if sign is None:  # an adjustment settles a period; with none it is carried credit
            sign = -1 if e.period_id is not None else 0
        sums[e.membership_id] += sign * e.amount
        if e.kind == "charge":
            charged[e.membership_id] += e.amount
    assert state.balances == sums
    billed: dict[uuid.UUID, int] = defaultdict(int)
    for p in state.periods:
        billed[p.membership_id] += p.amount_due
    assert {m: a for m, a in billed.items() if a} == dict(charged)


def should_lapse(state: State, member_id: uuid.UUID, member: Member, day: date) -> bool:
    """The lapse rules, from the spec rather than `app.domain`: a pack or a trial on the
    day after its last day or at zero credits; a monthly or prepaid membership once a
    period due by `day` is still unpaid more than the gym's grace days after its due
    date; a drop-in never."""
    if member.status == "trial" or member.kind == "credits":
        expired = member.current_period_end is not None and day > member.current_period_end
        return member.credits_remaining == 0 or expired
    if member.kind in RECURRING:
        return any(
            p.membership_id == member_id
            and p.due <= day
            and state.settled(p) < p.amount_due
            and (day - p.due).days > state.grace
            for p in state.periods
        )
    return False


def check_lapses(before: State, after: State, day: date) -> list[uuid.UUID]:
    """The memberships that lapsed on `day`, having checked each one should have.

    A freeze ends before anything lapses, so a membership unfrozen on `day` is held to
    the rules for an Active one from that day on."""
    lapsed = []
    for member_id, was in before.members.items():
        now = after.members[member_id]
        unfrozen = was.status == "frozen" and after.frozen_until[member_id] <= day
        assert after.unfrozen_on.get(member_id, []) == [
            *before.unfrozen_on.get(member_id, []),
            *([day] if unfrozen else []),
        ], member_id
        if unfrozen:
            was = replace(was, status="active")
        if was.status in ("active", "trial"):
            due = should_lapse(after, member_id, was, day)
            assert (now.status == "lapsed") == due, (member_id, was, now, day)
            if due:
                lapsed.append(member_id)
                assert after.lapsed_on.get(member_id) == [day], after.lapsed_on.get(member_id)
                continue
        assert now.status == was.status, (member_id, was, now)
        assert after.lapsed_on.get(member_id) == before.lapsed_on.get(member_id)
    return lapsed


def check_job_runs(db: Database, window: list[date]) -> None:
    rows = run(
        db.owner_url,
        lambda c: c.fetch("SELECT job_name, run_date, status FROM job_run ORDER BY run_date"),
    )
    assert {r["status"] for r in rows} == {"succeeded"}
    for job in JOBS:
        assert [r["run_date"] for r in rows if r["job_name"] == job] == window, job


@pytest.fixture(params=WINDOWS, ids=str)
def sim(request: pytest.FixtureRequest) -> Iterator[Simulation]:
    start: date = request.param
    with throwaway_database(require_test_database_url()) as db:
        migrate(db)

        async def seed(conn: asyncpg.Connection) -> Any:
            return await load(conn, start)

        run(db.owner_url, seed)
        zone = ZoneInfo(db.settings.jobs_timezone)
        yield Simulation(db, zone, start, f"simulation/{start}", {})


def test_ninety_days_of_nightly_jobs(sim: Simulation) -> None:
    window = [sim.start + timedelta(days=n) for n in range(DAYS)]
    offsets = {sim_now(sim, d).astimezone(sim.zone).utcoffset() for d in window}
    assert len(offsets) == 2, "the window crosses no clock change"
    state = fetch_state(sim.db)
    assert state.grace == GRACE_DAYS
    lapsed: dict[str, int] = Counter()
    paid = 0
    for day in window:
        paid += pay(sim, state, day)
        before = fetch_state(sim.db)

        today, ran = run_jobs_at(sim, sim_now(sim, day))
        assert today == day
        assert ran == [(job, day) for job in JOBS]
        state = fetch_state(sim.db)
        check_periods(state, day)
        check_balances(state)
        for member_id in check_lapses(before, state, day):
            lapsed[before.members[member_id].kind] += 1

        last_instant = sim_now(sim, day + timedelta(days=1)) - timedelta(microseconds=1)
        today, ran = run_jobs_at(sim, last_instant)
        assert (today, ran) == (day, [])
        assert fetch_state(sim.db) == state

    check_job_runs(sim.db, window)
    # Not vacuous: the jobs billed, members paid, and every kind of lapse happened.
    assert len(state.periods) > len(build(sim.start).billing_periods)
    assert paid > 0
    assert {"monthly", "credits", "trial"} <= set(lapsed), lapsed
    assert state.unfrozen_on, "no freeze ended"
