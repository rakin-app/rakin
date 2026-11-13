from collections.abc import Callable
from dataclasses import replace
from datetime import date, timedelta
from itertools import product

import pytest

from app.domain import membership as m
from app.domain.dates import is_past_grace
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.membership import Membership, MembershipStatus, PlanKind

S = MembershipStatus
NOV_10 = date(2026, 11, 10)
NOV_24 = date(2026, 11, 24)
NOV_30 = date(2026, 11, 30)
DEC_10 = date(2026, 12, 10)
DEC_24 = date(2026, 12, 24)
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
    S.FROZEN: lambda ms: m.freeze(ms, NOV_30, NOV_30 + timedelta(days=14)),
    S.CANCELLED: lambda ms: m.cancel(ms, "se mudó"),
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
    frozen = source is S.FROZEN
    ms = monthly(
        source,
        frozen_since=NOV_30 if frozen else None,
        frozen_until=NOV_30 + timedelta(days=14) if frozen else None,
    )

    with pytest.raises(InvalidTransition):
        ACTIONS[target](ms)


def test_cancelled_is_terminal() -> None:
    cancelled = m.cancel(monthly(), "se mudó")

    for action in ACTIONS.values():
        with pytest.raises(InvalidTransition):
            action(cancelled)
    with pytest.raises(InvalidTransition):
        m.unfreeze(cancelled, NOV_30)


@pytest.mark.parametrize("source", [S.ACTIVE, S.LAPSED])
def test_active_and_lapsed_can_be_cancelled(source: MembershipStatus) -> None:
    cancelled = m.cancel(monthly(source), "  se mudó  ")
    assert cancelled.status is S.CANCELLED
    assert cancelled.cancel_reason == "se mudó"


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_cancellation_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="reason"):
        m.cancel(monthly(), reason)


@pytest.mark.parametrize("source", [S.TRIAL, S.ACTIVE, S.FROZEN, S.LAPSED])
def test_leaving_the_gym_ends_any_live_membership(source: MembershipStatus) -> None:
    left = m.leave(monthly(source, frozen_since=NOV_10, frozen_until=NOV_24))
    assert left.status is S.CANCELLED
    assert left.cancel_reason == m.LEFT_REASON
    assert (left.frozen_since, left.frozen_until) == (None, None)


def test_a_cancelled_membership_cannot_leave_again() -> None:
    with pytest.raises(InvalidTransition):
        m.leave(m.cancel(monthly(), "se mudó"))


# --- starting -------------------------------------------------------------------------

NOV_15 = date(2026, 11, 15)
NOV_14 = date(2026, 11, 14)


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        (
            m.PlanTerms(PlanKind.MONTHLY, anchor="signup"),
            Membership(PlanKind.MONTHLY, S.ACTIVE, NOV_14, anchor_day=15),
        ),
        (
            m.PlanTerms(PlanKind.MONTHLY, anchor="first"),
            Membership(PlanKind.MONTHLY, S.ACTIVE, NOV_14, anchor_day=1),
        ),
        (
            m.PlanTerms(PlanKind.PREPAID),
            Membership(PlanKind.PREPAID, S.ACTIVE, NOV_14),
        ),
        (
            m.PlanTerms(PlanKind.CREDITS, credits=12, credit_expiry_days=60),
            Membership(PlanKind.CREDITS, S.ACTIVE, date(2027, 1, 13), credits_remaining=12),
        ),
        (
            m.PlanTerms(PlanKind.TRIAL, credits=2, credit_expiry_days=14),
            Membership(PlanKind.TRIAL, S.TRIAL, date(2026, 11, 28), credits_remaining=2),
        ),
        (
            m.PlanTerms(PlanKind.TRIAL, credits=2),
            Membership(PlanKind.TRIAL, S.TRIAL, None, credits_remaining=2),
        ),
        (
            m.PlanTerms(PlanKind.TRIAL, credit_expiry_days=1),
            Membership(PlanKind.TRIAL, S.TRIAL, NOV_15),
        ),
    ],
    ids=["signup", "first", "prepaid", "credits", "trial", "trial-classes", "trial-one-day"],
)
def test_start(terms: m.PlanTerms, expected: Membership) -> None:
    assert m.start(terms, NOV_15) == expected


DEC_10 = date(2026, 12, 10)


