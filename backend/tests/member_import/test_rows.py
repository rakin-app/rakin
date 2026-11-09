"""Rows to members, with no database: the mapping suggested, cells read, rows checked."""

import uuid
from datetime import date
from pathlib import Path

import pytest

from app.domain.membership import PlanKind, PlanTerms
from app.member_import.rows import (
    Field,
    Member,
    Plan,
    PlanFinder,
    RowError,
    fold,
    parse_date,
    read_members,
    suggest_mapping,
)
from app.member_import.sheet import read_sheet

F = Field
TODAY = date(2026, 11, 9)
PILOT = Path(__file__).parent.parent / "fixtures" / "pilot_sheet.csv"


def plan(name: str, kind: PlanKind, *, active: bool = True, **terms: object) -> Plan:
    return Plan(uuid.uuid4(), name, active, PlanTerms(kind, **terms))  # type: ignore[arg-type]


MENSUAL = plan("Mensual", PlanKind.MONTHLY, anchor="signup")
KIDS = plan("Mensual Kids", PlanKind.MONTHLY, anchor="first")
SEMESTRAL = plan("Semestral", PlanKind.PREPAID)
PACK = plan("Pack 12 clases", PlanKind.CREDITS, credits=12, credit_expiry_days=60)
SUELTA = plan("Clase suelta", PlanKind.DROPIN)
VIEJO = plan("Mensual 2025", PlanKind.MONTHLY, anchor="signup", active=False)
PLANS = PlanFinder([MENSUAL, KIDS, SEMESTRAL, PACK, SUELTA, VIEJO], {})

MAPPING = {F.NAME: 0, F.PHONE: 1, F.PLAN: 2, F.DUE_ON: 3, F.GUARDIAN_NAME: 4, F.GUARDIAN_PHONE: 5}


def read(*rows: list[str], plans: PlanFinder = PLANS) -> list[Member]:
    return read_members(list(enumerate(rows, start=2)), MAPPING, plans, TODAY)


def errors(*cells: str) -> list[RowError]:
    return read([*cells, *[""] * (6 - len(cells))])[0].errors


# --- the mapping ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("Nombre completo", F.NAME),
        ("ALUMNO", F.NAME),
        ("Apellidos", F.LAST_NAME),
        ("Teléfono", F.PHONE),
        ("WhatsApp", F.PHONE),
        ("E-mail", F.EMAIL),
        ("RUT", F.RUT),
        ("Fecha de nacimiento", F.DOB),
        ("Próximo pago", F.DUE_ON),
        ("Vencimiento", F.DUE_ON),
        ("Fecha de ingreso", F.STARTED_ON),
        ("Plan", F.PLAN),
        ("Nombre apoderado", F.GUARDIAN_NAME),
        ("Teléfono del apoderado", F.GUARDIAN_PHONE),
        ("Cel. Mamá/Papá", F.GUARDIAN_PHONE),
        ("Nombres", F.NAME),
        ("Observaciones", None),
        ("Runner", None),
    ],
)
def test_a_header_suggests_its_field(header: str, field: Field | None) -> None:
    assert suggest_mapping([header]) == ({} if field is None else {field: 0})


def test_the_first_column_of_a_field_wins() -> None:
    assert suggest_mapping(["Nombre", "Celular", "Celular 2"]) == {F.NAME: 0, F.PHONE: 1}


def test_the_pilot_sheet_maps_every_column_it_has() -> None:
    sheet = read_sheet(PILOT.read_bytes())
    mapped = {
        sheet.headers[column]: field for field, column in suggest_mapping(sheet.headers).items()
    }
    assert mapped == {
        "Nombre": F.NAME,
        "Apellido": F.LAST_NAME,
        "RUT": F.RUT,
        "Fecha Nac.": F.DOB,
        "Celular": F.PHONE,
        "Correo": F.EMAIL,
        "Plan": F.PLAN,
        "Fecha de pago": F.DUE_ON,
        "Apoderado": F.GUARDIAN_NAME,
        "Fono apoderado": F.GUARDIAN_PHONE,
    }


# --- cells ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-12-05", date(2026, 12, 5)),
        ("2026-12-05 00:00:00", date(2026, 12, 5)),
        ("05/12/2026", date(2026, 12, 5)),
        ("5-12-2026", date(2026, 12, 5)),
        ("05.12.26", date(2026, 12, 5)),
        ("14/03/88", date(1988, 3, 14)),
        ("01/01/27", date(2027, 1, 1)),
    ],
)
def test_a_date_reads_iso_or_day_first(raw: str, expected: date) -> None:
    assert parse_date(raw, TODAY) == expected


