"""Public holidays on the gym's calendar (#426), from the `holidays` package.

A gym has no country of its own: its timezone says which country's holidays it keeps.
Only Chile's for now; a gym in any other zone has none. The package carries Chile's
moved and one-off holidays (a 20 June moved to a Monday, an election day), so nothing
here lists a date by hand.
"""

from dataclasses import dataclass
from datetime import date

import holidays

# The country a gym in each timezone keeps the holidays of.
ZONE_COUNTRY = {"America/Santiago": "CL"}


@dataclass(frozen=True)
class PublicHoliday:
    date: date
    name: str


def country_of(zone: str) -> str | None:
    """`CL` for `America/Santiago`; None for a zone with no country mapped."""
    return ZONE_COUNTRY.get(zone)


def holidays_between(start: date, end: date, zone: str) -> list[PublicHoliday]:
    """The public holidays from `start` to `end`, both included, earliest first, named in
    Spanish. None for a gym whose zone has no country."""
    country = country_of(zone)
    if country is None or end < start:
        return []
    calendar = holidays.country_holidays(
        country, years=range(start.year, end.year + 1), language="es"
    )
    return [
        PublicHoliday(date=day, name=name)
        for day, name in sorted(calendar.items())
        if start <= day <= end
    ]
