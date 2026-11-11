"""The current gym's ledger: an admin records a payment ("Registrar pago", #37), sees
how many proofs wait for review (#35), reads one membership's ledger for the member
detail ("Ficha de alumno", #60), lists what is overdue for the owner's dashboard
("Hoy", #58), and reads the whole gym's ledger for the ledger book ("Libro de pagos",
#39). The member detail and the book list freezes (#26) among the entries, as lines
with no amount where each started and ended.

An admin also corrects what a period owes with an adjustment on it, with a note saying
why, and gives back part or all of a validated payment with a refund of it (#38). Each
is a new entry, validated by the admin making it, and settles the period as
`app.domain.billing` says: an adjustment in the member's favour counts towards it, one
against them is owed on top, and a refund no longer counts what it gives back.

`POST /api/ledger/payments` records money the gym received in cash, by a transfer the
admin saw arrive, or otherwise, against one billing period of a membership. There is
no proof to check, so the entry is created validated: the admin recording it is both
who claimed it and who validated it.

It settles the period as validating a proof does (`app.domain.billing`): a period
already paid in full is a 409, and whatever is paid beyond the amount due becomes a
validated credit adjustment with no period, for a later one to use.

Either way the student, or their guardian, is emailed a receipt (`receipt_for`): the
period the payment covers, what is left of it, and the membership's running balance.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well (migration 0006).
"""

import logging
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.entries import insert_entry
from app.api.extra_lines import refund_line_payment
from app.api.people import people_matching
from app.contacts import Contact, contact_for
from app.db import driver_connection
from app.domain import billing
from app.domain.billing import SETTLING_KINDS, Billing, BillingPeriod, Settlement, settled_amount
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.jobs.billing import billable_membership, write_billing
from app.notices import RECEIPT, Notice, Notices, get_notices
from app.roles import LedgerSession
from app.schemas.ledger import (
    AdjustmentRecord,
    AheadPeriod,
    AheadQuote,
    BookEntry,
    BookExtra,
    BookFilter,
    BookFreeze,
    BookKpis,
    BookPeriod,
    Entry,
    FreezeLine,
    LedgerBook,
    LedgerPeriod,
    MembershipLedger,
    OpenPeriod,
    Overdue,
    OverduePeriod,
    PaymentAheadRecord,
    PaymentRecord,
    Period,
    PersonRef,
    RecordedAdjustment,
    RecordedAhead,
    RecordedPayment,
    RecordedRefund,
    RefundablePayment,
    RefundRecord,
    TimelineEntry,
)
from app.schemas.proofs import PendingCount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "billing period not found")
NO_MEMBERSHIP = HTTPException(status.HTTP_404_NOT_FOUND, "membership not found")

# The member detail shows this many of a membership's latest entries: years of
# monthly charges and payments.
TIMELINE_LIMIT = 100

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
            f"SELECT coalesce(sum({settled_amount('ledger_entry')}), 0)::bigint FROM ledger_entry"
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
        paid_clp=paid,
        closed=paid >= row.amount_due_clp,
    )
    return row, period


