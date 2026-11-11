"""Ledger entries as the API reads and writes them.

An admin records a payment the gym received by other means than a student's proof
("Registrar pago", #37): cash, a transfer the admin saw arrive, or anything else. It
names the billing period it pays, and is created validated by that admin.

The member detail ("Ficha de alumno", #60) reads one membership's ledger: the periods
it still owes and its entries, newest first. Both it and the ledger book list a
membership's freezes (#26) beside the entries, as lines with no amount: one where
each freeze started, and one where it ended, once it has.

The owner's dashboard ("Hoy", #58) reads the gym's overdue periods.

An admin adjusts what a period owes, with a note saying why, and refunds part or all of
a validated payment (#38).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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


# An adjustment's sign says which way it goes: positive in the member's favour, negative
# owed (app.domain.ledger). Capped either way as `Amount` is.
SignedAmount = Annotated[int, Field(ge=-MAX_PRICE_CLP, le=MAX_PRICE_CLP)]


class AdjustmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID
    billing_period_id: uuid.UUID
    # Not zero; the domain refuses it as the API's other bounds do.
    amount_clp: SignedAmount
    # Mandatory: why the period owes more or less than it did.
    note: Note

    @field_validator("amount_clp")
    @classmethod
    def not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("an adjustment is not zero")
        return value


class RefundRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The validated payment it gives back part or all of.
    payment_id: uuid.UUID
    amount_clp: Amount
    # How the money went back.
    method: Method
    note: Note | None = None


class Entry(BaseModel):
    id: uuid.UUID
    # The membership whose period it settles, or none for one on a cobro line (#195).
    membership_id: uuid.UUID | None
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
    # The payment a refund gives back; null on every other kind.
    refund_of: uuid.UUID | None
    # The cobro extra line it settles, instead of a membership's period (#195).
    extra_line_id: uuid.UUID | None = None


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


class RecordedAdjustment(BaseModel):
    adjustment: Entry
    # The period as the adjustment leaves it.
    period: Period


class RecordedRefund(BaseModel):
    refund: Entry
    # The period as the refund leaves it: open again if it no longer covers it.
    period: Period


class OpenPeriod(BaseModel):
    """A billing period that validated payments and credit do not yet cover."""

    id: uuid.UUID
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int
    # Below zero while an adjustment against the member outweighs what was paid.
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
    # Signed on an adjustment: positive in the member's favour, negative owed.
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
    # The payment a refund gives back; null on every other kind.
    refund_of: uuid.UUID | None


class FreezeEdge(StrEnum):
    START = "start"
    END = "end"


class FreezeLine(BaseModel):
    """A freeze starting or ending ("Congelación"): no money, only the days it moved."""

    freeze_id: uuid.UUID
    edge: FreezeEdge
    # The day it started or ended, in the gym's timezone; today at the latest.
    day: date
    from_date: date
    # The day it ends, when the membership is Active again.
    to_date: date
    reason: str


class LedgerPeriod(BaseModel):
    """A billing period of the membership, open or paid: one an adjustment may go to."""

    id: uuid.UUID
    period_start: date
    period_end: date
    # What validated payments and adjustments, less refunds, leave owed; 0 once paid.
    outstanding_clp: int


class RefundablePayment(BaseModel):
    """A validated payment with something left to give back."""

    id: uuid.UUID
    billing_period_id: uuid.UUID
    period_start: date
    amount_clp: int
    method: Method | None
    validated_at: datetime | None
    # What its earlier refunds leave to give back: more than 0.
    refundable_clp: int


class MembershipLedger(BaseModel):
    """One membership's money: what it owes and its entries ("Ficha de alumno", #60)."""

    # Oldest first: the first is the one a payment settles next.
    open_periods: list[OpenPeriod]
    # Outstanding on the open periods due today or before, in the gym's timezone.
    owed_clp: int
    # Newest first, at most `TIMELINE_LIMIT`.
    entries: list[TimelineEntry]
    # Every freeze's start and end so far, newest first.
    freezes: list[FreezeLine]
    # Every billing period, newest first, and every validated payment with something
    # left to give back, newest first: what "Ajuste" and "Devolver" offer (#38). Not
    # capped as `entries` is.
    periods: list[LedgerPeriod]
    refundable_payments: list[RefundablePayment]


class BookFilter(StrEnum):
    """The ledger book's filters ("Libro de pagos", #39)."""

    # Every entry of the month: a charge by the month its period starts in (#206), any
    # other entry by the day it was made.
    ALL = "all"
    # Payments waiting for review, of any month: the queue as it stands today.
    PENDING = "pending"
    # The charges of periods overdue today (`v_overdue`), of any month, whatever the
    # membership's status (#207).
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


class BookExtra(BaseModel):
    """The cobro extra an entry is on (#195), labelled by its category."""

    id: uuid.UUID
    title: str
    category: str


class BookEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    kind: EntryKind
    status: EntryStatus
    amount_clp: int
    method: Method | None
    note: str | None
    # The payment a refund gives back; null on every other kind.
    refund_of: uuid.UUID | None
    # Null, with `plan_name`, for an entry on a cobro extra line, which `extra` names.
    membership_id: uuid.UUID | None
    plan_name: str | None
    # The membership's status today (`lapsed` once its plan lapsed), so a debt left on a
    # lapsed or cancelled plan reads as such (#207). Null for a cobro extra line.
    membership_status: str | None = None
    # Whose membership or line it is, and who pays for them when they are a dependent.
    person: PersonRef
    guardian: PersonRef | None
    # Null for a credit carried to a later period, and for a cobro extra's entry.
    period: BookPeriod | None
    validated_by_name: str | None
    extra: BookExtra | None = None


class BookFreeze(FreezeLine):
    """A freeze line in the book: the month's, on the memberships its filter lists."""

    membership_id: uuid.UUID
    plan_name: str
    person: PersonRef
    guardian: PersonRef | None


class BookKpis(BaseModel):
    # Validated payments less validated refunds, each by the month it was validated in
    # (`v_monthly_income`); the count is of the payments.
    collected_clp: int
    collected_payments: int
    # The month's validated refunds, which `collected_clp` is net of.
    refunded_clp: int
    refunds: int
    # What of `collected_clp` the cobros extra brought in (#195), net of their refunds.
    collected_extra_clp: int = 0
    # Payments waiting for review, today.
    pending_clp: int
    pending_payments: int
    # Outstanding on overdue periods today (`v_overdue`), whatever the membership's
    # status (#207).
    overdue_clp: int
    overdue_members: int
    # Per overdue member, the days since their oldest unpaid period fell due, averaged.
    overdue_avg_days: float
    # What is owed for the month: the periods falling due in it, of active and lapsed
    # memberships. Cancelled, trial and frozen ones are not counted.
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
    # The month's freeze lines, newest first, for `all` and `kids`; none for `pending`
    # and `overdue`, which are about money owed. Not paged: a handful a month.
    freezes: list[BookFreeze]


class OverduePeriod(BaseModel):
    """A period past its due date and not paid in full (`v_overdue`), of a membership in
    any status: lapsing or cancelling a plan does not pay what it owes (#207)."""

    billing_period_id: uuid.UUID
    membership_id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    plan_name: str
    membership_status: str
    period_start: date
    due_date: date
    outstanding_clp: int
    # Whole days past the due date in the gym's timezone; at least 1.
    days_overdue: int


class Overdue(BaseModel):
    """The gym's overdue periods ("Hoy", #58)."""

    # What `periods` still owe, together.
    total_clp: int
    # Longest overdue first.
    periods: list[OverduePeriod]
