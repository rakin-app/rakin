"""Resumen del mes: what happened after Rakin acted, by the rules of #504's spike
(`docs/design/value-summary.md`, section 1). Pure functions: `app.api.summary` reads
the rows, gym-local dates included, and these decide what each one counts as.

Every figure says what happened *after* a reminder or a nudge, never that Rakin
caused it: some would have paid, or come back, anyway.

**Cobrado después de un recordatorio.** A validated payment on a billing period,
made after its due date (the member's act: when the proof was uploaded, else when
staff recorded it, as a gym-local date), with at least one reminder about that period
sent after the due date and before the payment: an overdue email that went out, or a
WhatsApp reminder whose link was opened. "After the due date" compares the reminder's
gym-local date, so the day-0 email sent at 23:30 is not a day-1 one; a reminder on the
due date (the day-0 email, WhatsApp's `payment_due_today`) never makes a payment count.
It is "sin mensaje del equipo" when every such reminder was an email, and "después de
un WhatsApp" when one was a WhatsApp.

**Volvió después de un WhatsApp.** Of the people nudged from the inactive list in the
month, counted once from their first nudge, those who came to a class within
`BACK_WITHIN_DAYS` days after it.

**No percentage on fewer than `MIN_FOR_PERCENT`.** "1 de 3" says more than "33 %".
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Channel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class AfterReminder(StrEnum):
    # Every reminder before the payment was an email: nobody on the team wrote.
    EMAILS_ONLY = "emails_only"
    # At least one was a WhatsApp the team opened, and presumably sent.
    AFTER_WHATSAPP = "after_whatsapp"


# The inactive list's first bucket (`app.schemas.inactive.Bucket`): someone who came to
# a class within this many days of the nudge counts as back.
BACK_WITHIN_DAYS = 14

# Below this many people or payments a figure is "N de M", never a percentage.
MIN_FOR_PERCENT = 5


@dataclass(frozen=True)
class Reminder:
    """A payment reminder about a period: an email sent, or a WhatsApp link opened."""

    channel: Channel
    sent_at: datetime
    # `sent_at` as a gym-local date.
    sent_on: date


@dataclass(frozen=True)
class LatePayment:
    """A validated payment on a billing period, with every reminder about the period."""

    due_date: date
    # The member's act: the proof's upload, else when staff recorded it.
    paid_at: datetime
    # `paid_at` as a gym-local date.
    paid_on: date
    reminders: Sequence[Reminder]


def reminders_before(payment: LatePayment) -> list[Reminder]:
    """The reminders that count for `payment`: sent after the due date, by the gym's
    calendar, and before it was paid."""
    return [
        r for r in payment.reminders if r.sent_on > payment.due_date and r.sent_at < payment.paid_at
    ]


def after_reminder(payment: LatePayment) -> AfterReminder | None:
    """What `payment` counts as: paid late after a reminder, by email only or after a
    WhatsApp; `None` when it was on time or no reminder came before it."""
    if payment.paid_on <= payment.due_date:
        return None
    before = reminders_before(payment)
    if not before:
        return None
    if any(r.channel is Channel.WHATSAPP for r in before):
        return AfterReminder.AFTER_WHATSAPP
    return AfterReminder.EMAILS_ONLY


@dataclass(frozen=True)
class Nudge:
    """A nudge from the inactive list: a WhatsApp link to `about` (a person) opened."""

    about: str
    sent_at: datetime
    # `sent_at` as a gym-local date.
    sent_on: date
    # The gym-local date of the first class `about` came to after it, if any.
    first_class_on: date | None


def first_nudges(nudges: Iterable[Nudge]) -> list[Nudge]:
    """Each person's first nudge: someone nudged twice is counted once, from the first."""
    first: dict[str, Nudge] = {}
    for nudge in nudges:
        if nudge.about not in first or nudge.sent_at < first[nudge.about].sent_at:
            first[nudge.about] = nudge
    return list(first.values())


def came_back(nudge: Nudge) -> bool:
    """Whether the person nudged came to a class within `BACK_WITHIN_DAYS` days after
    it: on day 14 they did, on day 15 they did not."""
    if nudge.first_class_on is None:
        return False
    return 0 <= (nudge.first_class_on - nudge.sent_on).days <= BACK_WITHIN_DAYS


def percent(count: int, of: int) -> int | None:
    """`count` as a whole percentage of `of`; `None` with fewer than `MIN_FOR_PERCENT`
    behind it, or more counted than there are."""
    if of < MIN_FOR_PERCENT or not 0 <= count <= of:
        return None
    return round(100 * count / of)


def share_of_income(amount_clp: int, income_clp: int, payments: int) -> int | None:
    """`amount_clp` as a whole percentage of the month's income, when `payments`
    (the month's validated payments) are enough to say one."""
    if payments < MIN_FOR_PERCENT or income_clp <= 0 or not 0 <= amount_clp <= income_clp:
        return None
    return round(100 * amount_clp / income_clp)
