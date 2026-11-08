from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from itertools import product

import pytest

from app.domain import membership as m
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.membership import Membership, MembershipStatus, PlanKind

S = MembershipStatus
NOV_30 = date(2026, 11, 30)
VALIDATED_PAYMENT = LedgerEntry(EntryKind.PAYMENT, 30_000, EntryStatus.VALIDATED)


def monthly(status: MembershipStatus = S.ACTIVE, **fields: object) -> Membership:
    base = Membership(PlanKind.MONTHLY, status, current_period_end=NOV_30)
    return replace(base, **fields)  # type: ignore[arg-type]


def credits_pack(remaining: int = 10, expires: date = NOV_30) -> Membership:
    return m.create(PlanKind.CREDITS, current_period_end=expires, credits_remaining=remaining)


# --- the diagram ------------------------------------------------------------------------


def test_transitions_match_the_diagram() -> None:
    expected = {
        S.TRIAL: {S.ACTIVE, S.LAPSED},
        S.ACTIVE: {S.FROZEN, S.LAPSED, S.CANCELLED},
        S.FROZEN: {S.ACTIVE},
        S.LAPSED: {S.ACTIVE, S.CANCELLED},
        S.CANCELLED: set(),
    }

    assert expected == m.TRANSITIONS


@pytest.mark.parametrize(
    ("plan", "status"),
    [
        (PlanKind.TRIAL, S.TRIAL),
        (PlanKind.MONTHLY, S.ACTIVE),
        (PlanKind.PREPAID, S.ACTIVE),
        (PlanKind.CREDITS, S.ACTIVE),
    ],
)
def test_initial_status_follows_the_plan(plan: PlanKind, status: MembershipStatus) -> None:
    assert m.create(plan).status is status


def test_a_dropin_is_not_a_membership() -> None:
    with pytest.raises(ValueError, match="drop-in"):
        m.create(PlanKind.DROPIN)


# Every action, keyed by the status it leads to, so each invalid source can be tried.
ACTIONS: dict[MembershipStatus, Callable[[Membership], Membership]] = {
    S.FROZEN: lambda ms: m.freeze(ms, NOV_30),
    S.CANCELLED: m.cancel,
    S.ACTIVE: lambda ms: m.record_payment(ms, VALIDATED_PAYMENT, paid_through=NOV_30),
    S.LAPSED: lambda ms: m.lapse(ms, NOV_30 + timedelta(days=60)),
}

INVALID = [
    (source, target)
    for source, target in product(S, ACTIONS)
    if target not in m.TRANSITIONS[source]
    # Paying while Active extends the period rather than changing state.
    and (source, target) != (S.ACTIVE, S.ACTIVE)
]


@pytest.mark.parametrize(("source", "target"), INVALID)
def test_invalid_transitions_raise(source: MembershipStatus, target: MembershipStatus) -> None:
    ms = monthly(source, frozen_since=NOV_30 if source is S.FROZEN else None)

    with pytest.raises(InvalidTransition):
        ACTIONS[target](ms)


def test_cancelled_is_terminal() -> None:
    cancelled = m.cancel(monthly())

    for action in ACTIONS.values():
        with pytest.raises(InvalidTransition):
            action(cancelled)
    with pytest.raises(InvalidTransition):
        m.unfreeze(cancelled, NOV_30)


@pytest.mark.parametrize("source", [S.ACTIVE, S.LAPSED])
def test_active_and_lapsed_can_be_cancelled(source: MembershipStatus) -> None:
    assert m.cancel(monthly(source)).status is S.CANCELLED


# --- payments ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", [S.TRIAL, S.LAPSED, S.ACTIVE])
def test_a_validated_payment_activates(source: MembershipStatus) -> None:
    paid = m.record_payment(monthly(source), VALIDATED_PAYMENT, paid_through=date(2026, 12, 31))

    assert paid.status is S.ACTIVE
    assert paid.current_period_end == date(2026, 12, 31)


@pytest.mark.parametrize(
    "entry",
    [
        LedgerEntry(EntryKind.PAYMENT, 30_000),
        LedgerEntry(EntryKind.PAYMENT, 30_000, EntryStatus.REJECTED, note="no"),
        LedgerEntry(EntryKind.ADJUSTMENT, 30_000, EntryStatus.VALIDATED),
        LedgerEntry(EntryKind.REFUND, 30_000, EntryStatus.VALIDATED),
    ],
    ids=["pending", "rejected", "adjustment", "refund"],
)
def test_only_a_validated_payment_moves_lapsed_to_active(entry: LedgerEntry) -> None:
    with pytest.raises(InvalidTransition, match="validated payment"):
        m.record_payment(monthly(S.LAPSED), entry, paid_through=NOV_30)


def test_an_active_membership_due_date_never_regresses() -> None:
    for paid_through in (NOV_30, NOV_30 - timedelta(days=1)):
        with pytest.raises(ValueError, match="does not extend"):
            m.record_payment(monthly(), VALIDATED_PAYMENT, paid_through=paid_through)


@pytest.mark.parametrize("credits", [None, 0, -1])
def test_a_credits_pack_cannot_reactivate_without_a_top_up(credits: int | None) -> None:
    lapsed = m.consume_credits(credits_pack(remaining=1))

    with pytest.raises(ValueError, match="top up"):
        m.record_payment(lapsed, VALIDATED_PAYMENT, paid_through=NOV_30, credits=credits)


