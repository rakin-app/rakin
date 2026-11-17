"""The `team` job: the `staff` row of someone whose last appointment has ended is
deleted, so they are off the team's list and their session reaches the gym only as
anyone's with a record there does (migrations 0005, 0042) (#311).

What a person may do comes from their appointments' dates, read at each request
(`app.permissions`), so a term that ends on its date stops granting anything from that
day's first second, whether or not this has run. This only tidies up: it takes off the
team whoever holds nothing on the run date or later, as ending their last appointment
by hand does at once (`app.api.staff`). The titular holds the account, not an
appointment, and is never taken off.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as the other jobs do.
"""

import logging
from datetime import date

import asyncpg

from app.jobs.gyms import each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "team"

# RLS holds `staff` and `staff_title` to the gym in `app.gym_id`. Whoever holds nothing
# on `$1` or later, the titular aside.
HOLDS_NOTHING = """
    NOT s.account_holder
    AND NOT EXISTS (
        SELECT FROM staff_title st
        WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
          AND (st.ends_on IS NULL OR st.ends_on > greatest(st.starts_on, $1::date))
    )
"""

# The lock `app.api.staff` takes on a person before writing their appointments or their
# row: the same name, `<gym>:<person>`, so an appointment made as the job runs is
# either seen by the check under it or made after the row is gone, and writes it again.
LOCK_PERSON = (
    "SELECT pg_advisory_xact_lock(hashtext('rakin.appointment'),"
    " hashtext(s.gym_id::text || ':' || s.person_id::text))"
    " FROM staff s WHERE s.person_id = $1"
)


async def tidy_gym(conn: asyncpg.Connection, day: date) -> int:
    """Take off the team of the gym in `app.gym_id` whoever holds nothing on `day` or
    later; how many. Each under the person's lock, and checked again under it."""
    candidates = await conn.fetch(f"SELECT s.person_id FROM staff s WHERE {HOLDS_NOTHING}", day)
    deleted = 0
    for candidate in candidates:
        await conn.execute(LOCK_PERSON, candidate["person_id"])
        result: str = await conn.execute(
            f"DELETE FROM staff s WHERE s.person_id = $2 AND {HOLDS_NOTHING}",
            day,
            candidate["person_id"],
        )
        deleted += int(result.split()[-1])
    return deleted


async def tidy(conn: asyncpg.Connection, day: date) -> bool:
    """Tidy every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn,
        day,
        tidy_gym,
        job=NAME,
        logger=logger,
        failure="taking a gym's former staff off its team failed",
    )


JOB = Job(NAME, tidy)
