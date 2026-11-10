"""The `freezes` job: a freeze booked ahead starts on its first day, and a frozen
membership is Active again on the day its freeze ends.

First it starts every freeze booked to start by the run date (#115, migration 0024),
as `POST /api/memberships/{id}/freeze` starts one from today: the domain freezes the
membership (`app.domain.membership.freeze`), its due date, the billing periods from the
freeze's first day on and a pending plan change move past the frozen days, and a
`frozen` plan event is written. A membership no longer Active by then, lapsed or
cancelled, has the freeze called off instead: it ends on its first day, no day frozen.

Then, for every Frozen membership in every gym whose latest freeze (migration 0017)
ends by the run date, it asks the domain (`app.domain.membership.unfreeze`) to return
it to Active, and writes an `unfrozen` plan event (migration 0013) in the same transaction,
for the plan-event emails to send. The due date is not touched: the freeze moved it
past the frozen days as it started (`POST /api/memberships/{id}/freeze`).

It runs first on each day, before `billing_periods`, so a membership unfrozen today is
billed today: its next period falls due on or after the day the freeze ends, and is
written with the lead time billing gives every period. A second run on the same date
finds the freezes started and the memberships no longer Frozen, and the
`(membership_id, kind, occurred_on)` key on `plan_event` backs that up. A run that
catches up a missed day starts and unfreezes on that day, the one its events record.

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
# membership waits for the run to commit and then sees it frozen.
SELECT_TO_START = """
SELECT m.id, m.status, pl.kind, m.current_period_end, m.credits_remaining, m.anchor_day,
       f.id AS freeze_id, f.from_date, f.to_date,
       (SELECT max(bp.period_end) FROM billing_period bp
        WHERE bp.membership_id = m.id AND bp.period_start < f.from_date) AS billed_before
FROM membership_freeze f
JOIN membership m ON m.id = f.membership_id
JOIN plan pl ON pl.id = m.plan_id
WHERE NOT f.started AND f.to_date > f.from_date AND f.from_date <= $1
ORDER BY m.id
FOR UPDATE OF m, f
"""

SHIFT_PERIODS = "SELECT shift_billing_periods($1, $2, $3)"

FREEZE = """
UPDATE membership SET status = $2, current_period_end = $3, anchor_day = $4,
    next_plan_from = next_plan_from + $5::integer
WHERE id = $1
"""

START = "UPDATE membership_freeze SET started = true WHERE id = $1"

CALL_OFF = "UPDATE membership_freeze SET to_date = from_date WHERE id = $1"

INSERT_FROZEN = """
INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)
VALUES (current_setting('app.gym_id')::uuid, $1, 'frozen', $2)
ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING
"""

# Locked, so a request on the membership waits for the run to commit and then sees it
# Active. Freezes of no days, ended or called off on their first day, do not count.
SELECT_DUE = """
SELECT m.id, m.status, pl.kind, m.current_period_end, m.credits_remaining, m.anchor_day,
       fz.from_date, fz.to_date
FROM membership m
JOIN plan pl ON pl.id = m.plan_id
JOIN LATERAL (
    SELECT f.from_date, f.to_date FROM membership_freeze f
    WHERE f.membership_id = m.id AND f.to_date > f.from_date
    ORDER BY f.from_date DESC LIMIT 1
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


def _membership(row: asyncpg.Record, *, frozen: bool = True) -> Membership:
    return Membership(
        PlanKind(row["kind"]),
        MembershipStatus(row["status"]),
        current_period_end=row["current_period_end"],
        credits_remaining=row["credits_remaining"],
        anchor_day=row["anchor_day"],
        frozen_since=row["from_date"] if frozen else None,
        frozen_until=row["to_date"] if frozen else None,
    )


async def start_gym(conn: asyncpg.Connection, day: date) -> int:
    """Start the freezes booked to start by `day` in the gym in `app.gym_id`, calling
    off those of memberships no longer Active; the number started."""
    started = 0
    for row in await conn.fetch(SELECT_TO_START, day):
        try:
            current = _membership(row, frozen=False)
            if current.status is not MembershipStatus.ACTIVE:
                await conn.execute(CALL_OFF, row["freeze_id"])
                logger.info(
                    "freeze called off: the membership is %s",
                    current.status.value,
                    extra={"job": NAME, "membership_id": str(row["id"])},
                )
                continue
            frozen = memberships.freeze(
                current, row["from_date"], row["to_date"], billed_through=row["billed_before"]
            )
            days = (row["to_date"] - row["from_date"]).days
            await conn.execute(SHIFT_PERIODS, row["id"], row["from_date"], days)
            await conn.execute(
                FREEZE,
                row["id"],
                frozen.status.value,
                frozen.current_period_end,
                frozen.anchor_day,
                days,
            )
            await conn.execute(START, row["freeze_id"])
            await conn.execute(INSERT_FROZEN, row["id"], day)
        except Exception as error:
            raise MembershipFailed(row["id"]) from error
        started += 1
    return started


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


async def freeze_gym(conn: asyncpg.Connection, day: date) -> None:
    """Start, then unfreeze, in the gym in `app.gym_id`: a freeze booked on days the
    job did not run, and over by `day`, starts and ends on the same run."""
    await start_gym(conn, day)
    await unfreeze_gym(conn, day)


async def run_freezes(conn: asyncpg.Connection, day: date) -> bool:
    """Start and unfreeze in every gym; `False` if any failed, whose work alone is
    rolled back."""
    return await each_gym(
        conn, day, freeze_gym, job=NAME, logger=logger, failure="freezing a gym failed"
    )


JOB = Job(NAME, run_freezes)
