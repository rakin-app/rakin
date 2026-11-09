"""A spreadsheet as rows of text: the first row that holds anything is the header.

An XLSX is read from its first worksheet. A CSV is UTF-8 (with or without the BOM
Excel writes), else Windows-1252, which is what Excel in Spanish saves as "CSV"; its
delimiter is a comma, semicolon or tab, whichever the file uses. Cells come back as
text: dates as `YYYY-MM-DD`, whole numbers without a decimal point, since a phone
typed into Excel is often stored as the number 912345678.

Fully empty rows are skipped, and each row keeps its number in the sheet, so an error
can point at the line the admin sees.
"""

import csv
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from openpyxl import load_workbook

# Far above a small gym's roster (under ~150 active students), with room for history.
MAX_ROWS = 2000
MAX_COLUMNS = 60
MAX_CELL_LENGTH = 500

ZIP_SIGNATURE = b"PK\x03\x04"

# How many rows are read at most, empty ones included, as a multiple of `MAX_ROWS`: an
# XLSX formatted down to row 1,048,576 compresses to almost nothing.
SCAN_FACTOR = 10

# `too_many_empty_rows`: data, or formatting, that goes on past `SCAN_FACTOR * MAX_ROWS`
# rows when most are empty.
SheetErrorCode = Literal["unreadable", "empty", "too_many_rows", "too_many_empty_rows"]


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
    """`data`, an XLSX or a CSV, as a header and its rows. Raises `SheetError`."""
    # An XLSX is a zip; one that starts like a zip and is not one is a damaged workbook.
    if data.startswith(ZIP_SIGNATURE):
        return _table(_xlsx_rows(data))
    return _table(_csv_rows(data))


def _table(numbered: Iterable[tuple[int, list[str]]]) -> Sheet:
    headers: list[str] | None = None
    rows: list[Row] = []
    for number, raw in numbered:
        if number > SCAN_FACTOR * MAX_ROWS:
            raise SheetError("too_many_empty_rows")
        cells = [cell.strip()[:MAX_CELL_LENGTH] for cell in raw[:MAX_COLUMNS]]
        if not any(cells):
            continue
        if headers is None:
            headers = cells
            continue
        if len(rows) == MAX_ROWS:
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


def _xlsx_rows(data: bytes) -> Iterator[tuple[int, list[str]]]:
    # openpyxl parses through defusedxml, which is installed, so entity tricks fail. A
    # zip that is not a workbook, or a damaged one, raises any of a dozen types.
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise SheetError("unreadable") from None
    try:
        if not workbook.worksheets:
            raise SheetError("empty")
        rows = workbook.worksheets[0].iter_rows(max_col=MAX_COLUMNS, values_only=True)
        yield from ((n, [_cell(v) for v in values]) for n, values in enumerate(rows, start=1))
    except SheetError:
        raise
    except Exception:
        raise SheetError("unreadable") from None
    finally:
        workbook.close()