@pytest.mark.parametrize(
    ("terms", "expected"),
    [
        (
            m.PlanTerms(PlanKind.MONTHLY, anchor="signup"),
            Membership(PlanKind.MONTHLY, S.ACTIVE, date(2026, 12, 9), anchor_day=10),
        ),
        (
            m.PlanTerms(PlanKind.MONTHLY, anchor="first"),
            Membership(PlanKind.MONTHLY, S.ACTIVE, date(2026, 12, 9), anchor_day=1),
        ),
        (
            m.PlanTerms(PlanKind.PREPAID),
            Membership(PlanKind.PREPAID, S.ACTIVE, date(2026, 12, 9)),
        ),
        (
            m.PlanTerms(PlanKind.CREDITS, credits=12, credit_expiry_days=60),
            Membership(PlanKind.CREDITS, S.ACTIVE, DEC_10, credits_remaining=12),
        ),
        (
            m.PlanTerms(PlanKind.TRIAL, credits=2, credit_expiry_days=14),
            Membership(PlanKind.TRIAL, S.TRIAL, DEC_10, credits_remaining=2),
        ),
    ],
    ids=["signup", "first", "prepaid", "credits", "trial"],
)
def test_an_imported_membership_is_paid_through_the_day_before_its_due_date(
    terms: m.PlanTerms, expected: Membership
) -> None:
    assert m.imported(terms, NOV_15, DEC_10) == expected


def test_an_imported_pack_without_a_due_date_starts_as_new() -> None:
    terms = m.PlanTerms(PlanKind.CREDITS, credits=12, credit_expiry_days=60)
    assert m.imported(terms, NOV_15, None) == m.start(terms, NOV_15)


@pytest.mark.parametrize(
    ("terms", "due_on", "match"),
    [
        (m.PlanTerms(PlanKind.MONTHLY, anchor="signup"), None, "due date"),
        (m.PlanTerms(PlanKind.DROPIN), DEC_10, "drop-in"),
    ],
    ids=["recurring-without-due", "dropin"],
)
def test_an_import_refuses(terms: m.PlanTerms, due_on: date | None, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        m.imported(terms, NOV_15, due_on)


def test_a_dropin_does_not_start() -> None:
    with pytest.raises(ValueError, match="drop-in"):
        m.start(m.PlanTerms(PlanKind.DROPIN), NOV_15)


def test_a_new_recurring_membership_is_due_on_its_start_date() -> None:
    # Paid through the day before, so the first period lapses only after the grace.
    started = m.start(m.PlanTerms(PlanKind.MONTHLY, anchor="signup"), NOV_15)
    assert not m.is_due_to_lapse(started, NOV_15 + timedelta(days=m.DEFAULT_GRACE_DAYS))
    assert m.is_due_to_lapse(started, NOV_15 + timedelta(days=m.DEFAULT_GRACE_DAYS + 1))


@pytest.mark.parametrize(
    ("period_start", "anchor", "day"),
    [(date(2026, 1, 31), "signup", 31), (date(2026, 1, 31), "first", 1)],
)
def test_anchor_day(period_start: date, anchor: str, day: int) -> None:
    assert m.anchor_day(m.PlanTerms(PlanKind.MONTHLY, anchor=anchor), period_start) == day


# --- changing plan ----------------------------------------------------------------------


@pytest.mark.parametrize("source", [S.ACTIVE, S.FROZEN, S.LAPSED])
def test_a_plan_change_starts_after_the_paid_through_date(source: MembershipStatus) -> None:
    assert m.plan_change_starts(monthly(source), PlanKind.PREPAID) == date(2026, 12, 1)


def test_a_plan_change_waits_for_periods_billed_ahead() -> None:
    change = m.plan_change_starts(monthly(), PlanKind.MONTHLY, billed_through=date(2026, 12, 31))
    assert change == date(2027, 1, 1)


def test_a_billed_period_before_the_paid_through_date_moves_nothing() -> None:
    change = m.plan_change_starts(monthly(), PlanKind.MONTHLY, billed_through=date(2026, 10, 31))
    assert change == date(2026, 12, 1)


def test_an_unpaid_new_membership_changes_from_its_start() -> None:
    started = m.start(m.PlanTerms(PlanKind.MONTHLY, anchor="signup"), NOV_15)
    assert m.plan_change_starts(started, PlanKind.PREPAID) == NOV_15


def test_dates_past_the_edge_of_the_range_overflow() -> None:
    # The API keeps `started_on` near today; this is the backstop it maps to a 422.
    with pytest.raises(OverflowError):
        m.start(m.PlanTerms(PlanKind.MONTHLY, anchor="signup"), date.min)
    with pytest.raises(OverflowError):
        m.plan_change_starts(monthly(current_period_end=date.max), PlanKind.MONTHLY)


def test_a_cancelled_membership_does_not_change_plan() -> None:
    with pytest.raises(InvalidTransition):
        m.plan_change_starts(monthly(S.CANCELLED), PlanKind.MONTHLY)


@pytest.mark.parametrize(
    ("source", "to"),
    [
        (PlanKind.MONTHLY, PlanKind.CREDITS),
        (PlanKind.MONTHLY, PlanKind.TRIAL),
        (PlanKind.MONTHLY, PlanKind.DROPIN),
        (PlanKind.CREDITS, PlanKind.MONTHLY),
        (PlanKind.TRIAL, PlanKind.MONTHLY),
    ],
)
def test_only_recurring_plans_change(source: PlanKind, to: PlanKind) -> None:
    ms = Membership(source, S.ACTIVE, NOV_30, credits_remaining=1)
    with pytest.raises(ValueError, match="monthly or prepaid"):
        m.plan_change_starts(ms, to)


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
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    with pytest.raises(InvalidTransition, match="unfrozen"):
        m.record_payment(frozen, VALIDATED_PAYMENT, paid_through=date(2026, 12, 31))


def test_a_payment_can_refill_a_credits_pack() -> None:
    lapsed = m.consume_credits(credits_pack(remaining=1))

    refilled = m.record_payment(lapsed, VALIDATED_PAYMENT, paid_through=NOV_30, credits=10)

    assert refilled.status is S.ACTIVE
    assert refilled.credits_remaining == 10


# --- freeze -----------------------------------------------------------------------------


def test_freeze_shifts_the_due_date_by_the_frozen_days_as_it_starts() -> None:
    frozen = m.freeze(monthly(anchor_day=1), NOV_10, NOV_24)

    assert frozen.status is S.FROZEN
    assert frozen.current_period_end == NOV_30 + timedelta(days=14)
    # Next due Dec 15, so it bills on the 15th from then on.
    assert frozen.anchor_day == 15
    assert (frozen.frozen_since, frozen.frozen_until) == (NOV_10, NOV_24)


def test_freeze_moves_past_the_last_period_billed_before_it() -> None:
    # Paid through Nov 30 at the start, since billed through Dec 31: the Dec period
    # started before the freeze, so billing resumes 14 days after it ends.
    frozen = m.freeze(
        monthly(current_period_end=date(2026, 11, 4), anchor_day=5),
        DEC_10,
        DEC_24,
        billed_through=date(2027, 1, 4),
    )

    assert frozen.current_period_end == date(2027, 1, 18)
    assert frozen.anchor_day == 19


def test_freeze_keeps_a_later_paid_through_date() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24, billed_through=date(2026, 11, 4))

    assert frozen.current_period_end == NOV_30 + timedelta(days=14)


