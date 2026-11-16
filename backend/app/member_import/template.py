"""Rakin's spreadsheet to fill in, "Descargar plantilla" on Importar (#297).

The Alumnos tab's columns, in the order docs/design/historical-data.md (section 3) lists
them, each header one `rows.suggest_mapping` maps by itself, so a filled template
uploads with no change on the mapping step. One example row in grey, which the
instructions say to delete; the gym's active plans as the Plan column's choices; and an
"Instrucciones" tab.

A Pagos tab (#298): one row per payment from before Rakin, Efectivo, Transferencia and
Otro the Método column's choices, and on the instructions tab how a gym that keeps a grid
(a student per row, a month per column) turns it into rows.

In a gym that grades, a Grados tab too (#299): one row per belt or stripe earned, the
scheme's rank labels as the Grado column's choices.
"""

import io
from collections.abc import Mapping, Sequence
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from app.ledger_export import put
from app.member_import.grades import GradeField
from app.member_import.payments import PaymentField
from app.member_import.rows import Field
from app.member_import.sheet import MAX_PAYMENT_ROWS, MAX_ROWS
from app.schemas.grading import GradingScheme

TEMPLATE_NAME = "plantilla-alumnos.xlsx"

ALUMNOS = "Alumnos"
PAGOS = "Pagos"
GRADOS = "Grados"
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

# The Pagos tab's, as `payments.suggest_payment_mapping` maps them. The example is the
# Alumnos tab's example student, paying for April 2024.
PAYMENT_COLUMNS: tuple[tuple[str, PaymentField, str], ...] = (
    ("RUT", PaymentField.RUT, "12.345.678-5"),
    ("Correo", PaymentField.EMAIL, ""),
    ("Nombre", PaymentField.NAME, "Martina Soto Pérez"),
    ("Fecha de pago", PaymentField.PAID_ON, "03-04-2024"),
    ("Monto", PaymentField.AMOUNT, "25000"),
    ("Mes que paga", PaymentField.COVERS_MONTH, "04-2024"),
    ("Método", PaymentField.METHOD, "Transferencia"),
    ("Plan", PaymentField.PLAN_NAME, "Mensual 3x semana"),
    ("Nota", PaymentField.NOTE, ""),
)

METHODS = ("Efectivo", "Transferencia", "Otro")

PAYMENT_NOTES: dict[PaymentField, str] = {
    PaymentField.RUT: (
        "Por quién se pagó: su RUT, su correo o su nombre, como en Alumnos. El pago de un"
        " menor va con los datos del menor."
    ),
    PaymentField.PAID_ON: "Obligatorio. El día que pagó: día-mes-año.",
    PaymentField.AMOUNT: "Obligatorio. En pesos, sin decimales: 25000, 25.000 o $25.000.",
    PaymentField.COVERS_MONTH: "Opcional. El mes que pagó, como mes-año: 04-2024.",
    PaymentField.METHOD: "Opcional. Efectivo, Transferencia u Otro.",
    PaymentField.PLAN_NAME: "Opcional. El plan como lo llamaban entonces, en texto libre.",
}

PAYMENT_INTRO = (
    "Una fila por pago, en la pestaña Pagos. Cada persona debe estar en Alumnos o ya en"
    " Rakin; no se crea a nadie. Es solo historial: no se cobra ni cambia lo que deben.",
    "Los meses desde que la persona tiene un plan en Rakin no van aquí: se pagan con"
    " Pagado hasta, en su ficha.",
    "Si vuelves a subir la planilla, un pago que ya está (misma persona, día, monto y mes)"
    " no se repite. Dos pagos iguales en la planilla cuentan como uno: si de verdad fueron"
    " dos, cambia el Mes que paga, o agrega el segundo a mano en su ficha.",
)

# For a gym whose notebook is a grid: one row per student, one column per month.
GRID_RECIPE = (
    "¿Tu planilla tiene un alumno por fila y un mes por columna? Pásala a filas así:",
    "1. Por cada casilla con un pago, agrega una fila en Pagos.",
    "2. En RUT o Nombre, el del alumno de esa fila.",
    "3. En Monto, lo que dice la casilla.",
    "4. En Mes que paga, el mes de esa columna (04-2024).",
    "5. En Fecha de pago, el día que pagó; si no lo sabes, el 5 de ese mes (05-04-2024).",
    "Las casillas vacías no se copian: ese mes no pagó.",
)

# The Grados tab's, as `grades.suggest_grade_mapping` maps them. The example is the
# Alumnos tab's example student; its rank, the scheme's.
GRADE_COLUMNS: tuple[tuple[str, GradeField, str], ...] = (
    ("RUT", GradeField.RUT, "12.345.678-5"),
    ("Correo", GradeField.EMAIL, ""),
    ("Nombre", GradeField.NAME, "Martina Soto Pérez"),
    ("Grado", GradeField.RANK, ""),
    ("Sub-grado", GradeField.SUB_RANK, ""),
    ("Fecha", GradeField.AWARDED_ON, "12-08-2023"),
    ("Nota", GradeField.NOTE, "Graduación de invierno"),
)

GRADE_NOTES: dict[GradeField, str] = {
    GradeField.RUT: "Quién recibió el grado: su RUT, su correo o su nombre, como en Alumnos.",
    GradeField.RANK: "Obligatorio. El grado, de la lista.",
    GradeField.SUB_RANK: (
        "Opcional: cuántos grados (rayas) tiene, o el sub-grado por su nombre. Ej.: Azul y 2"
        " = azul con 2 grados. Vacío = sin grados."
    ),
    GradeField.AWARDED_ON: "Obligatorio. El día que lo recibió, aunque sea antes de Rakin.",
}

