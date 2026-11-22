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
the totals each under a title row after the entries, and a line saying how each entry is
dated after them. The XLSX has a sheet for each,
with real dates and integers in their cells.

The member's column is headed by what the gym calls one (#345, `app.domain.vocabulary`):
"Alumno" for a gym that never said, "Socio" for one that says "socios".

For a person who may also see the gym's expenses (`expenses_read`, #317), the XLSX
gains a **Gastos** sheet, the month's expenses by the day they were paid with the voided
ones listed apart as "Anulado", and a **Resumen**: Entradas, Salidas by category and
Resultado, as Finanzas shows them (#316). The same expenses go out as a CSV of their own,
"Gastos del mes", since a CSV holds one table. Anyone else gets the file as it was.

Every text a person typed (a name, a note, a custom field, a category, a payee) goes out
as text: one that starts like a formula is quoted in the CSV and typed as a string in
the XLSX, so a spreadsheet never runs it.
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

from app.domain.vocabulary import DEFAULT_WORDS, Words


def headers(words: Words) -> tuple[str, ...]:
    """The entries' headers, the member's in the gym's word, before the custom fields'."""
    return (
        "Fecha",
        words.member.capitalize(),
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


# As a gym with no words of its own has them: "Alumno".
HEADERS = headers(DEFAULT_WORDS)

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
    "matricula": "Matrícula",
}

PENDING_TITLE = "Comprobantes por validar (no cuentan en los totales)"
TOTALS_TITLE = "Totales del mes (solo lo validado)"
# How the export dates a payment, which the Pagos list dates by the day it was made.
FILED_BY = (
    "Fecha: un cargo, el inicio de su período; un pago o devolución validado, el día en"
    " que se validó (como Cobrado en Pagos); lo demás, el día en que se registró."
    " No incluye el historial anterior a Rakin."
)

# The expenses' columns (#317), as Gastos heads them.
EXPENSE_HEADERS = (
    "Fecha",
    "Categoría",
    "Pagado a",
    "Método",
    "Monto (CLP)",
    "Nota",
    "Comprobante",
    "Estado",
)
# How the gym paid: the ledger's methods, and a card (migration 0083).
EXPENSE_METHODS = {**METHODS, "card": "Tarjeta"}
COUNTS = "Vigente"
VOIDED = "Anulado"
RECEIPT = {True: "Sí", False: "No"}
VOIDED_TITLE = "Gastos anulados (no cuentan en los totales)"
EXPENSE_TOTALS_TITLE = "Totales del mes (sin los anulados)"

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
    # What the gym calls its members, for the member's column.
    words: Words = DEFAULT_WORDS


@dataclass(frozen=True)
class ExpenseRow:
    # The day it was paid on, which decides its month.
    day: date
    category: str
    payee: str | None
    method: str | None
    amount_clp: int
    note: str | None
    receipt: bool
    voided: bool = False


@dataclass(frozen=True)
class MonthExpenses:
    """The month's expenses for a person with `expenses_read` (#317)."""

    month: date
    # Those that count, by the day they were paid.
    expenses: tuple[ExpenseRow, ...]
    voided: tuple[ExpenseRow, ...]
    # What counts per category, in the gym's order, as Finanzas sums it.
    by_category: tuple[tuple[str, int], ...]
    # Entradas as Finanzas counts them; `None` when the file carries no income.
    income_clp: int | None = None


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


def expense_total_lines(e: MonthExpenses) -> list[tuple[str, int]]:
    """What the month spent per category, and in all."""
    return [*e.by_category, ("Total gastos", sum(amount for _, amount in e.by_category))]


def summary_lines(e: MonthExpenses) -> list[tuple[str, int]]:
    """The Resumen: what came in, what went out by category, and what is left."""
    assert e.income_clp is not None, "a Resumen needs the month's income"
    spent = sum(amount for _, amount in e.by_category)
    return [
        ("Entradas (cobrado neto)", e.income_clp),
        *((f"Salidas: {name}", amount) for name, amount in e.by_category),
        ("Total salidas", spent),
        ("Resultado (entradas menos salidas)", e.income_clp - spent),
    ]


def filename(month: date, extension: str) -> str:
    return f"pagos-{month:%Y-%m}.{extension}"


def expenses_filename(month: date) -> str:
    return f"gastos-{month:%Y-%m}.csv"


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


def expense_cells(row: ExpenseRow) -> list[str | int | date | None]:
    return [
        row.day,
        row.category,
        row.payee,
        row.method,
        row.amount_clp,
        row.note,
        RECEIPT[row.receipt],
        VOIDED if row.voided else COUNTS,
    ]


def csv_writer() -> tuple[io.StringIO, Any]:
    out = io.StringIO()
    return out, csv.writer(out, delimiter=";", lineterminator="\r\n")


def csv_bytes(out: io.StringIO) -> bytes:
    """What the writer wrote, as Excel opens it with a double click: UTF-8 with a BOM."""
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def to_csv(export: MonthExport) -> bytes:
    out, writer = csv_writer()
    writer.writerow([*headers(export.words), *(safe_text(f) for f in export.fields)])
    writer.writerows([csv_cell(c) for c in cells(row)] for row in export.entries)
    if export.pending:
        writer.writerow([])
        writer.writerow([PENDING_TITLE])
        writer.writerows([csv_cell(c) for c in cells(row)] for row in export.pending)
    writer.writerow([])
    writer.writerow([TOTALS_TITLE])
    writer.writerows([label, str(amount)] for label, amount in total_lines(export.totals))
    writer.writerow([])
    writer.writerow([FILED_BY])
    return csv_bytes(out)


def expenses_csv(e: MonthExpenses) -> bytes:
    """The month's expenses, "Gastos del mes (CSV)": those that count, the voided ones
    apart under a title row, then the totals by category, as the ledger's CSV is laid
    out."""
    out, writer = csv_writer()
    writer.writerow(EXPENSE_HEADERS)
    writer.writerows([csv_cell(c) for c in expense_cells(row)] for row in e.expenses)
    if e.voided:
        writer.writerow([])
        writer.writerow([VOIDED_TITLE])
        writer.writerows([csv_cell(c) for c in expense_cells(row)] for row in e.voided)
    writer.writerow([])
    writer.writerow([EXPENSE_TOTALS_TITLE])
    writer.writerows([safe_text(label), str(amount)] for label, amount in expense_total_lines(e))
    return csv_bytes(out)


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


def expense_sheets(book: Workbook, e: MonthExpenses) -> None:
    """Gastos, the voided ones listed apart under a title row, and the Resumen."""
    ws = book.create_sheet("Gastos")
    sheet(ws, EXPENSE_HEADERS, (expense_cells(row) for row in e.expenses))
    if e.voided:
        first = ws.max_row + 2
        put(ws, first, 1, VOIDED_TITLE).font = Font(bold=True)
        for r, row in enumerate(e.voided, start=first + 1):
            for col, value in enumerate(expense_cells(row), start=1):
                put(ws, r, col, value)
    sheet(book.create_sheet("Resumen"), ("Concepto", "Monto (CLP)"), summary_lines(e))


def to_xlsx(export: MonthExport, expenses: MonthExpenses | None = None) -> bytes:
    book = Workbook()
    columns = [*headers(export.words), *export.fields]
    entries = book.active
    assert entries is not None
    entries.title = "Movimientos"
    sheet(entries, columns, (cells(row) for row in export.entries))
    sheet(book.create_sheet("Por validar"), columns, (cells(row) for row in export.pending))
    totals = book.create_sheet("Totales")
    sheet(totals, ("Concepto", "Monto (CLP)"), total_lines(export.totals))
    put(totals, totals.max_row + 2, 1, FILED_BY)
    if expenses is not None:
        expense_sheets(book, expenses)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
