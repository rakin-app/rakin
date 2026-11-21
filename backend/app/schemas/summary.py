"""Resumen del mes (#505): what happened after Rakin's reminders and nudges in a month,
as counts with what each is out of (`app.domain.value_summary`).

`month_summary` builds it from a month's `Figure`s, counted or kept, for the page
(`app.api.summary`) and for the monthly email (`app.jobs.month_summary`, #507), so the
two never disagree."""

from collections.abc import Mapping
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.value_summary import Figure, percent, share_of_income


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


class KeptMonth(BaseModel):
    """A closed month read from what was kept of it (`gym_month_figure`, #506), not
    counted again: its figures as they were counted, under `rules_version`."""

    computed_at: datetime
    rules_version: int
    # Counted under rules older than today's: "Cómo contamos esto" says so.
    older_rules: bool


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
    # Owed on overdue periods of Active memberships as the month closed; `None` for the
    # current month, and for a closed month that was not kept.
    overdue_clp: int | None
    # How a closed month was kept; `None` when it was counted for this request, as the
    # current month always is.
    kept: KeptMonth | None


def month_summary(
    figures: Mapping[Figure, int],
    *,
    month: date,
    months: list[date],
    since: date | None,
    whatsapp: bool,
    kept: KeptMonth | None,
) -> MonthSummary:
    """The page's month from its `Figure`s, counted now or kept: the shares and
    percentages are worked out here, from the counts, either way."""

    def paid(payments: Figure, amount: Figure) -> Paid:
        return Paid(payments=figures[payments], amount_clp=figures[amount])

    emails_only = paid(Figure.EMAILS_ONLY_PAYMENTS, Figure.EMAILS_ONLY_CLP)
    after_whatsapp = paid(Figure.AFTER_WHATSAPP_PAYMENTS, Figure.AFTER_WHATSAPP_CLP)
    total = Paid(
        payments=emails_only.payments + after_whatsapp.payments,
        amount_clp=emails_only.amount_clp + after_whatsapp.amount_clp,
    )
    income_clp, income_payments = figures[Figure.INCOME_CLP], figures[Figure.INCOME_PAYMENTS]
    nudged, back = figures[Figure.NUDGED], figures[Figure.NUDGED_BACK]
    return MonthSummary(
        month=month,
        months=months,
        since=since,
        whatsapp=whatsapp,
        income_clp=income_clp,
        income_payments=income_payments,
        reminder_emails=figures[Figure.REMINDER_EMAILS],
        reminder_whatsapps=figures[Figure.REMINDER_WHATSAPPS],
        after_reminders=AfterReminders(
            total=total,
            emails_only=emails_only,
            after_whatsapp=after_whatsapp,
            income_percent=share_of_income(total.amount_clp, income_clp, income_payments),
        ),
        nudges=Nudges(nudged=nudged, back=back, percent=percent(back, nudged)),
        emails_sent=figures[Figure.EMAILS_SENT],
        own_payments=OwnPayments(
            by_members=figures[Figure.BY_MEMBERS],
            payments=income_payments,
            percent=percent(figures[Figure.BY_MEMBERS], income_payments),
        ),
        proofs=ProofReviews(
            reviewed=figures[Figure.PROOFS_REVIEWED],
            median_minutes=figures.get(Figure.PROOF_REVIEW_MEDIAN_MINUTES),
        ),
        reactivated=figures[Figure.REACTIVATED],
        trials_converted=figures[Figure.TRIALS_CONVERTED],
        overdue_clp=figures.get(Figure.OVERDUE_CLP),
        kept=kept,
    )


def partial_since(since: date, month: date) -> date | None:
    """The gym's first day, `since`, when `month` is its first and it began after the
    1st: a partial month, "desde el 12 de noviembre"."""
    return since if since.replace(day=1) == month and since.day > 1 else None


def has_news(summary: MonthSummary) -> bool:
    """Whether the month has a figure to show: one above zero, since the summary never
    shows a zero (#516). A late payment after a reminder, someone back after a WhatsApp,
    a reminder sent, a payment informed with its proof, a proof reviewed, an automatic
    email, a plan back or a trial converted. The closing debt alone is no gain; a month
    without any of these gets no email (#507), and its page one neutral line."""
    return any(
        (
            summary.after_reminders.total.payments,
            summary.whatsapp and summary.nudges.back,
            summary.reminder_emails,
            summary.reminder_whatsapps,
            summary.own_payments.by_members,
            summary.proofs.reviewed and summary.proofs.median_minutes is not None,
            summary.emails_sent,
            summary.reactivated,
            summary.trials_converted,
        )
    )
