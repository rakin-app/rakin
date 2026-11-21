"""Resumen del mes (#505): what happened in a month after Rakin's reminders and the
team's nudges.

The current month is counted when it is asked for, from rows that already exist
(`app.month_figures`). A closed month is read from what the nightly job kept of it on
the 1st (`gym_month_figure`, #506), so it reads the same once #378 has purged the log it
was counted from, and has the debt the month closed with. A kept month counted under
older rules is shown as it was counted, and says so. A closed month that was not kept
(one before #506, or a gym suspended over every run of the next month) is counted
again, and has no closing debt.

No person-level result is kept or returned, only totals, and each figure with what it
is out of.

Money, so `money_read` (`LedgerReadSession`): owner, admin, and the titles that read
Pagos. A coach gets a 403, not even the nudges, whose inactive list is money too.
"""

import logging
from collections.abc import Mapping
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from app.domain.dates import add_months
from app.domain.value_summary import (
    REQUIRED_FIGURES,
    RULES_VERSION,
    Figure,
    percent,
    share_of_income,
)
from app.month_figures import count_month, session_rows
from app.permissions import LedgerReadSession
from app.schemas.gym import Channels
from app.schemas.summary import (
    AfterReminders,
    KeptMonth,
    MonthSummary,
    Nudges,
    OwnPayments,
    Paid,
    ProofReviews,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/summary", tags=["ledger"])

NO_SUCH_MONTH = HTTPException(status.HTTP_404_NOT_FOUND, "no summary for that month")

# The gym's timezone, today and first day in it, and its settings.
CLOCK = text(
    """
    SELECT g.timezone, (now() AT TIME ZONE g.timezone)::date AS today,
           (g.created_at AT TIME ZONE g.timezone)::date AS since, g.settings
    FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
    """
)

# What was kept of a closed month. RLS holds it to the gym, under `money_read`.
KEPT = text(
    """
    SELECT figure, value, rules_version, computed_at FROM gym_month_figure
    WHERE month = :month
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
    kept_rows = [] if shown == months[0] else list(await session.execute(KEPT, {"month": shown}))
    kept = None
    figures: Mapping[Figure, int] = {
        Figure(r.figure): r.value for r in kept_rows if r.figure in Figure
    }
    if kept_rows and figures.keys() >= REQUIRED_FIGURES:
        version = min(r.rules_version for r in kept_rows)
        kept = KeptMonth(
            computed_at=min(r.computed_at for r in kept_rows),
            rules_version=version,
            older_rules=version < RULES_VERSION,
        )
    else:
        if kept_rows:
            # Not one `OPTIONAL_FIGURES` should allow: the month is counted again
            # rather than shown with a hole.
            logger.warning(
                "kept month lacks a required figure; counting it again",
                extra={"month": shown.isoformat()},
            )
        figures = await count_month(session_rows(session), shown)
    return month_summary(
        figures,
        month=shown,
        months=months,
        since=clock.since if clock.since.replace(day=1) == shown and clock.since.day > 1 else None,
        whatsapp=Channels.model_validate(clock.settings.get("channels", {})).whatsapp,
        kept=kept,
    )
