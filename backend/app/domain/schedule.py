"""How far ahead the weekly schedule makes its classes (#167)."""

from datetime import date, timedelta

# Classes are made through this many days ahead, today included.
HORIZON_DAYS = 14


def horizon(today: date) -> tuple[date, date]:
    """The first and last date the schedule makes classes for on `today`, a gym-local
    date."""
    return today, today + timedelta(days=HORIZON_DAYS - 1)
