"""The `catch_up` job: a gym resumed from a suspension gets the money jobs' days it missed
(#439).

While a gym is suspended `jobs_gym_ids()` leaves it out (0079), so every job does
nothing for it: no emails and no rows. The runner marks each day done for every gym at
once, so those days are never run again for it. Most jobs do not need them: `schedule`
makes classes from the run date on, `team` and `join_requests` only tidy up, and the
statements and overdue emails of those days are not sent late.

Three jobs move money, and skipping their days would not leave a resumed gym's ledger
as it would have been: billing alone would catch up, but bill a plan for the whole
suspension that `lapse` should have lapsed on a day in it, and a freeze booked to
start in it would start on the day the gym came back. So, as a gym is resumed,
`platform_resume_gym` sets `gym.jobs_owed_since` to when its suspension began, and
`jobs_gym_ids()` leaves the gym out until this job, the first of each day, has run
`freezes`, `billing_periods` and `lapse` for it on every day from that one (its date
in the gym's timezone, as the jobs take each gym's date) to the day before the run
date, in that order, as the runner would have; then it clears the column, and the
other jobs take the gym in from the run date on. Those three are safe to run again on
a day (`app.jobs`), so the day the suspension began, which may have run already, is
run again harmlessly.

The ledger then holds what it would have held without the suspension, but for what was
recorded meanwhile: `lapse` reads the payments there now, so one recorded during the
suspension counts on the days before it, too, and saves a membership that would have
lapsed.

A gym suspended again before this job ran keeps the earliest date. Each gym is caught
up in a savepoint of its own (`app.jobs.gyms`); one that fails keeps its date, stays
out of the other jobs and is caught up again on the next run.
"""

import logging
from datetime import date, timedelta

import asyncpg

from app.jobs import billing, freezes, lapse
from app.jobs.gyms import each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "catch_up"

# The resumed gyms the jobs still owe days.
RESUMED = "SELECT jobs_resumed_gym_ids()"

# RLS holds `gym` to the one in `app.gym_id`.
OWED_FROM = "SELECT (jobs_owed_since AT TIME ZONE timezone)::date FROM gym"
CAUGHT_UP = "UPDATE gym SET jobs_owed_since = NULL"

# The per-gym work of each job that moves money, in the order the runner runs them.
WORK = (freezes.freeze_gym, billing.bill_gym, lapse.lapse_gym)


async def catch_up_gym(conn: asyncpg.Connection, day: date) -> int:
    """Run the money jobs on each day the gym in `app.gym_id` missed before `day`; the
    number of days."""
    owed_from: date | None = await conn.fetchval(OWED_FROM)
    days = 0
    on = owed_from
    while on is not None and on < day:
        for work in WORK:
            await work(conn, on)
        on += timedelta(days=1)
        days += 1
    await conn.execute(CAUGHT_UP)
    return days


async def catch_up(conn: asyncpg.Connection, day: date) -> bool:
    """Catch up every resumed gym; `False` if any failed, whose work alone is rolled
    back."""
    return await each_gym(
        conn,
        day,
        catch_up_gym,
        job=NAME,
        logger=logger,
        failure="catching up a resumed gym failed",
        gyms=RESUMED,
    )


JOB = Job(NAME, catch_up)