GRADE_INTRO = (
    "Una fila por grado recibido, en la pestaña Grados: el más reciente queda como su"
    " grado actual. Cada persona debe estar en Alumnos o ya en Rakin; no se crea a nadie.",
)

INTRO = (
    "Una fila por alumno, en la pestaña Alumnos. La fila gris de cada pestaña es un"
    " ejemplo: bórrala antes de subir la planilla.",
    "Súbela en Alumnos, botón Importar. Primero revisamos cada fila sin guardar nada.",
    "Puedes volver a subirla: a quien ya está no lo duplicamos ni cambiamos lo que ya"
    " tiene. Alumno desde, Fecha de baja, Motivo de baja y Clases antes de Rakin se"
    " completan si estaban vacíos.",
    "Las fechas van como día-mes-año: 05-03-2019.",
)

GREY = "808080"


def template(plans: Sequence[str], scheme: GradingScheme | None = None) -> bytes:
    """The workbook, with `plans` (the gym's active plan names) as the Plan choices and
    the first of them in the example row, a Pagos tab, and a Grados tab for `scheme`'s
    ranks."""
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

    pagos = _tab(book, PAGOS, PAYMENT_COLUMNS, {})
    ranks = [] if scheme is None else [r.label for r in (*scheme.ranks, *scheme.kids_ladder)]
    grados = None
    if scheme is not None and ranks:
        grados = _grados(book, scheme)

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
    row += 1
    for line in (*PAYMENT_INTRO, "", *GRID_RECIPE):
        row += 1
        put(instructions, row, 1, line)
    row += 2
    put(instructions, row, 1, f"Columna de {PAGOS}").font = Font(bold=True)
    put(instructions, row, 2, "Qué va").font = Font(bold=True)
    for header, payment_field, _ in PAYMENT_COLUMNS:
        row += 1
        put(instructions, row, 1, header)
        put(instructions, row, 2, PAYMENT_NOTES.get(payment_field, ""))
    if grados is not None:
        row += 1
        for line in GRADE_INTRO:
            row += 1
            put(instructions, row, 1, line)
        row += 1
        put(instructions, row, 1, f"Columna de {GRADOS}").font = Font(bold=True)
        put(instructions, row, 2, "Qué va").font = Font(bold=True)
        for header, grade_field, _ in GRADE_COLUMNS:
            row += 1
            put(instructions, row, 1, header)
            put(instructions, row, 2, GRADE_NOTES.get(grade_field, ""))

    if plans:
        _choices(book, alumnos, "Planes", plans, _column(COLUMNS, Field.PLAN))
    # Three fixed words: the rule itself can list them.
    methods = DataValidation(
        type="list", formula1=f'"{",".join(METHODS)}"', allow_blank=True, showErrorMessage=False
    )
    letter = _column(PAYMENT_COLUMNS, PaymentField.METHOD)
    methods.add(f"{letter}2:{letter}{MAX_PAYMENT_ROWS + 1}")
    pagos.add_data_validation(methods)
    if grados is not None:
        _choices(book, grados, "Lista de grados", ranks, _column(GRADE_COLUMNS, GradeField.RANK))

    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _grados(book: Workbook, scheme: GradingScheme) -> Worksheet:
    """The Grados tab, its example the Alumnos tab's student at the scheme's second rank
    (the first a student is promoted to), with a stripe when it has them."""
    ranks = [*scheme.ranks, *scheme.kids_ladder]
    rank = ranks[1] if len(ranks) > 1 else ranks[0]
    examples = {
        GradeField.RANK: rank.label,
        GradeField.SUB_RANK: "1" if len(rank.sub_ranks) > 1 else "",
    }
    return _tab(book, GRADOS, GRADE_COLUMNS, examples)


def _tab(
    book: Workbook,
    title: str,
    columns: Sequence[tuple[str, object, str]],
    examples: Mapping[Any, str],
) -> Worksheet:
    """A tab of `columns`: their headers in bold, the example row in grey, the example
    `examples` gives a field in place of the column's own."""
    tab: Worksheet = book.create_sheet(title)
    for column, (header, field, example) in enumerate(columns, start=1):
        example = examples.get(field, example)
        put(tab, 1, column, header).font = Font(bold=True)
        put(tab, 2, column, example).font = Font(color=GREY, italic=True)
        letter = get_column_letter(column)
        tab.column_dimensions[letter].width = max(len(header), len(example)) + 4
    tab.freeze_panes = "A2"
    return tab


def _column(columns: Sequence[tuple[str, object, str]], field: object) -> str:
    return get_column_letter(next(i for i, c in enumerate(columns, 1) if c[1] is field))


def _choices(
    book: Workbook, tab: Worksheet, listed_on: str, values: Sequence[str], column: str
) -> None:
    """`tab`'s `column` offers `values`, listed on a hidden tab: a list typed into the
    rule itself breaks on a comma in a name and stops at 255 characters."""
    listed = book.create_sheet(listed_on)
    for row, value in enumerate(values, start=1):
        put(listed, row, 1, value)
    listed.sheet_state = "hidden"
    # A tab's name with a space is quoted in a formula.
    ref = f"'{listed_on}'" if " " in listed_on else listed_on
    rule = DataValidation(
        type="list",
        formula1=f"={ref}!$A$1:$A${len(values)}",
        allow_blank=True,
        showErrorMessage=False,
    )
    rule.add(f"{column}2:{column}{MAX_ROWS + 1}")
    tab.add_data_validation(rule)
