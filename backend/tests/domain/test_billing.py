from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from app.domain import billing, ledger
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms


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


# --- generating periods -------------------------------------------------------------

NOV_8 = date(2026, 11, 8)

MONTHLY = billing.Plan(PlanTerms(PlanKind.MONTHLY, anchor="signup"), 45_000)
FIRST = billing.Plan(PlanTerms(PlanKind.MONTHLY, anchor="first"), 40_000)
PREPAID = billing.Plan(PlanTerms(PlanKind.PREPAID), 240_000, period_months=6)
CREDITS = billing.Plan(PlanTerms(PlanKind.CREDITS, credits=12, credit_expiry_days=60), 45_000)
DROPIN = billing.Plan(PlanTerms(PlanKind.DROPIN), 10_000)
TRIAL = billing.Plan(PlanTerms(PlanKind.TRIAL, credits=2, credit_expiry_days=14), 0)


def billable(plan: billing.Plan = MONTHLY, **fields: Any) -> billing.Billable:
    """Started Nov 15 with nothing paid, as `membership.start` leaves it."""
    started_on = fields.pop("started_on", date(2026, 11, 15))
    defaults: dict[str, Any] = {
        "status": MembershipStatus.ACTIVE,
        "current_period_end": started_on - timedelta(days=1),
        "anchor_day": started_on.day if plan.terms.kind is PlanKind.MONTHLY else None,
    }
    return billing.Billable(plan=plan, started_on=started_on, **{**defaults, **fields})


def spans(owed: billing.Billing) -> list[tuple[date, date, int]]:
    return [(p.period_start, p.period_end, p.amount_due_clp) for p in owed.periods]


def test_a_period_is_generated_seven_days_before_it_falls_due() -> None:
    assert billing.due_periods(billable(), date(2026, 11, 7)).periods == ()

    (period,) = billing.due_periods(billable(), NOV_8).periods

    assert (period.period_start, period.period_end) == (date(2026, 11, 15), date(2026, 12, 14))
    assert period.due_date == period.period_start
    assert period.amount_due_clp == 45_000


def test_monthly_owes_one_period_per_cycle_and_catches_up_missed_ones() -> None:
    owed = billing.due_periods(billable(billed_through=date(2026, 11, 14)), date(2027, 1, 7))

    assert spans(owed) == [
        (date(2026, 11, 15), date(2026, 12, 14), 45_000),
        (date(2026, 12, 15), date(2027, 1, 14), 45_000),
    ]


def test_a_first_anchor_bills_to_the_end_of_the_month_then_month_by_month() -> None:
    owed = billing.due_periods(billable(FIRST, anchor_day=1), date(2026, 11, 24))

    assert spans(owed) == [
        (date(2026, 11, 15), date(2026, 11, 30), 40_000),
        (date(2026, 12, 1), date(2026, 12, 31), 40_000),
    ]


def test_a_31st_anchor_clamps_in_short_months_and_comes_back() -> None:
    owed = billing.due_periods(billable(started_on=date(2027, 1, 31)), date(2027, 3, 24))

    assert [p.period_start for p in owed.periods] == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
    ]
    assert owed.periods[1].period_end == date(2027, 3, 30)


def test_prepaid_owes_one_charge_per_block() -> None:
    owed = billing.due_periods(billable(PREPAID), date(2027, 5, 1))

    assert spans(owed) == [(date(2026, 11, 15), date(2027, 5, 14), 240_000)]


@pytest.mark.parametrize(
    ("plan", "end"),
    [(CREDITS, date(2027, 1, 13)), (DROPIN, date(2026, 11, 15))],
)
def test_a_pack_or_a_dropin_is_one_charge_and_never_another(plan: billing.Plan, end: date) -> None:
    pack = billable(plan, current_period_end=date(2027, 1, 13))

    assert spans(billing.due_periods(pack, date(2027, 6, 1))) == [
        (date(2026, 11, 15), end, plan.price_clp)
    ]
    charged = replace(pack, billed_through=end)
    assert billing.due_periods(charged, date(2027, 6, 1)).periods == ()


def test_a_trial_is_never_charged() -> None:
    trial = billable(TRIAL, status=MembershipStatus.TRIAL)

    assert billing.due_periods(trial, date(2027, 1, 1)).periods == ()


@pytest.mark.parametrize(
    "status", [MembershipStatus.FROZEN, MembershipStatus.LAPSED, MembershipStatus.CANCELLED]
)
def test_only_an_active_membership_is_billed(status: MembershipStatus) -> None:
    assert billing.due_periods(billable(status=status), date(2027, 1, 1)).periods == ()


def test_billing_resumes_after_the_paid_through_date_when_it_is_later() -> None:
    # Unfrozen: the paid-through date moved past the latest period by the frozen days.
    shifted = billable(billed_through=date(2026, 12, 14), current_period_end=date(2026, 12, 24))

    (period,) = billing.due_periods(shifted, date(2026, 12, 18)).periods

    assert period.period_start == date(2026, 12, 25)