@router.post("/payments", status_code=status.HTTP_201_CREATED)
async def record_payment(
    body: PaymentRecord,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> RecordedPayment:
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
    result = await settled(session, row.id, body.membership_id, recorded, settlement)
    await send_receipt(session, result, notices, background)
    return result


# Paying ahead (#196): the next periods of a membership with none open are billed on
# the spot, as the nightly job would bill them later (`app.jobs.billing`), and each is
# paid with a payment of its own. The job then finds them there and bills on after
# them; a refund gives back a month as it gives back any payment.

CANNOT_PAY_AHEAD = HTTPException(
    status.HTTP_409_CONFLICT,
    "only an Active monthly or prepaid membership with no period open pays ahead",
)

AMOUNT_CHANGED = HTTPException(
    status.HTTP_409_CONFLICT, "the amount is not what those periods cost"
)


async def ahead_of(session: AsyncSession, membership_id: uuid.UUID, count: int) -> Billing | None:
    """The next `count` periods the membership would pay ahead; `None` when it cannot:
    a period still open is paid first."""
    conn = await driver_connection(session)
    billable = await billable_membership(conn, membership_id)
    if billable is None:
        raise NO_MEMBERSHIP
    params = {
        "id": membership_id,
        "validated": EntryStatus.VALIDATED.value,
        "settling": sorted(k.value for k in SETTLING_KINDS),
    }
    if (await session.execute(OPEN_PERIODS, params)).first() is not None:
        return None
    owed = billing.periods_ahead(billable, count)
    return owed if owed.periods else None


@router.get("/memberships/{membership_id}/ahead")
async def ahead_quote(membership_id: uuid.UUID, session: LedgerSession) -> AheadQuote:
    """What the next periods would cost paid ahead, for "Registrar pago" to offer 1 to
    `MAX_PAID_AHEAD` of them."""
    owed = await ahead_of(session, membership_id, billing.MAX_PAID_AHEAD)
    return AheadQuote(
        periods=[
            AheadPeriod(
                period_start=p.period_start,
                period_end=p.period_end,
                amount_due_clp=p.amount_due_clp,
            )
            for p in (owed.periods if owed else ())
        ]
    )


@router.post("/payments/ahead", status_code=status.HTTP_201_CREATED)
async def record_payment_ahead(
    body: PaymentAheadRecord,
    session: LedgerSession,
    notices: Annotated[Notices, Depends(get_notices)],
    background: BackgroundTasks,
) -> RecordedAhead:
    """Bill the membership's next `periods` periods now and pay each in full, validated
    by the admin recording it, as `record_payment` pays one; one receipt for them all."""
    # Locked as a payment locks it, before anything about it is read.
    await session.execute(LOCK_MEMBERSHIP, {"membership_id": body.membership_id})
    owed = await ahead_of(session, body.membership_id, body.periods)
    if owed is None:
        raise CANNOT_PAY_AHEAD
    if sum(p.amount_due_clp for p in owed.periods) != body.amount_clp:
        raise AMOUNT_CHANGED
    written = await write_billing(await driver_connection(session), body.membership_id, owed)
    # The membership is locked and its periods were read under the lock, so none of
    # them can be there already.
    assert len(written) == len(owed.periods)

    payments, periods = [], []
    for period_id, period in written:
        if period.amount_due_clp == 0:
            continue
        payment = LedgerEntry(
            kind=EntryKind.PAYMENT,
            amount_clp=period.amount_due_clp,
            status=EntryStatus.VALIDATED,
            note=body.note,
        )
        settlement = billing.apply(period, payment)
        payments.append(
            await insert_entry(
                session,
                settlement.entry,
                membership_id=body.membership_id,
                billing_period_id=period_id,
                method=body.method.value,
            )
        )
        periods.append(period_after(period_id, settlement.period))
    result = RecordedAhead(
        payments=payments, periods=periods, paid_through=owed.periods[-1].period_end
    )
    await send_receipt_for(
        session,
        payments,
        last_period_id=periods[-1].id,
        period_outstanding_clp=0,
        notices=notices,
        background=background,
    )
    return result


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
    return RecordedPayment(
        payment=payment, credit=credit, period=period_after(period_id, settlement.period)
    )


def period_after(period_id: uuid.UUID, period: BillingPeriod) -> Period:
    """The period as an entry just settled leaves it."""
    return Period(
        id=period_id,
        amount_due_clp=period.amount_due_clp,
        paid_clp=period.paid_clp,
        outstanding_clp=period.outstanding_clp,
        closed=period.closed,
    )


@router.post("/adjustments", status_code=status.HTTP_201_CREATED)
async def record_adjustment(body: AdjustmentRecord, session: LedgerSession) -> RecordedAdjustment:
    """Correct what a period owes: in the member's favour, up to what it still owes, or
    against them, owed on top of its amount due."""
    row, period = await locked_period(session, body.billing_period_id, body.membership_id)
    try:
        settlement = billing.adjust(period, body.amount_clp, body.note)
    except InvalidTransition:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the adjustment exceeds what the period owes"
        ) from None
    adjustment = await insert_entry(
        session, settlement.entry, membership_id=body.membership_id, billing_period_id=row.id
    )
    return RecordedAdjustment(adjustment=adjustment, period=period_after(row.id, settlement.period))


