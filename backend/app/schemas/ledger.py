"""Ledger entries as the API reads and writes them.

An admin records a payment the gym received by other means than a student's proof
("Registrar pago", #37): cash, a transfer the admin saw arrive, or anything else. It
names the billing period it pays, and is created validated by that admin.
"""

import uuid
from datetime import datetime
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
# so a value `bigint` cannot hold is a 422 rather than a 500.
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
