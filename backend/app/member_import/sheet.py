"""A spreadsheet as rows of text: the first row that holds anything is the header.

A workbook is read by tab (`read_book`): the worksheets named Alumnos, Pagos and
Grados, by folded name, else the first visible one that is none of them as Alumnos
(#298, #299). The people's tab goes by any gym's word for its members too (#345):
Socios, Deportistas or Miembros, as the template names it in such a gym. A hidden
sheet is never that fallback, though it is the first: the template hides its lists. A CSV is one
tab, the one the upload says. `read_sheet` is the Alumnos tab alone.

A CSV is UTF-8 (with or without the BOM Excel writes), else Windows-1252, which is what
Excel in Spanish saves as "CSV"; its delimiter is a comma, semicolon or tab, whichever
the file uses. Cells come back as
text: dates as `YYYY-MM-DD`, whole numbers without a decimal point, since a phone
typed into Excel is often stored as the number 912345678.

Fully empty rows are skipped, and each row keeps its number in the sheet, so an error
can point at the line the admin sees.
"""

import csv
import io
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, get_args

from openpyxl import load_workbook

from app.domain.vocabulary import MEMBERS
from app.member_import.rows import fold

# Far above a small gym's roster (under ~150 active students), with room for history.
MAX_ROWS = 2000
# Five years of a 300-student gym paying monthly (#298).
MAX_PAYMENT_ROWS = 20_000
MAX_COLUMNS = 60
MAX_CELL_LENGTH = 500

ZIP_SIGNATURE = b"PK\x03\x04"

# How many rows are read at most, empty ones included, as a multiple of the tab's cap: an
# XLSX formatted down to row 1,048,576 compresses to almost nothing.
SCAN_FACTOR = 10

# `too_many_empty_rows`: data, or formatting, that goes on past `SCAN_FACTOR` times the
# tab's cap when most are empty.
SheetErrorCode = Literal["unreadable", "empty", "too_many_rows", "too_many_empty_rows"]


# The tabs an import reads, in the order it writes them: people first, so a payment or a
# grade finds a student the Alumnos tab adds.
Tab = Literal["alumnos", "pagos", "grados"]
TABS: tuple[Tab, ...] = get_args(Tab)
# The most rows each tab may have.
ROW_CAPS: dict[Tab, int] = {"alumnos": MAX_ROWS, "pagos": MAX_PAYMENT_ROWS, "grados": MAX_ROWS}
# A workbook's tab that is never the Alumnos one, however it comes first.
INSTRUCTIONS = "instrucciones"


class SheetError(ValueError):
    def __init__(self, code: SheetErrorCode) -> None:
        super().__init__(code)
        self.code: SheetErrorCode = code


@dataclass(frozen=True)
class Row:
    # 1-based, as the spreadsheet numbers it.
    number: int
    cells: list[str]


@dataclass(frozen=True)
class Sheet:
    headers: list[str]
    rows: list[Row]


def read_sheet(data: bytes) -> Sheet:
    """`data`, an XLSX or a CSV, as a header and its rows: the Alumnos tab. Raises
    `SheetError`."""
    sheet = read_book(data).get("alumnos")
    if sheet is None:
        raise SheetError("empty")
    return sheet


def read_book(data: bytes, csv_tab: Tab = "alumnos") -> dict[Tab, Sheet]:
    """`data`, an XLSX or a CSV, as the tabs it has rows for; a CSV is `csv_tab`. A tab
    with no rows is left out, and a book with none is `empty`. Raises `SheetError`."""
    # An XLSX is a zip; one that starts like a zip and is not one is a damaged workbook.
    if not data.startswith(ZIP_SIGNATURE):
        return {csv_tab: _table(_csv_rows(data), ROW_CAPS[csv_tab])}
    book: dict[Tab, Sheet] = {}
    with _workbook(data) as workbook:
        for tab, worksheet in _tabs(workbook):
            try:
                book[tab] = _table(_xlsx_rows(worksheet), ROW_CAPS[tab])
            except SheetError as error:
                if error.code != "empty":
                    raise
    if not book:
        raise SheetError("empty")
    return book


def _table(numbered: Iterable[tuple[int, list[str]]], max_rows: int) -> Sheet:
    headers: list[str] | None = None
    rows: list[Row] = []
    for number, raw in numbered:
        if number > SCAN_FACTOR * max_rows:
            raise SheetError("too_many_empty_rows")
        cells = [cell.strip()[:MAX_CELL_LENGTH] for cell in raw[:MAX_COLUMNS]]
        if not any(cells):
            continue
        if headers is None:
            headers = cells
            continue
        if len(rows) == max_rows:
            raise SheetError("too_many_rows")
        rows.append(Row(number, (cells + [""] * len(headers))[: len(headers)]))
    if headers is None:
        raise SheetError("empty")
    # A header with blank columns past the last named one, as Excel often leaves.
    while headers and not headers[-1] and not any(row.cells[len(headers) - 1] for row in rows):
        headers.pop()
        rows = [Row(row.number, row.cells[: len(headers)]) for row in rows]
    if not rows:
        raise SheetError("empty")
    return Sheet(headers, rows)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _csv_rows(data: bytes) -> Iterator[tuple[int, list[str]]]:
    text = _decode(data)
    if "\x00" in text:
        raise SheetError("unreadable")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:8192], delimiters=",;\t"
        )
    except csv.Error:
        dialect = csv.excel
    try:
        yield from enumerate(csv.reader(io.StringIO(text), dialect), start=1)
    except csv.Error:
        raise SheetError("unreadable") from None


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@contextmanager
def _workbook(data: bytes) -> Iterator[Any]:
    # openpyxl parses through defusedxml, which is installed, so entity tricks fail. A
    # zip that is not a workbook, or a damaged one, raises any of a dozen types.
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise SheetError("unreadable") from None
    try:
        yield workbook
    finally:
        workbook.close()


def _tabs(workbook: Any) -> list[tuple[Tab, Any]]:
    """The worksheet each tab is, in `TABS` order."""
    try:
        worksheets = list(workbook.worksheets)
        titles = [fold(ws.title) for ws in worksheets]
        visible = [ws.sheet_state == "visible" for ws in worksheets]
    except Exception:
        raise SheetError("unreadable") from None
    named = {tab: titles.index(tab) for tab in TABS if tab in titles}
    if "alumnos" not in named:
        # The template of a gym with words of its own: "Socios", say.
        people = next((i for i, title in enumerate(titles) if title in MEMBERS), None)
        if people is not None:
            named["alumnos"] = people
    if "alumnos" not in named:
        # An old sheet: its first tab is the people, unless it is another tab or the
        # template's instructions.
        first = next(
            (
                i
                for i, title in enumerate(titles)
                if visible[i] and title not in (*TABS, INSTRUCTIONS)
            ),
            None,
        )
        if first is not None:
            named["alumnos"] = first
    return [(tab, worksheets[named[tab]]) for tab in TABS if tab in named]


def _xlsx_rows(worksheet: Any) -> Iterator[tuple[int, list[str]]]:
    try:
        rows = worksheet.iter_rows(max_col=MAX_COLUMNS, values_only=True)
        yield from ((n, [_cell(v) for v in values]) for n, values in enumerate(rows, start=1))
    except Exception:
        raise SheetError("unreadable") from None
