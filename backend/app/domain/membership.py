"""Membership state machine: trial, active, frozen, lapsed, cancelled.

A membership moves right as time passes and returns to Active only when a
payment is validated. A freeze is a side trip that shifts the due date by the
frozen days. Cancelled is terminal.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum

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


def freeze(membership: Membership, on: date) -> Membership:
    _move(membership, S.FROZEN)
    return replace(membership, status=S.FROZEN, frozen_since=on)


def unfreeze(membership: Membership, on: date) -> Membership:
    """Back to Active, with the due date shifted by the days spent frozen."""
    _move(membership, S.ACTIVE)
    assert membership.frozen_since is not None
    if on < membership.frozen_since:
        raise ValueError("cannot unfreeze before the freeze started")
    period_end = membership.current_period_end
    if period_end is not None:
        period_end += on - membership.frozen_since
    return replace(membership, status=S.ACTIVE, current_period_end=period_end, frozen_since=None)


def is_due_to_lapse(membership: Membership, today: date, grace: int = DEFAULT_GRACE_DAYS) -> bool:
    """Whether the nightly job should flip this membership to Lapsed today."""
    end = membership.current_period_end
    if membership.status is S.TRIAL or membership.plan_kind is PlanKind.CREDITS:
        if membership.status not in (S.TRIAL, S.ACTIVE):
            return False
        out_of_credits = membership.credits_remaining == 0
        expired = end is not None and today > end
        return out_of_credits or expired
    if membership.status is S.ACTIVE:
        return end is not None and today > end + timedelta(days=grace)
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

    `credits` refills a credits pack; omit it to keep the current balance.
    """
    if payment.kind is not EntryKind.PAYMENT or payment.status is not EntryStatus.VALIDATED:
        raise InvalidTransition(
            f"only a validated payment activates a membership, not a {payment.status} "
            f"{payment.kind}"
        )
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


def cancel(membership: Membership) -> Membership:
    _move(membership, S.CANCELLED)
    return replace(membership, status=S.CANCELLED)
