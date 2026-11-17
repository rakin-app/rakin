"""Member import: a sheet read, the rows sent back with a mapping, and what each row did.

The file is read once (`POST /api/import/sheet`) and the browser holds its rows from
then on, sending them back with the admin's mapping for a dry run and then for real
(`POST /api/import/members`). Nothing is stored between the two.

A workbook has tabs (#298, #299). The Alumnos tab is the top level of each body, as it
was before there were others, and is empty in a workbook without one; every other tab is
a field of its own (`pagos`, `grados`), absent when the workbook has none.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.member_import.grades import GradeErrorCode, GradeField
from app.member_import.payments import PaymentErrorCode, PaymentField
from app.member_import.rows import ErrorCode
from app.member_import.rows import Field as ImportField
from app.member_import.sheet import (
    MAX_CELL_LENGTH,
    MAX_COLUMNS,
    MAX_PAYMENT_ROWS,
    MAX_ROWS,
    SheetErrorCode,
)
from app.schemas.grading import Key

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


class PaymentSheet(BaseModel):
    """The Pagos tab: one row per payment received before Rakin."""

    headers: list[str]
    rows: list[SheetRow]
    mapping: dict[PaymentField, int]


class GradeSheet(BaseModel):
    """The Grados tab: one row per belt or stripe earned."""

    headers: list[str]
    rows: list[SheetRow]
    mapping: dict[GradeField, int]


class Sheet(BaseModel):
    # The Alumnos tab; no headers and no rows in a workbook without one.
    headers: list[str]
    rows: list[SheetRow]
    # The column each field most likely is, by its header.
    mapping: dict[ImportField, int]
    # Sent back with the rows, so the import says which file it was.
    file: SheetFile
    pagos: PaymentSheet | None = None
    grados: GradeSheet | None = None
    # A Grados tab the file has and the gym, grading in none of its activities, does not
    # read (#352): `grados` is then null.
    grados_ignored: bool = False


# `too_large`: over `MAX_UPLOAD_BYTES`. `unreadable`: neither a workbook nor text.
SheetRefusalCode = SheetErrorCode | Literal["too_large"]


class SheetRefusal(BaseModel):
    code: SheetRefusalCode


class SheetRefused(BaseModel):
    """413 or 422 body."""

    detail: SheetRefusal


def _one_field_per_column(mapping: dict[Any, int]) -> None:
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("a column maps to one field only")


class PaymentImport(BaseModel):
    """The Pagos tab's rows, checked after the Alumnos tab's."""

    model_config = ConfigDict(extra="forbid")

    rows: Annotated[list[SheetRow], Field(min_length=1, max_length=MAX_PAYMENT_ROWS)]
    # Field to column: `paid_on`, `amount_clp`, and one of `rut`, `email` or `name`.
    mapping: dict[PaymentField, Column]

    @field_validator("mapping")
    @classmethod
    def _required(cls, value: dict[PaymentField, int]) -> dict[PaymentField, int]:
        if PaymentField.PAID_ON not in value or PaymentField.AMOUNT not in value:
            raise ValueError("map a column to paid_on and one to amount_clp")
        if not {PaymentField.RUT, PaymentField.EMAIL, PaymentField.NAME} & value.keys():
            raise ValueError("map a column to rut, email or name")
        _one_field_per_column(value)
        return value


class GradeImport(BaseModel):
    """The Grados tab's rows, written after the Alumnos tab's."""

    model_config = ConfigDict(extra="forbid")

    rows: Annotated[list[SheetRow], Field(min_length=1, max_length=MAX_ROWS)]
    # Field to column: `rank`, `awarded_on`, and one of `rut`, `email` or `name`.
    mapping: dict[GradeField, Column]
    # A Grado cell's value to the rank it means, by key, for values that are not a
    # rank's label ("Café" → `brown`).
    ranks: dict[Cell, Key] = {}

    @field_validator("mapping")
    @classmethod
    def _required(cls, value: dict[GradeField, int]) -> dict[GradeField, int]:
        if GradeField.RANK not in value or GradeField.AWARDED_ON not in value:
            raise ValueError("map a column to rank and one to awarded_on")
        if not {GradeField.RUT, GradeField.EMAIL, GradeField.NAME} & value.keys():
            raise ValueError("map a column to rut, email or name")
        _one_field_per_column(value)
        return value


class MemberImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The Alumnos tab; empty when the workbook has none, and then another tab has rows.
    rows: Annotated[list[SheetRow], Field(max_length=MAX_ROWS)] = []
    # Field to column. `name` is required with rows; one column is one field.
    mapping: dict[ImportField, Column] = {}
    # A plan cell's value to the plan it means, for values that are not a plan's name;
    # `null` for no plan, so those rows import the person with no membership.
    plans: dict[Cell, uuid.UUID | None] = {}
    # Check everything and write nothing; the default, so a slip never imports.
    dry_run: bool = True
    # Charge each membership the import starts its plan's matrícula (#355); off, since
    # the members a sheet brings in have mostly paid theirs already.
    charge_enrolment: bool = False
    # The file, as `POST /api/import/sheet` answered it: the import's record names it.
    file: SheetFile | None = None
    pagos: PaymentImport | None = None
    grados: GradeImport | None = None

    @field_validator("mapping")
    @classmethod
    def _one_column_one_field(cls, value: dict[ImportField, int]) -> dict[ImportField, int]:
        _one_field_per_column(value)
        return value

    @model_validator(mode="after")
    def _some_rows(self) -> "MemberImport":
        if not self.rows and self.pagos is None and self.grados is None:
            raise ValueError("no rows to import")
        if self.rows and ImportField.NAME not in self.mapping:
            raise ValueError("map a column to name")
        return self


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


class PaymentRowError(BaseModel):
    field: PaymentField
    code: PaymentErrorCode


class PaymentRowResult(BaseModel):
    row: int
    # As the row names them: its name, else its RUT or email.
    name: str
    # Empty when the row is imported; a row with errors writes nothing.
    errors: list[PaymentRowError]
    # `existing`: they already have a payment of that day, amount and month.
    payment: Outcome | None


class PaymentSummary(BaseModel):
    rows: int
    imported: int
    refused: int
    payments_created: int
    # Of `payments_created`, in pesos.
    amount_clp: int


class PaymentReport(BaseModel):
    summary: PaymentSummary
    # In the sheet's order.
    rows: list[PaymentRowResult]


class GradeRowError(BaseModel):
    field: GradeField
    code: GradeErrorCode


class GradeRowResult(BaseModel):
    row: int
    # As the row names them: its name, else its RUT or email.
    name: str
    # Empty when the row is imported; a row with errors writes nothing.
    errors: list[GradeRowError]
    # `existing`: the person already has this rank and sub-rank on that day.
    grade: Outcome | None


class GradeSummary(BaseModel):
    rows: int
    imported: int
    refused: int
    grades_created: int


class GradeReport(BaseModel):
    summary: GradeSummary
    # In the sheet's order.
    rows: list[GradeRowResult]


class ImportReport(BaseModel):
    dry_run: bool
    # The import's `history_imported` row, when it wrote anything; never on a dry run.
    import_id: uuid.UUID | None = None
    # The Alumnos tab's; all zero, with no rows, in a workbook without one.
    summary: ImportSummary
    # In the sheet's order.
    rows: list[RowResult]
    # The Pagos tab's, when the import had one.
    pagos: PaymentReport | None = None
    # The Grados tab's, when the import had one.
    grados: GradeReport | None = None


class ImportUndone(BaseModel):
    """An import's undo (#300): when, by whom, why, and what it removed."""

    at: datetime
    by: str | None
    reason: str
    payments: int
    grades: int
    people: int
    kept: int


class RecentImport(BaseModel):
    """A line of Importar's recent imports: the `history_imported` row (0053)."""

    id: uuid.UUID
    at: datetime
    # The name the gym has for whoever imported; null once they are deleted.
    by: str | None
    file_name: str | None
    tabs: list[str]
    # Per tab, the counts the import wrote (`ImportSummary`, `PaymentSummary`, ...).
    counts: dict[str, dict[str, int]]
    undone: ImportUndone | None = None


class UndoCounts(BaseModel):
    """What "Deshacer importación" would remove: its history payments and grades, the
    people whose fields go back to what the import found, and the fields changed since,
    which stay."""

    payments: int
    grades: int
    people: int
    kept: int


class Undoing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


UndoRefusalCode = Literal["undone"]


class UndoRefusal(BaseModel):
    code: UndoRefusalCode


class UndoRefused(BaseModel):
    """409 body."""

    detail: UndoRefusal
