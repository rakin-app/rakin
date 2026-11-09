"""The `freezes` job: a frozen membership is Active again on the day its freeze ends.

For every Frozen membership in every gym whose latest freeze (migration 0016) ends by
the run date, it asks the domain (`app.domain.membership.unfreeze`) to return it to
Active, and writes an `unfrozen` plan event (migration 0013) in the same transaction,
for the plan-event emails to send. The due date is not touched: the freeze moved it
past the frozen days as it started (`POST /api/memberships/{id}/freeze`).

It runs first on each day, before `billing_periods`, so a membership unfrozen today is
billed today: its next period falls due on or after the day the freeze ends, and is
written with the lead time billing gives every period. A second run on the same date
finds the memberships no longer Frozen, and the `(membership_id, kind, occurred_on)`
key on `plan_event` backs that up. A run that catches up a missed day unfreezes on
that day, the one its event records.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as billing does. There is
one run date for every gym, the runner's, in `JOBS_TIMEZONE`, as for billing.
"""

import logging
from datetime import date

import asyncpg

from app.domain import membership as memberships
from app.domain.membership import Membership, MembershipStatus, PlanKind
from app.jobs.gyms import MembershipFailed, each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "freezes"

# RLS holds every table to the gym in `app.gym_id`. Locked, so a request on the
# membership waits for the run to commit and then sees it Active.
SELECT_DUE = """
SELECT m.id, m.status, pl.kind, m.current_period_end, m.credits_remaining, m.anchor_day,
       fz.from_date, fz.to_date
FROM membership m
JOIN plan pl ON pl.id = m.plan_id
JOIN LATERAL (
    SELECT f.from_date, f.to_date FROM membership_freeze f
    WHERE f.membership_id = m.id ORDER BY f.from_date DESC LIMIT 1
) fz ON true
WHERE m.status = 'frozen' AND fz.to_date <= $1
ORDER BY m.id
FOR UPDATE OF m
"""

UNFREEZE = "UPDATE membership SET status = $2 WHERE id = $1"

INSERT_EVENT = """
INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)
VALUES (current_setting('app.gym_id')::uuid, $1, 'unfrozen', $2)
ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING
"""


def _membership(row: asyncpg.Record) -> Membership:
    return Membership(
        PlanKind(row["kind"]),
        MembershipStatus(row["status"]),
        current_period_end=row["current_period_end"],
        credits_remaining=row["credits_remaining"],
        anchor_day=row["anchor_day"],
        frozen_since=row["from_date"],
        frozen_until=row["to_date"],
    )


async def unfreeze_gym(conn: asyncpg.Connection, day: date) -> int:
    """Unfreeze what `day` ends the freeze of in the gym in `app.gym_id`; the number
    unfrozen."""
    unfrozen = 0
    for row in await conn.fetch(SELECT_DUE, day):
        try:
            after = memberships.unfreeze(_membership(row), day)
            await conn.execute(UNFREEZE, row["id"], after.status.value)
            await conn.execute(INSERT_EVENT, row["id"], day)
        except Exception as error:
            raise MembershipFailed(row["id"]) from error
        unfrozen += 1
    return unfrozen


async def unfreeze_memberships(conn: asyncpg.Connection, day: date) -> bool:
    """Unfreeze in every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn, day, unfreeze_gym, job=NAME, logger=logger, failure="unfreezing a gym failed"
    )


JOB = Job(NAME, unfreeze_memberships)
