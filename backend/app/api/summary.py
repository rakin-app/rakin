"""Resumen del mes (#505): what happened in a month after Rakin's reminders and the
team's nudges, computed when it is asked for from rows that already exist.

The rules are `app.domain.value_summary`'s, from #504's spike
(`docs/design/value-summary.md`). This reads what they need, each gym-local date
included, and counts: no person-level result is kept or returned, only totals, and
each figure with what it is out of. A payment counts in the month it was validated in,
as `v_monthly_income` counts it, so the money after a reminder is always a part of the
month's "Cobrado".

Money, so `money_read` (`LedgerReadSession`): owner, admin, and the titles that read
Pagos. A coach gets a 403, not even the nudges, whose inactive list is money too.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dates import add_months
from app.domain.value_summary import (
    AfterReminder,
    Channel,
    LatePayment,
    Nudge,
    Reminder,
    after_reminder,
    came_back,
    first_nudges,
    percent,
    share_of_income,
)
from app.notices import PAYMENT_OVERDUE, RECEIPT, STATEMENT
from app.notices.whatsapp import INACTIVE_NUDGE, PAYMENT_REMINDERS
from app.permissions import LedgerReadSession
from app.schemas.gym import Channels
from app.schemas.summary import (
    AfterReminders,
    MonthSummary,
    Nudges,
    OwnPayments,
    Paid,
    ProofReviews,
)

router = APIRouter(prefix="/api/summary", tags=["ledger"])

NO_SUCH_MONTH = HTTPException(status.HTTP_404_NOT_FOUND, "no summary for that month")

# The emails Rakin sends on its own about money: the statement, the overdue reminder
# and the receipt.
AUTOMATIC_EMAILS = (STATEMENT.name, PAYMENT_OVERDUE.name, RECEIPT.name)

# The gym's timezone, today and first day in it, and its settings.
CLOCK = text(
    """
    SELECT g.timezone, (now() AT TIME ZONE g.timezone)::date AS today,
           (g.created_at AT TIME ZONE g.timezone)::date AS since, g.settings
    FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
    """
)

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
    f"""
    SELECT ml.payload ->> 'billing_period_id' AS billing_period_id, ml.channel,
           ml.sent_at, (ml.sent_at AT TIME ZONE b.tz)::date AS sent_on
    FROM message_log ml
    CROSS JOIN ({BOUNDS}) b
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
    SELECT n.about, n.sent_at, (n.sent_at AT TIME ZONE b.tz)::date AS sent_on,
           (c.starts_at AT TIME ZONE b.tz)::date AS first_class_on
    FROM (
        SELECT ml.payload ->> 'about' AS about, ml.sent_at FROM message_log ml
        CROSS JOIN ({BOUNDS}) b
        WHERE ml.channel = 'whatsapp' AND ml.template = :nudge AND ml.status = 'sent'
          AND ml.payload ? 'about' AND {in_month("ml.sent_at")}
    ) n
    CROSS JOIN ({BOUNDS}) b
    LEFT JOIN LATERAL (
        SELECT min(s.starts_at) AS starts_at FROM attendance a
        JOIN session s ON s.id = a.session_id
        JOIN membership m ON m.id = a.membership_id
        WHERE m.person_id::text = n.about AND s.starts_at > n.sent_at
          AND s.cancelled_at IS NULL
    ) c ON true
    """
)

# The month's plain counts.
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
        (SELECT coalesce(sum(payments), 0)::bigint FROM v_monthly_income
         WHERE month = CAST(:month AS date)) AS income_payments,
        (SELECT count(*) FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status = 'validated' AND e.claimed_by IS NOT NULL
           AND {in_month("e.validated_at")}) AS by_members,
        (SELECT count(*) FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status IN ('validated', 'rejected')
           AND e.claimed_at IS NOT NULL AND {in_month("e.validated_at")}) AS proofs_reviewed,
        (SELECT percentile_cont(0.5) WITHIN GROUP (
                    ORDER BY extract(epoch FROM e.validated_at - e.claimed_at))
         FROM ledger_entry e
         WHERE e.kind = 'payment' AND e.status IN ('validated', 'rejected')
           AND e.claimed_at IS NOT NULL AND {in_month("e.validated_at")})
            AS review_median_seconds,
        (SELECT count(*) FROM membership m WHERE {in_month("m.reactivated_at")})
            AS reactivated,
        (SELECT count(*) FROM membership m
         WHERE m.converted_from IS NOT NULL AND {in_month("m.created_at")})
            AS trials_converted
    FROM ({BOUNDS}) b
    """
)


