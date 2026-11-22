"""Resumen del mes's figures for one month of one gym, counted from the rows already
there (#505), for the page (`app.api.summary`) and for the job that keeps each closed
month (`app.jobs.month_summary`, #506), so the two count the same way.

The rules are `app.domain.value_summary`'s, from #504's spike
(`docs/design/value-summary.md`). This reads what they need, each gym-local date
included, and counts: no person-level result is kept or returned, only totals, keyed
by `Figure`. A payment counts in the month it was validated in, as `v_monthly_income`
counts it, so the money after a reminder is always a part of the month's "Cobrado".

Every query runs in the gym `app.gym_id` names, and takes its parameters by name. The
caller runs them through a `Rows`: the API's SQLAlchemy session, or the job's asyncpg
connection (`asyncpg_rows`).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from typing import Any

import asyncpg
from sqlalchemy import TextClause, text
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_summary import (
    AfterReminder,
    Channel,
    Figure,
    LatePayment,
    Nudge,
    Reminder,
    after_reminder,
    came_back,
    first_nudges,
)
from app.notices import PAYMENT_OVERDUE, RECEIPT, STATEMENT
from app.notices.whatsapp import INACTIVE_NUDGE, PAYMENT_REMINDERS

# Runs a query with its named parameters; its rows, each by column name.
Rows = Callable[[TextClause, Mapping[str, Any]], Awaitable[Sequence[Mapping[str, Any]]]]


def session_rows(session: AsyncSession) -> Rows:
    async def rows(sql: TextClause, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        return [dict(r._mapping) for r in await session.execute(sql, dict(params))]

    return rows


# SQLAlchemy's asyncpg dialect, only to compile `:name` to `$n`.
ASYNCPG = asyncpg_dialect()  # type: ignore[no-untyped-call]


def asyncpg_rows(conn: asyncpg.Connection) -> Rows:
    """The same queries on a raw connection: compiled to asyncpg's `$n` placeholders,
    in the order SQLAlchemy numbered them."""

    async def rows(sql: TextClause, params: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        compiled = sql.compile(dialect=ASYNCPG)
        names = compiled.positiontup or []
        found = await conn.fetch(str(compiled), *(params[name] for name in names))
        return [dict(r) for r in found]

    return rows


# The emails Rakin sends on its own about money: the statement, the overdue reminder
# and the receipt.
AUTOMATIC_EMAILS = (STATEMENT.name, PAYMENT_OVERDUE.name, RECEIPT.name)

# The month asked for, `:month` its first day, as the instants it runs between in the
# gym's timezone, for `CROSS JOIN b`.
BOUNDS = """
    SELECT g.timezone AS tz,
           CAST(:month AS date)::timestamp AT TIME ZONE g.timezone AS start_at,
           (CAST(:month AS date) + interval '1 month') AT TIME ZONE g.timezone AS end_at
    FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
