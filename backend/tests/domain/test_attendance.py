"""What an attendance takes from a membership (`app.domain.attendance`)."""

import pytest

from app.domain.attendance import credits_to_consume
from app.domain.membership import Membership, MembershipStatus, PlanKind

K = PlanKind
S = MembershipStatus


def membership(kind: PlanKind, status: MembershipStatus, credits: int | None) -> Membership:
    return Membership(kind, status, credits_remaining=credits)


@pytest.mark.parametrize(
    ("kind", "status", "credits", "cost", "taken"),
    [
        (K.CREDITS, S.ACTIVE, 12, 1, 1),
        (K.CREDITS, S.ACTIVE, 12, 2, 2),
        (K.CREDITS, S.ACTIVE, 12, 0, 0),  # a free class
        (K.CREDITS, S.ACTIVE, 1, 2, 1),  # what is left, never below zero
        (K.CREDITS, S.ACTIVE, 0, 1, 0),  # spent: trains, pays nothing
        (K.CREDITS, S.LAPSED, 4, 1, 0),
        (K.CREDITS, S.FROZEN, 4, 1, 0),
        (K.TRIAL, S.TRIAL, 2, 3, 1),  # a free class is a class, whatever it costs
        (K.TRIAL, S.TRIAL, 2, 0, 1),
        (K.TRIAL, S.TRIAL, None, 1, 0),  # a trial of days alone
        (K.MONTHLY, S.ACTIVE, None, 1, 0),
        (K.PREPAID, S.ACTIVE, None, 2, 0),
    ],
)
def test_credits_to_consume(
    kind: PlanKind, status: MembershipStatus, credits: int | None, cost: int, taken: int
) -> None:
    assert credits_to_consume(membership(kind, status, credits), cost) == taken


def test_a_negative_cost_is_refused() -> None:
    with pytest.raises(ValueError):
        credits_to_consume(membership(K.CREDITS, S.ACTIVE, 4), -1)
