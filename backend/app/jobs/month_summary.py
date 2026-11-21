"""The `month_summary` job: each gym's month, once it has closed, is kept as numbers
only, so Resumen del mes still reads it after the log purges (#506).

On the 1st, for every gym, it counts the month that just closed by #505's rules
(`app.month_figures`) and writes each `Figure` to `gym_month_figure` (migration 0082),
with `RULES_VERSION` and no person in any of it. It also writes the debt the month
closed with: what Active memberships owe on overdue periods (`v_overdue`), read on that
run, since the view only knows today. It runs before `billing` and `lapse`, so the
debt is read before the new month bills or lapses anyone.

A month is written once. A gym with any figure of the month already kept is left
alone, so a second run on the 1st writes nothing, and nor does any later day: the page
reads what was kept, under the rules it was counted under. A gym the 1st did not reach,
one suspended then, is kept on its first run of the month, without the closing debt,
which by then would be another day's. A month before the gym's first is not written.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do. There
is one run date for every gym, the runner's, in `JOBS_TIMEZONE`, as for billing.
"""

import logging
from datetime import date

import asyncpg

from app.domain.dates import add_months
from app.domain.value_summary import RULES_VERSION, Figure
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.month_figures import asyncpg_rows, count_month, overdue_now

logger = logging.getLogger(__name__)

NAME = "month_summary"

# RLS holds `gym` and `gym_month_figure` to the gym in `app.gym_id`.
FIRST_MONTH = "SELECT date_trunc('month', created_at AT TIME ZONE timezone)::date FROM gym"
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


async def keep_gym(conn: asyncpg.Connection, day: date) -> int:
    """Keep the month before `day`'s of the gym in `app.gym_id`, unless it is kept
    already or the gym is newer than it; the number of figures written."""
    month = closed_month(day)
    if month < await conn.fetchval(FIRST_MONTH) or await conn.fetchval(KEPT, month):
        return 0
    rows = asyncpg_rows(conn)
    figures: dict[Figure, int] = dict(await count_month(rows, month))
    if day.day == 1:
        figures[Figure.OVERDUE_CLP] = await overdue_now(rows)
    names = sorted(figures)
    await conn.execute(INSERT, month, names, [figures[n] for n in names], RULES_VERSION)
    return len(names)


async def keep_months(conn: asyncpg.Connection, day: date) -> bool:
    """Keep the closed month in every gym; `False` if any failed, whose work alone is
    rolled back."""
    return await each_gym(
        conn,
        day,
        keep_gym,
        job=NAME,
        logger=logger,
        failure="keeping a gym's closed month failed",
    )


JOB = Job(NAME, keep_months)
