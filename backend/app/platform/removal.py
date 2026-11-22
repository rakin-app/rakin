"""How a gym is removed: the end of service in the Términos de encargo, clause 14
("Al terminar"), and the one place its numbers live (#439, #377).

Removal starts only for a suspended gym, from the panel, and never deletes at once:

1. The gym has `EXPORT_DAYS` to ask for a full copy of its data and files
   (`python -m app.gyms export`). Deletion does not start before they are over, unless
   the gym asks in writing for it sooner: the operator records the date it asked
   (`early_deletion_on`), and deletion may run from that day.
2. Its rows and files are deleted within `DELETION_DAYS` after that
   (`python -m app.gyms delete`, `app.offboarding`).
3. Its backups age out within `BACKUP_DAYS` after the deletion (`app.backup` keeps
   about 8 weeks).

Until the deletion runs, the operator can cancel the removal: the gym is suspended, as
it was. Each date is the gym's calendar day in `JOBS_TIMEZONE`, as the panel shows it.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

EXPORT_DAYS = 30
DELETION_DAYS = 30
BACKUP_DAYS = 60


@dataclass(frozen=True)
class RemovalSchedule:
    # The last day the gym may ask for its export.
    export_until: date
    # The day by which its rows and files are deleted.
    deleted_by: date
    # The day after which no backup holds it.
    backups_gone_by: date


def schedule(started_on: date) -> RemovalSchedule:
    """The dates a removal started on `started_on` keeps, at the latest."""
    export_until = started_on + timedelta(days=EXPORT_DAYS)
    deleted_by = export_until + timedelta(days=DELETION_DAYS)
    return RemovalSchedule(export_until, deleted_by, deleted_by + timedelta(days=BACKUP_DAYS))


def started_on(started_at: datetime, timezone: str) -> date:
    """The day a removal started at `started_at`, in `timezone`."""
    return started_at.astimezone(ZoneInfo(timezone)).date()


def deletion_opens(started: date, early_deletion_on: date | None) -> date:
    """The first day the gym's rows and files may be deleted: the day after its export
    window, or the day it asked in writing for its deletion, whichever comes first."""
    after_window = schedule(started).export_until + timedelta(days=1)
    if early_deletion_on is None:
        return after_window
    return min(after_window, max(early_deletion_on, started))


def deletion_problem(started: date, early_deletion_on: date | None, today: date) -> str | None:
    """Why the gym cannot be deleted `today`, or None when it can."""
    opens = deletion_opens(started, early_deletion_on)
    if today < opens:
        return f"its export window is open until {schedule(started).export_until}: from {opens}"
    return None


def early_problem(asked_on: date, today: date) -> str | None:
    """Why `asked_on` cannot be the day the gym asked for an early deletion. It may
    be before the removal started, since the letter that ends the service may ask it;
    deletion still opens no earlier than the removal (`deletion_opens`)."""
    if asked_on > today:
        return "early_deletion_future"
    return None


def backups_gone_by(deleted_on: date) -> date:
    """The day after which no backup holds a gym deleted on `deleted_on`."""
    return deleted_on + timedelta(days=BACKUP_DAYS)
