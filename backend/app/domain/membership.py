"""Membership state machine: trial, active, frozen, lapsed, cancelled.

A membership moves right as time passes and returns to Active only when a
payment is validated. A freeze is a side trip that shifts the due date by the
frozen days (`freeze`). Cancelled is terminal, and carries the reason it was
cancelled for.

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

# The longest freeze: a year, past which a date is more likely a typo than a plan.
MAX_FREEZE_DAYS = 365


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


# The statuses of a membership the member is on now.
LIVE = (S.TRIAL, S.ACTIVE, S.FROZEN)


def current_first(alias: str) -> str:
    """SQL `ORDER BY` terms that put a person's current membership first, of
    `membership` rows `alias` (#271): one they are on now, else one not cancelled, the
    latest created among them, then the latest started. Never by id, so two started on
    one day are not ordered by chance."""
    live = ", ".join(f"'{status.value}'" for status in LIVE)
    return (
        f"{alias}.status IN ({live}) DESC, {alias}.status = 'cancelled',"
        f" {alias}.created_at DESC, {alias}.started_at DESC"
    )


@dataclass(frozen=True)
class Membership:
    plan_kind: PlanKind
    status: MembershipStatus
    # Paid-through date; the pack expiry on a credits plan, the last free day on a trial.
    current_period_end: date | None = None
    # Credits left on a credits plan, free classes left on a trial.
    credits_remaining: int | None = None
    # A freeze's first day, and the day it ends, when the membership is Active again.
    frozen_since: date | None = None
    frozen_until: date | None = None
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


# The overdue email (#260): on the due date, the day after, then every this many days.
OVERDUE_EMAIL_EVERY_DAYS = 3


def is_overdue_email_day(days_overdue: int, grace: int) -> bool:
    """Whether a period this many days past its due date is emailed today: on the due
    date (0), the day after (1), then every `OVERDUE_EMAIL_EVERY_DAYS` (4, 7, 10, ...)
    while the grace lasts, the last day before the membership lapses
    (`app.domain.dates.is_past_grace`)."""
    if not 0 <= days_overdue <= grace:
        return False
    return days_overdue <= 1 or (days_overdue - 1) % OVERDUE_EMAIL_EVERY_DAYS == 0


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


def freeze_days(from_date: date, to_date: date) -> int:
    """The days a freeze from `from_date` until `to_date` lasts: one at least, and at
    most `MAX_FREEZE_DAYS`."""
    days = (to_date - from_date).days
    if days <= 0:
        raise ValueError("a freeze ends after the day it starts")
    if days > MAX_FREEZE_DAYS:
        raise ValueError(f"a freeze lasts at most {MAX_FREEZE_DAYS} days, not {days}")
    return days


def freeze(
    membership: Membership,
    from_date: date,
    to_date: date,
    *,
    billed_through: date | None = None,
) -> Membership:
    """Frozen from `from_date` until `to_date`, the day it is Active again.

    The days in between are not charged: the due date moves past them as the freeze
    starts, so a member reads the date they will next pay on all through it. The
    paid-through date moves by the frozen days, and a monthly plan's anchor day to the
    day after it, so later periods bill from there. A recurring membership resumes
    billing after the later of its paid-through date and `billed_through`, the end of
    its last billing period that started before `from_date`, so that is what moves.
    Periods starting on or after `from_date` move by the frozen days too
    (`app.api.memberships`), and keep their place after it.

    A credits pack's expiry moves the same way. Only an Active membership freezes.
    """
    _move(membership, S.FROZEN)
    days = freeze_days(from_date, to_date)
    end = membership.current_period_end
    if membership.plan_kind in RECURRING and billed_through is not None:
        end = billed_through if end is None else max(end, billed_through)
    anchor = membership.anchor_day
    if end is not None:
        end += timedelta(days=days)
        if anchor is not None:
            anchor = (end + timedelta(days=1)).day
    return replace(
        membership,
        status=S.FROZEN,
        current_period_end=end,
        anchor_day=anchor,
        frozen_since=from_date,
        frozen_until=to_date,
    )


def move_freeze_end(membership: Membership, to_date: date) -> Membership:
    """A running freeze that ends on `to_date` instead: earlier, as early as its first
    day, or later, up to `MAX_FREEZE_DAYS` after it.

    `freeze` moved the due date by the days it was to last, so it moves again by the
    difference: the paid-through date, a credits pack's expiry and a monthly plan's
    anchor day, which stays the day after it. The billing periods it moved, and a
    pending plan change, move by as many (`app.api.memberships`).
    """
    since, until = membership.frozen_since, membership.frozen_until
    if membership.status is not S.FROZEN or since is None or until is None:
        raise InvalidTransition(f"a {membership.status} membership has no freeze to move")
    days = (to_date - since).days
    if days < 0:
        raise ValueError("a freeze ends on the day it starts at the earliest")
    if days > MAX_FREEZE_DAYS:
        raise ValueError(f"a freeze lasts at most {MAX_FREEZE_DAYS} days, not {days}")
    shift = to_date - until
    end = membership.current_period_end
    anchor = membership.anchor_day
    if end is not None:
        end += shift
        if anchor is not None:
            anchor = (end + timedelta(days=1)).day
    return replace(membership, current_period_end=end, anchor_day=anchor, frozen_until=to_date)


def end_freeze(membership: Membership, today: date) -> Membership:
    """Active again `today`, before the freeze was to end: the due date moves back by
    the days it no longer lasts (`move_freeze_end`). A freeze whose end has come
    already ends as `unfreeze` would end it, the due date where it is."""
    if membership.frozen_until is None:
        raise InvalidTransition(f"a {membership.status} membership has no freeze to end")
    ended = move_freeze_end(membership, min(membership.frozen_until, today))
    return unfreeze(ended, today)


def is_due_to_unfreeze(membership: Membership, today: date) -> bool:
    """Whether the nightly job should return this frozen membership to Active on `today`."""
    until = membership.frozen_until
    return membership.status is S.FROZEN and until is not None and today >= until


def unfreeze(membership: Membership, on: date) -> Membership:
    """Back to Active on the day its freeze ends; `freeze` already moved the due date."""
    _move(membership, S.ACTIVE)
    if membership.frozen_until is None:
        raise InvalidTransition("frozen membership has no freeze end date")
    if not is_due_to_unfreeze(membership, on):
        raise InvalidTransition(f"membership is frozen until {membership.frozen_until}")
    return replace(membership, status=S.ACTIVE, frozen_since=None, frozen_until=None)


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
        # Only unfreeze() leaves Frozen, on the day the freeze ends.
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


# The reason a membership ended by its member leaving the gym carries (#157).
LEFT_REASON = "dado de baja"


def leave(membership: Membership) -> Membership:
    """The member left the gym: whatever their membership's state, it ends, a trial or a
    frozen one too, which `cancel` would refuse. A running freeze ends with it."""
    if membership.status is S.CANCELLED:
        raise InvalidTransition("membership: cancelled → cancelled")
    return replace(
        membership,
        status=S.CANCELLED,
        cancel_reason=LEFT_REASON,
        frozen_since=None,
        frozen_until=None,
    )