"""


def in_month(column: str) -> str:
    return f"{column} >= b.start_at AND {column} < b.end_at"


# The month's validated payments on a period paid after its due date, by the member's
# act: the proof's upload, else when staff recorded it. A payment moved from another
# period (`purpose = 'move'`) is staff's correction, not a payment made then.
LATE_PAYMENTS = text(
    f"""
    SELECT e.billing_period_id::text AS billing_period_id, e.amount_clp, bp.due_date,
           p.paid_at, (p.paid_at AT TIME ZONE b.tz)::date AS paid_on
    FROM ledger_entry e
    JOIN billing_period bp ON bp.id = e.billing_period_id
    CROSS JOIN ({BOUNDS}) b
    CROSS JOIN LATERAL (SELECT coalesce(e.claimed_at, e.created_at) AS paid_at) p
    WHERE e.kind = 'payment' AND e.status = 'validated' AND e.purpose IS NULL
      AND {in_month("e.validated_at")}
      AND (p.paid_at AT TIME ZONE b.tz)::date > bp.due_date
    """
)

# Every payment reminder about `:periods`: an overdue email sent, or a WhatsApp reminder
# opened. The two share the name `payment_overdue`; `channel` tells them apart.
REMINDERS = text(
    """
    SELECT ml.payload ->> 'billing_period_id' AS billing_period_id, ml.channel,
           ml.sent_at, (ml.sent_at AT TIME ZONE g.timezone)::date AS sent_on
    FROM message_log ml
    JOIN gym g ON g.id = ml.gym_id
    WHERE ml.status = 'sent'
      AND ml.payload ->> 'billing_period_id' = ANY(CAST(:periods AS text[]))
      AND ((ml.channel = 'email' AND ml.template = :overdue_email)
           OR (ml.channel = 'whatsapp' AND ml.template = ANY(CAST(:whatsapp AS text[]))))
    """
)

# The month's nudges from the inactive list, each with the first class its person came
# to after it.
NUDGES = text(
    f"""
    SELECT ml.payload ->> 'about' AS about, ml.sent_at,
           (ml.sent_at AT TIME ZONE b.tz)::date AS sent_on,
           (c.starts_at AT TIME ZONE b.tz)::date AS first_class_on
    FROM message_log ml
    CROSS JOIN ({BOUNDS}) b
    LEFT JOIN LATERAL (
        SELECT min(s.starts_at) AS starts_at FROM attendance a
        JOIN session s ON s.id = a.session_id
        JOIN membership m ON m.id = a.membership_id
        WHERE m.person_id::text = ml.payload ->> 'about' AND s.starts_at > ml.sent_at
          AND s.cancelled_at IS NULL
    ) c ON true
    WHERE ml.channel = 'whatsapp' AND ml.template = :nudge AND ml.status = 'sent'
      AND ml.payload ? 'about' AND {in_month("ml.sent_at")}
    """
)

# The month's plain counts. The payments behind "Cobrado" leave out moves, as
# `LATE_PAYMENTS` does: a move is staff's correction, not a member paying.
#
# A member's own payment, and a proof to review, is one with `proof_object_key` set.
# `claimed_by` / `claimed_at` cannot tell them apart: `app.api.entries.INSERT_ENTRY`
# sets both to the recording admin and `now()` for every entry staff record (#511).
# The key is exact: the member's claim (`app.api.proofs.CLAIM`) is the one write that
# sets it, it requires one, and nothing clears it.
COUNTS = text(
    f"""
    SELECT
        (SELECT count(*) FROM message_log ml
         WHERE ml.channel = 'email' AND ml.status = 'sent'
           AND ml.template = ANY(CAST(:automatic AS text[])) AND {in_month("ml.sent_at")})
            AS emails_sent,
        (SELECT count(*) FROM message_log ml
         WHERE ml.channel = 'email' AND ml.status = 'sent' AND ml.template = :overdue_email
           AND {in_month("ml.sent_at")}) AS reminder_emails,
        (SELECT count(*) FROM message_log ml
         WHERE ml.channel = 'whatsapp' AND ml.status = 'sent'
           AND ml.template = ANY(CAST(:whatsapp AS text[])) AND {in_month("ml.sent_at")})
            AS reminder_whatsapps,
        (SELECT coalesce(sum(income_clp), 0)::bigint FROM v_monthly_income
         WHERE month = CAST(:month AS date)) AS income_clp,
        -- Plain payments, moves left out: since 0089 the same as
        -- `v_monthly_income.payments`, which leaves them out too.
        (SELECT count(*) FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status = 'validated' AND e.purpose IS NULL
           AND {in_month("e.validated_at")}) AS income_payments,
        (SELECT count(*) FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status = 'validated' AND e.purpose IS NULL
           AND e.proof_object_key IS NOT NULL AND {in_month("e.validated_at")}) AS by_members,
        (SELECT count(*) FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status IN ('validated', 'rejected')
           AND e.proof_object_key IS NOT NULL AND {in_month("e.validated_at")}) AS proofs_reviewed,
        (SELECT percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY extract(epoch FROM e.validated_at - e.claimed_at))
         FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status IN ('validated', 'rejected')
           AND e.proof_object_key IS NOT NULL AND {in_month("e.validated_at")})
            AS review_median_seconds,
        (SELECT count(*) FROM membership m WHERE {in_month("m.reactivated_at")})
            AS reactivated,
        (SELECT count(*) FROM membership m
         WHERE m.converted_from IS NOT NULL AND {in_month("m.created_at")})
            AS trials_converted
    FROM ({BOUNDS}) b
    """
)

# What Active memberships owe on periods overdue now (`v_overdue`): read on the 1st, the
# debt the month closed with (#506). Today only, so a month that is not kept has none.
OVERDUE_NOW = text(
    """
    SELECT coalesce(sum(o.outstanding_clp), 0)::bigint AS overdue_clp FROM v_overdue o
    WHERE o.membership_status = 'active'
    """
)


async def _after_reminders(rows: Rows, month: date) -> dict[AfterReminder, list[int]]:
    """The amounts of the month's late payments that came after a reminder, by kind."""
    payments = await rows(LATE_PAYMENTS, {"month": month})
    reminders: dict[str, list[Reminder]] = {}
    if payments:
        found = await rows(
            REMINDERS,
            {
                "periods": sorted({p["billing_period_id"] for p in payments}),
                "overdue_email": PAYMENT_OVERDUE.name,
                "whatsapp": list(PAYMENT_REMINDERS),
            },
        )
        for r in found:
            reminders.setdefault(r["billing_period_id"], []).append(
                Reminder(channel=Channel(r["channel"]), sent_at=r["sent_at"], sent_on=r["sent_on"])
            )
    by_kind: dict[AfterReminder, list[int]] = {kind: [] for kind in AfterReminder}
    for p in payments:
        kind = after_reminder(
            LatePayment(
                due_date=p["due_date"],
                paid_at=p["paid_at"],
                paid_on=p["paid_on"],
                reminders=reminders.get(p["billing_period_id"], []),
            )
        )
        if kind is not None:
            by_kind[kind].append(p["amount_clp"])
    return by_kind