NO_PAYMENT = HTTPException(status.HTTP_404_NOT_FOUND, "payment not found")

PAYMENT = text(
    "SELECT membership_id, billing_period_id, extra_line_id, amount_clp, status FROM ledger_entry"
    " WHERE id = :id AND kind = :payment"
)

# What the payment's refunds have given back; every refund is validated as it is made.
REFUNDED = text(
    "SELECT coalesce(sum(amount_clp), 0)::bigint FROM ledger_entry WHERE refund_of = :id"
)


@router.post("/refunds", status_code=status.HTTP_201_CREATED)
async def record_refund(body: RefundRecord, session: LedgerSession) -> RecordedRefund:
    """Give back part or all of a validated payment: what is left of it after its
    earlier refunds, at most. The refund carries the payment's period, or its cobro line
    (#195), which no longer counts it and may be open again: unless the membership was
    cancelled before the period started, which is then not owed (`AFTER_LEAVING`)."""
    found = (
        await session.execute(PAYMENT, {"id": body.payment_id, "payment": EntryKind.PAYMENT.value})
    ).one_or_none()
    if found is None:
        raise NO_PAYMENT
    if found.extra_line_id is not None:
        return await refund_line_payment(session, body, found)
    # Locked as a payment locks them, so two refunds of one payment, or a refund and a
    # lapse, run one after the other.
    row, period = await locked_period(session, found.billing_period_id, found.membership_id)
    refunded = await session.scalar(REFUNDED, {"id": body.payment_id})
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
        membership_id=found.membership_id,
        billing_period_id=row.id,
        method=body.method.value,
        refund_of=body.payment_id,
    )
    waived = None
    if not settlement.period.closed and await session.scalar(AFTER_LEAVING, {"id": row.id}):
        # Not owed: the member left before it started. The refund gives back what was
        # paid for it, and an adjustment of as much takes it off what it owes, so it is
        # not a debt once it falls due.
        waiver = billing.adjust(
            settlement.period,
            min(body.amount_clp, settlement.period.outstanding_clp),
            UNUSED_AFTER_LEAVING,
        )
        waived = await insert_entry(
            session, waiver.entry, membership_id=found.membership_id, billing_period_id=row.id
        )
        settlement = waiver
    return RecordedRefund(
        refund=refund, period=period_after(row.id, settlement.period), waived=waived
    )


# The period starts after its membership was cancelled, in the gym's timezone: paid
# ahead (#196) by a member who then left.
AFTER_LEAVING = text(
    "SELECT m.status = 'cancelled'"
    " AND bp.period_start > (m.cancelled_at AT TIME ZONE g.timezone)::date"
    " FROM billing_period bp JOIN membership m ON m.id = bp.membership_id"
    " JOIN gym g ON g.id = m.gym_id WHERE bp.id = :id"
)

UNUSED_AFTER_LEAVING = "Período posterior a la baja: no se cobra"


# Who a notice about a period goes to, and what it says about it. RLS keeps it to the
# current gym.
PERIOD_FACTS = text(
    "SELECT bp.period_start, bp.period_end, m.person_id, gp.name AS person_name,"
    " g.id AS gym_id, g.name AS gym_name FROM billing_period bp"
    " JOIN membership m ON m.id = bp.membership_id"
    " JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id"
    " JOIN gym g ON g.id = m.gym_id WHERE bp.id = :id"
)

# The membership's running balance (`v_balance`, 0014): owed if positive, credit if not.
BALANCE = text(
    "SELECT coalesce(sum(balance_clp), 0)::bigint FROM v_balance WHERE membership_id = :id"
)


async def period_facts(session: AsyncSession, period_id: uuid.UUID) -> tuple[Any, Contact | None]:
    """The period a notice is about, and whom to send it to: `None` if no one."""
    facts = (await session.execute(PERIOD_FACTS, {"id": period_id})).one()
    contact = await contact_for(session, facts.person_id)
    return facts, (contact if contact is not None and contact.email else None)


