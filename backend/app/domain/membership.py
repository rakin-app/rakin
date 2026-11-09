"""Membership state machine: trial, active, frozen, lapsed, cancelled.

A membership moves right as time passes and returns to Active only when a
payment is validated. A freeze is a side trip that shifts the due date by the
frozen days. Cancelled is terminal, and carries the reason it was cancelled for.

A plan change waits for the next period: the periods already billed keep the plan
they were billed on, and the new one applies from the first period not yet billed
(`plan_change_starts`). Proration is v2.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum

from app.domain.dates import is_past_grace
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry

DEFAULT_GRACE_DAYS = 5


class PlanKind(StrEnum):
    MONTHLY = "monthly"
    PREPAID = "prepaid"
    CREDITS = "credits"
    DROPIN = "dropin"
    TRIAL = "trial"


class MembershipStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    FROZEN = "frozen"
    LAPSED = "lapsed"
    CANCELLED = "cancelled"


S = MembershipStatus
TRANSITIONS: dict[MembershipStatus, frozenset[MembershipStatus]] = {
    S.TRIAL: frozenset({S.ACTIVE, S.LAPSED}),
    S.ACTIVE: frozenset({S.FROZEN, S.LAPSED, S.CANCELLED}),
    S.FROZEN: frozenset({S.ACTIVE}),
    S.LAPSED: frozenset({S.ACTIVE, S.CANCELLED}),
    S.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class Membership:
    plan_kind: PlanKind
    status: MembershipStatus
    # Paid-through date; the pack expiry on a credits plan, the last free day on a trial.
    current_period_end: date | None = None
    # Credits left on a credits plan, free classes left on a trial.
    credits_remaining: int | None = None
    frozen_since: date | None = None
    # The day of the month a monthly plan bills on; `None` on every other kind.
    anchor_day: int | None = None
    cancel_reason: str | None = None


@dataclass(frozen=True)
class PlanTerms:
    """What a membership takes from its plan, as the `plan` columns hold it: a trial's
    free classes and free days are `credits` and `credit_expiry_days` (migration 0007)."""

    kind: PlanKind
    # A monthly plan's `signup` or `first`.
    anchor: str | None = None
    credits: int | None = None
    credit_expiry_days: int | None = None


# The kinds billed period after period, which a plan change can move between.
RECURRING = frozenset({PlanKind.MONTHLY, PlanKind.PREPAID})


def grace_days(gym_settings: Mapping[str, object]) -> int:
    """The gym's grace period, from `gym.settings["grace_days"]`."""
    value = gym_settings.get("grace_days", DEFAULT_GRACE_DAYS)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"grace_days must be a non-negative integer, got {value!r}")
    return value


def _move(membership: Membership, to: MembershipStatus) -> None:
    if to not in TRANSITIONS[membership.status]:
        raise InvalidTransition(f"membership: {membership.status} → {to}")


def create(
    plan_kind: PlanKind,
    *,
    current_period_end: date | None = None,
    credits_remaining: int | None = None,
) -> Membership:
    """A trial plan starts in Trial, every paid plan in Active."""
    if plan_kind is PlanKind.DROPIN:
        raise ValueError("a drop-in is a single attendance, not a membership")
    status = S.TRIAL if plan_kind is PlanKind.TRIAL else S.ACTIVE
    return Membership(plan_kind, status, current_period_end, credits_remaining)


def anchor_day(terms: PlanTerms, period_start: date) -> int | None:
    """The day of the month a membership on `terms` bills on, from `period_start`: that
    day on a `signup` anchor, the 1st on a `first` one, none off a monthly plan."""
    if terms.kind is not PlanKind.MONTHLY:
        return None
    return 1 if terms.anchor == "first" else period_start.day


def start(terms: PlanTerms, started_on: date) -> Membership:
    """A membership on `terms` from `started_on`, a calendar date in the gym's timezone.

    A monthly or prepaid membership starts with nothing paid: paid through the day
    before it starts, so its first period falls due on the start date. A credits pack
    or a trial starts with what it allows: its credits or free classes, and the last
    day it lasts as `current_period_end` (none for a trial limited by classes alone).
    """
    if terms.kind in (PlanKind.CREDITS, PlanKind.TRIAL):
        days = terms.credit_expiry_days
        last_day = None if days is None else started_on + timedelta(days=days - 1)
        return create(terms.kind, current_period_end=last_day, credits_remaining=terms.credits)
    membership = create(terms.kind, current_period_end=started_on - timedelta(days=1))
    return replace(membership, anchor_day=anchor_day(terms, started_on))


def imported(terms: PlanTerms, started_on: date, due_on: date | None) -> Membership:
    """A membership brought over from the gym's own records, already under way.

    A monthly or prepaid one is paid through the day before `due_on`, the day its next
    payment falls due, which it bills on from then: a monthly one's anchor day is
    `due_on`'s (the 1st on a `first` anchor). A credits pack or a trial starts as
    `start` would on `started_on`, lasting through `due_on` when given.
    """
    if terms.kind in RECURRING:
        if due_on is None:
            raise ValueError("an imported monthly or prepaid membership needs its due date")
        membership = create(terms.kind, current_period_end=due_on - timedelta(days=1))
        return replace(membership, anchor_day=anchor_day(terms, due_on))
    membership = start(terms, started_on)
    if due_on is not None:
        membership = replace(membership, current_period_end=due_on)
    return membership


