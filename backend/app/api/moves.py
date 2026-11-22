"""Mover un pago (#280): a payment recorded on the wrong month, plan, or sibling, moved.

docs/design/billing-corrections.md, section 2 (`move`). Today the only way out was a
refund and a payment recorded again, which reports money given back that never left and
sends a second receipt. A move is two entries in one transaction, both `purpose = 'move'`
and both naming the payment in `corrects`: a refund-shaped entry on the old period
(`refund_of` the payment, so what is left of it to refund or move goes down), and a
validated payment on the new one, with the original's method, settled by
`billing.apply`, so what the new period does not need is carried as credit, as any
overpayment is. Neither is income nor a refund (`v_monthly_income`, 0089); each
membership's balance follows its own entries, so the person's total does not change.

It is also how two plans of one person are merged: move the payments, then void the
duplicate ("Anular plan", #256).

What may move: at most what is left of the payment after its refunds and moves, to a
period of the same person or of one who shares a guardian with them (a parent paying
for two children, recorded on the wrong one). Never a cobro extra line's payment (plan
and cobro money are not mixed), never onto a period with a proof waiting or paid in
full, never onto a plan voided as started by mistake. A payment that carried credit
moves only as a whole, its credit reverted in the same transaction (`revert`).

Both memberships are locked first, then both periods, each pair in id order, so two
moves crossing the same two periods, or a move and a payment, run one after the other.
No email is sent: the money did not change, and the receipt still says it was received.

`GET /api/ledger/moves/targets` lists the periods a payment may go to, for the ficha's
"Mover a otro mes o plan". Owner and admin only; RLS holds a coach to it as well.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.corrections import record_correction
from app.api.entries import insert_entry
from app.api.ledger import (
    CARRIED_CREDIT,
    LOCK_MEMBERSHIP,
    NO_PAYMENT,
    NOT_FOUND,
    REFUNDED,
    figures,
    period_after,
    period_under_lock,
    settled,
)
from app.domain import billing
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry, Purpose
from app.permissions import LedgerReadSession, LedgerSession
from app.schemas.ledger import (
    Figures,
    MoveConflict,
    MoveRecord,
    MoveRefusal,
    MoveTarget,
    MoveTargets,
    RecordedMove,
)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The payment to move, and whose it is.
PAYMENT_TO_MOVE = text(
    "SELECT p.membership_id, p.billing_period_id, p.extra_line_id, p.amount_clp, p.status,"
    " p.method, m.person_id FROM ledger_entry p LEFT JOIN membership m ON m.id = p.membership_id"
    " WHERE p.id = :id AND p.kind = 'payment'"
)

# The period it goes to: its membership, whose it is, and whether that plan was voided.
TARGET = text(
    "SELECT bp.membership_id, m.person_id, m.voided_at IS NOT NULL AS voided"
    " FROM billing_period bp JOIN membership m ON m.id = bp.membership_id WHERE bp.id = :id"
)

# Whom a payment of `:person` may move to: themselves, and whoever shares a guardian
# with them (guardian_link holds one guardian per dependent).
RELATED = """
    SELECT :person AS person_id
    UNION
    SELECT sib.dependent_person_id FROM guardian_link me
    JOIN guardian_link sib ON sib.gym_id = me.gym_id
        AND sib.guardian_person_id = me.guardian_person_id
    WHERE me.gym_id = current_setting('app.gym_id')::uuid AND me.dependent_person_id = :person