def test_the_discount_comes_off_in_whole_pesos() -> None:
    (period,) = billing.due_periods(billable(discount_pct=15), NOV_8).periods
    assert period.amount_due_clp == 38_250

    odd = billable(replace(MONTHLY, price_clp=45_001), discount_pct=33)
    (period,) = billing.due_periods(odd, NOV_8).periods
    assert period.amount_due_clp == 30_150  # 30150.67, rounded down
    assert isinstance(period.amount_due_clp, int)

    assert billing.discounted(45_000, 100) == 0


@pytest.mark.parametrize("pct", [-1, 101])
def test_a_discount_is_a_percentage(pct: int) -> None:
    with pytest.raises(ValueError, match="discount_pct"):
        billing.discounted(45_000, pct)


def test_a_plan_change_prices_its_first_period_and_moves_the_anchor_to_the_first() -> None:
    changing = billable(
        billed_through=date(2026, 11, 14),
        started_on=date(2026, 10, 15),
        next_plan=FIRST,
        next_plan_from=date(2026, 11, 15),
    )

    owed = billing.due_periods(changing, date(2026, 11, 24))

    assert spans(owed) == [
        (date(2026, 11, 15), date(2026, 11, 30), 40_000),
        (date(2026, 12, 1), date(2026, 12, 31), 40_000),
    ]
    assert owed.plan_changed
    assert owed.plan == FIRST
    assert owed.anchor_day == 1


def test_a_change_to_prepaid_clears_the_anchor() -> None:
    changing = billable(
        billed_through=date(2026, 11, 14),
        started_on=date(2026, 10, 15),
        next_plan=PREPAID,
        next_plan_from=date(2026, 11, 15),
    )

    owed = billing.due_periods(changing, NOV_8)

    assert spans(owed) == [(date(2026, 11, 15), date(2027, 5, 14), 240_000)]
    assert owed.plan_changed
    assert owed.anchor_day is None


def test_a_plan_change_waits_for_its_day() -> None:
    changing = billable(next_plan=FIRST, next_plan_from=date(2026, 12, 15))

    owed = billing.due_periods(changing, NOV_8)

    assert spans(owed) == [(date(2026, 11, 15), date(2026, 12, 14), 45_000)]
    assert not owed.plan_changed
    assert (owed.plan, owed.anchor_day) == (MONTHLY, 15)


# --- adjustments and refunds (#38) ------------------------------------------------


def test_an_adjustment_in_the_members_favour_settles_up_to_what_is_owed() -> None:
    settlement = billing.adjust(replace(period(), paid_clp=20_000), 10_000, "beca")

    assert settlement.entry == LedgerEntry(
        kind=EntryKind.ADJUSTMENT, amount_clp=10_000, status=EntryStatus.VALIDATED, note="beca"
    )
    assert settlement.period.closed
    assert settlement.credit is None
    with pytest.raises(InvalidTransition, match="exceeds"):
        billing.adjust(replace(period(), paid_clp=20_000), 10_001, "beca")


def test_an_adjustment_against_the_member_is_owed_on_top() -> None:
    paid = replace(period(), paid_clp=30_000, closed=True)
    settlement = billing.adjust(paid, -5_000, "matrícula")

    assert not settlement.period.closed
    assert settlement.period.outstanding_clp == 5_000
    unpaid = billing.adjust(period(), -5_000, "matrícula")
    assert unpaid.period.outstanding_clp == 35_000


def test_an_adjustment_needs_a_note() -> None:
    with pytest.raises(ValueError, match="note"):
        billing.adjust(period(), -5_000, "  ")


def validated(amount: int) -> LedgerEntry:
    return ledger.validate(payment(amount))


def test_a_refund_no_longer_counts_towards_the_period() -> None:
    paid = replace(period(), paid_clp=30_000, closed=True)
    settlement = billing.refund(paid, validated(30_000), 0, 10_000, "lesión")

    assert settlement.entry == LedgerEntry(
        kind=EntryKind.REFUND, amount_clp=10_000, status=EntryStatus.VALIDATED, note="lesión"
    )
    assert not settlement.period.closed
    assert settlement.period.outstanding_clp == 10_000


def test_a_refund_of_an_overpayment_leaves_the_period_closed() -> None:
    overpaid = replace(period(), paid_clp=35_000, closed=True)
    assert billing.refund(overpaid, validated(35_000), 0, 5_000, None).period.closed


def test_a_refund_gives_back_at_most_what_is_left_of_its_payment() -> None:
    paid = replace(period(), paid_clp=30_000, closed=True)
    assert billing.refund(paid, validated(30_000), 20_000, 10_000, None)
    with pytest.raises(InvalidTransition, match="exceeds"):
        billing.refund(paid, validated(30_000), 20_000, 10_001, None)


