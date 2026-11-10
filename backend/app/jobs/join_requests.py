"""The `join_requests` job: join link requests nobody approved or rejected in 30 days
are deleted (#154).

A request holds a person's details before the gym has agreed to keep them, so it is
not kept for long: approving or rejecting one deletes it at once (`app.api.join`), and
this job deletes the rest once they are `STALE_AFTER` old, counted in whole days of
the gym's timezone from the run date.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do.
"""

import logging
from datetime import date, timedelta

import asyncpg

from app.domain.dates import start_of_local_day
from app.jobs.gyms import each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "join_requests"

STALE_AFTER = timedelta(days=30)


async def delete_stale_gym(conn: asyncpg.Connection, day: date) -> int:
    """Delete the gym in `app.gym_id`'s requests sent before `STALE_AFTER` ago; how many."""
    # RLS holds `gym` and `join_request` to the one in `app.gym_id`.
    timezone: str = await conn.fetchval("SELECT timezone FROM gym")
    cutoff = start_of_local_day(day - STALE_AFTER, timezone)
    deleted: str = await conn.execute("DELETE FROM join_request WHERE created_at < $1", cutoff)
    return int(deleted.split()[-1])


async def delete_stale(conn: asyncpg.Connection, day: date) -> bool:
    """Delete in every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn,
        day,
        delete_stale_gym,
        job=NAME,
        logger=logger,
        failure="deleting a gym's stale join requests failed",
    )


JOB = Job(NAME, delete_stale)
