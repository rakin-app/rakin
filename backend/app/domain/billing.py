"""Generating billing periods, and settling them against validated ledger entries.

The nightly job generates each period `GENERATE_AHEAD_DAYS` before it falls due, on
its first day (`due_periods`). A monthly membership owes one period per cycle, from
its anchor day to the day before the next; a prepaid one a block of `period_months`;
a credits pack (or a drop-in) a single charge for the whole of it; a trial nothing.
A fixed-period plan (#351) owes one period, its own dates the same for every member,
due on its first day or on the day the membership started if later, at the full
price; nothing after it, until a plan change moves the member to the next period's
plan.
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
counts towards the payment's period, which may open again (#38). A charge made by
mistake is voided (`void`): an adjustment of all the period still owes (#256). A
payment recorded by mistake is undone (`undo_payment`, #281): a refund of what is left
of it, which the reports count as a correction rather than money given back, and the
credit it carried, if any, reverted (`revert_credit`).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.domain import ledger
from app.domain import membership as memberships
from app.domain.dates import add_months
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry, Purpose
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

# The kinds a member pays ahead on (#196): a fixed-period plan has no next period.
PAID_AHEAD = frozenset({PlanKind.MONTHLY, PlanKind.PREPAID})


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


def void(period: BillingPeriod, reason: str) -> Settlement:
    """Void what `period` still owes, for a charge made by mistake (#256): an adjustment
    in the member's favour of all of it, validated as the admin makes it, with `reason`
    for its note. Nothing is owed on the period afterwards. The caller refuses a period
    with money on it first; the money is real, and is refunded before."""
    if not reason.strip():
        raise ValueError("a void needs a reason")
    if period.outstanding_clp == 0:
        raise InvalidTransition("the period owes nothing to void")
    entry = LedgerEntry(
        kind=EntryKind.ADJUSTMENT,
        amount_clp=period.outstanding_clp,
        status=EntryStatus.VALIDATED,
        note=reason.strip(),
        purpose=Purpose.VOID,
    )
    return _resettled(period, entry, entry.amount_clp)


def restore(period: BillingPeriod, voided_clp: int, reason: str) -> Settlement:
    """Put back on `period` the `voided_clp` a void took off it, for a charge voided by
    mistake (#278): an adjustment owed by the member of as much, validated as the admin
    makes it, with `reason` for its note. The period owes it again, as if the void had
    not happened. The caller names the void it restores, and refuses one restored."""
    if not reason.strip():
        raise ValueError("a restore needs a reason")
    if voided_clp <= 0:
        raise ValueError("a void takes a positive amount off its period")
    entry = LedgerEntry(
        kind=EntryKind.ADJUSTMENT,
        amount_clp=-voided_clp,
        status=EntryStatus.VALIDATED,
        note=reason.strip(),
        purpose=Purpose.RESTORE,
    )
    return _resettled(period, entry, entry.amount_clp)


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


def undo_payment(
    period: BillingPeriod, payment: LedgerEntry, given_back_clp: int, reason: str
) -> Settlement:
    """Undo `payment`, recorded on `period` by mistake (#281): a refund of all that is left
    of it after the `given_back_clp` its refunds took, validated as the admin makes it,
    with `reason` for its note. The period owes it again, as after a refund. Never a part
    of it: what is left is wrong as a whole, and the right amount is recorded anew."""
    if not reason.strip():
        raise ValueError("undoing a payment needs a reason")
    if payment.kind is not EntryKind.PAYMENT or payment.status is not EntryStatus.VALIDATED:
        raise InvalidTransition("only a validated payment is undone")
    left = payment.amount_clp - given_back_clp
    if left <= 0:
        raise InvalidTransition("nothing is left of the payment to undo")
    entry = LedgerEntry(
        kind=EntryKind.REFUND,
        amount_clp=left,
        status=EntryStatus.VALIDATED,
        note=reason.strip(),
        purpose=Purpose.MISTAKE,
    )
    return _resettled(period, entry, -left)


def revert_credit(credit_clp: int, reason: str) -> LedgerEntry:
    """The credit an overpayment carried (`apply`), taken back with the payment undone
    (#281): an adjustment of minus as much, on no period, as the credit is."""
    if credit_clp <= 0:
        raise ValueError("a carried credit is in the member's favour")
    return LedgerEntry(
        kind=EntryKind.ADJUSTMENT,
        amount_clp=-credit_clp,
        status=EntryStatus.VALIDATED,
        note=reason.strip(),
        purpose=Purpose.REVERT,
    )


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


def _period(
    plan: Plan, start: date, anchor_day: int | None, discount_pct: int
) -> BillingPeriod | None:
    """The period of `plan` billed from `start`, the first day not billed, priced less
    `discount_pct`; `None` for a fixed-period plan whose period ended before `start`."""
    amount = discounted(plan.price_clp, discount_pct)
    terms = plan.terms
    if terms.kind is PlanKind.FIXED_PERIOD:
        if terms.period_start is None or terms.period_end is None:
            raise ValueError("a fixed-period plan has period_start and period_end")
        if start > terms.period_end:
            return None
        due = max(terms.period_start, start)
        return BillingPeriod(terms.period_start, terms.period_end, amount, due_date=due)
    end = _period_end(plan, start, anchor_day)
    return BillingPeriod(start, end, amount_due_clp=amount, due_date=start)


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


def first_unbilled(billable: Billable) -> date | None:
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
        billable, lambda due, billed: due <= horizon and (limit is None or billed < limit)
    )


# How many periods a member may pay ahead at once (#196).
MAX_PAID_AHEAD = 12


def periods_ahead(billable: Billable, count: int) -> Billing:
    """The next `count` periods of an Active monthly or prepaid membership, after the
    last one billed, for a member paying ahead (#196): each priced, and a pending plan
    change applied, as the nightly job would when it reached it. None for any other."""
    if not 1 <= count <= MAX_PAID_AHEAD:
        raise ValueError(f"count must be 1..{MAX_PAID_AHEAD}, got {count}")
    if billable.plan.terms.kind not in PAID_AHEAD:
        return Billing((), plan_changed=False, plan=billable.plan, anchor_day=billable.anchor_day)
    return _billing(billable, lambda _, billed: billed < count)


def _billing(billable: Billable, more: Callable[[date, int], bool]) -> Billing:
    """The periods `billable` owes from the first day not billed, oldest first, while
    `more(due date, periods so far)` says another falling due then is billed."""
    plan, anchor_day = billable.plan, billable.anchor_day
    unchanged = Billing((), plan_changed=False, plan=plan, anchor_day=anchor_day)
    if billable.status is not MembershipStatus.ACTIVE or plan.terms.kind is PlanKind.TRIAL:
        return unchanged
    start = first_unbilled(billable)
    pending, pending_from = billable.next_plan, billable.next_plan_from
    changed = False
    # A monthly row from before anchor days were stored bills on the day it resumes.
    fallback_anchor = start.day if start is not None else None
    periods: list[BillingPeriod] = []
    while start is not None:
        # The plan change applies with the period it reaches, not before.
        bill_plan, bill_anchor = plan, anchor_day
        changing = pending is not None and pending_from is not None and start >= pending_from
        if changing:
            assert pending is not None and pending_from is not None
            bill_plan, bill_anchor = pending, changed_anchor(pending, pending_from)
        period = _period(bill_plan, start, bill_anchor or fallback_anchor, billable.discount_pct)
        if period is None or not more(period.due_date, len(periods)):
            break
        if changing:
            plan, anchor_day, pending, changed = bill_plan, bill_anchor, None, True
        periods.append(period)
        start = period.period_end + timedelta(days=1)
        if plan.terms.kind in SINGLE_CHARGE:
            start = None
    return Billing(tuple(periods), plan_changed=changed, plan=plan, anchor_day=anchor_day)


def changed_anchor(plan: Plan, starts_on: date) -> int | None:
    """The anchor day of a membership changing to `plan` from `starts_on`."""
    if plan.terms.kind not in memberships.RECURRING:
        raise ValueError(f"a plan change moves to a monthly or prepaid plan, not {plan}")
    return memberships.anchor_day(plan.terms, starts_on)


def first_period_after_change(plan: Plan, starts_on: date, discount_pct: int = 0) -> BillingPeriod:
    """The first period a change to `plan` from `starts_on` bills, as the nightly job
    will when it reaches that day: for the ficha to say so before it is saved (#249)."""
    period = _period(plan, starts_on, changed_anchor(plan, starts_on), discount_pct)
    if period is None:
        raise ValueError(f"the plan's period ended before {starts_on}")
    return period


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