def plan_change_starts(
    membership: Membership, to: PlanKind, *, billed_through: date | None = None
) -> date:
    """The day a change to a plan of kind `to` takes effect: the first day not yet paid
    for, or past the last billed period's end (`billed_through`), whichever is later.

    Only a recurring membership changes plan, and only to another recurring plan: a
    pack or a trial ends, and the member starts a new membership (or a trial converts,
    on payment). A cancelled membership changes nothing.
    """
    if membership.status is S.CANCELLED:
        raise InvalidTransition("a cancelled membership cannot change plan")
    if membership.plan_kind not in RECURRING or to not in RECURRING:
        raise ValueError(
            f"only a monthly or prepaid membership changes plan, to a monthly or prepaid"
            f" plan, not {membership.plan_kind} to {to}"
        )
    if membership.current_period_end is None:
        raise ValueError("a recurring membership has a paid-through date")
    last = membership.current_period_end
    if billed_through is not None and billed_through > last:
        last = billed_through
    return last + timedelta(days=1)


def freeze(membership: Membership, on: date) -> Membership:
    _move(membership, S.FROZEN)
    return replace(membership, status=S.FROZEN, frozen_since=on)


def unfreeze(membership: Membership, on: date) -> Membership:
    """Back to Active, with the due date shifted by the days spent frozen."""
    _move(membership, S.ACTIVE)
    if membership.frozen_since is None:
        raise InvalidTransition("frozen membership has no freeze start date")
    if on < membership.frozen_since:
        raise ValueError("cannot unfreeze before the freeze started")
    period_end = membership.current_period_end
    if period_end is not None:
        period_end += on - membership.frozen_since
    return replace(membership, status=S.ACTIVE, current_period_end=period_end, frozen_since=None)


def is_due_to_lapse(membership: Membership, today: date, grace: int = DEFAULT_GRACE_DAYS) -> bool:
    """Whether the nightly job should flip this membership to Lapsed on `today`.

    A credits pack or a trial lapses with no grace, the day after its last day or at
    zero credits. A recurring one is next due the day after it is paid through, and
    lapses once that due date is past the grace (`app.domain.dates.is_past_grace`).
    """
    end = membership.current_period_end
    if membership.status is S.TRIAL or membership.plan_kind is PlanKind.CREDITS:
        if membership.status not in (S.TRIAL, S.ACTIVE):
            return False
        out_of_credits = membership.credits_remaining == 0
        expired = end is not None and today > end
        return out_of_credits or expired
    if membership.status is S.ACTIVE:
        return end is not None and is_past_grace(end + timedelta(days=1), grace, today)
    return False


def lapse(membership: Membership, today: date, grace: int = DEFAULT_GRACE_DAYS) -> Membership:
    _move(membership, S.LAPSED)
    if not is_due_to_lapse(membership, today, grace):
        raise InvalidTransition(f"membership is not due to lapse on {today}")
    return replace(membership, status=S.LAPSED)


def consume_credits(membership: Membership, credits: int = 1) -> Membership:
    """Spend credits on an attendance; at zero the membership lapses."""
    if membership.credits_remaining is None:
        raise ValueError("this membership has no credits to consume")
    if membership.status not in (S.TRIAL, S.ACTIVE):
        raise InvalidTransition(f"a {membership.status} membership cannot consume credits")
    if not 0 < credits <= membership.credits_remaining:
        raise ValueError(f"cannot consume {credits} of {membership.credits_remaining} credits")
    remaining = membership.credits_remaining - credits
    status = S.LAPSED if remaining == 0 else membership.status
    return replace(membership, status=status, credits_remaining=remaining)


def record_payment(
    membership: Membership,
    payment: LedgerEntry,
    *,
    paid_through: date,
    credits: int | None = None,
) -> Membership:
    """A validated payment: Trial converts, Lapsed comes back, Active extends.

    `credits` refills a pack: a credits plan needs it, since a pack at zero would
    lapse again at once. Elsewhere, omit it to keep the current balance. An
    Active membership's due date only ever moves forward.
    """
    if payment.kind is not EntryKind.PAYMENT or payment.status is not EntryStatus.VALIDATED:
        raise InvalidTransition(
            f"only a validated payment activates a membership, not a {payment.status} "
            f"{payment.kind}"
        )
    if membership.plan_kind is PlanKind.CREDITS and (credits is None or credits <= 0):
        raise ValueError("a credits plan payment must top up the pack with credits")
    end = membership.current_period_end
    if membership.status is S.ACTIVE and end is not None and paid_through <= end:
        raise ValueError(f"paid_through {paid_through} does not extend the due date {end}")
    if membership.status is S.FROZEN:
        # Only unfreeze() leaves Frozen: it is what shifts the due date.
        raise InvalidTransition("a frozen membership must be unfrozen before it is paid")
    if membership.status is not S.ACTIVE:
        _move(membership, S.ACTIVE)
    return replace(
        membership,
        status=S.ACTIVE,
        current_period_end=paid_through,
        credits_remaining=membership.credits_remaining if credits is None else credits,
    )


def cancel(membership: Membership, reason: str) -> Membership:
    """Terminal: a cancelled membership never moves again. `reason` is required."""
    _move(membership, S.CANCELLED)
    if not reason.strip():
        raise ValueError("a cancellation needs a reason")
    return replace(membership, status=S.CANCELLED, cancel_reason=reason.strip())