"""

IS_RELATED = text(f"SELECT EXISTS (SELECT FROM ({RELATED}) r WHERE r.person_id = :other)")

PROOF_WAITING = text(
    "SELECT EXISTS (SELECT FROM ledger_entry WHERE billing_period_id = :id"
    " AND kind = 'payment' AND status = 'pending')"
)

# Every period of the people a payment may move to that still owes, of plans not voided,
# with whether a proof waits on it: the payment's own person first, then by date.
TARGETS = text(
    f"""
    SELECT bp.id AS billing_period_id, bp.membership_id, m.person_id, gp.name AS person_name,
           pl.name AS plan_name, bp.period_start, bp.period_end,
           bp.amount_due_clp - coalesce(paid.amount, 0) AS outstanding_clp,
           EXISTS (SELECT FROM ledger_entry w WHERE w.billing_period_id = bp.id
                   AND w.kind = 'payment' AND w.status = 'pending') AS pending
    FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    LEFT JOIN LATERAL (
        SELECT sum({billing.settled_amount("e")})::bigint AS amount FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = 'validated'
          AND e.kind IN ('payment', 'adjustment', 'refund')
    ) paid ON true
    WHERE m.person_id IN ({RELATED}) AND m.voided_at IS NULL AND bp.id <> :period
      AND bp.amount_due_clp > coalesce(paid.amount, 0)
    ORDER BY m.person_id <> :person, bp.period_start, pl.name, bp.id
    """
)


def move_refused(code: MoveRefusal, message: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, MoveConflict(code=code, message=message).model_dump()
    )


async def payment_to_move(session: AsyncSession, payment_id: uuid.UUID) -> Any:
    """The payment, or a 404 or 409 saying why it cannot move at all."""
    found = (await session.execute(PAYMENT_TO_MOVE, {"id": payment_id})).one_or_none()
    if found is None:
        raise NO_PAYMENT
    if found.status != EntryStatus.VALIDATED:
        raise move_refused(MoveRefusal.NOT_VALIDATED, "only a validated payment is moved")
    if found.extra_line_id is not None:
        raise move_refused(
            MoveRefusal.EXTRA_LINE, "a cobro extra line's payment is not moved to a plan"
        )
    return found


@router.get("/moves/targets")
async def move_targets(
    session: LedgerReadSession, payment_id: Annotated[uuid.UUID, Query()]
) -> MoveTargets:
    """Where a payment may move, and how much of it: for "Mover a otro mes o plan"."""
    found = await payment_to_move(session, payment_id)
    given_back = int(await session.scalar(REFUNDED, {"id": payment_id}) or 0)
    credit = (await session.execute(CARRIED_CREDIT, {"id": payment_id})).first()
    rows = await session.execute(
        TARGETS, {"person": found.person_id, "period": found.billing_period_id}
    )
    return MoveTargets(
        movable_clp=max(found.amount_clp - given_back, 0),
        whole_only=credit is not None,
        targets=[MoveTarget.model_validate(r, from_attributes=True) for r in rows],
    )


async def lock_both(
    session: AsyncSession, source: tuple[uuid.UUID, uuid.UUID], target: tuple[uuid.UUID, uuid.UUID]
) -> tuple[BillingPeriod, BillingPeriod]:
    """Both memberships locked, then both periods, each in id order: `(membership,
    period)` pairs in, the two periods as their settling entries leave them out."""
    for membership_id in sorted({source[0], target[0]}):
        await session.execute(LOCK_MEMBERSHIP, {"membership_id": membership_id})
    periods: dict[uuid.UUID, BillingPeriod] = {}
    for membership_id, period_id in sorted([source, target], key=lambda pair: pair[1]):
        _, periods[period_id] = await period_under_lock(session, period_id, membership_id)
    return periods[source[1]], periods[target[1]]


@router.post(
    "/moves",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": MoveConflict}},
)
async def record_move(body: MoveRecord, session: LedgerSession) -> RecordedMove:
    """Mover un pago (#280): `amount_clp` of the payment off its period and onto
    `billing_period_id`, in one transaction, neither income nor a refund. Refused, as the
    module says, for a payment or a period it may not go to. Writes a `ledger_corrected`
    audit row, purpose `move`, on the payment's membership, and one on the other
    person's when it goes to a sibling. No email."""
    found = await payment_to_move(session, body.payment_id)
    target = (await session.execute(TARGET, {"id": body.billing_period_id})).one_or_none()
    if target is None:
        raise NOT_FOUND
    if body.billing_period_id == found.billing_period_id:
        raise move_refused(MoveRefusal.SAME_PERIOD, "the payment is on that period already")
    related = await session.scalar(
        IS_RELATED, {"person": found.person_id, "other": target.person_id}
    )
    if not related:
        raise move_refused(
            MoveRefusal.UNRELATED,
            "a payment moves to the same person, or to one who shares a guardian with them",
        )
    if target.voided:
        raise move_refused(MoveRefusal.PLAN_VOIDED, "that plan was voided: assign it again")

    source_pair = (found.membership_id, found.billing_period_id)
    target_pair = (target.membership_id, body.billing_period_id)
    source, destination = await lock_both(session, source_pair, target_pair)
    # Read under the locks every refund, move and proof of them takes.
    if await session.scalar(PROOF_WAITING, {"id": body.billing_period_id}):
        raise move_refused(MoveRefusal.PENDING, "a proof waits on that period: review it first")
    if destination.closed:
        raise move_refused(MoveRefusal.PAID, "that period is paid in full")
    given_back = int(await session.scalar(REFUNDED, {"id": body.payment_id}) or 0)
    left = found.amount_clp - given_back
    if left <= 0:
        raise move_refused(MoveRefusal.NOTHING_LEFT, "nothing is left of the payment to move")
    if body.amount_clp > left:
        raise move_refused(MoveRefusal.BEYOND_LEFT, "the move exceeds what is left of the payment")
    credit = (await session.execute(CARRIED_CREDIT, {"id": body.payment_id})).first()
    if credit is not None and body.amount_clp != left:
        raise move_refused(
            MoveRefusal.WHOLE_ONLY, "the payment carried credit: it moves only as a whole"
        )

    payment = LedgerEntry(
        kind=EntryKind.PAYMENT, amount_clp=found.amount_clp, status=EntryStatus.VALIDATED
    )
    try:
        out = billing.move_out(source, payment, given_back, body.amount_clp, body.reason)
        into = billing.move_in(destination, body.amount_clp, body.reason)
    except InvalidTransition as refused:
        raise move_refused(MoveRefusal.BEYOND_LEFT, str(refused)) from None

    before_from = await figures(session, found.membership_id, source)
    before_to = await figures(session, target.membership_id, destination)
    moved_out = await insert_entry(
        session,
        out.entry,
        membership_id=found.membership_id,
        billing_period_id=found.billing_period_id,
        refund_of=body.payment_id,
        corrects=body.payment_id,
    )
    reverted = None
    if credit is not None:
        reverted = await insert_entry(
            session,
            billing.revert_credit(credit.amount_clp, body.reason),
            membership_id=found.membership_id,
            billing_period_id=None,
            corrects=credit.id,
        )
    moved_in = await insert_entry(
        session,
        into.entry,
        membership_id=target.membership_id,
        billing_period_id=body.billing_period_id,
        method=found.method,
        corrects=body.payment_id,
    )
    # The one writer of a carried credit (`settled`): only this payment of the target
    # membership is validated in this transaction, as `CARRIED_CREDIT` needs.
    landed = await settled(session, body.billing_period_id, target.membership_id, moved_in, into)

    entry_ids = [moved_out.id, *([reverted.id] if reverted else []), moved_in.id]
    if landed.credit is not None:
        entry_ids.append(landed.credit.id)
    after_from = await figures(session, found.membership_id, out.period)
    after_to = await figures(session, target.membership_id, into.period)
    await record_move_audit(
        session,
        body,
        found,
        target,
        entry_ids,
        (before_from, after_from),
        (before_to, after_to),
    )
    return RecordedMove(
        moved_out=moved_out,
        moved_in=moved_in,
        reverted=reverted,
        credit=landed.credit,
        from_period=period_after(found.billing_period_id, out.period),
        to_period=period_after(body.billing_period_id, into.period),
    )


async def record_move_audit(
    session: AsyncSession,
    body: MoveRecord,
    found: Any,
    target: Any,
    entry_ids: list[uuid.UUID],
    source: tuple[Figures, Figures],
    destination: tuple[Figures, Figures],
) -> None:
    """The move's audit row on the payment's membership, its figures the old period's
    and the other's beside them; and, when it went to a sibling, one on theirs, so each
    person's "Correcciones" shows it."""
    common = {
        "payment_id": str(body.payment_id),
        "amount_clp": body.amount_clp,
    }
    await record_correction(
        session,
        membership_id=found.membership_id,
        billing_period_id=found.billing_period_id,
        entry_ids=entry_ids,
        purpose=Purpose.MOVE.value,
        reason=body.reason,
        before=source[0],
        after=source[1],
        moved="out",
        other_membership_id=str(target.membership_id),
        other_billing_period_id=str(body.billing_period_id),
        other_before=destination[0].model_dump(),
        other_after=destination[1].model_dump(),
        **common,
    )
    if target.person_id != found.person_id:
        await record_correction(
            session,
            membership_id=target.membership_id,
            billing_period_id=body.billing_period_id,
            entry_ids=entry_ids,
            purpose=Purpose.MOVE.value,
            reason=body.reason,
            before=destination[0],
            after=destination[1],
            moved="in",
            other_membership_id=str(found.membership_id),
            other_billing_period_id=str(found.billing_period_id),
            other_before=source[0].model_dump(),
            other_after=source[1].model_dump(),
            **common,
        )
