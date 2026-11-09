"""Member import: a sheet read, the rows sent back with a mapping, and what each row did.

The file is read once (`POST /api/import/sheet`) and the browser holds its rows from
then on, sending them back with the admin's mapping for a dry run and then for real
(`POST /api/import/members`). Nothing is stored between the two.
"""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.member_import.rows import ErrorCode
from app.member_import.rows import Field as ImportField
from app.member_import.sheet import MAX_CELL_LENGTH, MAX_COLUMNS, MAX_ROWS, SheetErrorCode

Cell = Annotated[str, StringConstraints(max_length=MAX_CELL_LENGTH)]
Column = Annotated[int, Field(ge=0, lt=MAX_COLUMNS)]


class SheetRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The row's number in the spreadsheet, which errors are reported by.
    number: Annotated[int, Field(ge=1)]
    cells: Annotated[list[Cell], Field(max_length=MAX_COLUMNS)]


class Sheet(BaseModel):
    headers: list[str]
    rows: list[SheetRow]
    # The column each field most likely is, by its header.
    mapping: dict[ImportField, int]


# `too_large`: over `MAX_UPLOAD_BYTES`. `unreadable`: neither a workbook nor text.
SheetRefusalCode = SheetErrorCode | Literal["too_large"]


class SheetRefusal(BaseModel):
    code: SheetRefusalCode


class SheetRefused(BaseModel):
    """413 or 422 body."""

    detail: SheetRefusal


class MemberImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: Annotated[list[SheetRow], Field(min_length=1, max_length=MAX_ROWS)]
    # Field to column. `name` is required; one column is one field.
    mapping: dict[ImportField, Column]
    # A plan cell's value to the plan it means, for values that are not a plan's name.
    plans: dict[Cell, uuid.UUID] = {}
    # Check everything and write nothing; the default, so a slip never imports.
    dry_run: bool = True

    @field_validator("mapping")
    @classmethod
    def _one_column_one_field(cls, value: dict[ImportField, int]) -> dict[ImportField, int]:
        if ImportField.NAME not in value:
            raise ValueError("map a column to name")
        if len(set(value.values())) != len(value):
            raise ValueError("a column maps to one field only")
        return value


class RowError(BaseModel):
    field: ImportField
    code: ErrorCode


# What the import found and did: `created` it, or found it `existing` and left it be.
Outcome = Literal["created", "existing"]


class RowResult(BaseModel):
    row: int
    name: str
    # Empty when the row is imported; a row with errors writes nothing.
    errors: list[RowError]
    person: Outcome | None
    guardian: Outcome | None
    # The guardian link between the two.
    link: Outcome | None
    membership: Outcome | None


class ImportSummary(BaseModel):
    rows: int
    imported: int
    refused: int
    people_created: int
    links_created: int
    memberships_created: int


class ImportReport(BaseModel):
    dry_run: bool
    summary: ImportSummary
    # In the sheet's order.
    rows: list[RowResult]
