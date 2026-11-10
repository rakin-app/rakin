"""An admin validates or rejects a student's transfer proof ("Validar comprobante", #36).

`GET /api/ledger/proofs` is the queue: every pending payment a student (or their
guardian) claimed with a proof (#35), oldest first, each with what the admin needs to
decide in one tap: the claimed amount against the period it pays, the proof itself,
the plan, what else the membership owes, and its latest payments.

Validating settles the period as recording a payment does (`app.api.ledger`): the
entry turns validated, the period closes once paid in full, and whatever was paid
beyond the amount due becomes a validated credit adjustment for a later period. A
period that is already paid in full is a 409: the admin rejects the proof instead.

Validating emails the student a receipt (`app.api.ledger.send_receipt`). Rejecting
needs a note, which the student is emailed; the period stays open, since a
rejected entry never counts towards it. Both record the reviewing admin in
`validated_by` and `validated_at`, the ledger's audit columns (docs/technical.md),
and both are terminal (migration 0002), so a second review of one proof is a 409.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well (migration 0006).
"""

import asyncio
import logging
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attendance import recent_from
from app.api.ledger import (
    CURRENT_PERSON,
    ENTRY_COLUMNS,
    locked_period,
    period_facts,
    send_receipt,
    settled,
)
from app.contacts import Contact
from app.domain import billing, ledger
from app.domain.billing import SETTLING_KINDS, settled_amount
from app.domain.dates import gym_today
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.integrations import Integrations, get_integrations
from app.integrations.blobstore import BlobStore
from app.notices import PROOF_REJECTED, Notice, Notices, get_notices
from app.roles import LedgerSession
from app.schemas.ledger import Entry, RecordedPayment
from app.schemas.proofs import ProofRejection, ProofReview, RecentPayment, ReviewPeriod

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ledger/proofs", tags=["ledger"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "pending proof not found")
REVIEWED = HTTPException(status.HTTP_409_CONFLICT, "this proof was already reviewed")

# Every pending payment with a proof, oldest claim first. "Prior balance" counts the
# membership's other periods already due in the gym's timezone, each less what
# validated payments and credits settle on it, as the guardian page does (`app.api.me`).
# Attendance is the person's, over every membership, from `:recent`
# (`app.api.attendance.recent_from`).
QUEUE = f"""
    SELECT e.id, e.membership_id, m.person_id, gp.name AS person_name,
           e.amount_clp, e.method, e.claimed_at, cg.name AS claimed_by_name,
           e.proof_object_key, pl.name AS plan_name, pl.kind AS plan_kind, m.anchor_day,
           bp.id AS period_id, bp.period_start, bp.period_end, bp.due_date,
           bp.amount_due_clp, coalesce(paid.amount, 0) AS paid_clp,
           coalesce(prior.amount, 0) AS prior_balance_clp,
           coalesce(recent.amounts, '{{}}') AS recent_amounts,
           coalesce(recent.paid_at, '{{}}') AS recent_paid_at, att.classes AS attendance_30d
    FROM ledger_entry e
    JOIN membership m ON m.id = e.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    JOIN gym g ON g.id = m.gym_id
    JOIN billing_period bp ON bp.id = e.billing_period_id
    LEFT JOIN gym_person cg ON cg.gym_id = e.gym_id AND cg.person_id = e.claimed_by
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("s")})::bigint AS amount FROM ledger_entry s
        WHERE s.billing_period_id = bp.id AND s.status = :validated
          AND s.kind = ANY(CAST(:settling AS text[]))
    ) paid ON true
    LEFT JOIN LATERAL (
        SELECT sum(greatest(o.amount_due_clp - coalesce((
                   SELECT sum({settled_amount("s")}) FROM ledger_entry s
                   WHERE s.billing_period_id = o.id AND s.status = :validated
                     AND s.kind = ANY(CAST(:settling AS text[]))), 0), 0))::bigint AS amount
        FROM billing_period o
        WHERE o.membership_id = m.id AND o.id <> bp.id
          AND o.due_date <= (now() AT TIME ZONE g.timezone)::date
    ) prior ON true
    LEFT JOIN LATERAL (
        SELECT array_agg(r.amount_clp ORDER BY r.at DESC) AS amounts,
               array_agg(r.at ORDER BY r.at DESC) AS paid_at
        FROM (SELECT p.amount_clp, coalesce(p.claimed_at, p.created_at) AS at
              FROM ledger_entry p
              WHERE p.membership_id = m.id AND p.kind = :payment AND p.status = :validated
              ORDER BY at DESC LIMIT 3) r
    ) recent ON true
    CROSS JOIN LATERAL (
        SELECT count(*) AS classes FROM attendance a
        JOIN session s ON s.id = a.session_id
        JOIN membership am ON am.id = a.membership_id
        WHERE am.person_id = m.person_id
          AND s.starts_at >= :recent
    ) att
    WHERE e.kind = :payment AND e.status = :pending AND e.proof_object_key IS NOT NULL
"""

QUEUE_ORDER = " ORDER BY e.claimed_at, e.id"

# The proof to review; locked, so two admins reviewing it at once settle it once.
PROOF = (
    "SELECT id, membership_id, billing_period_id, amount_clp, status, note, claimed_by"
    " FROM ledger_entry"
    " WHERE id = :id AND kind = :payment AND proof_object_key IS NOT NULL"
    " AND billing_period_id IS NOT NULL"
)
PENDING_PROOF = text(PROOF + " FOR UPDATE")

REVIEW = text(
    "UPDATE ledger_entry SET status = :status, note = :note,"
    f" validated_by = {CURRENT_PERSON}, validated_at = now()"
    f" WHERE id = :id RETURNING {ENTRY_COLUMNS}"
)