def test_a_payment_does_not_unfreeze() -> None:
    frozen = m.freeze(monthly(), date(2026, 11, 10))

    with pytest.raises(InvalidTransition, match="unfrozen"):
        m.record_payment(frozen, VALIDATED_PAYMENT, paid_through=date(2026, 12, 31))


def test_a_payment_can_refill_a_credits_pack() -> None:
    lapsed = m.consume_credits(credits_pack(remaining=1))

    refilled = m.record_payment(lapsed, VALIDATED_PAYMENT, paid_through=NOV_30, credits=10)

    assert refilled.status is S.ACTIVE
    assert refilled.credits_remaining == 10


# --- freeze -----------------------------------------------------------------------------


def test_freeze_shifts_the_due_date_by_the_frozen_days() -> None:
    frozen = m.freeze(monthly(), date(2026, 11, 10))

    thawed = m.unfreeze(frozen, date(2026, 11, 24))

    assert thawed.status is S.ACTIVE
    assert thawed.current_period_end == NOV_30 + timedelta(days=14)
    assert thawed.frozen_since is None


def test_cannot_unfreeze_before_the_freeze_started() -> None:
    frozen = m.freeze(monthly(), date(2026, 11, 10))

    with pytest.raises(ValueError, match="before"):
        m.unfreeze(frozen, date(2026, 11, 9))


def test_unfreeze_needs_the_freeze_start_date() -> None:
    with pytest.raises(InvalidTransition, match="freeze start"):
        m.unfreeze(monthly(S.FROZEN), NOV_30)


def test_unfreeze_needs_a_frozen_membership() -> None:
    with pytest.raises(InvalidTransition):
        m.unfreeze(monthly(), NOV_30)


def test_a_frozen_membership_does_not_lapse() -> None:
    frozen = m.freeze(monthly(), date(2026, 11, 10))

    assert not m.is_due_to_lapse(frozen, NOV_30 + timedelta(days=90))


# --- lapsing ----------------------------------------------------------------------------


def test_active_lapses_only_after_the_default_five_day_grace() -> None:
    assert m.DEFAULT_GRACE_DAYS == 5
    assert not m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=5))
    assert m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=6))

    assert m.lapse(monthly(), NOV_30 + timedelta(days=6)).status is S.LAPSED


def test_grace_is_per_gym() -> None:
    grace = m.grace_days({"grace_days": 10})

    assert not m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=10), grace)
    assert m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=11), grace)


def test_grace_defaults_when_the_gym_sets_none() -> None:
    assert m.grace_days({}) == 5


@pytest.mark.parametrize("value", [-1, "5", 2.5, True, None])
def test_grace_must_be_a_non_negative_integer(value: object) -> None:
    with pytest.raises(ValueError, match="grace_days"):
        m.grace_days({"grace_days": value})


def test_lapse_raises_when_not_due() -> None:
    with pytest.raises(InvalidTransition, match="not due"):
        m.lapse(monthly(), NOV_30)


def test_credits_lapse_when_the_last_credit_is_used() -> None:
    pack = credits_pack(remaining=2)

    once = m.consume_credits(pack)
    assert once.status is S.ACTIVE
    assert once.credits_remaining == 1

    empty = m.consume_credits(once)
    assert empty.status is S.LAPSED
    assert empty.credits_remaining == 0


def test_credits_lapse_when_the_pack_expires_without_grace() -> None:
    pack = credits_pack(remaining=5)

    assert not m.is_due_to_lapse(pack, NOV_30)
    assert m.is_due_to_lapse(pack, NOV_30 + timedelta(days=1))


def test_a_credits_membership_at_zero_is_due_to_lapse() -> None:
    assert m.is_due_to_lapse(credits_pack(remaining=0), date(2026, 11, 1))


def test_cannot_consume_more_credits_than_remain() -> None:
    with pytest.raises(ValueError, match="cannot consume"):
        m.consume_credits(credits_pack(remaining=1), 2)


def test_a_lapsed_membership_cannot_consume_credits() -> None:
    lapsed = m.consume_credits(credits_pack(remaining=1))

    with pytest.raises(InvalidTransition):
        m.consume_credits(lapsed)


def test_a_plan_without_credits_cannot_consume_them() -> None:
    with pytest.raises(ValueError, match="no credits"):
        m.consume_credits(monthly())


def test_a_trial_lapses_when_its_free_classes_run_out() -> None:
    trial = m.create(PlanKind.TRIAL, credits_remaining=1)

    assert m.consume_credits(trial).status is S.LAPSED


def test_a_trial_lapses_after_its_free_days() -> None:
    trial = m.create(PlanKind.TRIAL, current_period_end=NOV_30)

    assert not m.is_due_to_lapse(trial, NOV_30)
    assert m.lapse(trial, NOV_30 + timedelta(days=1)).status is S.LAPSED


def test_a_trial_converts_on_a_validated_payment() -> None:
    trial = m.create(PlanKind.TRIAL, credits_remaining=3)

    assert m.record_payment(trial, VALIDATED_PAYMENT, paid_through=NOV_30).status is S.ACTIVE