def months_between(first: date, last: date) -> list[date]:
    """The first day of every month from `first`'s to `last`'s, newest first."""
    months, month = [], last.replace(day=1)
    while month >= first.replace(day=1):
        months.append(month)
        month = add_months(month, -1)
    return months


def parse_month(month: str | None, today: date) -> date:
    if month is None:
        return today.replace(day=1)
    year, number = month.split("-")
    return date(int(year), int(number), 1)


async def after_reminders(session: AsyncSession, month: date, counts: Any) -> AfterReminders:
    payments = list((await session.execute(LATE_PAYMENTS, {"month": month})).all())
    reminders: dict[str, list[Reminder]] = {}
    if payments:
        rows = await session.execute(
            REMINDERS,
            {
                "month": month,
                "periods": sorted({p.billing_period_id for p in payments}),
                "overdue_email": PAYMENT_OVERDUE.name,
                "whatsapp": list(PAYMENT_REMINDERS),
            },
        )
        for r in rows:
            reminders.setdefault(r.billing_period_id, []).append(
                Reminder(channel=Channel(r.channel), sent_at=r.sent_at, sent_on=r.sent_on)
            )
    by_kind: dict[AfterReminder, list[int]] = {kind: [] for kind in AfterReminder}
    for p in payments:
        kind = after_reminder(
            LatePayment(
                due_date=p.due_date,
                paid_at=p.paid_at,
                paid_on=p.paid_on,
                reminders=reminders.get(p.billing_period_id, []),
            )
        )
        if kind is not None:
            by_kind[kind].append(p.amount_clp)

    def paid(amounts: list[int]) -> Paid:
        return Paid(payments=len(amounts), amount_clp=sum(amounts))

    total = paid([a for amounts in by_kind.values() for a in amounts])
    return AfterReminders(
        total=total,
        emails_only=paid(by_kind[AfterReminder.EMAILS_ONLY]),
        after_whatsapp=paid(by_kind[AfterReminder.AFTER_WHATSAPP]),
        income_percent=share_of_income(total.amount_clp, counts.income_clp, counts.income_payments),
    )


async def nudges(session: AsyncSession, month: date) -> Nudges:
    rows = await session.execute(NUDGES, {"month": month, "nudge": INACTIVE_NUDGE})
    first = first_nudges(
        Nudge(about=r.about, sent_at=r.sent_at, sent_on=r.sent_on, first_class_on=r.first_class_on)
        for r in rows
    )
    back = sum(came_back(n) for n in first)
    return Nudges(nudged=len(first), back=back, percent=percent(back, len(first)))


@router.get("")
async def summary(
    session: LedgerReadSession,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> MonthSummary:
    """The gym's month, `YYYY-MM` in its timezone, the current one by default: what was
    paid after a reminder, who came back after a nudge, and the plain counts."""
    clock = (await session.execute(CLOCK)).one()
    shown = parse_month(month, clock.today)
    months = months_between(clock.since, clock.today)
    if shown not in months:
        raise NO_SUCH_MONTH
    counts = (
        await session.execute(
            COUNTS,
            {
                "month": shown,
                "automatic": list(AUTOMATIC_EMAILS),
                "overdue_email": PAYMENT_OVERDUE.name,
                "whatsapp": list(PAYMENT_REMINDERS),
            },
        )
    ).one()
    median = counts.review_median_seconds
    return MonthSummary(
        month=shown,
        months=months,
        since=clock.since if clock.since.replace(day=1) == shown and clock.since.day > 1 else None,
        whatsapp=Channels.model_validate(clock.settings.get("channels", {})).whatsapp,
        income_clp=counts.income_clp,
        income_payments=counts.income_payments,
        reminder_emails=counts.reminder_emails,
        reminder_whatsapps=counts.reminder_whatsapps,
        after_reminders=await after_reminders(session, shown, counts),
        nudges=await nudges(session, shown),
        emails_sent=counts.emails_sent,
        own_payments=OwnPayments(
            by_members=counts.by_members,
            payments=counts.income_payments,
            percent=percent(counts.by_members, counts.income_payments),
        ),
        proofs=ProofReviews(
            reviewed=counts.proofs_reviewed,
            median_minutes=None if median is None else round(median / 60),
        ),
        reactivated=counts.reactivated,
        trials_converted=counts.trials_converted,
    )
