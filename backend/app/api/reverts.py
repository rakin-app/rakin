"""Revertir ajuste and Condonar deuda (#282): undo an adjustment made by mistake, and
forgive a debt that was real but will not be collected.

docs/design/billing-corrections.md, section 2 (`revert`, `write_off`). Both are new
entries, validated by the admin making them, under the membership's and the period's
locks (`locked_period`), each with a required reason and a `ledger_corrected` audit
row (0048) with the period and the balance before and after.

- `POST /api/ledger/reverts`: an adjustment of minus the adjustment's amount on its
  period, `purpose = 'revert'`, naming it in `corrects`, so the period settles as if it
  never was. Reverting one in the member's favour (a discount) is owed; reverting a
  Recargo is in their favour and capped at what the period still owes, as any
  adjustment in their favour is (`billing.revert`). Refused on a void (it is restored
  instead), on a correction's own entry (a restore, a revert, a move, a mistake), on a
  carried credit (it follows its payment, #280 and #281), on an adjustment reverted
  already, on a period whose charge stands voided, and on a plan voided by mistake. A
  write-off is an adjustment like any other here: reverting it puts the debt back.
- `POST /api/ledger/write-offs`: an adjustment in the member's favour of all the period
  still owes, `purpose = 'write_off'` (`billing.write_off`). Unlike a void, the charge
  was real: "Esperado" keeps the period, and the book reports it as "Condonado". What
  was paid on it stays paid. Refused on a period with a proof waiting, on one owing
  nothing, and on a plan voided by mistake.

The database holds a revert to an adjustment of its own period and of minus its amount
(`ledger_entry_revert`, 0091), and to one revert per adjustment (0087).

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.api.corrections import record_correction
from app.api.entries import insert_entry, standing_void
from app.api.ledger import (
    MONEY_ON_PERIOD,
    NO_ENTRY,
    figures,
    locked_period,
    period_after,
)
from app.domain import billing
from app.domain.errors import InvalidTransition
from app.domain.ledger import Purpose
from app.permissions import LedgerSession
from app.schemas.ledger import (
    RecordedRevert,
    RecordedWriteOff,
    RevertConflict,
    RevertRecord,
    RevertRefusal,
    WriteOffConflict,
    WriteOffRecord,
    WriteOffRefusal,
)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The entry a revert names.
ADJUSTMENT = text(
    "SELECT membership_id, billing_period_id, kind, amount_clp, purpose FROM ledger_entry"
    " WHERE id = :id"
)

# Read under the period's locks: whether the adjustment was reverted already, whether
# its period's charge stands voided, and whether its plan was voided since.
REVERT_STATE = text(
    "SELECT EXISTS (SELECT FROM ledger_entry WHERE corrects = :id AND purpose = 'revert')"
    " AS reverted,"
    " EXISTS (SELECT FROM ledger_entry v WHERE v.billing_period_id = :period"
    f" AND {standing_void('v')}) AS voided,"
    " m.voided_at IS NOT NULL AS plan_voided"
    " FROM membership m WHERE m.id = :membership_id"
)

PLAN_VOIDED = text("SELECT voided_at IS NOT NULL FROM membership WHERE id = :id")

# The purposes whose entries are undone by their own inverse, never reverted (guard 7).
CORRECTIONS = frozenset({Purpose.RESTORE, Purpose.REVERT, Purpose.MOVE, Purpose.MISTAKE})


def revert_refused(code: RevertRefusal, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, RevertConflict(code=code, message=message).model_dump()
    )


def write_off_refused(code: WriteOffRefusal, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, WriteOffConflict(code=code, message=message).model_dump()
    )


@router.post(
    "/reverts",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": RevertConflict}},
)
async def record_revert(body: RevertRecord, session: LedgerSession) -> RecordedRevert:
    """Revertir un ajuste (#282): an adjustment made by mistake is undone, its period as
    before it. The ledger keeps both, the adjustment reading "Revertido"."""
    found = (await session.execute(ADJUSTMENT, {"id": body.adjustment_id})).one_or_none()
    if found is None:
        raise NO_ENTRY
    if found.kind != "adjustment":
        raise revert_refused(RevertRefusal.NOT_AN_ADJUSTMENT, "the entry is not an adjustment")
    if found.purpose == Purpose.VOID:
        raise revert_refused(RevertRefusal.VOID, "the entry is a void: restore it instead")
    if found.purpose in CORRECTIONS:
        raise revert_refused(
            RevertRefusal.CORRECTION, "the entry is a correction: undo it by its inverse"
        )
    if found.billing_period_id is None:
        raise revert_refused(
            RevertRefusal.CREDIT, "a carried credit follows its payment: undo or move the payment"
        )
    row, period = await locked_period(session, found.billing_period_id, found.membership_id)
    state = (
        await session.execute(
            REVERT_STATE,
            {"id": body.adjustment_id, "period": row.id, "membership_id": found.membership_id},
        )
    ).one()
    if state.reverted:
        raise revert_refused(RevertRefusal.REVERTED, "the adjustment was reverted already")
    if state.plan_voided:
        raise revert_refused(RevertRefusal.PLAN_VOIDED, "the plan was voided: assign it again")
    if state.voided:
        raise revert_refused(RevertRefusal.VOIDED, "the charge is voided: restore it first")
    try:
        settlement = billing.revert(period, found.amount_clp, body.reason)
    except InvalidTransition:
        raise revert_refused(
            RevertRefusal.EXCEEDS, "reverting the adjustment exceeds what the period owes"
        ) from None
    before = await figures(session, found.membership_id, period)
    entry = await insert_entry(
        session,
        settlement.entry,
        membership_id=found.membership_id,
        billing_period_id=row.id,
        corrects=body.adjustment_id,
    )
    await record_correction(
        session,
        membership_id=found.membership_id,
        billing_period_id=row.id,
        entry_ids=[entry.id],
        purpose=Purpose.REVERT.value,
        reason=entry.note,
        before=before,
        after=await figures(session, found.membership_id, settlement.period),
        adjustment_id=str(body.adjustment_id),
    )
    return RecordedRevert(revert=entry, period=period_after(row.id, settlement.period))


@router.post(
    "/write-offs",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": WriteOffConflict}},
)
async def record_write_off(body: WriteOffRecord, session: LedgerSession) -> RecordedWriteOff:
    """Condonar una deuda (#282): a real charge the gym will not collect. Nothing is owed
    on the period afterwards, so it leaves Hoy and the balance, but "Esperado" still
    counts it, and the book reports it as "Condonado"."""
    row, period = await locked_period(session, body.billing_period_id, body.membership_id)
    if await session.scalar(PLAN_VOIDED, {"id": body.membership_id}):
        raise write_off_refused(WriteOffRefusal.PLAN_VOIDED, "the plan was voided")
    money = (await session.execute(MONEY_ON_PERIOD, {"id": row.id})).one()
    if money.pending:
        raise write_off_refused(
            WriteOffRefusal.PENDING, "a proof waits on the period: review it first"
        )
    try:
        settlement = billing.write_off(period, body.reason)
    except InvalidTransition:
        raise write_off_refused(WriteOffRefusal.NOTHING_OWED, "the period owes nothing") from None
    before = await figures(session, body.membership_id, period)
    entry = await insert_entry(
        session, settlement.entry, membership_id=body.membership_id, billing_period_id=row.id
    )
    await record_correction(
        session,
        membership_id=body.membership_id,
        billing_period_id=row.id,
        entry_ids=[entry.id],
        purpose=Purpose.WRITE_OFF.value,
        reason=entry.note,
        before=before,
        after=await figures(session, body.membership_id, settlement.period),
    )
    return RecordedWriteOff(write_off=entry, period=period_after(row.id, settlement.period))
