from datetime import date

import pytest

from app.domain import billing, ledger
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry


def period(due: int = 30_000) -> BillingPeriod:
    return BillingPeriod(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount_due_clp=due,
        due_date=date(2026, 11, 1),
    )


def payment(amount: int) -> LedgerEntry:
    return LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=amount)


def test_validating_the_full_amount_closes_the_period() -> None:
    settlement = billing.validate_payment(period(), payment(30_000))

    assert settlement.entry.status is EntryStatus.VALIDATED
    assert settlement.period.closed
    assert settlement.period.outstanding_clp == 0
    assert settlement.credit is None


def test_overpayment_creates_a_credit_adjustment_for_the_next_period() -> None:
    settlement = billing.validate_payment(period(), payment(45_000))

    assert settlement.period.closed
    assert settlement.credit == LedgerEntry(
        kind=EntryKind.ADJUSTMENT,
        amount_clp=15_000,
        status=EntryStatus.VALIDATED,
        note="Pagó $45.000, quedan $15.000 a favor",
    )

    next_period = billing.apply(period(due=30_000), settlement.credit)
    assert next_period.period.paid_clp == 15_000
    assert next_period.period.outstanding_clp == 15_000
    assert not next_period.period.closed


def test_a_credit_larger_than_the_next_period_carries_on() -> None:
    credit = billing.validate_payment(period(), payment(90_000)).credit
    assert credit is not None

    second = billing.apply(period(), credit)

    assert second.period.closed
    assert second.credit is not None
    assert second.credit.amount_clp == 30_000


def test_a_partial_payment_leaves_the_period_open_with_the_rest_outstanding() -> None:
    settlement = billing.validate_payment(period(), payment(10_000))

    assert not settlement.period.closed
    assert settlement.period.outstanding_clp == 20_000

    rest = billing.validate_payment(settlement.period, payment(20_000))
    assert rest.period.closed


def test_a_rejected_proof_keeps_the_period_open() -> None:
    open_period = period()
    rejected = ledger.reject(payment(30_000), "blurry receipt")

    with pytest.raises(InvalidTransition, match="validated"):
        billing.apply(open_period, rejected)
    assert not open_period.closed


def test_a_pending_entry_does_not_settle_a_period() -> None:
    with pytest.raises(InvalidTransition, match="validated"):
        billing.apply(period(), payment(30_000))


@pytest.mark.parametrize("kind", [EntryKind.CHARGE, EntryKind.REFUND])
def test_charges_and_refunds_do_not_settle_a_period(kind: EntryKind) -> None:
    entry = LedgerEntry(kind=kind, amount_clp=30_000, status=EntryStatus.VALIDATED)

    with pytest.raises(InvalidTransition, match="does not settle"):
        billing.apply(period(), entry)


def test_only_payments_go_through_validate_payment() -> None:
    adjustment = LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=1_000)

    with pytest.raises(InvalidTransition, match="not a payment"):
        billing.validate_payment(period(), adjustment)


def test_a_closed_period_takes_no_more_payments() -> None:
    closed = billing.validate_payment(period(), payment(30_000)).period

    with pytest.raises(InvalidTransition, match="closed"):
        billing.validate_payment(closed, payment(1_000))


def test_validating_twice_raises() -> None:
    settled = billing.validate_payment(period(), payment(10_000))

    with pytest.raises(InvalidTransition):
        billing.validate_payment(settled.period, settled.entry)