async def send_receipt(
    session: AsyncSession,
    recorded: RecordedPayment,
    notices: Notices,
    background: BackgroundTasks,
) -> None:
    """Email the receipt for a validated payment, after the response, which is after
    the payment has committed."""
    payment = recorded.payment
    assert payment.billing_period_id is not None
    await send_receipt_for(
        session,
        [payment],
        last_period_id=payment.billing_period_id,
        period_outstanding_clp=recorded.period.outstanding_clp,
        notices=notices,
        background=background,
    )


async def send_receipt_for(
    session: AsyncSession,
    payments: list[Entry],
    *,
    last_period_id: uuid.UUID,
    period_outstanding_clp: int,
    notices: Notices,
    background: BackgroundTasks,
) -> None:
    """Email one receipt for `payments` of one membership, oldest period first: their
    total, from the first one's period to the end of `last_period_id`'s."""
    first = payments[0]
    assert first.billing_period_id is not None
    facts, contact = await period_facts(session, first.billing_period_id)
    if contact is None:
        logger.info("receipt: no email to send it to", extra={"entry_id": str(first.id)})
        return
    last = facts if last_period_id == first.billing_period_id else None
    if last is None:
        last, _ = await period_facts(session, last_period_id)
    balance = await session.scalar(BALANCE, {"id": first.membership_id})
    notice = receipt(
        contact,
        gym_id=facts.gym_id,
        gym=facts.gym_name,
        amount_clp=sum(p.amount_clp for p in payments),
        period_start=facts.period_start,
        period_end=last.period_end,
        period_outstanding_clp=period_outstanding_clp,
        balance_clp=int(balance or 0),
        dependent_name=facts.person_name if contact.on_behalf_of else None,
    )
    # An address the gym typed wrong is a failed send in `message_log`, and must not
    # undo the payment.
    background.add_task(notices.send, notice)


def receipt(
    contact: Contact,
    *,
    gym_id: uuid.UUID,
    gym: str,
    amount_clp: int,
    period_start: date,
    period_end: date,
    period_outstanding_clp: int,
    balance_clp: int,
    dependent_name: str | None,
) -> Notice:
    """The receipt: what was paid, the period it covers, and the balance it leaves."""
    assert contact.email is not None
    return Notice(
        RECEIPT,
        to=contact.email,
        person_id=contact.person_id,
        gym_id=gym_id,
        context={
            "name": contact.name,
            "gym": gym,
            "amount_clp": amount_clp,
            "period_start": period_start,
            "period_end": period_end,
            "period_outstanding_clp": period_outstanding_clp,
            "balance_clp": balance_clp,
            "dependent_name": dependent_name,
        },
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
    f"""
    SELECT bp.id, bp.period_start, bp.period_end, bp.due_date, bp.amount_due_clp,
           least(coalesce(paid.amount, 0), bp.amount_due_clp) AS paid_clp,
           bp.due_date <= t.today AS due,
           greatest(t.today - bp.due_date, 0) AS days_overdue
    FROM billing_period bp
    JOIN gym g ON g.id = bp.gym_id
    CROSS JOIN LATERAL (SELECT (now() AT TIME ZONE g.timezone)::date AS today) t
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("e")})::bigint AS amount FROM ledger_entry e
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
           e.validated_at, e.refund_of
    FROM ledger_entry e
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    LEFT JOIN gym_person vp ON vp.gym_id = e.gym_id AND vp.person_id = e.validated_by
    WHERE e.membership_id = :id
    ORDER BY e.created_at DESC, e.id DESC
    LIMIT :limit
    """
)


# Every period of the membership, newest first, with what it still owes settled as
# `OPEN_PERIODS` settles it: what an adjustment may go to (#38). Not capped as the
# timeline is, so a period older than its latest entries is still there.
PERIODS = text(
    f"""
    SELECT bp.id, bp.period_start, bp.period_end,
           greatest(bp.amount_due_clp - coalesce(paid.amount, 0), 0) AS outstanding_clp
    FROM billing_period bp
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("e")})::bigint AS amount FROM ledger_entry e
        WHERE e.billing_period_id = bp.id AND e.status = :validated
          AND e.kind = ANY(CAST(:settling AS text[]))
    ) paid ON true
    WHERE bp.membership_id = :id
    ORDER BY bp.period_start DESC, bp.id
    """
)

