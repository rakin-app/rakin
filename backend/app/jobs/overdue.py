"""The `overdue` job: a period past due is emailed until it is paid or the plan lapses.

For every gym it finds the billing periods of Active memberships that validated
payments and credit still leave short, as `app.domain.billing` settles them, and emails
each one on the days `app.domain.membership.is_overdue_email_day` names: the due date,
the day after, then every 3 days while the gym's grace lasts (`grace_days`). With a
grace of 15 that is days 0, 1, 4, 7, 10 and 13; the lapse job lapses the membership
once the grace is past, and the lapse sends its own plan-event email. The email says
what is owed, for which period, how many days late, the gym's bank details and a link
to the student page to upload the proof, and is signed `Recordatorio automático · <gym>`
in its footer, as the WhatsApp reminders are. It goes to the member, or to their
guardian (`app.contacts`).

Nothing goes to a period that is paid, whose membership is cancelled, frozen or lapsed,
or with a proof waiting for review: the member says they paid, and the review answers
them. The email is essential, like the statement: it is about money owed, so an
unsubscribe does not stop it (`app.notices.PAYMENT_OVERDUE`).

A period is emailed at most once a day. Each email's `message_log` payload carries the
day it went out for (`on`), the run date here and the gym's today for one sent by hand
from "Enviar recordatorio" (`app.api.reminders`), and a period already emailed `on` the
run date is skipped. One that failed is not tried again until its next day.

It runs after `lapse`, so a membership lapsed today is no longer Active, and after
`statements`. As there, each gym's periods are read in its savepoint and sent once
every gym has been read, so no savepoint is open while the relay answers; each send
and its `message_log` row commit on a connection of their own (`Notices`).
"""

import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any

import asyncpg

from app.contacts import contact_query
from app.domain import membership as memberships
from app.domain.billing import SETTLING_KINDS, settled_amount
from app.jobs.gyms import each_gym
from app.jobs.runner import Job
from app.notices import PAYMENT_OVERDUE, Notice, Notices
from app.notices.whatsapp import signature

logger = logging.getLogger(__name__)

NAME = "overdue"

# RLS holds `gym` to the one in `app.gym_id`.
SELECT_SETTINGS = "SELECT settings::text FROM gym"

# The periods due between `$2` and `$1`, the run date, that are still owed and were
# not emailed for the run date yet. RLS holds every table to the gym.
SELECT_OVERDUE = f"""
SELECT bp.id, bp.period_start, bp.period_end, bp.due_date,
       bp.amount_due_clp - coalesce(paid.amount, 0) AS outstanding_clp,
       $1::date - bp.due_date AS days_overdue,
       m.person_id, gp.name AS person_name, pl.name AS plan_name,
       g.id AS gym_id, g.name AS gym_name, g.settings -> 'bank_account' AS bank_account
FROM billing_period bp
JOIN membership m ON m.id = bp.membership_id
JOIN plan pl ON pl.id = m.plan_id
JOIN gym g ON g.id = m.gym_id
JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
LEFT JOIN LATERAL (
    SELECT sum({settled_amount("e")})::bigint AS amount FROM ledger_entry e
    WHERE e.billing_period_id = bp.id AND e.status = 'validated'
      AND e.kind = ANY($3::text[])
) paid ON true
WHERE bp.due_date BETWEEN $2 AND $1
  AND m.status = 'active'
  AND coalesce(paid.amount, 0) < bp.amount_due_clp
  AND NOT EXISTS (
      SELECT FROM ledger_entry e
      WHERE e.billing_period_id = bp.id AND e.kind = 'payment' AND e.status = 'pending'
  )
  AND NOT EXISTS (
      SELECT FROM message_log l
      WHERE l.channel = 'email' AND l.template = 'payment_overdue' AND l.status = 'sent'
        AND l.payload ->> 'billing_period_id' = bp.id::text
        AND l.payload ->> 'on' = $1::date::text
  )
ORDER BY bp.due_date, bp.id
"""

CONTACT = contact_query("$1")


def overdue_notice(
    *,
    to: str,
    contact_id: uuid.UUID,
    contact_name: str,
    dependent_name: str | None,
    gym_id: uuid.UUID,
    gym_name: str,
    plan_name: str,
    billing_period_id: uuid.UUID,
    period_start: date,
    period_end: date,
    due_date: date,
    amount_clp: int,
    days_overdue: int,
    bank_account: Any,
    on: date,
) -> Notice:
    """The overdue email about a period, to `to`: the member's, or their guardian's
    with `dependent_name` the member's. `on` is the day it goes out for."""
    return Notice(
        PAYMENT_OVERDUE,
        to=to,
        person_id=contact_id,
        gym_id=gym_id,
        context={
            "name": contact_name,
            "gym": gym_name,
            "plan_name": plan_name,
            "billing_period_id": billing_period_id,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "amount_clp": amount_clp,
            "days_overdue": days_overdue,
            "bank_account": bank_account,
            "dependent_name": dependent_name,
            "on": on,
            # Over the footer, as on the WhatsApp reminders.
            "signature": signature(gym_name),
        },
    )


async def due_overdue(conn: asyncpg.Connection, day: date) -> list[Notice]:
    """The overdue emails owed in the gym in `app.gym_id` on `day`."""
    grace = memberships.grace_days(json.loads(await conn.fetchval(SELECT_SETTINGS)))
    rows = await conn.fetch(
        SELECT_OVERDUE,
        day,
        day - timedelta(days=grace),
        sorted(k.value for k in SETTLING_KINDS),
    )
    notices = []
    for row in rows:
        if not memberships.is_overdue_email_day(row["days_overdue"], grace):
            continue
        contact = await conn.fetchrow(CONTACT, row["person_id"])
        if contact is None or not contact["email"]:
            logger.info("overdue: no email to send it to", extra={"period_id": str(row["id"])})
            continue
        notices.append(
            overdue_notice(
                to=contact["email"],
                contact_id=contact["person_id"],
                contact_name=contact["name"],
                dependent_name=row["person_name"] if contact["on_behalf_of"] else None,
                gym_id=row["gym_id"],
                gym_name=row["gym_name"],
                plan_name=row["plan_name"],
                billing_period_id=row["id"],
                period_start=row["period_start"],
                period_end=row["period_end"],
                due_date=row["due_date"],
                amount_clp=row["outstanding_clp"],
                days_overdue=row["days_overdue"],
                bank_account=_json(row["bank_account"]),
                on=day,
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
            due.extend(await due_overdue(conn, day))

        complete = await each_gym(
            conn, day, read_gym, job=NAME, logger=logger, failure="reading a gym's overdue failed"
        )
        for notice in due:
            # Never raises: a notice it could not send is a `failed` row.
            await notices.send(notice)
        return complete

    return Job(NAME, run)
