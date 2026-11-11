"""Generating billing periods, and settling them against validated ledger entries.

The nightly job generates each period `GENERATE_AHEAD_DAYS` before it falls due, on
its first day (`due_periods`). A monthly membership owes one period per cycle, from
its anchor day to the day before the next; a prepaid one a block of `period_months`;
a credits pack (or a drop-in) a single charge for the whole of it; a trial nothing.
Each is priced at the plan's price less the membership's discount, in whole pesos.
A pending plan change prices the first period starting on or after its day at the new
plan, which becomes the membership's plan from then on. A member paying ahead is
billed the next periods on the spot (`periods_ahead`, #196), the same periods the job
would write later, which it then finds already there.

A period closes once validated payments (and credit carried in from an earlier
overpayment) cover its amount due. Whatever is paid beyond that becomes a credit
adjustment to apply against the next period. A rejected proof never reaches a
period, so the period stays open.

An admin corrects a period with an adjustment on it (`adjust`): one in the member's
favour counts towards it as a payment does, one against them is owed on top of its
amount due. A refund gives back part or all of a payment (`refund`) and no longer
counts towards the payment's period, which may open again (#38).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.domain import ledger
from app.domain import membership as memberships
from app.domain.dates import add_months
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.membership import MembershipStatus, PlanKind, PlanTerms
from app.domain.money import format_clp

# The kinds whose validated entries count towards their period: a refund counts against.
SETTLING_KINDS = frozenset({EntryKind.PAYMENT, EntryKind.ADJUSTMENT, EntryKind.REFUND})

# The kinds `apply` settles a period with.
PAYING_KINDS = frozenset({EntryKind.PAYMENT, EntryKind.ADJUSTMENT})


def settled_amount(alias: str) -> str:
    """What the `ledger_entry` row `alias` counts towards its period, in SQL, for a row of
    `SETTLING_KINDS`: its amount, which an adjustment signs, or a refund's taken back.
    Migration 0021's `v_overdue` repeats it."""
    return f"CASE WHEN {alias}.kind = 'refund' THEN -{alias}.amount_clp ELSE {alias}.amount_clp END"


# A period is generated this many days before it falls due (docs/technical.md).
GENERATE_AHEAD_DAYS = 7

# The kinds charged once, for the whole of what was bought.
SINGLE_CHARGE = frozenset({PlanKind.CREDITS, PlanKind.DROPIN})


@dataclass(frozen=True)
class BillingPeriod:
    period_start: date
    period_end: date
    amount_due_clp: int
    due_date: date
    # What its settling entries add up to: below zero once an adjustment against the
    # member outweighs what was paid, above `amount_due_clp` once overpaid.
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
    if entry.kind not in PAYING_KINDS:
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


def _resettled(period: BillingPeriod, entry: LedgerEntry, counts: int) -> Settlement:
    """`period` once `entry`, counting `counts` towards it, is in the ledger."""
    paid = period.paid_clp + counts
    return Settlement(
        period=replace(
            period, paid_clp=min(paid, period.amount_due_clp), closed=paid >= period.amount_due_clp
        ),
        entry=entry,
    )


def adjust(period: BillingPeriod, amount_clp: int, note: str) -> Settlement:
    """An admin's adjustment to `period`, validated as they make it: `amount_clp` in the
    member's favour if positive, owed if negative, and `note` saying why.

    One in the member's favour settles no more than the period still owes; credit is a
    payment's to carry, not an adjustment's.
    """
    if not note.strip():
        raise ValueError("an adjustment needs a note saying why")
    if amount_clp > period.outstanding_clp:
        raise InvalidTransition("an adjustment in the member's favour exceeds what is owed")
    entry = LedgerEntry(
        kind=EntryKind.ADJUSTMENT, amount_clp=amount_clp, status=EntryStatus.VALIDATED, note=note
    )
    return _resettled(period, entry, amount_clp)


def refund(
    period: BillingPeriod,
    payment: LedgerEntry,
    refunded_clp: int,
    amount_clp: int,
    note: str | None,
) -> Settlement:
    """Give back `amount_clp` of `payment`, which paid `period` and of which `refunded_clp`
    was given back already: at most what is left of it. It no longer counts towards
    `period`."""
    if payment.kind is not EntryKind.PAYMENT or payment.status is not EntryStatus.VALIDATED:
        raise InvalidTransition("only a validated payment is refunded")
    if amount_clp > payment.amount_clp - refunded_clp:
        raise InvalidTransition("a refund exceeds what is left of its payment")
    entry = LedgerEntry(
        kind=EntryKind.REFUND, amount_clp=amount_clp, status=EntryStatus.VALIDATED, note=note
    )
    return _resettled(period, entry, -amount_clp)


def validate_payment(period: BillingPeriod, entry: LedgerEntry) -> Settlement:
    """Validate a pending payment against `period`."""
    if entry.kind is not EntryKind.PAYMENT:
        raise InvalidTransition(f"a {entry.kind} entry is not a payment")
    if period.closed:
        raise InvalidTransition("billing period is already closed")
    return apply(period, ledger.validate(entry))


@dataclass(frozen=True)
class Plan:
    """What billing reads from a `plan` row."""

    terms: PlanTerms
    price_clp: int
    # A prepaid plan's block length.
    period_months: int | None = None


@dataclass(frozen=True)
class Billable:
    """A membership as billing sees it."""

    plan: Plan
    status: MembershipStatus
    # The calendar day it started, in the gym's timezone.
    started_on: date
    current_period_end: date | None = None
    # The latest billing period's end; `None` before the first one.
    billed_through: date | None = None
    anchor_day: int | None = None
    discount_pct: int = 0
    # A pending plan change: the plan, and the first day it applies (migration 0009).
    next_plan: Plan | None = None
    next_plan_from: date | None = None


