"""Public holidays on the gym's calendar (#426): no database."""

from datetime import date

from app.domain.public_holidays import PublicHoliday, country_of, holidays_between


def test_the_country_comes_from_the_timezone_chile_only() -> None:
    assert country_of("America/Santiago") == "CL"
    assert country_of("America/Buenos_Aires") is None
    assert country_of("UTC") is None


def test_chiles_holidays_between_two_days_both_included_in_spanish() -> None:
    assert holidays_between(date(2026, 9, 18), date(2026, 9, 19), "America/Santiago") == [
        PublicHoliday(date(2026, 9, 18), "Día de la Independencia"),
        PublicHoliday(date(2026, 9, 19), "Día de las Glorias del Ejército"),
    ]
    assert holidays_between(date(2026, 9, 20), date(2026, 9, 30), "America/Santiago") == []


def test_no_holidays_without_a_country_or_a_range() -> None:
    assert holidays_between(date(2026, 9, 1), date(2026, 9, 30), "UTC") == []
    assert holidays_between(date(2026, 9, 30), date(2026, 9, 1), "America/Santiago") == []
