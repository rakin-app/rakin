"""The Pagos tab (#298): one row per payment received before Rakin, read with no database.

A row names someone by RUT, else email, else name, as the Grados tab does, and never
creates anyone: who they are is looked up as the row is written (`app.api.member_import`),
after the Alumnos tab, so a payment finds a student that tab adds. The day it was paid
and the amount are required; the month it paid for (`MM-AAAA`, or a date: its month),
the method (Efectivo, Transferencia, Otro), the plan as the gym called it and a note are
not. Days may go back `HISTORY_WINDOW_YEARS`, never past today. A row read without
errors carries the payment as the ficha's form would send it (`entry`), so both are
held to one shape (`schemas.history.HistoryPaymentIn`).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Literal

from app.member_import.rows import (
    EMAIL_WORDS,
    RUT_WORDS,
    Cells,
    fold,
    header_words,
    holds,
    identity,
    in_history,
    parse_date,
    read_who,
)
from app.schemas.history import HistoryPaymentIn
from app.schemas.ledger import Method
from app.schemas.plans import MAX_PRICE_CLP


class PaymentField(StrEnum):
    RUT = "rut"
    EMAIL = "email"
    NAME = "name"
    PAID_ON = "paid_on"
    AMOUNT = "amount_clp"
    COVERS_MONTH = "covers_month"
    METHOD = "method"
    PLAN_NAME = "plan_name"
    NOTE = "note"


# As `history_payment` holds them (0055).
MAX_PLAN_NAME = 200
MAX_NOTE = 500

# `required`: the cell is empty and the row needs it; on `name`, the row says nobody.
# `invalid_amount`: not a whole number of pesos above zero. `invalid_method`: none of
# Efectivo, Transferencia, Otro. `unknown_person`: nobody in the gym or on the Alumnos
# tab is the row. `ambiguous_name`: two people of the name. `covers_plan`: the month (else
# the day) is on or after their first plan here, which "Pagado hasta" pays. `repeated`:
# an earlier row gives the same person the same day, amount and month.
PaymentErrorCode = Literal[
    "required",
    "invalid_rut",
    "invalid_email",
    "invalid_date",
    "invalid_amount",
    "invalid_method",
    "unknown_person",
    "ambiguous_name",
    "covers_plan",
    "repeated",
    "too_long",
]


@dataclass(frozen=True)
class PaymentRowError:
    field: PaymentField
    code: PaymentErrorCode


@dataclass
class Payment:
    """One Pagos row, read. `entry` is the payment when `errors` names none."""

    number: int
    name: str
    rut: str | None = None
    email: str | None = None
    entry: HistoryPaymentIn | None = None
    errors: list[PaymentRowError] = field(default_factory=list)

    def refuse(self, on: PaymentField, code: PaymentErrorCode) -> None:
        self.errors.append(PaymentRowError(on, code))

    @property
    def key(self) -> tuple[str, str] | None:
        """Who the row is, by RUT, else email."""
        return identity(self.rut, self.email)


# In order: the first field whose words a header holds is the one suggested. The month's
# "mes" and the method's "forma de pago" before the day's "fecha de pago"; the plan's
# "nombre del plan" before the person's "nombre".
_HEADER_WORDS: tuple[tuple[PaymentField, tuple[str, ...]], ...] = (
    (PaymentField.COVERS_MONTH, ("mes que paga", "mes pagado", "mes", "periodo")),
    (PaymentField.METHOD, ("metodo", "medio de pago", "forma de pago", "medio", "forma")),
    (PaymentField.PAID_ON, ("fecha de pago", "fecha pago", "fecha", "pagado el", "dia de pago")),
    (PaymentField.AMOUNT, ("monto", "valor", "importe", "total", "amount")),
    (PaymentField.PLAN_NAME, ("plan", "mensualidad")),
    (PaymentField.NOTE, ("nota", "observacion", "observaciones", "comentario")),
    (PaymentField.EMAIL, EMAIL_WORDS),
    (PaymentField.RUT, RUT_WORDS),
    (PaymentField.NAME, ("nombre", "alumno", "alumna", "name")),
)


def suggest_payment_mapping(headers: Sequence[str]) -> dict[PaymentField, int]:
    """The column each field most likely is, by its header; the first column wins."""
    mapping: dict[PaymentField, int] = {}
    for column, header in enumerate(headers):
        words = header_words(header)
        suggested = next((f for f, keys in _HEADER_WORDS if holds(words, keys)), None)
        if suggested is not None and suggested not in mapping:
            mapping[suggested] = column
    return mapping


# Whole pesos, as Chile writes them: "25000", "25.000", "$ 25.000", "25.000,00". A
# thousands comma is read too ("25,000"), as a sheet kept in English writes it.
_PESOS = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+|\d+)(?:,0{1,2}|\.0{1,2})?")
# The month a payment paid for: "04-2024", "4/2024", "2024-04".
_MONTH_YEAR = re.compile(r"(\d{1,2})[/.\-](\d{4})")
_YEAR_MONTH = re.compile(r"(\d{4})[/.\-](\d{1,2})")

_METHODS: dict[str, Method] = {
    "efectivo": Method.CASH,
    "cash": Method.CASH,
    "transferencia": Method.TRANSFER,
    "transf": Method.TRANSFER,
    "transfer": Method.TRANSFER,
    "deposito": Method.TRANSFER,
    "otro": Method.OTHER,
    "other": Method.OTHER,
}


def parse_amount(raw: str) -> int | None:
    """A cell's whole pesos above zero, at most what a price may be; `None` for anything
    else."""
    value = raw.replace("$", "").replace(" ", "").removesuffix("CLP").removesuffix("clp")
    if not (match := _PESOS.fullmatch(value)):
        return None
    amount = int(re.sub(r"[.,]", "", match.group(1)))
    return amount if 0 < amount <= MAX_PRICE_CLP else None


def parse_month(raw: str, today: date) -> date:
    """The first day of the month a cell names: `MM-AAAA`, `AAAA-MM`, or a date's month.
    Raises `ValueError`."""
    value = raw.strip().split(" ")[0]
    if match := _MONTH_YEAR.fullmatch(value):
        month, year = (int(g) for g in match.groups())
    elif match := _YEAR_MONTH.fullmatch(value):
        year, month = (int(g) for g in match.groups())
    else:
        return parse_date(raw, today).replace(day=1)
    return date(year, month, 1)


def _day(payment: Payment, on: PaymentField, raw: str, today: date) -> date | None:
    try:
        day = parse_month(raw, today) if on is PaymentField.COVERS_MONTH else parse_date(raw, today)
    except ValueError:
        day = None
    if day is None or not in_history(day, today):
        payment.refuse(on, "invalid_date")
        return None
    return day


def _text(payment: Payment, on: PaymentField, raw: str, longest: int) -> str | None:
    value = " ".join(raw.split()) or None
    if value is not None and len(value) > longest:
        payment.refuse(on, "too_long")
        return None
    return value


def read_payment(
    number: int, cells: Sequence[str], mapping: Mapping[PaymentField, int], today: date
) -> Payment:
    """One row, every check that needs nothing but the row made."""
    cell = Cells(cells, mapping)
    payment = Payment(number, "")
    read_who(payment, cell, PaymentField.RUT, PaymentField.EMAIL, PaymentField.NAME)

    paid_on = None
    if raw := cell(PaymentField.PAID_ON):
        paid_on = _day(payment, PaymentField.PAID_ON, raw, today)
    else:
        payment.refuse(PaymentField.PAID_ON, "required")
    amount = None
    if raw := cell(PaymentField.AMOUNT):
        if (amount := parse_amount(raw)) is None:
            payment.refuse(PaymentField.AMOUNT, "invalid_amount")
    else:
        payment.refuse(PaymentField.AMOUNT, "required")
    covers_month = None
    if raw := cell(PaymentField.COVERS_MONTH):
        covers_month = _day(payment, PaymentField.COVERS_MONTH, raw, today)
    raw = cell(PaymentField.METHOD)
    method = _METHODS.get(fold(raw).rstrip(".")) if raw else None
    if raw and method is None:
        payment.refuse(PaymentField.METHOD, "invalid_method")
    plan_name = _text(payment, PaymentField.PLAN_NAME, cell(PaymentField.PLAN_NAME), MAX_PLAN_NAME)
    note = _text(payment, PaymentField.NOTE, cell(PaymentField.NOTE), MAX_NOTE)

    if not payment.errors:
        assert paid_on is not None and amount is not None
        payment.entry = HistoryPaymentIn(
            paid_on=paid_on,
            amount_clp=amount,
            method=method,
            covers_month=covers_month,
            plan_name=plan_name,
            note=note,
        )
    return payment


def read_payments(
    rows: Sequence[tuple[int, Sequence[str]]], mapping: Mapping[PaymentField, int], today: date
) -> list[Payment]:
    return [read_payment(n, cells, mapping, today) for n, cells in rows]