@dataclass(frozen=True)
class Billing:
    """The periods a membership owes, and its plan and anchor day after them."""

    periods: tuple[BillingPeriod, ...]
    # True when the pending plan change was applied: `plan` and `anchor_day` replace
    # the membership's own, and the change is no longer pending.
    plan_changed: bool
    plan: Plan
    anchor_day: int | None


def discounted(price_clp: int, discount_pct: int) -> int:
    """`price_clp` less `discount_pct` percent, rounded down to a whole peso."""
    if not 0 <= discount_pct <= 100:
        raise ValueError(f"discount_pct must be 0..100, got {discount_pct}")
    return price_clp * (100 - discount_pct) // 100


def _next_anchor(after: date, anchor_day: int) -> date:
    """The first date after `after` on `anchor_day` (clamped to the end of a short month)."""
    same_month = add_months(after, 0, anchor_day=anchor_day)
    return same_month if same_month > after else add_months(after, 1, anchor_day=anchor_day)


def _period_end(plan: Plan, start: date, anchor_day: int | None) -> date:
    kind = plan.terms.kind
    if kind is PlanKind.MONTHLY:
        return _next_anchor(start, anchor_day or start.day) - timedelta(days=1)
    if kind is PlanKind.PREPAID:
        if plan.period_months is None:
            raise ValueError("a prepaid plan has period_months")
        return add_months(start, plan.period_months) - timedelta(days=1)
    if kind is PlanKind.CREDITS:
        days = plan.terms.credit_expiry_days
        if days is None:
            raise ValueError("a credits plan has credit_expiry_days")
        return start + timedelta(days=days - 1)
    if kind is PlanKind.DROPIN:
        return start
    raise ValueError(f"a {kind} plan is not billed")


def _first_unbilled(billable: Billable) -> date | None:
    """The first day the membership has not been billed for, or `None` if it never
    will be again: a single charge already made."""
    if billable.plan.terms.kind in SINGLE_CHARGE:
        return billable.started_on if billable.billed_through is None else None
    ends = [d for d in (billable.current_period_end, billable.billed_through) if d is not None]
    return max(ends) + timedelta(days=1) if ends else billable.started_on


def due_periods(
    billable: Billable,
    today: date,
    *,
    ahead: int = GENERATE_AHEAD_DAYS,
    limit: int | None = None,
) -> Billing:
    """Every period `billable` owes that falls due by `today + ahead`, oldest first;
    the first `limit` of them, if given.

    Only an Active membership is billed: a trial is free, a frozen one waits for its
    due date to shift, and a lapsed or cancelled one is not charged further. A period
    falls due on its first day, so a run after downtime catches up every period
    missed, one per cycle.
    """
    horizon = today + timedelta(days=ahead)
    return _billing(
        billable, lambda start, billed: start <= horizon and (limit is None or billed < limit)
    )


# How many periods a member may pay ahead at once (#196).
MAX_PAID_AHEAD = 12


def periods_ahead(billable: Billable, count: int) -> Billing:
    """The next `count` periods of an Active monthly or prepaid membership, after the
    last one billed, for a member paying ahead (#196): each priced, and a pending plan
    change applied, as the nightly job would when it reached it. None for any other."""
    if not 1 <= count <= MAX_PAID_AHEAD:
        raise ValueError(f"count must be 1..{MAX_PAID_AHEAD}, got {count}")
    if billable.plan.terms.kind not in memberships.RECURRING:
        return Billing((), plan_changed=False, plan=billable.plan, anchor_day=billable.anchor_day)
    return _billing(billable, lambda _, billed: billed < count)


def _billing(billable: Billable, more: Callable[[date, int], bool]) -> Billing:
    """The periods `billable` owes from the first day not billed, oldest first, while
    `more(start, periods so far)` says another starting on `start` is billed."""
    plan, anchor_day = billable.plan, billable.anchor_day
    unchanged = Billing((), plan_changed=False, plan=plan, anchor_day=anchor_day)
    if billable.status is not MembershipStatus.ACTIVE or plan.terms.kind is PlanKind.TRIAL:
        return unchanged
    start = _first_unbilled(billable)
    pending, pending_from = billable.next_plan, billable.next_plan_from
    changed = False
    # A monthly row from before anchor days were stored bills on the day it resumes.
    fallback_anchor = start.day if start is not None else None
    periods: list[BillingPeriod] = []
    while start is not None and more(start, len(periods)):
        if pending is not None and pending_from is not None and start >= pending_from:
            if pending.terms.kind not in memberships.RECURRING:
                raise ValueError(f"a plan change moves to a monthly or prepaid plan, not {pending}")
            plan, anchor_day = pending, memberships.anchor_day(pending.terms, pending_from)
            pending, changed = None, True
        end = _period_end(plan, start, anchor_day or fallback_anchor)
        amount = discounted(plan.price_clp, billable.discount_pct)
        periods.append(BillingPeriod(start, end, amount_due_clp=amount, due_date=start))
        start = end + timedelta(days=1) if plan.terms.kind not in SINGLE_CHARGE else None
    return Billing(tuple(periods), plan_changed=changed, plan=plan, anchor_day=anchor_day)


def paid_through(periods: Iterable[tuple[date, date, int]]) -> date | None:
    """The last day a membership's periods, as `(start, end, outstanding)`, are paid
    through: the end of the latest one with every one before it settled. `None` with
    no period, or with the first one still owing ("Pagado hasta", #196)."""
    through = None
    for _, end, outstanding in sorted(periods):
        if outstanding > 0:
            break
        through = end
    return through
