"""Resumen del mes (#505): what happened after Rakin's reminders and nudges in a month,
as counts with what each is out of (`app.domain.value_summary`)."""

from datetime import date

from pydantic import BaseModel


class Paid(BaseModel):
    """Late payments that came after a reminder: how many, and how much."""

    payments: int
    amount_clp: int


class AfterReminders(BaseModel):
    """`Cobrado después de un recordatorio`, counted in the month each was validated in,
    as the month's income counts it, and split by who wrote the reminders."""

    total: Paid
    # Every reminder before the payment was an email: nobody on the team wrote.
    emails_only: Paid
    # At least one was a WhatsApp the team opened.
    after_whatsapp: Paid
    # `total.amount_clp` as a percentage of `MonthSummary.income_clp`; `None` with fewer
    # than 5 payments in the month.
    income_percent: int | None


class Nudges(BaseModel):
    """`Volvió después de un WhatsApp`: of the `nudged` people messaged from the inactive
    list in the month, the `back` who came to a class within 14 days."""

    nudged: int
    back: int
    # `None` with fewer than 5 nudged.
    percent: int | None


class OwnPayments(BaseModel):
    """Of the month's validated payments, those the members recorded themselves, with
    their proof."""

    by_members: int
    payments: int
    percent: int | None


class ProofReviews(BaseModel):
    """Proofs validated or rejected in the month, and the median time each waited."""

    reviewed: int
    # From upload to review, in whole minutes; `None` with none reviewed.
    median_minutes: int | None


class MonthSummary(BaseModel):
    """`GET /api/summary?month=YYYY-MM`, the gym's month in its timezone."""

    # Its first day.
    month: date
    # Every month there is one of, newest first: from the gym's first to the current.
    months: list[date]
    # The gym's first day, when it is in this month: a partial month, "desde el 12".
    since: date | None
    # Whether the gym has its WhatsApp channel on (Ajustes).
    whatsapp: bool
    # The month's income, net of refunds, as the ledger's "Cobrado" (`v_monthly_income`).
    income_clp: int
    # Validated payments in the month, the count behind `income_clp`.
    income_payments: int
    # Payment reminders in the month: overdue emails sent, WhatsApp reminders opened.
    reminder_emails: int
    reminder_whatsapps: int
    after_reminders: AfterReminders
    nudges: Nudges
    # Automatic emails sent: statements, overdue reminders and receipts.
    emails_sent: int
    own_payments: OwnPayments
    proofs: ProofReviews
    # Lapsed plans brought back.
    reactivated: int
    # Trials that became a paid plan.
    trials_converted: int
