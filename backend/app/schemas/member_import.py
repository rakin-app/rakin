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


# A file's name as the browser gives it, no path.
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class SheetFile(BaseModel):
    """The file a sheet was read from, which the import's record names (#297)."""

    model_config = ConfigDict(extra="forbid")

    name: FileName | None
    sha256: Sha256


class Sheet(BaseModel):
    headers: list[str]
    rows: list[SheetRow]
    # The column each field most likely is, by its header.
    mapping: dict[ImportField, int]
    # Sent back with the rows, so the import says which file it was.
    file: SheetFile


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
    # A plan cell's value to the plan it means, for values that are not a plan's name;
    # `null` for no plan, so those rows import the person with no membership.
    plans: dict[Cell, uuid.UUID | None] = {}
    # Check everything and write nothing; the default, so a slip never imports.
    dry_run: bool = True
    # The file, as `POST /api/import/sheet` answered it: the import's record names it.
    file: SheetFile | None = None

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
    # The fields this row has that the import leaves unapplied: someone found here
    # keeps this gym's record of them, and a live membership keeps its plan and dates.
    ignored: list[ImportField]
    # Whom the gym messages about them (their guardian, for a dependent) has no phone:
    # imported anyway, and flagged "Falta teléfono" until one is filled in (#165).
    missing_phone: bool = False
    # Neither a RUT nor an email: imported, and found again by their name in this gym.
    missing_identity: bool = False
    # The import wrote some of their history from before Rakin: "Alumno desde", the day
    # they left and why, their classes before Rakin. Only where the gym had none.
    history: bool = False
    # A former student's row: one with the day they left, imported with no membership.
    former: bool = False


class ImportSummary(BaseModel):
    rows: int
    imported: int
    refused: int
    people_created: int
    links_created: int
    memberships_created: int
    # Rows imported with "Falta teléfono".
    missing_phone: int = 0
    # Rows imported with neither a RUT nor an email.
    missing_identity: int = 0
    # People whose history the import wrote.
    history_set: int = 0
    # Of the people created, those who had already left: former students.
    former_created: int = 0


class ImportReport(BaseModel):
    dry_run: bool
    # The import's `history_imported` row, when it wrote anything; never on a dry run.
    import_id: uuid.UUID | None = None
    summary: ImportSummary
    # In the sheet's order.
    rows: list[RowResult]
