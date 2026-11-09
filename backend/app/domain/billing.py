"""Settling billing periods against validated ledger entries.

A period closes once validated payments (and credit carried in from an earlier
overpayment) cover its amount due. Whatever is paid beyond that becomes a credit
adjustment to apply against the next period. A rejected proof never reaches a
period, so the period stays open.
"""

from dataclasses import dataclass, replace
from datetime import date

from app.domain import ledger
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.money import format_clp

SETTLING_KINDS = frozenset({EntryKind.PAYMENT, EntryKind.ADJUSTMENT})


@dataclass(frozen=True)
class BillingPeriod:
    period_start: date
    period_end: date
    amount_due_clp: int
    due_date: date
    paid_clp: int = 0
    closed: bool = False

    @property
    def outstanding_clp(self) -> int:
        return max(self.amount_due_clp - self.paid_clp, 0)


@dataclass(frozen=True)
class Settlement:
    period: BillingPeriod
    entry: LedgerEntry
    # A validated adjustment for the overpayment, to apply to the next period.
    credit: LedgerEntry | None = None


def overpayment_note(paid_clp: int, credit_clp: int) -> str:
    """The credit adjustment's note, which the student reads: what they paid, what is left."""
    return f"Pagó {format_clp(paid_clp)}, quedan {format_clp(credit_clp)} a favor"


def apply(period: BillingPeriod, entry: LedgerEntry) -> Settlement:
    """Count a validated payment or credit adjustment towards `period`."""
    if entry.status is not EntryStatus.VALIDATED:
        raise InvalidTransition(f"only a validated entry settles a period, not {entry.status}")
    if entry.kind not in SETTLING_KINDS:
        raise InvalidTransition(f"a {entry.kind} entry does not settle a period")
    if period.closed:
        raise InvalidTransition("billing period is already closed")

    paid = period.paid_clp + entry.amount_clp
    overpaid = paid - period.amount_due_clp
    settled = replace(period, paid_clp=min(paid, period.amount_due_clp), closed=overpaid >= 0)
    credit = None
    if overpaid > 0:
        credit = LedgerEntry(
            kind=EntryKind.ADJUSTMENT,
            amount_clp=overpaid,
            status=EntryStatus.VALIDATED,
            note=overpayment_note(entry.amount_clp, overpaid),
        )
    return Settlement(period=settled, entry=entry, credit=credit)


def validate_payment(period: BillingPeriod, entry: LedgerEntry) -> Settlement:
    """Validate a pending payment against `period`."""
    if entry.kind is not EntryKind.PAYMENT:
        raise InvalidTransition(f"a {entry.kind} entry is not a payment")
    if period.closed:
        raise InvalidTransition("billing period is already closed")
    return apply(period, ledger.validate(entry))
