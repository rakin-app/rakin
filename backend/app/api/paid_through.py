"""Pagado hasta… (#286): the payments or gifts up to a date, for a member who paid
before the gym used Rakin.

docs/design/billing-corrections.md, section 1 (C14). "Pagado hasta" is computed from the
periods (`billing.paid_through`) and is never set by hand: a date typed there would say
"paid" while the ledger says "owes". This shortcut writes the entries instead. Every
period of the membership starting on or before the chosen date is settled: those billed
and still owing, then those not billed yet, which it bills first as paying ahead does
(`billing.periods_through`, #196), at most `MAX_PAID_AHEAD` of them. Each is settled with
what it still owes, in one transaction:

- `paid`: a validated payment with the method given and the note "Pagado antes de
  Rakin". It counts in "Cobrado" in the month it is recorded in, as any payment does. No
  receipt is emailed: the money arrived long ago.
- `gift`: a validated adjustment in the member's favour, the note "Bonificación"
  ("le regalamos diciembre"), as "Cambiar monto" writes one.

Each writes a `ledger_corrected` audit row (0048) for its period, marked `paid_through`
with the mode, and the period and balance before and after.

`GET /api/ledger/memberships/{id}/paid-through?through=` quotes it: the periods, their
total and the "Pagado hasta" it leaves. `POST` the same path writes it, refused with a 409
whose `code` says why (`PaidThroughRefusal`): not an Active monthly or prepaid plan, a
date before the plan started (that is the Historial's, #295), one paid through already,
one too far ahead, a proof waiting on one of the periods, or a total not the quoted one.

Owner and admin only (`LedgerSession`); RLS holds a coach to it as well.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.corrections import record_correction
from app.api.entries import insert_entry
from app.api.ledger import (
    LOCK_MEMBERSHIP,
    NO_MEMBERSHIP,
    figures,
    period_after,
    period_under_lock,
)
from app.db import driver_connection
from app.domain import billing
from app.domain.billing import SETTLING_KINDS, Billing, BillingPeriod, settled_amount
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.domain.membership import MembershipStatus
from app.jobs.billing import billable_membership, write_billing
from app.permissions import LedgerReadSession, LedgerSession
from app.schemas.ledger import (
    Entry,
    Method,
    PaidThroughConflict,
    PaidThroughMode,
    PaidThroughPeriod,
    PaidThroughQuote,
    PaidThroughRecord,
    PaidThroughRefusal,
    Period,
    RecordedPaidThrough,
)

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

# The notes the entries carry, which the student reads on their page.
PAID_NOTE = "Pagado antes de Rakin"
GIFT_NOTE = "Bonificación"

# Every period of the membership, oldest first, with what it was paid and whether a
# proof waits on it.
PERIODS = text(
    f"""
    SELECT bp.id, bp.period_start, bp.period_end, bp.amount_due_clp,
           coalesce(paid.amount, 0)::bigint AS paid_clp, coalesce(paid.pending, false) AS pending
    FROM billing_period bp
    LEFT JOIN LATERAL (
        SELECT sum({settled_amount("e")}) FILTER (
                   WHERE e.status = :validated AND e.kind = ANY(CAST(:settling AS text[]))
               ) AS amount,
               bool_or(e.kind = 'payment' AND e.status = 'pending') AS pending
        FROM ledger_entry e WHERE e.billing_period_id = bp.id
    ) paid ON true
    WHERE bp.membership_id = :id
    ORDER BY bp.period_start, bp.id
    """
)


def refused(code: PaidThroughRefusal, message: str, **facts: Any) -> HTTPException:
    conflict = PaidThroughConflict(code=code, message=message, **facts)
    return HTTPException(status.HTTP_409_CONFLICT, conflict.model_dump(mode="json"))


@dataclass(frozen=True)
class Settling:
    """What settling up to a date writes: the billed periods still owing, by id, and
    those to bill; and the "Pagado hasta" it leaves."""

    owing: list[tuple[uuid.UUID, date, date, int]]
    unbilled: Billing
    paid_through: date

    @property
    def periods(self) -> list[PaidThroughPeriod]:
        billed = [
            PaidThroughPeriod(period_start=s, period_end=e, amount_clp=owed, billed=True)
            for _, s, e, owed in self.owing
        ]
        return billed + [
            PaidThroughPeriod(
                period_start=p.period_start,
                period_end=p.period_end,
                amount_clp=p.amount_due_clp,
                billed=False,
            )
            for p in self.unbilled.periods
        ]

    @property
    def total_clp(self) -> int:
        return sum(p.amount_clp for p in self.periods)


async def plan_through(session: AsyncSession, membership_id: uuid.UUID, through: date) -> Settling:
    """What settling the membership up to `through` writes, or the refusal. The caller
    writing it holds the membership locked, so what is read is what it settles."""
    billable = await billable_membership(await driver_connection(session), membership_id)
    if billable is None:
        raise NO_MEMBERSHIP
    if (
        billable.status is not MembershipStatus.ACTIVE
        or billable.plan.terms.kind not in billing.PAID_AHEAD
    ):
        raise refused(
            PaidThroughRefusal.CANNOT, "only an Active monthly or prepaid plan is paid up to a date"
        )
    if through < billable.started_on:
        raise refused(
            PaidThroughRefusal.BEFORE_PLAN,
            "the date is before the plan started: add it to the history",
            started_on=billable.started_on,
        )
    rows = (
        await session.execute(
            PERIODS,
            {
                "id": membership_id,
                "validated": EntryStatus.VALIDATED.value,
                "settling": sorted(k.value for k in SETTLING_KINDS),
            },
        )
    ).all()
    owing = [
        (r.id, r.period_start, r.period_end, r.amount_due_clp - r.paid_clp)
        for r in rows
        if r.period_start <= through and r.paid_clp < r.amount_due_clp
    ]
    # One more than may be billed, to tell a date too far from one just far enough.
    unbilled = billing.periods_through(billable, through, billing.MAX_PAID_AHEAD + 1)
    if len(unbilled.periods) > billing.MAX_PAID_AHEAD:
        raise refused(
            PaidThroughRefusal.TOO_FAR,
            f"at most {billing.MAX_PAID_AHEAD} periods not billed yet are paid up to a date",
        )
    settled = {r for r, *_ in owing}
    spans = [
        (r.period_start, r.period_end, 0 if r.id in settled else r.amount_due_clp - r.paid_clp)
        for r in rows
    ] + [(p.period_start, p.period_end, 0) for p in unbilled.periods]
    paid_through = billing.paid_through(spans)
    if not owing and not unbilled.periods:
        raise refused(
            PaidThroughRefusal.ALREADY_PAID,
            "every period up to the date is settled already",
            paid_through=paid_through,
        )
    if any(r.pending for r in rows if r.id in settled):
        raise refused(PaidThroughRefusal.PENDING, "a proof waits on one of the periods")
    assert paid_through is not None  # every period up to `through` is settled
    return Settling(owing=owing, unbilled=unbilled, paid_through=paid_through)


@router.get(
    "/memberships/{membership_id}/paid-through",
    responses={status.HTTP_409_CONFLICT: {"model": PaidThroughConflict}},
)
async def paid_through_quote(
    membership_id: uuid.UUID, session: LedgerReadSession, through: date
) -> PaidThroughQuote:
    """What "Pagado hasta" `through` would write: the periods, their total, and the
    "Pagado hasta" it leaves."""
    plan = await plan_through(session, membership_id, through)
    return PaidThroughQuote(
        periods=plan.periods, total_clp=plan.total_clp, paid_through=plan.paid_through
    )


@router.post(
    "/memberships/{membership_id}/paid-through",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"model": PaidThroughConflict}},
)
async def record_paid_through(
    membership_id: uuid.UUID, body: PaidThroughRecord, session: LedgerSession
) -> RecordedPaidThrough:
    """Settle every period up to `through` with a payment or a gift each, billing those
    not billed yet, as the quote said."""
    # Locked as a payment locks it, before anything about it is read.
    await session.execute(LOCK_MEMBERSHIP, {"membership_id": membership_id})
    plan = await plan_through(session, membership_id, body.through)
    if plan.total_clp != body.total_clp:
        raise refused(PaidThroughRefusal.AMOUNT_CHANGED, "the total is not what those periods owe")

    targets: list[tuple[uuid.UUID, BillingPeriod]] = []
    for period_id, *_ in plan.owing:
        row, period = await period_under_lock(session, period_id, membership_id)
        targets.append((row.id, period))
    if plan.unbilled.periods:
        written = await write_billing(
            await driver_connection(session), membership_id, plan.unbilled
        )
        # The membership is locked and its periods were read under the lock, so none of
        # them should be there already; if one is, the request rolls back.
        if len(written) != len(plan.unbilled.periods):
            raise HTTPException(status.HTTP_409_CONFLICT, "a period was billed meanwhile")
        targets += written

    entries: list[Entry] = []
    periods: list[Period] = []
    for period_id, period in targets:
        if period.outstanding_clp == 0:
            continue
        entry, after = await settle(session, membership_id, period_id, period, body)
        entries.append(entry)
        periods.append(period_after(period_id, after))
    return RecordedPaidThrough(entries=entries, periods=periods, paid_through=plan.paid_through)


async def settle(
    session: AsyncSession,
    membership_id: uuid.UUID,
    period_id: uuid.UUID,
    period: BillingPeriod,
    body: PaidThroughRecord,
) -> tuple[Entry, BillingPeriod]:
    """Settle what `period` still owes with a payment or a gift, and record it."""
    owed = period.outstanding_clp
    if body.mode is PaidThroughMode.PAID:
        payment = LedgerEntry(
            kind=EntryKind.PAYMENT, amount_clp=owed, status=EntryStatus.VALIDATED, note=PAID_NOTE
        )
        settlement = billing.apply(period, payment)
        method: Method | None = body.method
    else:
        settlement = billing.adjust(period, owed, GIFT_NOTE)
        method = None
    before = await figures(session, membership_id, period)
    entry = await insert_entry(
        session,
        settlement.entry,
        membership_id=membership_id,
        billing_period_id=period_id,
        method=method.value if method else None,
    )
    await record_correction(
        session,
        membership_id=membership_id,
        billing_period_id=period_id,
        entry_ids=[entry.id],
        purpose=None,
        reason=entry.note,
        before=before,
        after=await figures(session, membership_id, settlement.period),
        paid_through=body.mode.value,
    )
    return entry, settlement.period
