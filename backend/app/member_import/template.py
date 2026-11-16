"""Rakin's spreadsheet to fill in, "Descargar plantilla" on Importar (#297).

The Alumnos tab's columns, in the order docs/design/historical-data.md (section 3) lists
them, each header one `rows.suggest_mapping` maps by itself, so a filled template
uploads with no change on the mapping step. One example row in grey, which the
instructions say to delete; the gym's active plans as the Plan column's choices; and an
"Instrucciones" tab.
"""

import io
from collections.abc import Sequence

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.ledger_export import put
from app.member_import.rows import Field
from app.member_import.sheet import MAX_ROWS

TEMPLATE_NAME = "plantilla-alumnos.xlsx"

ALUMNOS = "Alumnos"
INSTRUCTIONS = "Instrucciones"

# Header, the field it maps to, and the example row's value.
COLUMNS: tuple[tuple[str, Field, str], ...] = (
    ("Nombre", Field.NAME, "Martina"),
    ("Apellido", Field.LAST_NAME, "Soto Pérez"),
    ("RUT", Field.RUT, "12.345.678-5"),
    ("Correo", Field.EMAIL, "martina@example.cl"),
    ("Teléfono", Field.PHONE, "+56 9 1234 5678"),
    ("Fecha de nacimiento", Field.DOB, "14-03-2010"),
    ("Apoderado", Field.GUARDIAN_NAME, "Paula Pérez"),
    ("RUT apoderado", Field.GUARDIAN_RUT, ""),
    ("Correo apoderado", Field.GUARDIAN_EMAIL, ""),
    ("Teléfono apoderado", Field.GUARDIAN_PHONE, ""),
    ("Plan", Field.PLAN, "Mensual"),
    ("Próximo vencimiento", Field.DUE_ON, "01-12-2026"),
    ("Inicio del plan", Field.STARTED_ON, ""),
    ("Alumno desde", Field.MEMBER_SINCE, "05-03-2019"),
    ("Fecha de baja", Field.LEFT_ON, ""),
    ("Motivo de baja", Field.LEFT_REASON, ""),
    ("Clases antes de Rakin", Field.PRIOR_CLASSES, "320"),
)

# What each column is for, on the instructions tab.
NOTES: dict[Field, str] = {
    Field.NAME: "Obligatorio.",
    Field.RUT: "Con RUT o correo encontramos a la persona si vuelves a importar. Mejor el RUT.",
    Field.EMAIL: "",
    Field.PHONE: "Celular, como +56 9 1234 5678.",
    Field.DOB: "Día-mes-año.",
    Field.GUARDIAN_NAME: "Para un menor: quien está a cargo. Recibe los avisos.",
    Field.PLAN: "El plan que tiene hoy, de la lista. Vacío para un exalumno.",
    Field.DUE_ON: "Su próximo pago. Necesario con un plan mensual o semestral.",
    Field.STARTED_ON: "Solo para packs de clases y pruebas.",
    Field.MEMBER_SINCE: "El día que empezó a entrenar aquí, aunque sea antes de Rakin.",
    Field.LEFT_ON: "Para un exalumno: el día que dejó de venir. Se importa sin plan.",
    Field.LEFT_REASON: "Por qué se fue, si lo sabes. Solo lo ven el dueño y los admins.",
    Field.PRIOR_CLASSES: "Cuántas clases tuvo antes de Rakin: un número.",
}

INTRO = (
    "Una fila por alumno, en la pestaña Alumnos. La fila gris es un ejemplo: bórrala antes"
    " de subir la planilla.",
    "Súbela en Alumnos, botón Importar. Primero revisamos cada fila sin guardar nada.",
    "Puedes volver a subirla: a quien ya está no lo duplicamos ni cambiamos lo que ya"
    " tiene. Alumno desde, Fecha de baja, Motivo de baja y Clases antes de Rakin se"
    " completan si estaban vacíos.",
    "Las fechas van como día-mes-año: 05-03-2019.",
)

GREY = "808080"


def template(plans: Sequence[str]) -> bytes:
    """The workbook, with `plans` (the gym's active plan names) as the Plan choices and
    the first of them in the example row."""
    book = Workbook()
    alumnos = book.active
    assert alumnos is not None
    alumnos.title = ALUMNOS
    for column, (header, field, example) in enumerate(COLUMNS, start=1):
        if field is Field.PLAN and plans:
            example = plans[0]
        put(alumnos, 1, column, header).font = Font(bold=True)
        put(alumnos, 2, column, example).font = Font(color=GREY, italic=True)
        letter = get_column_letter(column)
        alumnos.column_dimensions[letter].width = max(len(header), len(example)) + 4
    alumnos.freeze_panes = "A2"

    instructions = book.create_sheet(INSTRUCTIONS)
    instructions.column_dimensions["A"].width = 24
    instructions.column_dimensions["B"].width = 90
    row = 1
    for line in INTRO:
        put(instructions, row, 1, line)
        row += 1
    row += 1
    put(instructions, row, 1, "Columna").font = Font(bold=True)
    put(instructions, row, 2, "Qué va").font = Font(bold=True)
    for header, field, _ in COLUMNS:
        row += 1
        put(instructions, row, 1, header)
        put(instructions, row, 2, NOTES.get(field, ""))

    if plans:
        _plan_choices(book, alumnos, plans)

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _plan_choices(book: Workbook, alumnos: Worksheet, plans: Sequence[str]) -> None:
    """The Plan column offers the gym's plans, listed on a hidden tab: a list typed into
    the rule itself breaks on a comma in a name and stops at 255 characters."""
    listed = book.create_sheet("Planes")
    for row, name in enumerate(plans, start=1):
        put(listed, row, 1, name)
    listed.sheet_state = "hidden"
    column = get_column_letter(next(i for i, c in enumerate(COLUMNS, 1) if c[1] is Field.PLAN))
    rule = DataValidation(
        type="list",
        formula1=f"=Planes!$A$1:$A${len(plans)}",
        allow_blank=True,
        showErrorMessage=False,
    )
    rule.add(f"{column}2:{column}{MAX_ROWS + 1}")
    alumnos.add_data_validation(rule)
