"""The `lapse` job: memberships past their grace, or out of their pack, become Lapsed.

For every Active or Trial membership in every gym it asks the domain
(`app.domain.membership.is_due_to_lapse`) whether the run date lapses it, and if so
sets `status = 'lapsed'` and writes a `lapsed` plan event (migration 0013) in the same
transaction, for the plan-event emails to send.

- A monthly or prepaid membership lapses once its oldest billing period still unpaid
  is past its due date plus the gym's grace days (`gym.settings["grace_days"]`, 5 by
  default). Unpaid means its validated payments and credit adjustments do not cover
  its amount due, as `app.domain.billing` settles it. The ledger is what says whether
  the member paid, so the job reads it, not `current_period_end`: the membership is
  treated as paid through the day before that period falls due. A membership created
  with a start already past due (a backdated "Asignar plan") is not due before the day
  it was created, in the gym's timezone: the owner has the whole grace from then to
  record the payment, so it lapses on `max(due_date, created_on) + grace` (#271).
- A credits pack or a trial lapses with no grace, the day after its last day
  (`current_period_end`) or at zero credits left.
- A drop-in is a single attendance and never lapses; a Frozen membership waits for
  its freeze to end (`app.jobs.freezes`), and a Lapsed or Cancelled one has nowhere
  to lapse to.

A payment recorded while the job runs is never lost to it. Both lock the membership
row before they decide: the job locks every membership it may lapse and only then reads
what is unpaid, so a payment that committed first is counted, and one that comes later
waits for the run to commit and is recorded against a membership already lapsed, as a
payment after the lapse would be.

It runs after `billing_periods` on each day, so the periods it reads are there. A
second run on the same date finds the lapsed memberships no longer Active, and the
`(membership_id, kind, occurred_on)` key on `plan_event` backs that up.

Each gym works in a savepoint of its own (`app.jobs.gyms`), as billing does. There is
one run date for every gym, the runner's, in `JOBS_TIMEZONE`, as for billing.
"""

import json
import logging
from datetime import date, timedelta

import asyncpg

from app.domain import membership as memberships
from app.domain.billing import SETTLING_KINDS, settled_amount
from app.domain.ledger import EntryStatus
from app.domain.membership import RECURRING, Membership, MembershipStatus, PlanKind
from app.jobs.gyms import MembershipFailed, each_gym
from app.jobs.runner import Job

logger = logging.getLogger(__name__)

NAME = "lapse"

# RLS holds `gym` to the one in `app.gym_id`.
SELECT_SETTINGS = "SELECT settings::text FROM gym"

# The memberships that may lapse, locked until the run commits, in id order. A payment
# locks its membership before it reads or settles anything (`app.api.ledger`), so a
# payment and a lapse of one membership run one after the other.
LOCK_LAPSABLE = """
SELECT m.id
FROM membership m
JOIN plan pl ON pl.id = m.plan_id
WHERE m.status IN ('active', 'trial') AND pl.kind <> 'dropin'
ORDER BY m.id
FOR UPDATE OF m
"""

# Read after the lock, in a statement of its own: in READ COMMITTED each statement takes
# a fresh snapshot, so this one sees every payment that committed while the lock above
# waited for it. A `FOR UPDATE` query re-checks only its locked rows once it gets them,
# not its subqueries, so the unpaid date cannot be read in that same statement.
# `unpaid_due` is the due date of the oldest period due by the run date that its
# settling entries leave short.
SELECT_LAPSABLE = f"""
SELECT m.id, m.status, pl.kind, m.current_period_end, m.credits_remaining,
       (SELECT min(b.due_date) FROM billing_period b
        WHERE b.membership_id = m.id AND b.due_date <= $2
          AND b.amount_due_clp > (
              SELECT coalesce(sum({settled_amount("e")}), 0) FROM ledger_entry e
              WHERE e.billing_period_id = b.id AND e.status = $3
                AND e.kind = ANY($4::text[]))) AS unpaid_due,
       (m.created_at AT TIME ZONE g.timezone)::date AS created_on
FROM membership m
JOIN plan pl ON pl.id = m.plan_id
JOIN gym g ON g.id = m.gym_id
WHERE m.id = ANY($1::uuid[]) AND m.status IN ('active', 'trial')
ORDER BY m.id
"""

LAPSE = "UPDATE membership SET status = $2 WHERE id = $1"

INSERT_EVENT = """
INSERT INTO plan_event (gym_id, membership_id, kind, occurred_on)
VALUES (current_setting('app.gym_id')::uuid, $1, 'lapsed', $2)
ON CONFLICT (membership_id, kind, occurred_on) DO NOTHING
"""


def _membership(row: asyncpg.Record) -> Membership:
    """The membership as the domain sees it; a recurring one paid through the day
    before its oldest unpaid period falls due, or the day before it was created if that
    is later, or with nothing owed if it has none."""
    kind = PlanKind(row["kind"])
    end = row["current_period_end"]
    if kind in RECURRING:
        unpaid = row["unpaid_due"]
        end = None if unpaid is None else max(unpaid, row["created_on"]) - timedelta(days=1)
    return Membership(kind, MembershipStatus(row["status"]), end, row["credits_remaining"])


async def lapse_gym(conn: asyncpg.Connection, day: date) -> int:
    """Lapse what `day` lapses in the gym in `app.gym_id`; the number lapsed."""
    settings = json.loads(await conn.fetchval(SELECT_SETTINGS))
    grace = memberships.grace_days(settings)
    locked = [r["id"] for r in await conn.fetch(LOCK_LAPSABLE)]
    rows = await conn.fetch(
        SELECT_LAPSABLE,
        locked,
        day,
        EntryStatus.VALIDATED.value,
        [k.value for k in SETTLING_KINDS],
    )
    lapsed = 0
    for row in rows:
        try:
            membership = _membership(row)
            if not memberships.is_due_to_lapse(membership, day, grace):
                continue
            after = memberships.lapse(membership, day, grace)
            await conn.execute(LAPSE, row["id"], after.status.value)
            await conn.execute(INSERT_EVENT, row["id"], day)
        except Exception as error:
            raise MembershipFailed(row["id"]) from error
        lapsed += 1
    return lapsed


async def lapse_memberships(conn: asyncpg.Connection, day: date) -> bool:
    """Lapse in every gym; `False` if any failed, whose work alone is rolled back."""
    return await each_gym(
        conn, day, lapse_gym, job=NAME, logger=logger, failure="lapsing a gym failed"
    )


JOB = Job(NAME, lapse_memberships)
