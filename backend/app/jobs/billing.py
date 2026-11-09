"""The `billing_periods` job: each gym's billing periods and charges, 7 days ahead.

For every Active membership in every gym it writes the periods that fall due by the
run date plus `GENERATE_AHEAD_DAYS` (`app.domain.billing.due_periods`), each with a
validated `charge` ledger entry for its amount. A period discounted to nothing has no
charge: a ledger entry's amount is positive. A pending plan change that a new period
reaches is applied with it: `plan_id` takes `next_plan_id`, and `anchor_day` is
recomputed from the day it starts (migration 0009).

It picks up from the latest period each membership has (or the day it was paid
through, if later), so a second run on the same date finds nothing owed. The
`(membership_id, period_start)` key backs that up: a period already there is skipped,
and its charge with it.

On its first run a credits pack or drop-in with no period yet is charged once, with a
period starting on the day it started, even if that day is past; a monthly or prepaid
membership catches up from its paid-through date. That is accepted because no
production data predates this job.

Each gym is billed in a savepoint of its own. A gym that fails (a row the schedule
refuses, say) is rolled back and logged with its id and the membership's, which
Sentry receives; the other gyms are still billed, and the day is failed so the runner
reports it and the next run retries it, finding nothing new owed for the gyms that
were billed.

There is one run date for every gym: the runner's, in `JOBS_TIMEZONE`. Only each
membership's start date is read in its gym's timezone. A gym in another timezone
would want its own local date; v1 has none.
"""

import logging
from datetime import date

import asyncpg

from app.domain import billing
from app.domain.billing import Billable, Plan
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.jobs.gyms import MembershipFailed, each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "billing_periods"

# RLS holds every table to the gym in `app.gym_id`. Locked so a plan change waits for
# the periods it would be billed against (`POST /api/memberships/{id}/plan-change`).
SELECT_BILLABLE = """
SELECT m.id, m.status, (m.started_at AT TIME ZONE g.timezone)::date AS started_on,
       m.current_period_end, m.anchor_day, m.discount_pct, m.next_plan_from,
       (SELECT max(b.period_end) FROM billing_period b WHERE b.membership_id = m.id)
           AS billed_through,
       pl.kind, pl.anchor, pl.credits, pl.credit_expiry_days, pl.price_clp,
       pl.period_months,
       np.kind AS next_kind, np.anchor AS next_anchor, np.credits AS next_credits,
       np.credit_expiry_days AS next_credit_expiry_days, np.price_clp AS next_price_clp,
       np.period_months AS next_period_months
FROM membership m
JOIN gym g ON g.id = m.gym_id
JOIN plan pl ON pl.id = m.plan_id
LEFT JOIN plan np ON np.id = m.next_plan_id
WHERE m.status = 'active'
ORDER BY m.id
FOR UPDATE OF m
"""

INSERT_PERIOD = """
INSERT INTO billing_period
    (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)
VALUES (current_setting('app.gym_id')::uuid, $1, $2, $3, $4, $5)
ON CONFLICT (membership_id, period_start) DO NOTHING
RETURNING id
"""

# Validated as it is written: a charge is what the gym bills, not a claim to check.
INSERT_CHARGE = """
INSERT INTO ledger_entry
    (gym_id, membership_id, billing_period_id, amount_clp, kind, status, validated_at)
VALUES (current_setting('app.gym_id')::uuid, $1, $2, $3, 'charge', 'validated', now())
"""

APPLY_PLAN_CHANGE = """
UPDATE membership
SET plan_id = next_plan_id, anchor_day = $2, next_plan_id = NULL, next_plan_from = NULL
WHERE id = $1
"""


def _plan(row: asyncpg.Record, prefix: str = "") -> Plan | None:
    kind = row[f"{prefix}kind"]
    if kind is None:
        return None
    terms = PlanTerms(
        PlanKind(kind),
        row[f"{prefix}anchor"],
        row[f"{prefix}credits"],
        row[f"{prefix}credit_expiry_days"],
    )
    return Plan(terms, row[f"{prefix}price_clp"], row[f"{prefix}period_months"])


def _billable(row: asyncpg.Record) -> Billable:
    plan = _plan(row)
    assert plan is not None  # an inner join
    return Billable(
        plan=plan,
        status=MembershipStatus(row["status"]),
        started_on=row["started_on"],
        current_period_end=row["current_period_end"],
        billed_through=row["billed_through"],
        anchor_day=row["anchor_day"],
        discount_pct=row["discount_pct"],
        next_plan=_plan(row, "next_"),
        next_plan_from=row["next_plan_from"],
    )


async def bill_gym(conn: asyncpg.Connection, day: date) -> int:
    """Generate the periods due by `day` plus the lead time in the gym in `app.gym_id`;
    the number of periods written."""
    written = 0
    for row in await conn.fetch(SELECT_BILLABLE):
        try:
            written += await _bill_membership(conn, row, day)
        except Exception as error:
            raise MembershipFailed(row["id"]) from error
    return written


async def _bill_membership(conn: asyncpg.Connection, row: asyncpg.Record, day: date) -> int:
    written = 0
    owed = billing.due_periods(_billable(row), day)
    for period in owed.periods:
        period_id = await conn.fetchval(
            INSERT_PERIOD,
            row["id"],
            period.period_start,
            period.period_end,
            period.amount_due_clp,
            period.due_date,
        )
        if period_id is None:
            continue
        written += 1
        if period.amount_due_clp > 0:
            await conn.execute(INSERT_CHARGE, row["id"], period_id, period.amount_due_clp)
    if owed.plan_changed:
        await conn.execute(APPLY_PLAN_CHANGE, row["id"], owed.anchor_day)
    return written


async def generate_billing_periods(conn: asyncpg.Connection, day: date) -> bool:
    """Bill every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn, day, bill_gym, job=NAME, logger=logger, failure="billing a gym failed"
    )


JOB = Job(NAME, generate_billing_periods)
