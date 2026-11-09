"""The `statements` job: each period's statement, emailed 7 days before it is due.

For every gym it finds the billing periods due between the run date and
`STATEMENT_DAYS` later that validated payments and credit still leave short, and
emails each one's statement: what is owed, when, the gym's bank details and a link
to the student page to upload the proof. It goes to the member, or to their guardian
(`app.contacts`). The billing job writes each period 7 days before its due date, on
the same run and before this one, so a period is usually stated the day it appears.

A period is stated once: one whose statement `message_log` records as sent is
skipped. One that failed (an address the gym typed wrong, the relay down) is tried
again on each later run until its due date. A period of a cancelled membership, or
one paid in full meanwhile, is not stated at all, and neither is a frozen one's while
the freeze lasts: it moved the periods it reaches past its end, and the statement
goes out when they come due again.

Each gym's statements are read in its savepoint and sent once every gym has been
read, so no savepoint is open while the relay answers. The runner's transaction for
the day still is, holding only those reads. Each send, its sign-in link and its
`message_log` row go through a connection of their own (`Notices`), so they commit
whatever the day's outcome: a day that fails and is run again sends only what it
had not sent.
"""

import json
import logging
from datetime import date, timedelta

import asyncpg

from app.contacts import contact_query
from app.domain.billing import SETTLING_KINDS
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.notices import STATEMENT, Notice, Notices

logger = logging.getLogger(__name__)

NAME = "statements"

STATEMENT_DAYS = 7

# RLS holds every table to the gym in `app.gym_id`, `message_log` included.
SELECT_DUE = """
SELECT bp.id, bp.period_start, bp.period_end, bp.due_date,
       bp.amount_due_clp - coalesce(paid.amount, 0) AS outstanding_clp,
       m.person_id, gp.name AS person_name, pl.name AS plan_name,
       g.id AS gym_id, g.name AS gym_name, g.settings -> 'bank_account' AS bank_account
FROM billing_period bp
JOIN membership m ON m.id = bp.membership_id
JOIN plan pl ON pl.id = m.plan_id
JOIN gym g ON g.id = m.gym_id
JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
LEFT JOIN LATERAL (
    SELECT sum(e.amount_clp)::bigint AS amount FROM ledger_entry e
    WHERE e.billing_period_id = bp.id AND e.status = 'validated'
      AND e.kind = ANY($3::text[])
) paid ON true
WHERE bp.due_date BETWEEN $1 AND $2
  AND m.status NOT IN ('cancelled', 'frozen')
  AND coalesce(paid.amount, 0) < bp.amount_due_clp
  AND NOT EXISTS (
      SELECT FROM message_log l
      WHERE l.template = 'statement' AND l.status = 'sent'
        AND l.payload ->> 'billing_period_id' = bp.id::text
  )
ORDER BY bp.due_date, bp.id
"""

CONTACT = contact_query("$1")


async def due_statements(conn: asyncpg.Connection, day: date) -> list[Notice]:
    """The statements owed in the gym in `app.gym_id` on `day`."""
    notices = []
    rows = await conn.fetch(
        SELECT_DUE,
        day,
        day + timedelta(days=STATEMENT_DAYS),
        sorted(k.value for k in SETTLING_KINDS),
    )
    for row in rows:
        contact = await conn.fetchrow(CONTACT, row["person_id"])
        if contact is None or not contact["email"]:
            logger.info("statement: no email to send it to", extra={"period_id": str(row["id"])})
            continue
        notices.append(
            Notice(
                STATEMENT,
                to=contact["email"],
                person_id=contact["person_id"],
                gym_id=row["gym_id"],
                context={
                    "name": contact["name"],
                    "gym": row["gym_name"],
                    "plan_name": row["plan_name"],
                    "billing_period_id": row["id"],
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "due_date": row["due_date"],
                    "amount_clp": row["outstanding_clp"],
                    "bank_account": _json(row["bank_account"]),
                    "dependent_name": row["person_name"] if contact["on_behalf_of"] else None,
                },
            )
        )
    return notices


def _json(value: str | None) -> object:
    # asyncpg hands `jsonb` over as its text.
    return None if value is None else json.loads(value)


def job(notices: Notices) -> Job:
    """The job, sending through `notices`."""

    async def run(conn: asyncpg.Connection, day: date) -> bool:
        due: list[Notice] = []

        async def read_gym(conn: asyncpg.Connection, day: date) -> None:
            due.extend(await due_statements(conn, day))

        complete = await each_gym(
            conn, day, read_gym, job=NAME, logger=logger, failure="stating a gym failed"
        )
        for notice in due:
            # Never raises: a notice it could not send is a `failed` row, tried again
            # tomorrow.
            await notices.send(notice)
        return complete

    return Job(NAME, run)