def test_freeze_moves_a_credits_pack_expiry() -> None:
    frozen = m.freeze(credits_pack(), NOV_10, NOV_24, billed_through=date(2027, 1, 4))

    assert frozen.current_period_end == NOV_30 + timedelta(days=14)
    assert frozen.anchor_day is None


def test_freeze_keeps_a_prepaid_plan_without_an_anchor_day() -> None:
    prepaid = Membership(PlanKind.PREPAID, S.ACTIVE, current_period_end=NOV_30)

    assert m.freeze(prepaid, NOV_10, NOV_24).anchor_day is None


@pytest.mark.parametrize("days", [0, -1])
def test_a_freeze_ends_after_it_starts(days: int) -> None:
    with pytest.raises(ValueError, match="ends after"):
        m.freeze(monthly(), NOV_10, NOV_10 + timedelta(days=days))


def test_a_freeze_lasts_at_most_a_year() -> None:
    m.freeze(monthly(), NOV_10, NOV_10 + timedelta(days=m.MAX_FREEZE_DAYS))
    with pytest.raises(ValueError, match="at most"):
        m.freeze(monthly(), NOV_10, NOV_10 + timedelta(days=m.MAX_FREEZE_DAYS + 1))


@pytest.mark.parametrize("source", [S.TRIAL, S.FROZEN, S.LAPSED, S.CANCELLED])
def test_only_an_active_membership_freezes(source: MembershipStatus) -> None:
    with pytest.raises(InvalidTransition):
        m.freeze(monthly(source), NOV_10, NOV_24)


def test_unfreeze_on_the_day_the_freeze_ends_keeps_the_due_date() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    thawed = m.unfreeze(frozen, NOV_24)

    assert thawed.status is S.ACTIVE
    assert thawed.current_period_end == NOV_30 + timedelta(days=14)
    assert (thawed.frozen_since, thawed.frozen_until) == (None, None)


def test_cannot_unfreeze_before_the_freeze_ends() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    assert not m.is_due_to_unfreeze(frozen, NOV_24 - timedelta(days=1))
    assert m.is_due_to_unfreeze(frozen, NOV_24)
    with pytest.raises(InvalidTransition, match="frozen until"):
        m.unfreeze(frozen, NOV_24 - timedelta(days=1))


def test_a_late_run_still_unfreezes() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    assert m.unfreeze(frozen, NOV_30).status is S.ACTIVE


