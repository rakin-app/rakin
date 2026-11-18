"""Running a job's work once per gym, each gym in a savepoint of its own (see `app.jobs`).

A gym that fails is rolled back and logged with its id, and with the membership's when
the work raised `MembershipFailed`, which Sentry receives; the other gyms' work still
commits, and the job returns `False` so the runner fails the day and retries it.

The gyms are `jobs_gym_ids()`'s (0011, 0079): a suspended gym is left out, and so is
a resumed one until `app.jobs.catch_up` has caught up the days it missed, which works
on `jobs_resumed_gym_ids()`'s instead.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date

import asyncpg

# The gyms the jobs work on: neither suspended nor owed a catch-up.
GYMS = "SELECT jobs_gym_ids()"


class MembershipFailed(Exception):
    """The work on one membership broke; the cause is chained."""

    def __init__(self, membership_id: object) -> None:
        super().__init__(f"membership {membership_id} failed")
        self.membership_id = membership_id


async def each_gym(
    conn: asyncpg.Connection,
    day: date,
    work: Callable[[asyncpg.Connection, date], Awaitable[object]],
    *,
    job: str,
    logger: logging.Logger,
    failure: str,
    gyms: str = GYMS,
) -> bool:
    """Run `work` for every gym `gyms` lists, with `app.gym_id` set to it; `False` if
    any failed, whose work alone is rolled back and logged as `failure` on `logger`."""
    complete = True
    for gym_id in [r[0] for r in await conn.fetch(gyms)]:
        try:
            async with conn.transaction():  # a savepoint in the runner's transaction
                # Transaction-local, so it goes with the savepoint.
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
                await work(conn, day)
        except Exception as error:
            complete = False
            failed = error.membership_id if isinstance(error, MembershipFailed) else None
            logger.exception(
                failure,
                extra={
                    "job": job,
                    "run_date": day.isoformat(),
                    "gym_id": str(gym_id),
                    "membership_id": None if failed is None else str(failed),
                },
            )
    return complete
