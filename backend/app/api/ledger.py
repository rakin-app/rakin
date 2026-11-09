"""The current gym's ledger: an admin records a payment ("Registrar pago", #37), sees
how many proofs wait for review (#35), reads one membership's ledger for the member
detail ("Ficha de alumno", #60), and reads the whole gym's for the ledger book ("Libro
de pagos", #39).

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
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import billing
from app.domain.billing import SETTLING_KINDS, BillingPeriod, Settlement
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry
from app.roles import LedgerSession
from app.schemas.ledger import (
    BookEntry,
    BookFilter,
    BookKpis,
    BookPeriod,
    Entry,
    LedgerBook,
    MembershipLedger,
    OpenPeriod,
    PaymentRecord,
    Period,
    PersonRef,
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


# The gym's timezone and today in it; every month the book shows is a gym-local one.
GYM_CLOCK = """
    SELECT g.timezone, (now() AT TIME ZONE g.timezone)::date AS today
    FROM gym g WHERE g.id = current_setting('app.gym_id')::uuid
"""

# An entry's gym-local day, for `e`, a `ledger_entry`, and `t`, `GYM_CLOCK`.
ENTRY_DAY = "(e.created_at AT TIME ZONE t.timezone)::date"

# The months with entries, newest first. RLS keeps them to the gym.
BOOK_MONTHS = text(
    f"""
    SELECT DISTINCT date_trunc('month', {ENTRY_DAY})::date AS month
    FROM ledger_entry e CROSS JOIN ({GYM_CLOCK}) t
    ORDER BY month DESC
    """
)

# The ledger as the book lists it: each entry with whose membership it is, the
# guardian who pays for them, and its period settled as `OPEN_PERIODS` settles it.
BOOK_ROWS = f"""
    SELECT e.id, e.created_at, e.kind, e.status, e.amount_clp, e.method, e.note,
           e.membership_id, pl.name AS plan_name,
           m.person_id, mp.name AS person_name,
           gl.guardian_person_id AS guardian_id, gp.name AS guardian_name,
           bp.period_start, bp.period_end, bp.due_date,
           bp.amount_due_clp - least(coalesce(paid.amount, 0), bp.amount_due_clp)
               AS outstanding_clp,
           CASE WHEN coalesce(paid.amount, 0) < bp.amount_due_clp
                THEN greatest(t.today - bp.due_date, 0) ELSE 0 END AS days_overdue,
           vp.name AS validated_by_name
    FROM ledger_entry e
    CROSS JOIN ({GYM_CLOCK}) t
    JOIN membership m ON m.id = e.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person mp ON mp.gym_id = m.gym_id AND mp.person_id = m.person_id
    LEFT JOIN guardian_link gl
        ON gl.gym_id = m.gym_id AND gl.dependent_person_id = m.person_id
    LEFT JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.guardian_person_id
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    LEFT JOIN LATERAL (
        SELECT sum(s.amount_clp)::bigint AS amount FROM ledger_entry s
        WHERE s.billing_period_id = bp.id AND s.status = 'validated'
          AND s.kind = ANY(CAST(:settling AS text[]))
    ) paid ON bp.id IS NOT NULL
    LEFT JOIN gym_person vp ON vp.gym_id = e.gym_id AND vp.person_id = e.validated_by
"""

IN_MONTH = f"{ENTRY_DAY} >= :month AND {ENTRY_DAY} < (:month + interval '1 month')::date"

# What each filter keeps of `BOOK_ROWS`.
BOOK_FILTERS = {
    BookFilter.ALL: IN_MONTH,
    BookFilter.PENDING: "e.kind = 'payment' AND e.status = 'pending'",
    BookFilter.OVERDUE: (
        "e.kind = 'charge' AND e.billing_period_id IN"
        " (SELECT billing_period_id FROM v_overdue WHERE membership_status = 'active')"
    ),
    BookFilter.KIDS: f"{IN_MONTH} AND gl.dependent_person_id IS NOT NULL",
}

# The book's KPIs. Collected and expected are the month's; pending and overdue, and the
# membership counts, are how the gym stands today. Overdue counts active memberships
# only, as the owner's "Vencido" does (`v_overdue`).
BOOK_KPIS = text(
    """
    SELECT
        (SELECT coalesce(sum(income_clp), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS collected_clp,
        (SELECT coalesce(sum(payments), 0)::bigint FROM v_monthly_income
         WHERE month = :month) AS collected_payments,
        pending.amount AS pending_clp, pending.n AS pending_payments,
        overdue.amount AS overdue_clp, overdue.members AS overdue_members,
        overdue.avg_days AS overdue_avg_days,
        (SELECT coalesce(sum(amount_due_clp), 0)::bigint FROM billing_period
         WHERE due_date >= :month AND due_date < (:month + interval '1 month')::date)
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
            FROM v_overdue WHERE membership_status = 'active' GROUP BY person_id
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
) -> LedgerBook:
    """The gym's ledger, every entry newest first, with the month's KPIs ("Libro de
    pagos", #39). Owner and admin only: a coach never sees money."""
    clock = (await session.execute(text(GYM_CLOCK))).one()
    current = clock.today.replace(day=1)
    shown = month.replace(day=1) if month else current
    with_entries = [row.month for row in await session.execute(BOOK_MONTHS)]
    months = sorted({*with_entries, current, shown}, reverse=True)

    params: dict[str, Any] = {
        "month": shown,
        "settling": sorted(k.value for k in SETTLING_KINDS),
    }
    matching = f"{BOOK_ROWS} WHERE {BOOK_FILTERS[book_filter]}"
    total = await session.scalar(text(f"SELECT count(*) FROM ({matching}) f"), params)
    rows = await session.execute(
        text(f"{matching} ORDER BY e.created_at DESC, e.id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    )
    kpis = (await session.execute(BOOK_KPIS, {"month": shown})).one()
    return LedgerBook(
        month=shown,
        months=months,
        timezone=clock.timezone,
        kpis=BookKpis.model_validate(kpis, from_attributes=True),
        items=[book_entry(row) for row in rows],
        total=total or 0,
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
        membership_id=row.membership_id,
        plan_name=row.plan_name,
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
    )