@pytest.mark.parametrize(
    "entry",
    [
        payment(30_000),
        ledger.reject(payment(30_000), "borroso"),
        LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=30_000, status=EntryStatus.VALIDATED),
    ],
    ids=["pending", "rejected", "adjustment"],
)
def test_only_a_validated_payment_is_refunded(entry: LedgerEntry) -> None:
    with pytest.raises(InvalidTransition, match="validated payment"):
        billing.refund(period(), entry, 0, 1_000, None)


def test_settled_amount_takes_a_refund_back() -> None:
    assert billing.settled_amount("e") == (
        "CASE WHEN e.kind = 'refund' THEN -e.amount_clp ELSE e.amount_clp END"
    )
    assert EntryKind.REFUND in billing.SETTLING_KINDS


# --- paying ahead (#196) ----------------------------------------------------------


def test_paying_ahead_bills_the_next_periods_after_the_last_one_billed() -> None:
    paid_up = billable(billed_through=date(2026, 12, 14), discount_pct=10)

    owed = billing.periods_ahead(paid_up, 3)

    assert spans(owed) == [
        (date(2026, 12, 15), date(2027, 1, 14), 40_500),
        (date(2027, 1, 15), date(2027, 2, 14), 40_500),
        (date(2027, 2, 15), date(2027, 3, 14), 40_500),
    ]
    assert not owed.plan_changed


def test_paying_ahead_bills_the_periods_the_nightly_job_would() -> None:
    paid_up = billable(billed_through=date(2026, 12, 14))
    ahead = billing.periods_ahead(paid_up, 2)

    later = billing.due_periods(paid_up, date(2027, 1, 8))

    assert ahead.periods == later.periods


def test_prepaid_pays_ahead_a_block_at_a_time() -> None:
    owed = billing.periods_ahead(billable(PREPAID, billed_through=date(2027, 5, 14)), 1)

    assert spans(owed) == [(date(2027, 5, 15), date(2027, 11, 14), 240_000)]


def test_paying_ahead_past_a_plan_change_prices_it_from_its_day() -> None:
    changing = billable(
        billed_through=date(2026, 11, 14),
        next_plan=FIRST,
        next_plan_from=date(2026, 12, 15),
    )

    owed = billing.periods_ahead(changing, 3)

    assert spans(owed) == [
        (date(2026, 11, 15), date(2026, 12, 14), 45_000),
        (date(2026, 12, 15), date(2026, 12, 31), 40_000),
        (date(2027, 1, 1), date(2027, 1, 31), 40_000),
    ]
    assert owed.plan_changed
    assert owed.anchor_day == 1


@pytest.mark.parametrize("plan", [CREDITS, DROPIN, TRIAL])
def test_only_a_monthly_or_prepaid_plan_pays_ahead(plan: billing.Plan) -> None:
    assert billing.periods_ahead(billable(plan), 1).periods == ()


@pytest.mark.parametrize(
    "status", [MembershipStatus.FROZEN, MembershipStatus.LAPSED, MembershipStatus.CANCELLED]
)
def test_only_an_active_membership_pays_ahead(status: MembershipStatus) -> None:
    assert billing.periods_ahead(billable(status=status), 1).periods == ()


@pytest.mark.parametrize("count", [0, billing.MAX_PAID_AHEAD + 1])
def test_paying_ahead_is_one_to_a_year_of_periods(count: int) -> None:
    with pytest.raises(ValueError):
        billing.periods_ahead(billable(), count)


NOV, DEC, JAN = (
    (date(2026, 11, 15), date(2026, 12, 14)),
    (date(2026, 12, 15), date(2027, 1, 14)),
    (date(2027, 1, 15), date(2027, 2, 14)),
)


@pytest.mark.parametrize(
    ("periods", "through"),
    [
        ([], None),
        ([(*NOV, 45_000)], None),
        ([(*NOV, 0)], NOV[1]),
        ([(*JAN, 0), (*NOV, 0), (*DEC, 0)], JAN[1]),
        ([(*NOV, 0), (*DEC, 5_000), (*JAN, 0)], NOV[1]),
    ],
    ids=["none", "first-owing", "paid", "unordered", "gap"],
)
def test_paid_through_is_the_end_of_the_last_period_with_none_owing_before_it(
    periods: list[tuple[date, date, int]], through: date | None
) -> None:
    assert billing.paid_through(periods) == through


def test_due_periods_stops_at_its_limit() -> None:
    owed = billing.due_periods(
        billable(billed_through=date(2026, 11, 14)), date(2027, 3, 7), limit=2
    )

    assert spans(owed) == [
        (date(2026, 11, 15), date(2026, 12, 14), 45_000),
        (date(2026, 12, 15), date(2027, 1, 14), 45_000),
    ]
