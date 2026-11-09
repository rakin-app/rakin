"""The current gym's ledger: an admin records a payment ("Registrar pago", #37), sees
how many proofs wait for review (#35), and reads one membership's ledger for the
member detail ("Ficha de alumno", #60).

`POST /api/ledger/payments` records money the gym received in cash, by a transfer the
admin saw arrive, or otherwise, against one billing period of a membership. There is
no proof to check, so the entry is created validated: the admin recording it is both
who claimed it and who validated it.

It settles the period as validating a proof does (`app.domain.billing`): a period
already paid in full is a 409, and whatever is paid beyond the amount due becomes a
validated credit adjustment with no period, for a later one to use.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well (migration 0006).
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import billing
from app.domain.billing import SETTLING_KINDS, BillingPeriod, Settlement
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.roles import LedgerSession
from app.schemas.ledger import (
    Entry,
    MembershipLedger,
    OpenPeriod,
    PaymentRecord,
    Period,
    RecordedPayment,
    TimelineEntry,
)
from app.schemas.proofs import PendingCount

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "billing period not found")
NO_MEMBERSHIP = HTTPException(status.HTTP_404_NOT_FOUND, "membership not found")

# The member detail shows this many of a membership's latest entries: years of
# monthly charges and payments.
TIMELINE_LIMIT = 100

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


# Taken before the period's lock, in that order wherever both are taken.
LOCK_MEMBERSHIP = text("SELECT FROM membership WHERE id = :membership_id FOR UPDATE")


async def locked_period(
    session: AsyncSession, period_id: uuid.UUID, membership_id: uuid.UUID
) -> tuple[Any, BillingPeriod]:
    """The membership's period, locked until the request ends, and what it has been paid.

    The membership is locked first, as the nightly `lapse` job locks it before it reads
    what is unpaid (`app.jobs.lapse`): a payment and a lapse of one membership run one
    after the other, so the job never lapses a member whose payment is mid-flight. Then
    the period, so two payments recorded or validated at once for one period settle one
    after the other instead of both finding it open.
    """
    await session.execute(LOCK_MEMBERSHIP, {"membership_id": membership_id})
    row = (
        await session.execute(
            text(
                "SELECT id, period_start, period_end, amount_due_clp, due_date"
                " FROM billing_period WHERE id = :id AND membership_id = :membership_id"
                " FOR UPDATE"
            ),
            {"id": period_id, "membership_id": membership_id},
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


async def insert_entry(session: AsyncSession, entry: LedgerEntry, **columns: Any) -> Entry:
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
    row, period = await locked_period(session, body.billing_period_id, body.membership_id)
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

    recorded = await insert_entry(
        session,
        settlement.entry,
        membership_id=body.membership_id,
        billing_period_id=row.id,
        method=body.method.value,
    )
    return await settled(session, row.id, body.membership_id, recorded, settlement)


async def settled(
    session: AsyncSession,
    period_id: uuid.UUID,
    membership_id: uuid.UUID,
    payment: Entry,
    settlement: Settlement,
) -> RecordedPayment:
    """Record the credit `settlement` leaves, if any, and the period as `payment` leaves it."""
    credit = None
    if settlement.credit is not None:
        credit = await insert_entry(
            session, settlement.credit, membership_id=membership_id, billing_period_id=None
        )
    period = settlement.period
    return RecordedPayment(
        payment=payment,
        credit=credit,
        period=Period(
            id=period_id,
            amount_due_clp=period.amount_due_clp,
            paid_clp=period.paid_clp,
            outstanding_clp=period.outstanding_clp,
            closed=period.closed,
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


# The membership's periods that validated payments and credit leave short, settled as
# `locked_period` settles them, with whether each is due by today in the gym's
# timezone and how many days past due it is.
OPEN_PERIODS = text(
    """
    SELECT bp.id, bp.period_start, bp.period_end, bp.due_date, bp.amount_due_clp,
           least(coalesce(paid.amount, 0), bp.amount_due_clp) AS paid_clp,
           bp.due_date <= t.today AS due,
           greatest(t.today - bp.due_date, 0) AS days_overdue
    FROM billing_period bp
    JOIN gym g ON g.id = bp.gym_id
    CROSS JOIN LATERAL (SELECT (now() AT TIME ZONE g.timezone)::date AS today) t
    LEFT JOIN LATERAL (
        SELECT sum(e.amount_clp)::bigint AS amount FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = :validated
          AND e.kind = ANY(CAST(:settling AS text[]))
    ) paid ON true
    WHERE bp.membership_id = :id AND coalesce(paid.amount, 0) < bp.amount_due_clp
    ORDER BY bp.period_start, bp.id
    """
)

TIMELINE = text(
    """
    SELECT e.id, e.kind, e.status, e.amount_clp, e.method, e.billing_period_id,
           bp.period_start, e.note, e.created_at, vp.name AS validated_by_name,
           e.validated_at
    FROM ledger_entry e
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    LEFT JOIN gym_person vp ON vp.gym_id = e.gym_id AND vp.person_id = e.validated_by
    WHERE e.membership_id = :id
    ORDER BY e.created_at DESC, e.id DESC
    LIMIT :limit
    """
)


@router.get("/memberships/{membership_id}")
async def membership_ledger(membership_id: uuid.UUID, session: LedgerSession) -> MembershipLedger:
    """What the membership owes, and its latest entries: the member detail's money."""
    found = await session.scalar(
        text("SELECT EXISTS (SELECT FROM membership WHERE id = :id)"), {"id": membership_id}
    )
    if not found:
        raise NO_MEMBERSHIP
    params = {
        "id": membership_id,
        "validated": EntryStatus.VALIDATED.value,
        "settling": sorted(k.value for k in SETTLING_KINDS),
    }
    periods = (await session.execute(OPEN_PERIODS, params)).all()
    entries = (
        await session.execute(TIMELINE, {"id": membership_id, "limit": TIMELINE_LIMIT})
    ).all()
    open_periods = [
        OpenPeriod(
            id=row.id,
            period_start=row.period_start,
            period_end=row.period_end,
            due_date=row.due_date,
            amount_due_clp=row.amount_due_clp,
            paid_clp=row.paid_clp,
            outstanding_clp=row.amount_due_clp - row.paid_clp,
            due=row.due,
            days_overdue=row.days_overdue,
        )
        for row in periods
    ]
    return MembershipLedger(
        open_periods=open_periods,
        owed_clp=sum(p.outstanding_clp for p in open_periods if p.due),
        entries=[TimelineEntry.model_validate(row, from_attributes=True) for row in entries],
    )
