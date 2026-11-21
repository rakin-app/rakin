"""The `month_summary` job: each gym's month, once it has closed, is kept as numbers
only, so Resumen del mes still reads it after the log purges (#506).

On the 1st, for every gym, it counts the month that just closed by #505's rules
(`app.month_figures`) and writes each `Figure` to `gym_month_figure` (migration 0082),
with `RULES_VERSION` and no person in any of it. It also writes the debt the month
closed with: what Active memberships owe on overdue periods (`v_overdue`), read on that
run, since the view only knows today. It runs before `billing` and `lapse`, so the
debt is read before the new month bills or lapses anyone.

The debt is written only when the run's day is the gym's real today, the 1st on its
own clock. The runner replays owed days and retries failed ones (`app.jobs.runner`), so
the run for the 1st can happen on the 3rd; that run keeps the figures, which are
counted from rows, but not the debt, which would be the 3rd's and not the month's
close.

A month is written once. A gym with any figure of the month already kept is left
alone, so a second run on the 1st writes nothing, and nor does any later day: the page
reads what was kept, under the rules it was counted under. A gym the 1st did not reach,
one suspended then, is kept on its first run of the month, without the closing debt,
which by then would be another day's. A month before the gym's first is not written.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do. The
run date is the runner's, in `JOBS_TIMEZONE`, as for billing, but whether a gym's month
has ended is asked of the gym's own clock (`gym.timezone`): a gym still in the closed
month, one west of the runner, is left for the next day's run, which keeps it then.
That run's day is no longer the gym's 1st, so such a gym keeps no closing debt that
month; for Chile's gyms, on the runner's timezone, the two clocks agree.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

import asyncpg

from app.domain.dates import add_months, local_date
from app.domain.value_summary import RULES_VERSION, Figure
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.month_figures import asyncpg_rows, count_month, overdue_now

logger = logging.getLogger(__name__)

NAME = "month_summary"

# RLS holds `gym` and `gym_month_figure` to the gym in `app.gym_id`.
GYM = """
SELECT date_trunc('month', created_at AT TIME ZONE timezone)::date AS first_month, timezone
FROM gym
"""
KEPT = "SELECT EXISTS (SELECT FROM gym_month_figure WHERE month = $1)"
INSERT = """
INSERT INTO gym_month_figure (gym_id, month, figure, value, rules_version)
SELECT current_setting('app.gym_id')::uuid, $1, f.figure, f.value, $4
FROM unnest($2::text[], $3::bigint[]) AS f (figure, value)
ON CONFLICT (gym_id, month, figure) DO NOTHING
"""


def closed_month(day: date) -> date:
    """The first day of the month before `day`'s."""
    return add_months(day.replace(day=1), -1)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def keep_gym(conn: asyncpg.Connection, day: date, now: datetime) -> int:
    """Keep the month before `day`'s of the gym in `app.gym_id`, unless it is kept
    already, the gym is newer than it, or the month has not ended on the gym's clock at
    `now`; the number of figures written."""
    month = closed_month(day)
    gym = await conn.fetchrow(GYM)
    gym_today = local_date(now, gym["timezone"])
    if gym_today < add_months(month, 1) or month < gym["first_month"]:
        return 0
    if await conn.fetchval(KEPT, month):
        return 0
    rows = asyncpg_rows(conn)
    figures: dict[Figure, int] = dict(await count_month(rows, month))
    if day.day == 1 and day == gym_today:
        figures[Figure.OVERDUE_CLP] = await overdue_now(rows)
    names = sorted(figures)
    await conn.execute(INSERT, month, names, [figures[n] for n in names], RULES_VERSION)
    return len(names)


async def keep_months(
    conn: asyncpg.Connection, day: date, clock: Callable[[], datetime] = utc_now
) -> bool:
    """Keep the closed month in every gym, each by its own clock, read from `clock` as
    the job reaches it; `False` if any failed, whose work alone is rolled back."""

    async def work(gym_conn: asyncpg.Connection, on: date) -> int:
        return await keep_gym(gym_conn, on, clock())

    return await each_gym(
        conn,
        day,
        work,
        job=NAME,
        logger=logger,
        failure="keeping a gym's closed month failed",
    )


JOB = Job(NAME, keep_months)
