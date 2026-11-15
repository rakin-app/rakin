"""The month's ledger for the gym's accountant, as CSV or XLSX (#40). Pure: rows in,
bytes out, no I/O.

One row per ledger entry, with Spanish headers: the date it counts on, the member and
their RUT, the plan or cobro extra, the period, the kind, method, amount, status, bank
reference and note, then the gym's custom fields that are not sensitive. A void (#256)
is a row of its own, "Anulación", never netted into the charge it voids. Proofs still
waiting are listed on their own, after the rest, and the totals count validated
entries only.

The CSV is what Excel opens in a Spanish locale with a double click: UTF-8 with a BOM,
`;` between fields, dates as dd-mm-yyyy, CLP as plain integers, the pending proofs and
the totals each under a title row after the entries. The XLSX has a sheet for each,
with real dates and integers in their cells.

Every text a person typed (a name, a note, a custom field) goes out as text: one that
starts like a formula is quoted in the CSV and typed as a string in the XLSX, so a
spreadsheet never runs it.
"""

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import Cell
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADERS = (
    "Fecha",
    "Alumno",
    "RUT",
    "Plan o cobro",
    "Período",
    "Tipo",
    "Método",
    "Monto (CLP)",
    "Estado",
    "Ref. bancaria",
    "Nota",
)

KINDS = {
    "charge": "Cargo",
    "payment": "Pago",
    "adjustment": "Ajuste",
    "refund": "Devolución",
}
VOID = "Anulación"
STATUSES = {"validated": "Validado", "pending": "Por validar", "rejected": "Rechazado"}
METHODS = {"cash": "Efectivo", "transfer": "Transferencia", "other": "Otro"}
# app.domain.extra_charges.Category, as the cobros screen names them.
CATEGORIES = {
    "rifa": "Rifa",
    "seminario": "Seminario",
    "equipamiento": "Equipamiento",
    "gasto_compartido": "Gasto compartido",
    "otro": "Otro",
}

PENDING_TITLE = "Comprobantes por validar (no cuentan en los totales)"
TOTALS_TITLE = "Totales del mes (solo lo validado)"

CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

DATE_FORMAT = "%d-%m-%Y"
XLSX_DATE = "DD-MM-YYYY"
XLSX_CLP = "#,##0"

# What a spreadsheet reads as the start of a formula.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class Row:
    day: date
    member: str
    rut: str | None
    # The plan's name, or a cobro extra's category and title (#195).
    concept: str | None
    # A cobro extra's entry has none.
    period: tuple[date, date] | None
    kind: str
    method: str | None
    # As the ledger keeps it: positive, but an adjustment's sign says which way it went,
    # positive in the member's favour.
    amount_clp: int
    status: str
    bank_ref: str | None
    note: str | None
    # The custom fields' values, in `MonthExport.fields`' order: text, a number or a day.
    fields: tuple[str | int | float | date | None, ...] = ()
    # On a cobro extra's line rather than a membership (#195).
    extra: bool = False


@dataclass(frozen=True)
class Totals:
    charged_clp: int
    paid_clp: int
    # Of what was paid, what cobros extra brought in.
    paid_extra_clp: int
    # Adjustments other than voids, each signed: in the member's favour is positive.
    adjusted_clp: int
    voided_clp: int
    refunded_clp: int
    # What the month's charges still owe today.
    outstanding_clp: int


@dataclass(frozen=True)
class MonthExport:
    month: date
    # The custom fields' labels, one column each after `HEADERS`.
    fields: tuple[str, ...]
    # Validated and rejected entries, in the order they count.
    entries: tuple[Row, ...]
    pending: tuple[Row, ...]
    totals: Totals


def kind_label(kind: str, voids: bool) -> str:
    return VOID if voids else KINDS[kind]


def concept(plan: str | None, category: str | None, title: str | None) -> str | None:
    """A cobro extra's entry by its category and title, any other by its plan."""
    if title is not None:
        return f"{CATEGORIES.get(category or '', 'Cobro extra')}: {title}"
    return plan