@pytest.mark.parametrize("raw", ["12/31/2026", "diciembre", "2026-02-30", "5/12"])
def test_a_date_refuses(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_date(raw, TODAY)


def test_fold_ignores_accents_case_and_spacing() -> None:
    assert fold("  Martín   NÚÑEZ ") == "martin nunez"


# --- rows -------------------------------------------------------------------------


def test_an_adult_row_reads_normalised() -> None:
    [member] = read(["  Camila  Ortiz ", "9 8765 4321", "mensual", "05/12/2026", "", ""])
    assert (member.name, member.phone, member.plan, member.due_on) == (
        "Camila Ortiz",
        "+56987654321",
        MENSUAL,
        date(2026, 12, 5),
    )
    assert member.errors == []


def test_a_last_name_column_joins_the_name() -> None:
    mapping = {F.NAME: 0, F.LAST_NAME: 1, F.PHONE: 2}
    [member] = read_members([(2, ["Camila", "Ortiz Rojas", "912345678"])], mapping, PLANS, TODAY)
    assert member.name == "Camila Ortiz Rojas"


def test_a_dependent_row_needs_only_a_name_and_the_guardians_phone() -> None:
    [member] = read(["Mateo", "", "", "", "Camila", "+56 9 8765 4321"])
    assert (member.phone, member.guardian_phone, member.guardian_name) == (
        None,
        "+56987654321",
        "Camila",
    )
    assert member.errors == []


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        (["", "912345678"], [RowError(F.NAME, "required")]),
        (["Camila"], [RowError(F.PHONE, "required")]),
        (["Mateo", "", "", "", "Camila"], [RowError(F.GUARDIAN_PHONE, "required")]),
        (["Isidora", "2 2345 6789"], [RowError(F.PHONE, "invalid_phone")]),
        (["Mateo", "", "", "", "", "123"], [RowError(F.GUARDIAN_PHONE, "invalid_phone")]),
        (
            ["Ana", "912345678", "", "", "", "912345678"],
            [RowError(F.GUARDIAN_PHONE, "own_guardian")],
        ),
        (["Ana", "912345678", "Beca"], [RowError(F.PLAN, "unknown_plan")]),
        (["Ana", "912345678", "Mensual 2025", "05/12/2026"], [RowError(F.PLAN, "inactive_plan")]),
        (["Ana", "912345678", "Clase suelta"], [RowError(F.PLAN, "dropin_plan")]),
        (["Ana", "912345678", "Mensual"], [RowError(F.DUE_ON, "required")]),
        (["Ana", "912345678", "Mensual", "pronto"], [RowError(F.DUE_ON, "invalid_date")]),
        (["Ana", "912345678", "Mensual", "05/12/2040"], [RowError(F.DUE_ON, "invalid_date")]),
        (["Ana", "912345678", "Pack 12 clases"], []),
    ],
    ids=[
        "no-name",
        "no-phone-no-guardian",
        "guardian-without-phone",
        "landline",
        "bad-guardian-phone",
        "own-guardian",
        "unknown-plan",
        "inactive-plan",
        "dropin",
        "recurring-without-due",
        "bad-due",
        "due-out-of-range",
        "pack-without-due",
    ],
)
def test_a_row_reports_what_is_wrong_with_it(cells: list[str], expected: list[RowError]) -> None:
    assert errors(*cells) == expected


def test_a_row_reports_every_error_it_has() -> None:
    mapping = {F.NAME: 0, F.PHONE: 1, F.EMAIL: 2, F.RUT: 3, F.DOB: 4}
    [member] = read_members(
        [(2, ["Ana", "123", "ana@", "11.111.111-2", "01/01/2030"])], mapping, PLANS, TODAY
    )
    assert member.errors == [
        RowError(F.PHONE, "invalid_phone"),
        RowError(F.EMAIL, "invalid_email"),
        RowError(F.RUT, "invalid_rut"),
        RowError(F.DOB, "invalid_date"),
    ]


def test_a_due_date_before_the_start_is_refused() -> None:
    mapping = {F.NAME: 0, F.PHONE: 1, F.PLAN: 2, F.DUE_ON: 3, F.STARTED_ON: 4}
    rows = [(2, ["Ana", "912345678", "Mensual", "01/11/2026", "05/11/2026"])]
    [member] = read_members(rows, mapping, PLANS, TODAY)
    assert member.errors == [RowError(F.DUE_ON, "due_before_start")]


def test_a_later_row_with_the_same_phone_or_dependent_is_repeated() -> None:
    members = read(
        ["Camila", "987654321", "", "", "", ""],
        ["Mateo", "", "", "", "Camila", "987654321"],
        ["Camila Ortiz", "+56 9 8765 4321", "", "", "", ""],
        ["MATEO", "", "", "", "", "987654321"],
        ["Sofía", "", "", "", "", "987654321"],
    )
    assert [m.errors for m in members] == [
        [],
        [],
        [RowError(F.PHONE, "repeated")],
        [RowError(F.NAME, "repeated")],
        [],
    ]


def test_the_admins_choice_of_plan_comes_before_the_name() -> None:
    plans = PlanFinder([MENSUAL, KIDS], {"Beca 50%": MENSUAL.id, "mensual": KIDS.id})
    assert plans.find("beca 50%") == MENSUAL
    assert plans.find("Mensual") == KIDS
    assert plans.find("Mensual Kids") == KIDS
    assert PlanFinder([MENSUAL], {"Beca": uuid.uuid4()}).find("Beca") is None


def test_an_active_plan_comes_before_an_inactive_one_of_the_same_name() -> None:
    old = plan("Mensual", PlanKind.MONTHLY, anchor="signup", active=False)
    assert PlanFinder([old, MENSUAL], {}).find("MENSUAL") == MENSUAL


# --- a plan value cleared on purpose ----------------------------------------------


@pytest.mark.parametrize("value", ["Mensual", "Beca 50%"], ids=["name-matched", "unmatched"])
def test_a_cleared_plan_value_imports_the_person_with_no_plan(value: str) -> None:
    plans = PlanFinder([MENSUAL], {value: None})
    # No due date, and a bad start: neither matters with no membership to read them.
    mapping = {F.NAME: 0, F.PHONE: 1, F.PLAN: 2, F.STARTED_ON: 3}
    [member] = read_members([(2, ["Ana", "912345678", value, "pronto"])], mapping, plans, TODAY)
    assert (member.plan, member.due_on, member.started_on, member.errors) == (None, None, None, [])


def test_clearing_one_value_leaves_the_others_matched_by_name() -> None:
    plans = PlanFinder([MENSUAL, KIDS], {"beca": None})
    assert plans.cleared("Beca") and not plans.cleared("Mensual")
    assert plans.find("Mensual") == MENSUAL