# The membership's validated payments with something left to give back after their
# refunds, newest first: what a refund may go to (#38), however old.
REFUNDABLE = text(
    """
    SELECT p.id, p.billing_period_id, bp.period_start, p.amount_clp, p.method,
           p.validated_at, p.amount_clp - coalesce(r.amount, 0) AS refundable_clp
    FROM ledger_entry p
    JOIN billing_period bp ON bp.id = p.billing_period_id
    LEFT JOIN LATERAL (
        SELECT sum(x.amount_clp)::bigint AS amount FROM ledger_entry x WHERE x.refund_of = p.id
    ) r ON true
    WHERE p.membership_id = :id AND p.kind = 'payment' AND p.status = 'validated'
      AND p.amount_clp > coalesce(r.amount, 0)
    ORDER BY p.validated_at DESC, p.id
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
    every_period = [
        LedgerPeriod.model_validate(row, from_attributes=True)
        for row in await session.execute(PERIODS, params)
    ]
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
        freezes=[
            FreezeLine.model_validate(row, from_attributes=True)
            for row in await session.execute(MEMBERSHIP_FREEZES, {"id": membership_id})
        ],
        periods=every_period,
        refundable_payments=[
            RefundablePayment.model_validate(row, from_attributes=True)
            for row in await session.execute(REFUNDABLE, {"id": membership_id})
        ],
        paid_through=billing.paid_through(
            (p.period_start, p.period_end, p.outstanding_clp) for p in every_period
        ),
    )


# The gym's timezone and today in it; every month the book shows is a gym-local one.
GYM_CLOCK = """
    SELECT g.timezone, (now() AT TIME ZONE g.timezone)::date AS today
    FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
"""

# Each freeze's start and end as lines, the end once it has come, in the gym's timezone:
# the days it actually ran, after an end moved or ended early (#115). A freeze of no
# days, ended or called off on its first day, has none; one booked ahead has none until
# it starts.
FREEZE_EDGES = f"""
    SELECT f.id AS freeze_id, f.membership_id, edge.kind AS edge, edge.day,
           f.from_date, f.to_date, f.reason
    FROM membership_freeze f
    CROSS JOIN ({GYM_CLOCK}) t
    CROSS JOIN LATERAL (VALUES ('start', f.from_date), ('end', f.to_date)) AS edge (kind, day)
    WHERE edge.day <= t.today AND f.to_date > f.from_date AND f.started
"""

# Newest first; a freeze starting the day another ended is the newer of the two lines.
FREEZE_ORDER = "fe.day DESC, fe.edge = 'start' DESC, fe.freeze_id"

MEMBERSHIP_FREEZES = text(
    f"SELECT fe.* FROM ({FREEZE_EDGES}) fe WHERE fe.membership_id = :id ORDER BY {FREEZE_ORDER}"
)

# An entry's gym-local day, for `e`, a `ledger_entry`, and `t`, `GYM_CLOCK`.
ENTRY_DAY = "(e.created_at AT TIME ZONE t.timezone)::date"

# The day the book files an entry under, for `e`, `t` and `bp`, the entry's period: a
# charge's is the day its period starts, so a November charge billed in late October is
# November's, as its "Período" and the overdue KPI say (#206); any other entry's, a
# payment's included, is the day it was made.
BOOK_DAY = (
    f"CASE WHEN e.kind = 'charge' AND bp.id IS NOT NULL THEN bp.period_start ELSE {ENTRY_DAY} END"
)

# The months with entries, newest first. RLS keeps them to the gym.
BOOK_MONTHS = text(
    f"""
    SELECT DISTINCT date_trunc('month', {BOOK_DAY})::date AS month
    FROM ledger_entry e CROSS JOIN ({GYM_CLOCK}) t
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    ORDER BY month DESC
    """
)

# The ledger as the book lists it: each entry with whose membership it is, the
# guardian who pays for them, and its period settled as `OPEN_PERIODS` settles it. An
# entry on a cobro extra line (#195) has no membership: `m` is whoever's line it is.
BOOK_ROWS = f"""
    SELECT e.id, e.created_at, e.kind, e.status, e.amount_clp, e.method, e.note,
           e.refund_of, e.membership_id, pl.name AS plan_name, em.status AS membership_status,
           m.person_id, mp.name AS person_name,
           x.id AS extra_charge_id, x.title AS charge_title, x.category AS charge_category,
           gl.guardian_person_id AS guardian_id, gp.name AS guardian_name,
           bp.period_start, bp.period_end, bp.due_date,
           bp.amount_due_clp - least(coalesce(paid.amount, 0), bp.amount_due_clp)
               AS outstanding_clp,
           CASE WHEN coalesce(paid.amount, 0) < bp.amount_due_clp
                THEN greatest(t.today - bp.due_date, 0) ELSE 0 END AS days_overdue,
           vp.name AS validated_by_name
    FROM ledger_entry e
    CROSS JOIN ({GYM_CLOCK}) t
    LEFT JOIN membership em ON em.id = e.membership_id
    LEFT JOIN plan pl ON pl.id = em.plan_id
    LEFT JOIN extra_line xl ON xl.id = e.extra_line_id
    LEFT JOIN extra_charge x ON x.id = xl.extra_charge_id
    CROSS JOIN LATERAL (
        SELECT e.gym_id, coalesce(em.person_id, xl.person_id) AS person_id
    ) m
    JOIN gym_person mp ON mp.gym_id = m.gym_id AND mp.person_id = m.person_id
    LEFT JOIN guardian_link gl
        ON gl.gym_id = m.gym_id AND gl.dependent_person_id = m.person_id
    LEFT JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.guardian_person_id
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("s")})::bigint AS amount FROM ledger_entry s
        WHERE s.billing_period_id = bp.id AND s.status = 'validated'
          AND s.kind = ANY(CAST(:settling AS text[]))
    ) paid ON bp.id IS NOT NULL
    LEFT JOIN gym_person vp ON vp.gym_id = e.gym_id AND vp.person_id = e.validated_by