def totals(entries: Iterable[Row], outstanding_clp: int) -> Totals:
    """The month's totals from its entries, counting the validated ones alone."""
    sums: dict[str, int] = {}
    extra = 0
    for row in entries:
        if row.status != STATUSES["validated"]:
            continue
        sums[row.kind] = sums.get(row.kind, 0) + row.amount_clp
        if row.kind == KINDS["payment"] and row.extra:
            extra += row.amount_clp
    return Totals(
        charged_clp=sums.get(KINDS["charge"], 0),
        paid_clp=sums.get(KINDS["payment"], 0),
        paid_extra_clp=extra,
        adjusted_clp=sums.get(KINDS["adjustment"], 0),
        voided_clp=sums.get(VOID, 0),
        refunded_clp=sums.get(KINDS["refund"], 0),
        outstanding_clp=outstanding_clp,
    )


def total_lines(t: Totals) -> list[tuple[str, int]]:
    return [
        ("Total cargado", t.charged_clp),
        ("Total pagado", t.paid_clp),
        ("De lo pagado, cobros extra", t.paid_extra_clp),
        ("Total ajustado (a favor +, en contra -)", t.adjusted_clp),
        ("Total anulado", t.voided_clp),
        ("Total devuelto", t.refunded_clp),
        ("Cobrado neto (pagado menos devuelto)", t.paid_clp - t.refunded_clp),
        ("Saldo pendiente de los cargos del mes", t.outstanding_clp),
    ]


def filename(month: date, extension: str) -> str:
    return f"pagos-{month:%Y-%m}.{extension}"


# --- CSV ----------------------------------------------------------------------------


def safe_text(value: str) -> str:
    """`value` as a spreadsheet shows it and never runs it."""
    return f"'{value}" if value.startswith(FORMULA_START) else value


def csv_cell(value: str | int | float | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime(DATE_FORMAT)
    if isinstance(value, int | float):
        return str(value)
    return safe_text(value)


def period_text(period: tuple[date, date] | None) -> str | None:
    if period is None:
        return None
    start, end = period
    return f"{start.strftime(DATE_FORMAT)} al {end.strftime(DATE_FORMAT)}"


def cells(row: Row) -> list[str | int | float | date | None]:
    return [
        row.day,
        row.member,
        row.rut,
        row.concept,
        period_text(row.period),
        row.kind,
        row.method,
        row.amount_clp,
        row.status,
        row.bank_ref,
        row.note,
        *row.fields,
    ]


def to_csv(export: MonthExport) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow([*HEADERS, *(safe_text(f) for f in export.fields)])
    writer.writerows([csv_cell(c) for c in cells(row)] for row in export.entries)
    if export.pending:
        writer.writerow([])
        writer.writerow([PENDING_TITLE])
        writer.writerows([csv_cell(c) for c in cells(row)] for row in export.pending)
    writer.writerow([])
    writer.writerow([TOTALS_TITLE])
    writer.writerows([label, str(amount)] for label, amount in total_lines(export.totals))
    return ("﻿" + out.getvalue()).encode("utf-8")


# --- XLSX ---------------------------------------------------------------------------


def put(ws: Worksheet, row: int, column: int, value: str | int | float | date | None) -> Cell:
    """`value` into the cell at `row` and `column` with its type: a day as a date, CLP
    and numbers as numbers, anything else as text, a formula's look included."""
    cell = ws.cell(row=row, column=column)
    assert isinstance(cell, Cell)
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"
    elif isinstance(value, date):
        cell.number_format = XLSX_DATE
    elif isinstance(value, int):
        cell.number_format = XLSX_CLP
    return cell


def sheet(ws: Worksheet, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    widths = [len(h) for h in headers]
    for col, header in enumerate(headers, start=1):
        put(ws, 1, col, header).font = Font(bold=True)
    for r, values in enumerate(rows, start=2):
        for col, value in enumerate(values, start=1):
            put(ws, r, col, value)
            shown = value.strftime(DATE_FORMAT) if isinstance(value, date) else str(value or "")
            widths[col - 1] = max(widths[col - 1], len(shown))
    ws.freeze_panes = "A2"
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = min(width + 2, 60)


def to_xlsx(export: MonthExport) -> bytes:
    book = Workbook()
    headers = [*HEADERS, *export.fields]
    entries = book.active
    assert entries is not None
    entries.title = "Movimientos"
    sheet(entries, headers, (cells(row) for row in export.entries))
    sheet(book.create_sheet("Por validar"), headers, (cells(row) for row in export.pending))
    sheet(book.create_sheet("Totales"), ("Concepto", "Monto (CLP)"), total_lines(export.totals))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