def _params(**extra: Any) -> dict[str, Any]:
    return {
        "validated": EntryStatus.VALIDATED.value,
        "pending": EntryStatus.PENDING.value,
        "payment": EntryKind.PAYMENT.value,
        "settling": sorted(k.value for k in SETTLING_KINDS),
        **extra,
    }


async def _review(row: Any, store: BlobStore) -> ProofReview:
    stored = await store.stat(row.proof_object_key)
    paid = min(row.paid_clp, row.amount_due_clp)
    return ProofReview(
        id=row.id,
        membership_id=row.membership_id,
        person_id=row.person_id,
        person_name=row.person_name,
        amount_clp=row.amount_clp,
        method=row.method,
        claimed_at=row.claimed_at,
        claimed_by_name=row.claimed_by_name,
        proof_url=None if stored is None else store.presign_download(row.proof_object_key),
        proof_content_type=None if stored is None else stored.content_type,
        plan_name=row.plan_name,
        plan_kind=row.plan_kind,
        anchor_day=row.anchor_day,
        period=ReviewPeriod(
            id=row.period_id,
            period_start=row.period_start,
            period_end=row.period_end,
            due_date=row.due_date,
            amount_due_clp=row.amount_due_clp,
            paid_clp=paid,
            outstanding_clp=row.amount_due_clp - paid,
        ),
        prior_balance_clp=row.prior_balance_clp,
        last_payments=[
            RecentPayment(amount_clp=amount, paid_at=at)
            for amount, at in zip(row.recent_amounts, row.recent_paid_at, strict=True)
        ],
        attendance_30d=row.attendance_30d,
    )


@router.get("")
async def queue(
    session: LedgerSession, integrations: Annotated[Integrations, Depends(get_integrations)]
) -> list[ProofReview]:
    """The proofs waiting for review, oldest first: the admin pages through them."""
    zone: str = await session.scalar(text("SELECT timezone FROM gym"))
    recent = recent_from(gym_today(zone), zone)
    rows = (await session.execute(text(QUEUE + QUEUE_ORDER), _params(recent=recent))).all()
    store = integrations.blob_store
    return list(await asyncio.gather(*(_review(row, store) for row in rows)))


async def _pending_proof(session: AsyncSession, entry_id: uuid.UUID) -> Any:
    row = (
        await session.execute(PENDING_PROOF, {"id": entry_id, "payment": EntryKind.PAYMENT.value})
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    if row.status != EntryStatus.PENDING:
        raise REVIEWED
    return row


async def _record_review(session: AsyncSession, entry: LedgerEntry, entry_id: uuid.UUID) -> Entry:
    result = await session.execute(
        REVIEW, {"id": entry_id, "status": entry.status.value, "note": entry.note}
    )
    return Entry.model_validate(dict(result.one()._mapping))


@router.post("/{entry_id}/validate")
async def validate(
    entry_id: uuid.UUID,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> RecordedPayment:
    """Validate the proof: its payment counts towards the period, any overpayment
    becomes a credit, and the student is emailed a receipt."""
    # Membership, period, then the entry, the order every payment and the lapse job
    # take them in (`locked_period`): a lapse never acts on a payment mid-validation, a
    # payment recorded for the period settles before or after this one, and a second
    # review of the proof waits on the first and then finds it reviewed.
    found = (
        await session.execute(text(PROOF), {"id": entry_id, "payment": EntryKind.PAYMENT.value})
    ).one_or_none()
    if found is None:
        raise NOT_FOUND
    row, period = await locked_period(session, found.billing_period_id, found.membership_id)
    proof = await _pending_proof(session, entry_id)
    pending = LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=proof.amount_clp, note=proof.note)
    try:
        settlement = billing.validate_payment(period, pending)
    except InvalidTransition:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "billing period is already paid in full"
        ) from None
    payment = await _record_review(session, settlement.entry, entry_id)
    result = await settled(session, row.id, proof.membership_id, payment, settlement)
    await send_receipt(session, result, notices, background)
    return result


@router.post("/{entry_id}/reject")
async def reject(
    entry_id: uuid.UUID,
    body: ProofRejection,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> Entry:
    """Reject the proof with a note for the student, who is emailed it. The period
    stays open."""
    proof = await _pending_proof(session, entry_id)
    pending = LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=proof.amount_clp, note=proof.note)
    entry = await _record_review(session, ledger.reject(pending, body.note), entry_id)

    period, contact = await period_facts(session, proof.billing_period_id)
    if contact is None:
        logger.info("proof rejected: no email to send it to", extra={"entry_id": str(entry.id)})
        return entry
    notice = proof_rejected(
        contact,
        gym_id=period.gym_id,
        gym=period.gym_name,
        amount_clp=entry.amount_clp,
        period_start=period.period_start,
        period_end=period.period_end,
        note=body.note,
        dependent_name=period.person_name if contact.on_behalf_of else None,
    )
    # An address the gym typed wrong is a failed send in `message_log`, and must not
    # undo the review.
    background.add_task(notices.send, notice)
    return entry


def proof_rejected(
    contact: Contact,
    *,
    gym_id: uuid.UUID,
    gym: str,
    amount_clp: int,
    period_start: date,
    period_end: date,
    note: str,
    dependent_name: str | None,
) -> Notice:
    """The "proof rejected" notice: which proof, the admin's note, and what to do next."""
    assert contact.email is not None
    return Notice(
        PROOF_REJECTED,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym_id,
        context={
            "name": contact.name,
            "gym": gym,
            "amount_clp": amount_clp,
            "period_start": period_start,
            "period_end": period_end,
            "note": note,
            "dependent_name": dependent_name,
        },
    )
