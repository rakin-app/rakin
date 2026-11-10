"""What an attendance takes from a membership, and what unmarking it gives back.

A credits pack pays for each class with the class type's `credit_cost` (0 for a free
class), and a trial's free classes are its credits too (`PlanTerms`): a class is one
of them, whatever it costs. Every other plan has no credits to spend.

An attendance never refuses a member: lapsed or overdue, they can still train, and the
roster only flags it (docs/technical.md#core-state-machines). So it takes what is
there, up to the cost, and only from a Trial or Active membership; a member whose pack
is spent, or who is Lapsed or Frozen, attends for nothing. It does not lapse a pack at
zero itself: the nightly `lapse` job does (`is_due_to_lapse`), so a mistaken mark
unmarked the same day leaves the membership as it was.
"""

from app.domain.membership import Membership, MembershipStatus, PlanKind

SPENDS = frozenset({MembershipStatus.TRIAL, MembershipStatus.ACTIVE})


def credits_to_consume(membership: Membership, credit_cost: int) -> int:
    """The credits marking `membership` present at a class costing `credit_cost` takes."""
    if credit_cost < 0:
        raise ValueError(f"a class costs no fewer than 0 credits, not {credit_cost}")
    remaining = membership.credits_remaining
    if remaining is None or membership.status not in SPENDS:
        return 0
    if membership.plan_kind is PlanKind.TRIAL:
        cost = 1
    elif membership.plan_kind is PlanKind.CREDITS:
        cost = credit_cost
    else:
        return 0
    return min(cost, remaining)
