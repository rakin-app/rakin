"""The current gym's ledger: an admin records a payment ("Registrar pago", #37), and
sees how many proofs wait for review (#35).

`POST /api/ledger/payments` records money the gym received in cash, by a transfer the
admin saw arrive, or otherwise, against one billing period of a membership. There is
no proof to check, so the entry is created validated: the admin recording it is both
who claimed it and who validated it.

It settles the period as validating a proof does (`app.domain.billing`): a period
already paid in full is a 409, and whatever is paid beyond the amount due becomes a
validated credit adjustment with no period, for a later one to use.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well (migration 0006).
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import billing
from app.domain.billing import SETTLING_KINDS, BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.roles import LedgerSession
from app.schemas.ledger import Entry, PaymentRecord, Period, RecordedPayment
from app.schemas.proofs import PendingCount

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "billing period not found")

ENTRY_COLUMNS = (
    "id, membership_id, billing_period_id, amount_clp, kind, status, method,"
    " claimed_by, claimed_at, validated_by, validated_at, proof_object_key, note, created_at"
)

# Who is acting, as `app.tenancy` set it; the recording admin.
CURRENT_PERSON = "current_setting('app.person_id')::uuid"

# Validated by the admin who records it, at the same moment; `now()` is the
# transaction's, so the payment and its credit carry one time.
INSERT_ENTRY = text(
    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
    " status, method, claimed_by, claimed_at, validated_by, validated_at, note)"
    " VALUES (current_setting('app.gym_id')::uuid, :membership_id, :billing_period_id,"
    f" :amount_clp, :kind, :status, :method, {CURRENT_PERSON}, now(), {CURRENT_PERSON}, now(),"
    f" :note) RETURNING {ENTRY_COLUMNS}"
)


async def _period(session: AsyncSession, body: PaymentRecord) -> tuple[Any, BillingPeriod]:
    """The membership's period, locked until the request ends, and what it has been paid.

    Locked, so two payments recorded at once for one period settle one after the other
    instead of both finding it open.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, period_start, period_end, amount_due_clp, due_date"
                " FROM billing_period WHERE id = :id AND membership_id = :membership_id"
                " FOR UPDATE"
            ),
            {"id": body.billing_period_id, "membership_id": body.membership_id},
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    paid = await session.scalar(
        text(
            # `sum` of a `bigint` is `numeric`, which arrives as a `Decimal`.
            "SELECT coalesce(sum(amount_clp), 0)::bigint FROM ledger_entry"
            " WHERE billing_period_id = :id AND status = :status AND kind = ANY(:kinds)"
        ),
        {
            "id": row.id,
            "status": EntryStatus.VALIDATED.value,
            "kinds": [k.value for k in SETTLING_KINDS],
        },
    )
    period = BillingPeriod(
        period_start=row.period_start,
        period_end=row.period_end,
        amount_due_clp=row.amount_due_clp,
        due_date=row.due_date,
        paid_clp=min(paid, row.amount_due_clp),
        closed=paid >= row.amount_due_clp,
    )
    return row, period


async def _insert(session: AsyncSession, entry: LedgerEntry, **columns: Any) -> Entry:
    result = await session.execute(
        INSERT_ENTRY,
        {
            "amount_clp": entry.amount_clp,
            "kind": entry.kind.value,
            "status": entry.status.value,
            "note": entry.note,
            "method": None,
            **columns,
        },
    )
    return Entry.model_validate(dict(result.one()._mapping))


@router.post("/payments", status_code=status.HTTP_201_CREATED)
async def record_payment(body: PaymentRecord, session: LedgerSession) -> RecordedPayment:
    row, period = await _period(session, body)
    payment = LedgerEntry(
        kind=EntryKind.PAYMENT,
        amount_clp=body.amount_clp,
        status=EntryStatus.VALIDATED,
        note=body.note,
    )
    try:
        settlement = billing.apply(period, payment)
    except InvalidTransition:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "billing period is already paid in full"
        ) from None

    recorded = await _insert(
        session,
        settlement.entry,
        membership_id=body.membership_id,
        billing_period_id=row.id,
        method=body.method.value,
    )
    credit = None
    if settlement.credit is not None:
        credit = await _insert(
            session, settlement.credit, membership_id=body.membership_id, billing_period_id=None
        )
    settled = settlement.period
    return RecordedPayment(
        payment=recorded,
        credit=credit,
        period=Period(
            id=row.id,
            amount_due_clp=settled.amount_due_clp,
            paid_clp=settled.paid_clp,
            outstanding_clp=settled.outstanding_clp,
            closed=settled.closed,
        ),
    )


@router.get("/pending")
async def pending(session: LedgerSession) -> PendingCount:
    """Payments students claimed with a proof, waiting to be validated or rejected: the
    admin's pending badge."""
    count = await session.scalar(
        text("SELECT count(*) FROM ledger_entry WHERE kind = :payment AND status = :pending"),
        {"payment": EntryKind.PAYMENT.value, "pending": EntryStatus.PENDING.value},
    )
    return PendingCount(count=count or 0)
