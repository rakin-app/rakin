"""How a gym is removed: the end of service in the Términos de encargo, clause 14
("Al terminar"), and the one place its numbers live (#439, #377).

Removal starts only for a suspended gym, and never deletes at once:

1. The gym has `EXPORT_DAYS` to ask for a full copy of its data and files. Deletion
   does not start before they are over, unless the gym asks in writing for it sooner.
2. Its rows and files are deleted within `DELETION_DAYS` after that (#377).
3. Its backups age out within `BACKUP_DAYS` after the deletion.

Until #377 defines how a gym is deleted, the panel refuses to start a removal
(`DELETE /api/platform/gyms/{id}`, `removal_unavailable`) and shows, for a suspended
gym, the dates a removal started today would keep.
"""

from dataclasses import dataclass
from datetime import date, timedelta

EXPORT_DAYS = 30
DELETION_DAYS = 30
BACKUP_DAYS = 60

# The issue that defines how a gym's rows and files are deleted.
DELETION_ISSUE = 377


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
