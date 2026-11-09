"""Ledger entries as the API reads and writes them.

An admin records a payment the gym received by other means than a student's proof
("Registrar pago", #37): cash, a transfer the admin saw arrive, or anything else. It
names the billing period it pays, and is created validated by that admin.

The member detail ("Ficha de alumno", #60) reads one membership's ledger: the periods
it still owes and its entries, newest first.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.ledger import EntryKind, EntryStatus
from app.schemas.plans import MAX_PRICE_CLP


class Method(StrEnum):
    """How the money arrived; the column's check is migration 0008."""

    CASH = "cash"
    TRANSFER = "transfer"
    OTHER = "other"


# Positive: the kind says which way it goes (app.domain.ledger). Capped as a price is,
# so a value `bigint` cannot hold, or a typo's extra zeros, is a 422 rather than a 500
# or an absurd entry. Not capped at what is outstanding: an overpayment is allowed and
# becomes a credit for the next period (app.domain.billing).
Amount = Annotated[int, Field(gt=0, le=MAX_PRICE_CLP)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PaymentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID
    billing_period_id: uuid.UUID
    amount_clp: Amount
    method: Method
    note: Note | None = None


class Entry(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    billing_period_id: uuid.UUID | None
    amount_clp: int
    kind: EntryKind
    status: EntryStatus
    method: Method | None
    claimed_by: uuid.UUID | None
    claimed_at: datetime | None
    validated_by: uuid.UUID | None
    validated_at: datetime | None
    # Where the transfer proof is stored, for a payment a student claimed (#35).
    proof_object_key: str | None
    note: str | None
    created_at: datetime


class Period(BaseModel):
    id: uuid.UUID
    amount_due_clp: int
    paid_clp: int
    outstanding_clp: int
    closed: bool


class RecordedPayment(BaseModel):
    payment: Entry
    # The overpayment, as a validated adjustment to apply to a later period.
    credit: Entry | None
    # The period as the payment leaves it.
    period: Period


class OpenPeriod(BaseModel):
    """A billing period that validated payments and credit do not yet cover."""

    id: uuid.UUID
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int
    paid_clp: int
    outstanding_clp: int
    # Due today or before, in the gym's timezone: what `owed_clp` counts.
    due: bool
    # Whole days past the due date in the gym's timezone; 0 on or before it.
    days_overdue: int


class TimelineEntry(BaseModel):
    id: uuid.UUID
    kind: EntryKind
    status: EntryStatus
    amount_clp: int
    method: Method | None
    # The period it belongs to; null for a credit carried to a later one.
    billing_period_id: uuid.UUID | None
    period_start: date | None
    note: str | None
    created_at: datetime
    # Who reviewed it (validated or rejected) and when; null while pending.
    validated_by_name: str | None
    validated_at: datetime | None


class MembershipLedger(BaseModel):
    """One membership's money: what it owes and its entries ("Ficha de alumno", #60)."""

    # Oldest first: the first is the one a payment settles next.
    open_periods: list[OpenPeriod]
    # Outstanding on the open periods due today or before, in the gym's timezone.
    owed_clp: int
    # Newest first, at most `TIMELINE_LIMIT`.
    entries: list[TimelineEntry]


class BookFilter(StrEnum):
    """The ledger book's filters ("Libro de pagos", #39)."""

    # Every entry made in the month.
    ALL = "all"
    # Payments waiting for review, of any month: the queue as it stands today.
    PENDING = "pending"
    # The charges of active memberships' periods overdue today (`v_overdue`), of any month.
    OVERDUE = "overdue"
    # The month's entries on dependents' memberships: the kids a guardian pays for.
    KIDS = "kids"


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class BookPeriod(BaseModel):
    """The billing period an entry belongs to, settled as `app.domain.billing` does."""

    period_start: date
    period_end: date
    due_date: date
    outstanding_clp: int
    # Whole days past the due date in the gym's timezone while unpaid; 0 otherwise.
    days_overdue: int


class BookEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    kind: EntryKind
    status: EntryStatus
    amount_clp: int
    method: Method | None
    note: str | None
    membership_id: uuid.UUID
    plan_name: str
    # Whose membership it is, and who pays for them when they are a dependent.
    person: PersonRef
    guardian: PersonRef | None
    # Null for a credit carried to a later period.
    period: BookPeriod | None
    validated_by_name: str | None


class BookKpis(BaseModel):
    # Validated payments, by the month each was validated in (`v_monthly_income`).
    collected_clp: int
    collected_payments: int
    # Payments waiting for review, today.
    pending_clp: int
    pending_payments: int
    # Outstanding on active memberships' overdue periods, today (`v_overdue`).
    overdue_clp: int
    overdue_members: int
    # Per overdue member, the days since their oldest unpaid period fell due, averaged.
    overdue_avg_days: float
    # What the periods falling due in the month bill.
    expected_clp: int
    # Memberships as they stand today.
    active_memberships: int
    frozen_memberships: int


class LedgerBook(BaseModel):
    """The gym's ledger for a month: its KPIs and a page of entries, newest first."""

    # The first day of the month shown, and of every month with entries, newest first.
    month: date
    months: list[date]
    timezone: str
    kpis: BookKpis
    items: list[BookEntry]
    # Entries the filter matches, across every page.
    total: int
