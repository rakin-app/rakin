"""Mover vencimiento (#283): "le doy hasta el 10", a period's due date moved by hand.

docs/design/billing-corrections.md, section 2 ("What changes in rows", C8). Owners give
a member extra days to pay, and until now only a freeze moved a due date. This moves
`billing_period.due_date` of a period not paid in full to any day from its start to its
end plus 60 days (`billing.due_date_bounds`), with a reason. Everything that reads a due
date follows it: the nightly lapse (`app.jobs.lapse`, past the due date plus grace), the
overdue emails (`app.jobs.overdue`), Hoy and the ficha. The period's other dates and its
amount stay: the next period bills from its end, and its amount changes only by
adjustments, which the database holds to (`billing_period_amount_fixed`, 0090).

It is a row change, not an entry, so its `due_date_changed` audit row (0048) is its only
record: who, when, why, and the due date before and after. Written under the membership
and period locks (`locked_period`), as a payment and the lapse job take them, so a lapse
running at the same moment judges the period by one due date or the other, never half.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well.
"""

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.corrections import record_audit
from app.api.ledger import NOT_FOUND, locked_period
from app.domain import billing
from app.permissions import LedgerSession
from app.schemas.ledger import (
    CorrectionAction,
    DueDateConflict,
    DueDateRecord,
    DueDateRefusal,
    MovedDueDate,
)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

PERIOD_MEMBERSHIP = text("SELECT membership_id FROM billing_period WHERE id = :id")

MOVE_DUE_DATE = text("UPDATE billing_period SET due_date = :due_date WHERE id = :id")


def refused(
    code: DueDateRefusal, message: str, earliest: date | None = None, latest: date | None = None
) -> HTTPException:
    conflict = DueDateConflict(code=code, message=message, earliest=earliest, latest=latest)
    return HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))


@router.patch(
    "/periods/{period_id}/due-date",
    responses={status.HTTP_409_CONFLICT: {"model": DueDateConflict}},
)
async def move_due_date(
    period_id: uuid.UUID, body: DueDateRecord, session: LedgerSession
) -> MovedDueDate:
    """Mover vencimiento: the period falls due on `due_date` instead, with `reason`.
    Refused on a period paid in full (a void included), on the due date it already has,
    and outside its start to its end plus 60 days."""
    membership_id = await session.scalar(PERIOD_MEMBERSHIP, {"id": period_id})
    if membership_id is None:
        raise NOT_FOUND
    row, period = await locked_period(session, period_id, membership_id)
    if period.closed:
        raise refused(DueDateRefusal.PAID, "the period is paid in full: nothing falls due")
    if body.due_date == row.due_date:
        raise refused(DueDateRefusal.UNCHANGED, "the period already falls due then")
    earliest, latest = billing.due_date_bounds(period)
    if not earliest <= body.due_date <= latest:
        raise refused(
            DueDateRefusal.OUT_OF_RANGE,
            "a due date goes from the period's start to its end plus"
            f" {billing.MAX_DUE_DATE_DAYS_PAST_END} days",
            earliest=earliest,
            latest=latest,
        )
    await session.execute(MOVE_DUE_DATE, {"id": period_id, "due_date": body.due_date})
    await record_audit(
        session,
        action=CorrectionAction.DUE_DATE_CHANGED.value,
        membership_id=membership_id,
        reason=body.reason,
        billing_period_id=str(period_id),
        due_date={"before": row.due_date.isoformat(), "after": body.due_date.isoformat()},
    )
    return MovedDueDate(id=period_id, due_date=body.due_date, due_date_was=row.due_date)
