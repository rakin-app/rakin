"""The `schedule` job: each gym's weekly schedule makes its classes ahead (#167).

Every run makes the classes due through `HORIZON_DAYS` days from the run date
(`app.domain.schedule`), taken as the gym's local date as every job does, through
`schedule_sessions()` (migration 0035): one per slot and date, none on a closed day,
and only for dates after the last one a slot made, so a class someone deleted does not
come back and a second run on the same day makes nothing.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do.
"""

import logging
from datetime import date

import asyncpg

from app.domain.schedule import horizon
from app.jobs.gyms import each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "schedule"


async def make_sessions_gym(conn: asyncpg.Connection, day: date) -> int:
    """Make the gym in `app.gym_id`'s classes due through the horizon; how many."""
    made: int = await conn.fetchval("SELECT schedule_sessions($1, $2)", *horizon(day))
    return made


async def make_sessions(conn: asyncpg.Connection, day: date) -> bool:
    """Make them in every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn,
        day,
        make_sessions_gym,
        job=NAME,
        logger=logger,
        failure="making a gym's scheduled classes failed",
    )


JOB = Job(NAME, make_sessions)