"""

IN_MONTH = f"{BOOK_DAY} >= :month AND {BOOK_DAY} < (:month + interval '1 month')::date"

# What each filter keeps of `BOOK_ROWS`.
BOOK_FILTERS = {
    BookFilter.ALL: IN_MONTH,
    BookFilter.PENDING: "e.kind = 'payment' AND e.status = 'pending'",
    BookFilter.OVERDUE: (
        "e.kind = 'charge' AND e.billing_period_id IN (SELECT billing_period_id FROM v_overdue)"
    ),
    BookFilter.KIDS: f"{IN_MONTH} AND gl.dependent_person_id IS NOT NULL",
}

# The month's freeze lines as the book lists them, with whose membership it is, as
# `BOOK_ROWS` has it.
BOOK_FREEZES = f"""
    SELECT fe.*, pl.name AS plan_name, m.person_id, mp.name AS person_name,
           gl.guardian_person_id AS guardian_id, gp.name AS guardian_name
    FROM ({FREEZE_EDGES}) fe
    JOIN membership m ON m.id = fe.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person mp ON mp.gym_id = m.gym_id AND mp.person_id = m.person_id
    LEFT JOIN guardian_link gl
        ON gl.gym_id = m.gym_id AND gl.dependent_person_id = m.person_id
    LEFT JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.guardian_person_id
    WHERE fe.day >= :month AND fe.day < (:month + interval '1 month')::date
