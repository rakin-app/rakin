"""Where someone stands on a requirement: `app.domain.requirements`."""

from datetime import date

import pytest

from app.domain.requirements import RequirementState, expires_on, state_of

OK, EXPIRING, EXPIRED, PENDING = (
    RequirementState.OK,
    RequirementState.EXPIRING,
    RequirementState.EXPIRED,
    RequirementState.PENDING,
)


def test_twelve_months_from_1_march_is_expired_on_2_march_next_year() -> None:
    done = date(2026, 3, 1)
    assert expires_on(done, 12) == date(2027, 3, 1)
    assert state_of(done, 12, date(2027, 3, 1)) is EXPIRING
    assert state_of(done, 12, date(2027, 3, 2)) is EXPIRED


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 3, 1), OK),
        (date(2027, 1, 29), OK),
        # 30 days before the last day it is in force.
        (date(2027, 1, 30), EXPIRING),
        (date(2027, 3, 1), EXPIRING),
        (date(2027, 3, 2), EXPIRED),
        (date(2030, 1, 1), EXPIRED),
    ],
)
def test_a_year_long_requirement_over_time(today: date, expected: RequirementState) -> None:
    assert state_of(date(2026, 3, 1), 12, today) is expected


def test_one_done_once_never_expires() -> None:
    assert expires_on(date(2020, 1, 1), None) is None
    assert state_of(date(2020, 1, 1), None, date(2040, 1, 1)) is OK


def test_never_done_is_pending() -> None:
    assert state_of(None, 12, date(2026, 3, 1)) is PENDING
    assert state_of(None, None, date(2026, 3, 1)) is PENDING


def test_a_month_ends_at_the_end_of_a_short_month() -> None:
    assert expires_on(date(2026, 1, 31), 1) == date(2026, 2, 28)
