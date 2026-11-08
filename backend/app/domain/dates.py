"""Due-date math in the gym's timezone.

Instants are stored in UTC; due dates are calendar dates in `gym.timezone`. Chile shifts
DST at local midnight, so arithmetic on UTC instants (or naive local datetimes) drifts by a
day around the transitions. The rule here: do calendar arithmetic on `date`s, and cross
between instants and dates only through `local_date` and `start_of_local_day`.

A due date is met for the whole of that local day; a period is overdue from the next one.
"""

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def _zone(tz: ZoneInfo | str) -> ZoneInfo:
    return tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)


def _require_aware(instant: datetime) -> None:
    if instant.utcoffset() is None:
        raise ValueError("naive datetime: pass an aware instant (UTC from the database)")


def local_date(instant: datetime, tz: ZoneInfo | str) -> date:
    """The calendar date at `instant` in the gym's timezone."""
    _require_aware(instant)
    return instant.astimezone(_zone(tz)).date()


def start_of_local_day(day: date, tz: ZoneInfo | str) -> datetime:
    """The first instant of `day` in the gym's timezone, as an aware UTC datetime.

    On Chile's spring-forward day local midnight does not exist and the day starts at
    01:00. `fold=0` on a skipped wall time takes the pre-transition offset, which lands on
    exactly that instant, and on a repeated one it takes the earlier of the two.
    """
    return datetime.combine(day, time.min, tzinfo=_zone(tz)).astimezone(UTC)


def due_deadline(due: date, tz: ZoneInfo | str) -> datetime:
    """The UTC instant a due date passes: the start of the following local day."""
    return start_of_local_day(due + timedelta(days=1), tz)


def add_months(day: date, months: int, *, anchor_day: int | None = None) -> date:
    """`day` moved by `months` calendar months, clamped to the end of a short month.

    `anchor_day` is the day of month the result aims for (default `day.day`). Pass the
    membership's anchor so a 31st anchor that clamped to Feb 28 returns to Mar 31.
    """
    target = day.day if anchor_day is None else anchor_day
    if not 1 <= target <= 31:
        raise ValueError(f"anchor_day must be 1..31, got {target}")
    year, month0 = divmod(day.year * 12 + day.month - 1 + months, 12)
    month = month0 + 1
    return date(year, month, min(target, calendar.monthrange(year, month)[1]))


def days_overdue(due: date, now: datetime, tz: ZoneInfo | str) -> int:
    """Whole local days past `due` at `now`; 0 on or before the due date."""
    return max(0, (local_date(now, tz) - due).days)


def is_past_grace(due: date, grace_days: int, now: datetime, tz: ZoneInfo | str) -> bool:
    """True once the gym-local date is beyond `due + grace_days` (Active -> Lapsed)."""
    if grace_days < 0:
        raise ValueError(f"grace_days must be >= 0, got {grace_days}")
    return days_overdue(due, now, tz) > grace_days
