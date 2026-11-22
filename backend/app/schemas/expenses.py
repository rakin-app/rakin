"""Gastos (#314): what the gym spends, as its list reads it and its form writes it.

An expense is the gym's record, not a member's debt: it is edited, and voided with a
reason, never deleted (docs/design/expenses-and-officers.md, sections 10 and 12).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.ledger import Amount, Note
from app.schemas.memberships import Reason

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Payee = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ReceiptKey = Annotated[str, StringConstraints(min_length=1, max_length=512)]

# More live categories than this is a list nobody picks from: an add or a restore
# past it is refused, so every live one can still be reordered in one request.
MAX_CATEGORIES = 100


class ExpenseMethod(StrEnum):
    """How the gym paid: the ledger's methods, and a card (migration 0083)."""

    TRANSFER = "transfer"
    CASH = "cash"
    CARD = "card"
    OTHER = "other"


class ExpenseIn(BaseModel):
    """A new expense, as the form sends it. `receipt_key` is an upload's key from
    `POST /api/expenses/receipt-upload`, once its PUT has landed."""

    model_config = ConfigDict(extra="forbid")

    spent_on: date
    amount_clp: Amount
    category_id: uuid.UUID
    payee: Payee | None = None
    method: ExpenseMethod | None = None
    note: Note | None = None
    receipt_key: ReceiptKey | None = None
    # The gasto fijo it is recorded from (#315): an estimated one's form sends it.
    recurring_id: uuid.UUID | None = None
    # The cobro extra that recovers it (#318), if the gym gets it back from the group.
    extra_charge_id: uuid.UUID | None = None


class ExpenseChange(BaseModel):
    """An edit: only the fields sent change. A field sent as null is cleared, except
    those an expense always has; `remove_receipt` takes its receipt off."""

    model_config = ConfigDict(extra="forbid")

    spent_on: date | None = None
    amount_clp: Amount | None = None
    category_id: uuid.UUID | None = None
    payee: Payee | None = None
    method: ExpenseMethod | None = None
    note: Note | None = None
    receipt_key: ReceiptKey | None = None
    remove_receipt: bool = False
    # The cobro extra that recovers it (#318); null unlinks it.
    extra_charge_id: uuid.UUID | None = None

    @field_validator("spent_on", "amount_clp", "category_id", mode="before")
    @classmethod
    def _always_has_one(cls, value: object) -> object:
        if value is None:
            raise ValueError("an expense always has one")
        return value


class ExpenseVoid(BaseModel):
    """Anular, with why."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason


class Expense(BaseModel):
    """A line of the Gastos list: a voided one is listed, struck through, and counts
    nowhere."""

    id: uuid.UUID
    spent_on: date
    amount_clp: int
    category_id: uuid.UUID
    category_name: str
    payee: str | None
    method: ExpenseMethod | None
    note: str | None
    has_receipt: bool
    # The gasto fijo it was recorded from, if any (#315).
    recurring_id: uuid.UUID | None
    # The cobro extra that recovers it, if any (#318), and its title: `None` to whoever
    # cannot read cobros (`money_read`), who still sees that it names one.
    extra_charge_id: uuid.UUID | None
    extra_charge_title: str | None
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime | None
    voided_at: datetime | None
    voided_by_name: str | None
    void_reason: str | None


class ExpenseMonth(BaseModel):
    """A month of Gastos, newest first, and what its expenses that count add up to."""

    month: date
    # The gym's current month: the list goes no later.
    current_month: date
    # The gym's today, in its timezone: the latest day an expense may be paid on.
    today: date
    category_id: uuid.UUID | None
    total_clp: int
    count: int
    items: list[Expense]


class Receipt(BaseModel):
    """Where the browser GETs an expense's receipt, briefly, and what it is."""

    url: str
    content_type: str


class ExpenseCategory(BaseModel):
    id: uuid.UUID
    name: str
    sort: int
    # Otros, which cannot be archived.
    is_other: bool
    archived: bool
    # Expenses recorded under it, voided or not.
    expenses: int


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: CategoryName


class CategoryOrder(BaseModel):
    """Every live category, in the order the gym wants them."""

    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_CATEGORIES)]


# --- gastos fijos (#315) -------------------------------------------------------------

# More templates than this is not a list of monthly bills: one more is refused.
MAX_RECURRING = 100

DayOfMonth = Annotated[int, Field(ge=1, le=31)]


class AmountKind(StrEnum):
    """`fixed`: rent, internet, recorded at its amount in one tap. `estimated`: power,
    water, gas, where the amount is last bill's and only a hint (migration 0085)."""

    FIXED = "fixed"
    ESTIMATED = "estimated"


class RecurringIn(BaseModel):
    """A new gasto fijo."""

    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID
    payee: Payee | None = None
    method: ExpenseMethod | None = None
    amount_clp: Amount
    amount_kind: AmountKind
    day_of_month: DayOfMonth


class RecurringChange(BaseModel):
    """An edit of a gasto fijo, or its pause (`active`): only the fields sent change. A
    field sent as null is cleared, except those a template always has."""

    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID | None = None
    payee: Payee | None = None
    method: ExpenseMethod | None = None
    amount_clp: Amount | None = None
    amount_kind: AmountKind | None = None
    day_of_month: DayOfMonth | None = None
    active: bool | None = None

    @field_validator(
        "category_id", "amount_clp", "amount_kind", "day_of_month", "active", mode="before"
    )
    @classmethod
    def _always_has_one(cls, value: object) -> object:
        if value is None:
            raise ValueError("a template always has one")
        return value


class Recurring(BaseModel):
    """A gasto fijo, as Gastos lists it."""

    id: uuid.UUID
    category_id: uuid.UUID
    category_name: str
    # Its category was archived: it is recorded through the form, under another.
    category_archived: bool
    payee: str | None
    method: ExpenseMethod | None
    amount_clp: int
    amount_kind: AmountKind
    day_of_month: int
    active: bool
    created_at: datetime


class DueRecurring(Recurring):
    """A gasto fijo not yet recorded in the month: `due_on` is the day it would be
    recorded on, its day of that month, or the gym's today if that is earlier."""

    due_on: date


class RecurringMonth(BaseModel):
    """ "Gastos fijos por registrar": the active templates with no expense from them in
    the month, and those skipped for it ("No este mes")."""

    month: date
    current_month: date
    today: date
    due: list[DueRecurring]
    skipped: list[DueRecurring]


class RecordRecurring(BaseModel):
    """Record fixed templates in a month, each at its amount: one tap names one,
    "Registrar los fijos" all of them."""

    model_config = ConfigDict(extra="forbid")

    month: date
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_RECURRING)]


class SkipRecurring(BaseModel):
    """No este mes: the template leaves the month's card."""

    model_config = ConfigDict(extra="forbid")

    month: date