def test_unfreeze_needs_the_freeze_end_date() -> None:
    with pytest.raises(InvalidTransition, match="freeze end"):
        m.unfreeze(monthly(S.FROZEN), NOV_30)


def test_unfreeze_needs_a_frozen_membership() -> None:
    assert not m.is_due_to_unfreeze(monthly(frozen_until=NOV_24), NOV_30)
    with pytest.raises(InvalidTransition):
        m.unfreeze(monthly(), NOV_30)


def test_a_frozen_membership_does_not_lapse() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    assert not m.is_due_to_lapse(frozen, NOV_30 + timedelta(days=90))


# --- lapsing ----------------------------------------------------------------------------


def test_active_lapses_only_after_the_default_five_day_grace() -> None:
    # Paid through Nov 30, so due Dec 1: Dec 2 to 6 are the grace, Dec 7 lapses.
    assert m.DEFAULT_GRACE_DAYS == 5
    assert not m.is_due_to_lapse(monthly(), date(2026, 12, 6))
    assert m.is_due_to_lapse(monthly(), date(2026, 12, 7))

    assert m.lapse(monthly(), date(2026, 12, 7)).status is S.LAPSED


def test_lapsing_agrees_with_the_grace_rule_in_dates() -> None:
    due = NOV_30 + timedelta(days=1)
    for days in range(15):
        today = due + timedelta(days=days)
        assert m.is_due_to_lapse(monthly(), today) is is_past_grace(due, 5, today)


def test_grace_is_per_gym() -> None:
    grace = m.grace_days({"grace_days": 10})

    assert not m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=11), grace)
    assert m.is_due_to_lapse(monthly(), NOV_30 + timedelta(days=12), grace)


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


# --- a freeze's end moved, and ended early (#115) --------------------------------------


def test_moving_a_freeze_end_moves_the_due_date_by_the_difference() -> None:
    frozen = m.freeze(monthly(anchor_day=1), NOV_10, NOV_24)

    longer = m.move_freeze_end(frozen, NOV_30)
    shorter = m.move_freeze_end(frozen, date(2026, 11, 15))

    assert longer.current_period_end == NOV_30 + timedelta(days=20)
    assert longer.anchor_day == 21
    assert longer.frozen_until == NOV_30
    assert shorter.current_period_end == NOV_30 + timedelta(days=5)
    assert shorter.anchor_day == 6
    assert shorter.status is S.FROZEN


def test_a_freeze_ended_on_its_first_day_moves_nothing() -> None:
    before = monthly(anchor_day=1)

    ended = m.end_freeze(m.freeze(before, NOV_10, NOV_24), NOV_10)

    assert ended.status is S.ACTIVE
    assert ended.current_period_end == before.current_period_end
    assert (ended.frozen_since, ended.frozen_until) == (None, None)


def test_ending_a_freeze_early_keeps_the_days_frozen() -> None:
    ended = m.end_freeze(m.freeze(credits_pack(), NOV_10, NOV_24), date(2026, 11, 14))

    assert ended.status is S.ACTIVE
    assert ended.current_period_end == NOV_30 + timedelta(days=4)


def test_ending_a_freeze_past_its_end_keeps_the_due_date() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    ended = m.end_freeze(frozen, NOV_30)

    assert ended.current_period_end == frozen.current_period_end


def test_a_freeze_end_stays_within_its_first_day_and_a_year() -> None:
    frozen = m.freeze(monthly(), NOV_10, NOV_24)

    with pytest.raises(ValueError, match="at the earliest"):
        m.move_freeze_end(frozen, NOV_10 - timedelta(days=1))
    with pytest.raises(ValueError, match="at most"):
        m.move_freeze_end(frozen, NOV_10 + timedelta(days=m.MAX_FREEZE_DAYS + 1))


def test_only_a_running_freeze_moves_or_ends() -> None:
    with pytest.raises(InvalidTransition):
        m.move_freeze_end(monthly(), NOV_24)
    with pytest.raises(InvalidTransition):
        m.end_freeze(monthly(), NOV_24)


def test_overdue_emails_go_on_the_due_date_the_day_after_then_every_three_days() -> None:
    days = [d for d in range(-3, 30) if m.is_overdue_email_day(d, 15)]

    assert days == [0, 1, 4, 7, 10, 13]


def test_overdue_emails_stop_with_the_grace() -> None:
    assert [d for d in range(30) if m.is_overdue_email_day(d, 5)] == [0, 1, 4]
    assert [d for d in range(30) if m.is_overdue_email_day(d, 0)] == [0]
    # The last email goes on the last day of the grace, the day before the lapse.
    assert m.is_overdue_email_day(13, 13)
    due = NOV_30 + timedelta(days=1)
    assert not m.is_due_to_lapse(monthly(), due + timedelta(days=13), 13)