async def _nudges(rows: Rows, month: date) -> tuple[int, int]:
    """People nudged in the month, and how many of them came back."""
    found = await rows(NUDGES, {"month": month, "nudge": INACTIVE_NUDGE})
    first = first_nudges(
        Nudge(
            about=r["about"],
            sent_at=r["sent_at"],
            sent_on=r["sent_on"],
            first_class_on=r["first_class_on"],
        )
        for r in found
    )
    return len(first), sum(came_back(n) for n in first)


async def count_month(rows: Rows, month: date) -> dict[Figure, int]:
    """The month starting `month`, in the gym `app.gym_id` names, by today's rules:
    every figure but `OVERDUE_CLP`, which only the month's close can read."""
    (counts,) = await rows(
        COUNTS,
        {
            "month": month,
            "automatic": list(AUTOMATIC_EMAILS),
            "overdue_email": PAYMENT_OVERDUE.name,
            "whatsapp": list(PAYMENT_REMINDERS),
        },
    )
    paid = await _after_reminders(rows, month)
    nudged, back = await _nudges(rows, month)
    figures = {
        Figure.INCOME_CLP: counts["income_clp"],
        Figure.INCOME_PAYMENTS: counts["income_payments"],
        Figure.REMINDER_EMAILS: counts["reminder_emails"],
        Figure.REMINDER_WHATSAPPS: counts["reminder_whatsapps"],
        Figure.EMAILS_ONLY_PAYMENTS: len(paid[AfterReminder.EMAILS_ONLY]),
        Figure.EMAILS_ONLY_CLP: sum(paid[AfterReminder.EMAILS_ONLY]),
        Figure.AFTER_WHATSAPP_PAYMENTS: len(paid[AfterReminder.AFTER_WHATSAPP]),
        Figure.AFTER_WHATSAPP_CLP: sum(paid[AfterReminder.AFTER_WHATSAPP]),
        Figure.NUDGED: nudged,
        Figure.NUDGED_BACK: back,
        Figure.EMAILS_SENT: counts["emails_sent"],
        Figure.BY_MEMBERS: counts["by_members"],
        Figure.PROOFS_REVIEWED: counts["proofs_reviewed"],
        Figure.REACTIVATED: counts["reactivated"],
        Figure.TRIALS_CONVERTED: counts["trials_converted"],
    }
    median = counts["review_median_seconds"]
    if median is not None:
        figures[Figure.PROOF_REVIEW_MEDIAN_MINUTES] = round(median / 60)
    return figures


async def overdue_now(rows: Rows) -> int:
    """What Active memberships owe on overdue periods today."""
    (row,) = await rows(OVERDUE_NOW, {})
    overdue: int = row["overdue_clp"]
    return overdue
