from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.dates import (
    add_months,
    days_overdue,
    due_deadline,
    is_past_grace,
    local_date,
    start_of_local_day,
)
from app.domain.money import format_clp
from app.domain.phone import InvalidPhoneError, is_valid_phone, normalize_phone
from app.domain.rut import InvalidRutError, check_digit, format_rut, is_valid_rut, normalize_rut

SCL = "America/Santiago"


@pytest.mark.parametrize(
    ("amount", "text"),
    [(0, "$0"), (999, "$999"), (45000, "$45.000"), (1234567, "$1.234.567"), (-1500, "-$1.500")],
)
def test_format_clp(amount: int, text: str) -> None:
    assert format_clp(amount) == text


@pytest.mark.parametrize("bad", [45000.0, True, "45000"])
def test_format_clp_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        format_clp(bad)  # type: ignore[arg-type]


def test_start_of_day_on_spring_forward_is_01_local() -> None:
    # 2026-09-06: Santiago skips 00:00-01:00; the day starts at 01:00 -03 = 04:00 UTC.
    assert start_of_local_day(date(2026, 9, 6), SCL) == datetime(2026, 9, 6, 4, tzinfo=UTC)


def test_start_of_day_on_fall_back() -> None:
    # 2026-04-05: 00:00 -04 happens once, after the repeated 23:00 hour of the 4th.
    assert start_of_local_day(date(2026, 4, 5), SCL) == datetime(2026, 4, 5, 4, tzinfo=UTC)
    assert start_of_local_day(date(2026, 4, 4), SCL) == datetime(2026, 4, 4, 3, tzinfo=UTC)


@pytest.mark.parametrize("tz", [SCL, "America/Punta_Arenas", "Pacific/Easter"])
def test_day_bounds_round_trip_every_day(tz: str) -> None:
    day = date(2020, 1, 1)
    while day < date(2031, 1, 1):
        start = start_of_local_day(day, tz)
        assert local_date(start, tz) == day
        assert local_date(start - timedelta(microseconds=1), tz) == day - timedelta(days=1)
        assert due_deadline(day, tz) == start_of_local_day(day + timedelta(days=1), tz)
        day += timedelta(days=1)


def test_local_date_rejects_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        local_date(datetime(2026, 1, 1), SCL)


def test_local_date_differs_from_utc_date() -> None:
    assert local_date(datetime(2026, 3, 1, 2, tzinfo=UTC), SCL) == date(2026, 2, 28)


@pytest.mark.parametrize(
    ("day", "months", "anchor", "expected"),
    [
        (date(2026, 1, 15), 1, None, date(2026, 2, 15)),
        (date(2026, 1, 31), 1, None, date(2026, 2, 28)),
        (date(2028, 1, 31), 1, None, date(2028, 2, 29)),
        (date(2026, 2, 28), 1, 31, date(2026, 3, 31)),
        (date(2026, 11, 30), 3, None, date(2027, 2, 28)),
        (date(2026, 3, 31), -1, None, date(2026, 2, 28)),
        (date(2026, 1, 1), 12, None, date(2027, 1, 1)),
    ],
)
def test_add_months(day: date, months: int, anchor: int | None, expected: date) -> None:
    assert add_months(day, months, anchor_day=anchor) == expected


def test_add_months_rejects_bad_anchor() -> None:
    with pytest.raises(ValueError):
        add_months(date(2026, 1, 1), 1, anchor_day=32)


def test_overdue_across_spring_forward() -> None:
    due = date(2026, 9, 5)
    # 03:59 UTC on the 6th is still the 5th locally (23:59 -04); 04:00 UTC is 01:00 on the 6th.
    assert days_overdue(due, datetime(2026, 9, 6, 3, 59, tzinfo=UTC), SCL) == 0
    assert days_overdue(due, datetime(2026, 9, 6, 4, tzinfo=UTC), SCL) == 1
    assert due_deadline(due, SCL) == datetime(2026, 9, 6, 4, tzinfo=UTC)


def test_grace_across_fall_back() -> None:
    due = date(2026, 3, 31)
    # Lapses on Apr 6 local, the first day beyond due + 5; Apr 6 starts at 04:00 UTC (-04).
    assert not is_past_grace(due, 5, datetime(2026, 4, 6, 3, 59, tzinfo=UTC), SCL)
    assert is_past_grace(due, 5, datetime(2026, 4, 6, 4, tzinfo=UTC), SCL)
    with pytest.raises(ValueError):
        is_past_grace(due, -1, datetime(2026, 4, 6, tzinfo=UTC), SCL)


@pytest.mark.parametrize(
    ("raw", "normal", "display"),
    [
        ("76.123.456-0", "76123456-0", "76.123.456-0"),
        ("12.345.678-5", "12345678-5", "12.345.678-5"),
        ("11111111-1", "11111111-1", "11.111.111-1"),
        (" 10.000.013-k ", "10000013-K", "10.000.013-K"),
        ("6-K", "6-K", "6-K"),
    ],
)
def test_rut_normalize_and_format(raw: str, normal: str, display: str) -> None:
    assert normalize_rut(raw) == normal
    assert format_rut(raw) == display
    assert is_valid_rut(raw)


@pytest.mark.parametrize(
    "raw", ["76.123.456-K", "", "-", "0-0", "12a45678-5", "1234567890-1", "\u0661-9"]
)
def test_rut_rejects(raw: str) -> None:
    assert not is_valid_rut(raw)
    with pytest.raises(InvalidRutError):
        normalize_rut(raw)


def test_rut_round_trips_and_detects_every_wrong_digit() -> None:
    for body in range(1, 30_000_000, 7_919):
        digit = check_digit(body)
        assert normalize_rut(format_rut(f"{body}{digit}")) == f"{body}-{digit}"
        for wrong in set("0123456789K") - {digit}:
            assert not is_valid_rut(f"{body}-{wrong}")


@pytest.mark.parametrize(
    "raw",
    [
        "+56 9 1234 5678",
        "56912345678",
        "0056 9 1234 5678",
        "(9) 1234-5678",
        "912345678",
        "+56.9.1234.5678",
    ],
)
def test_phone_normalizes(raw: str) -> None:
    assert normalize_phone(raw) == "+56912345678"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "+56 2 2123 4567",
        "+54 9 11 1234 5678",
        "12345678",
        "91234567",
        "+56 9 1234 567x",
        "\uff1912345678",
    ],
)
def test_phone_rejects(raw: str) -> None:
    assert not is_valid_phone(raw)
    with pytest.raises(InvalidPhoneError):
        normalize_phone(raw)
