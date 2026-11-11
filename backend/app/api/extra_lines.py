"""A cobro extra line's ledger (#195): its locks, how it settles, and refunding it.

A line settles as a billing period does (`app.domain.billing`). Whatever writes money
to one takes the cobro's lock and then the line's (`locked_line`): two payments on a
line settle one after the other, and cancelling a line or dividing the total again
waits for a payment and then sees it. A student's claim cannot take those locks, since
it may not update either row; `ledger_entry_line_open` (migration 0037) takes the
cobro's lock for it, as a share, and refuses an entry on a cancelled line.

Below both `app.api.ledger` and `app.api.extra_charges`, which each build on it.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entries import insert_entry
from app.domain import billing
from app.domain.billing import SETTLING_KINDS, BillingPeriod, settled_amount
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.schemas.ledger import Period, RecordedRefund, RefundRecord

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "cobro extra not found")
NO_LINE = HTTPException(status.HTTP_404_NOT_FOUND, "line not found")
CANCELLED = HTTPException(status.HTTP_409_CONFLICT, "this line is cancelled")

VALIDATED = f"'{EntryStatus.VALIDATED.value}'"
PENDING = f"'{EntryStatus.PENDING.value}'"
PAYMENT = f"'{EntryKind.PAYMENT.value}'"
REFUND = f"'{EntryKind.REFUND.value}'"
SETTLING = ", ".join(f"'{k.value}'" for k in sorted(SETTLING_KINDS))

LOCK_CHARGE = text(
    "SELECT amount_mode, amount_clp, due_date FROM extra_charge WHERE id = :id FOR UPDATE"
)
LOCK_LINE = text(
    "SELECT l.id, l.extra_charge_id, l.person_id, l.amount_due_clp, l.cancelled_at"
    " FROM extra_line l WHERE l.id = :line AND l.extra_charge_id = :charge FOR UPDATE"
)
SETTLED = text(
    f"SELECT coalesce(sum({settled_amount('ledger_entry')}), 0)::bigint FROM ledger_entry"
    f" WHERE extra_line_id = :id AND status = {VALIDATED} AND kind IN ({SETTLING})"
)


async def locked_line(
    session: AsyncSession, charge_id: uuid.UUID, line_id: uuid.UUID
) -> tuple[Any, Any, BillingPeriod]:
    """The cobro and its line, locked until the request ends, and the line settled as a
    period is: the cobro first, then the line, wherever both are taken."""
    charge = (await session.execute(LOCK_CHARGE, {"id": charge_id})).one_or_none()
    if charge is None:
        raise NOT_FOUND
    line = (await session.execute(LOCK_LINE, {"line": line_id, "charge": charge_id})).one_or_none()
    if line is None:
        raise NO_LINE
    paid = await session.scalar(SETTLED, {"id": line_id})
    period = BillingPeriod(
        period_start=charge.due_date,
        period_end=charge.due_date,
        amount_due_clp=line.amount_due_clp,
        due_date=charge.due_date,
        paid_clp=paid,
        closed=paid >= line.amount_due_clp,
    )
    return charge, line, period


async def locked_line_by_id(
    session: AsyncSession, line_id: uuid.UUID
) -> tuple[Any, Any, BillingPeriod]:
    """`locked_line` for a line known by its id alone: a proof's or a payment's."""
    charge_id = await session.scalar(
        text("SELECT extra_charge_id FROM extra_line WHERE id = :id"), {"id": line_id}
    )
    if charge_id is None:
        raise NO_LINE
    return await locked_line(session, charge_id, line_id)


def line_after(line_id: uuid.UUID, period: BillingPeriod) -> Period:
    """The line as an entry just settled leaves it, in the shape a period's is given."""
    return Period(
        id=line_id,
        amount_due_clp=period.amount_due_clp,
        paid_clp=period.paid_clp,
        outstanding_clp=period.outstanding_clp,
        closed=period.closed,
    )


async def refund_line_payment(
    session: AsyncSession, body: RefundRecord, found: Any
) -> RecordedRefund:
    """`POST /api/ledger/refunds` for a payment on a line: the line's locks, then as a
    period's refund (`app.api.ledger.record_refund`)."""
    _, _, period = await locked_line_by_id(session, found.extra_line_id)
    refunded = await session.scalar(
        text("SELECT coalesce(sum(amount_clp), 0)::bigint FROM ledger_entry WHERE refund_of = :id"),
        {"id": body.payment_id},
    )
    payment = LedgerEntry(
        kind=EntryKind.PAYMENT, amount_clp=found.amount_clp, status=EntryStatus(found.status)
    )
    try:
        settlement = billing.refund(period, payment, refunded or 0, body.amount_clp, body.note)
    except InvalidTransition as refused:
        raise HTTPException(status.HTTP_409_CONFLICT, str(refused)) from None
    refund = await insert_entry(
        session,
        settlement.entry,
        extra_line_id=found.extra_line_id,
        method=body.method.value,
        refund_of=body.payment_id,
    )
    return RecordedRefund(refund=refund, period=line_after(found.extra_line_id, settlement.period))
