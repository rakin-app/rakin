"""Historial de pagos (#295): what a student paid before Rakin, as the ficha's
Historial card reads it and its "Pagos anteriores" form writes it."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.ledger import Amount, Method, Note
from app.schemas.memberships import Reason

PlanName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# "Desde enero 2000 hasta hoy" is some three hundred months; more in one form is a typo.
MAX_PAYMENTS_AT_ONCE = 360

HistorySource = Literal["manual", "import"]


class HistoryPaymentIn(BaseModel):
    """One payment from before Rakin: when, how much, how (if known), the month it paid
    for as its first day (if known), the plan as the gym called it, a note. The API
    checks the days against the gym's today, `HISTORY_WINDOW_YEARS` and the person's
    first plan."""

    model_config = ConfigDict(extra="forbid")

    paid_on: date
    amount_clp: Amount
    method: Method | None = None
    covers_month: date | None = None
    plan_name: PlanName | None = None
    note: Note | None = None

    @field_validator("covers_month")
    @classmethod
    def _first_of_a_month(cls, value: date | None) -> date | None:
        if value is not None and value.day != 1:
            raise ValueError("covers_month is the first day of a month")
        return value


class HistoryPayments(BaseModel):
    """ "Pagos anteriores": every month of the form, written in one transaction or none."""

    model_config = ConfigDict(extra="forbid")

    payments: Annotated[
        list[HistoryPaymentIn], Field(min_length=1, max_length=MAX_PAYMENTS_AT_ONCE)
    ]


class HistoryRemoval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class HistoryPayment(BaseModel):
    """A line of the Historial card, with where it came from."""

    id: uuid.UUID
    paid_on: date
    amount_clp: int
    method: Method | None
    covers_month: date | None
    plan_name: str | None
    note: str | None
    source: HistorySource
    # The file an import read, from its audit row (#297); null when typed.
    import_name: str | None
    created_by_name: str | None
    created_at: datetime


class HistoryYear(BaseModel):
    """A year of the card, collapsed to its count and total: the year of the month each
    payment paid for, else of the day it was paid."""

    year: int
    count: int
    total_clp: int
    payments: list[HistoryPayment]


class HistoryPaymentsRead(BaseModel):
    """The person's payments from before Rakin by year, newest first. `plan_from` is the
    start of their first plan here, if any: a month on or after it is their plan's, for
    "Pagado hasta" (#286), and never history."""

    plan_from: date | None
    years: list[HistoryYear]