"""

# What each filter keeps of `BOOK_FREEZES`; a filter of money owed keeps none.
BOOK_FREEZE_FILTERS = {
    BookFilter.ALL: "true",
    BookFilter.KIDS: "gl.dependent_person_id IS NOT NULL",
}

# The membership statuses whose periods "Esperado" counts (`BOOK_KPIS`).
EXPECTED_STATUSES = ("active", "lapsed")

# The book's KPIs. Collected and expected are the month's; pending and overdue, and the
# membership counts, are how the gym stands today. Collected is net of the month's
# refunds, which it reports beside it (#126). Overdue is every unpaid period past due
# (`v_overdue`), as the owner's "Vencidos" lists them: a lapsed, frozen or cancelled
# membership still owes what it owed (#207).
#
# Expected ("Esperado") is what is owed for the month: the periods falling due in it of
# active and lapsed memberships, since a lapsed member still owes what was billed. A
# cancelled membership's periods are not expected, and neither are a trial's or a
# frozen one's.
BOOK_KPIS = text(
    """
    SELECT
        (SELECT coalesce(sum(income_clp), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS collected_clp,
        (SELECT coalesce(sum(payments), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS collected_payments,
        (SELECT coalesce(sum(refunds_clp), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS refunded_clp,
        (SELECT coalesce(sum(refunds), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS refunds,
        (SELECT coalesce(sum(extra_income_clp), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS collected_extra_clp,
        pending.amount AS pending_clp, pending.n AS pending_payments,
        overdue.amount AS overdue_clp, overdue.members AS overdue_members,
        overdue.avg_days AS overdue_avg_days,
        (SELECT coalesce(sum(bp.amount_due_clp), 0)::bigint FROM billing_period bp
         JOIN membership m ON m.id = bp.membership_id
         WHERE m.status = ANY(CAST(:expected_statuses AS text[]))
           AND bp.due_date >= :month AND bp.due_date < (:month + interval '1 month')::date)
            AS expected_clp,
        (SELECT count(*) FROM membership WHERE status = 'active') AS active_memberships,
        (SELECT count(*) FROM membership WHERE status = 'frozen') AS frozen_memberships
    FROM (
        SELECT coalesce(sum(amount_clp), 0)::bigint AS amount, count(*) AS n
        FROM ledger_entry WHERE kind = 'payment' AND status = 'pending'
    ) pending
    CROSS JOIN (
        SELECT coalesce(sum(outstanding), 0)::bigint AS amount, count(*) AS members,
               coalesce(avg(days), 0)::float AS avg_days
        FROM (
            SELECT person_id, sum(outstanding_clp) AS outstanding, max(days_overdue) AS days
            FROM v_overdue GROUP BY person_id
        ) per_member
    ) overdue
    """
)

BOOK_PAGE_MAX = 200


@router.get("/book")
async def ledger_book(
    session: LedgerSession,
    # Any day of the month to show; the current one in the gym's timezone by default.
    month: date | None = None,
    book_filter: Annotated[BookFilter, Query(alias="filter")] = BookFilter.ALL,
    limit: Annotated[int, Query(ge=1, le=BOOK_PAGE_MAX)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    # A member's name, phone or RUT, as the member list searches them (#107).
    q: Annotated[str, Query(max_length=100)] = "",
) -> LedgerBook:
    """The gym's ledger, every entry newest first, with the month's KPIs ("Libro de
    pagos", #39). Owner and admin only: a coach never sees money.

    `q` keeps the entries and freeze lines of the members it finds, and of the
    dependents of the guardians it finds, within the filter. The KPIs stay the gym's."""
    clock = (await session.execute(text(GYM_CLOCK))).one()
    current = clock.today.replace(day=1)
    shown = month.replace(day=1) if month else current
    with_entries = [row.month for row in await session.execute(BOOK_MONTHS)]
    months = sorted({*with_entries, current, shown}, reverse=True)

    searched, search_params = book_search(q)
    params: dict[str, Any] = {
        "month": shown,
        "settling": sorted(k.value for k in SETTLING_KINDS),
        **search_params,
    }
    matching = f"{BOOK_ROWS} WHERE {BOOK_FILTERS[book_filter]} AND {searched}"
    total = await session.scalar(text(f"SELECT count(*) FROM ({matching}) f"), params)
    rows = await session.execute(
        # By the day each is filed under, the one "Fecha" shows (#206), then as made.
        text(
            f"{matching} ORDER BY {BOOK_DAY} DESC, e.created_at DESC, e.id DESC"
            " LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    )
    kpis = (
        await session.execute(
            BOOK_KPIS, {"month": shown, "expected_statuses": list(EXPECTED_STATUSES)}
        )
    ).one()
    freezes = []
    if book_filter in BOOK_FREEZE_FILTERS:
        freeze_rows = await session.execute(
            text(
                f"{BOOK_FREEZES} AND {BOOK_FREEZE_FILTERS[book_filter]} AND {searched}"
                f" ORDER BY {FREEZE_ORDER}"
            ),
            {"month": shown, **search_params},
        )
        freezes = [book_freeze(row) for row in freeze_rows]
    return LedgerBook(
        month=shown,
        months=months,
        timezone=clock.timezone,
        kpis=BookKpis.model_validate(kpis, from_attributes=True),
        items=[book_entry(row) for row in rows],
        total=total or 0,
        freezes=freezes,
    )


def book_search(q: str) -> tuple[str, dict[str, Any]]:
    """What `q` keeps of `BOOK_ROWS` and `BOOK_FREEZES`: the membership's member, or
    the guardian who pays for them, is one the member list's search finds."""
    if not q.strip():
        return "true", {}
    people, params = people_matching(q.strip())
    return f"(m.person_id IN ({people}) OR gl.guardian_person_id IN ({people}))", params


def book_freeze(row: Any) -> BookFreeze:
    return BookFreeze(
        freeze_id=row.freeze_id,
        edge=row.edge,
        day=row.day,
        from_date=row.from_date,
        to_date=row.to_date,
        reason=row.reason,
        membership_id=row.membership_id,
        plan_name=row.plan_name,
        person=PersonRef(id=row.person_id, name=row.person_name),
        guardian=None
        if row.guardian_id is None
        else PersonRef(id=row.guardian_id, name=row.guardian_name),
    )


def book_entry(row: Any) -> BookEntry:
    return BookEntry(
        id=row.id,
        created_at=row.created_at,
        kind=row.kind,
        status=row.status,
        amount_clp=row.amount_clp,
        method=row.method,
        note=row.note,
        refund_of=row.refund_of,
        membership_id=row.membership_id,
        plan_name=row.plan_name,
        membership_status=row.membership_status,
        person=PersonRef(id=row.person_id, name=row.person_name),
        guardian=None
        if row.guardian_id is None
        else PersonRef(id=row.guardian_id, name=row.guardian_name),
        period=None
        if row.period_start is None
        else BookPeriod(
            period_start=row.period_start,
            period_end=row.period_end,
            due_date=row.due_date,
            outstanding_clp=row.outstanding_clp,
            days_overdue=row.days_overdue,
        ),
        validated_by_name=row.validated_by_name,
        extra=None
        if row.extra_charge_id is None
        else BookExtra(
            id=row.extra_charge_id, title=row.charge_title, category=row.charge_category
        ),
    )


# Every membership's unpaid periods past due, whatever its status: a plan that lapsed
# or was cancelled still owes them until they are paid or adjusted (#207).
OVERDUE = text(
    """
    SELECT o.billing_period_id, o.membership_id, o.person_id, gp.name AS person_name,
           pl.name AS plan_name, o.membership_status, o.period_start, o.due_date,
           o.outstanding_clp, o.days_overdue
    FROM v_overdue o
    JOIN membership m ON m.id = o.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.gym_id = o.gym_id AND gp.person_id = o.person_id
    ORDER BY o.days_overdue DESC, gp.name, o.billing_period_id
    """
)


@router.get("/overdue")
async def overdue(session: LedgerSession) -> Overdue:
    """The periods past due and not paid in full, of memberships in any status: the
    owner's "Vencidos" ("Hoy", #58)."""
    periods = [
        OverduePeriod.model_validate(row, from_attributes=True)
        for row in (await session.execute(OVERDUE)).all()
    ]
    return Overdue(
        total_clp=sum(p.outstanding_clp for p in periods),
        periods=periods,
    )
