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

MAPPING = {
    F.NAME: 0,
    F.PHONE: 1,
    F.PLAN: 2,
    F.DUE_ON: 3,
    F.GUARDIAN_NAME: 4,
    F.GUARDIAN_PHONE: 5,
    F.RUT: 6,
    F.GUARDIAN_RUT: 7,
    F.EMAIL: 8,
    F.GUARDIAN_EMAIL: 9,
}
COLUMNS = ("name", "phone", "plan", "due", "gname", "gphone", "rut", "grut", "email", "gemail")

CAMILA_RUT = "7.654.321-6"
MARTA_RUT = "11.111.111-1"


def cells(**values: str) -> list[str]:
    """A row, by column: `name`, `phone`, `plan`, `due`, `gname`, `gphone`, `rut`,
    `grut`, `email`, `gemail`."""
    return [values.get(column, "") for column in COLUMNS]


def read(*rows: list[str], plans: PlanFinder = PLANS) -> list[Member]:
    return read_members(list(enumerate(rows, start=2)), MAPPING, plans, TODAY)


def errors(**values: str) -> list[RowError]:
    return read(cells(**values))[0].errors


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
        ("RUT apoderado", F.GUARDIAN_RUT),
        ("Correo del apoderado", F.GUARDIAN_EMAIL),
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


# --- rows ------------------------------------------------------------------------


def test_an_adult_row_reads_normalised() -> None:
    [member] = read(
        cells(
            name="  Camila  Ortiz ",
            phone="9 8765 4321",
            plan="mensual",
            due="05/12/2026",
            rut=CAMILA_RUT,
        )
    )
    assert (member.name, member.rut, member.phone, member.plan, member.due_on) == (
        "Camila Ortiz",
        "7654321-6",
        "+56987654321",
        MENSUAL,
        date(2026, 12, 5),
    )
    assert member.key == ("rut", "7654321-6")
    assert member.errors == []


def test_a_last_name_column_joins_the_name() -> None:
    mapping = {F.NAME: 0, F.LAST_NAME: 1, F.EMAIL: 2}
    [member] = read_members(
        [(2, ["Camila", "Ortiz Rojas", "c@example.com"])], mapping, PLANS, TODAY
    )
    assert member.name == "Camila Ortiz Rojas"


def test_with_no_rut_the_email_is_who_they_are() -> None:
    [member] = read(cells(name="Camila", email=" Camila@Example.com "))
    assert member.key == ("email", "camila@example.com")
    assert member.errors == []


def test_a_row_with_no_phone_imports_flagged() -> None:
    [member] = read(cells(name="Camila", rut=CAMILA_RUT))
    assert (member.phone, member.errors, member.missing_phone) == (None, [], True)


def test_a_row_with_neither_a_rut_nor_an_email_imports_flagged() -> None:
    [member] = read(cells(name="Camila", phone="912345678"))
    assert (member.key, member.is_dependent, member.missing_identity) == (None, False, True)
    assert member.errors == []


def test_a_guardian_may_be_named_alone() -> None:
    [member] = read(cells(name="Mateo", gname="Camila Ortiz", gphone="912345678"))
    assert (member.is_dependent, member.guardian_ident, member.missing_phone) == (
        True,
        ("name", "camila ortiz"),
        False,
    )
    assert member.errors == []


def test_a_dependent_row_needs_only_a_name_and_the_guardian() -> None:
    [member] = read(cells(name="Mateo", gname="Camila", grut=CAMILA_RUT, gphone="+56 9 8765 4321"))
    assert (member.key, member.phone, member.guardian_phone, member.guardian_name) == (
        None,
        None,
        "+56987654321",
        "Camila",
    )
    assert member.guardian_key == ("rut", "7654321-6")
    assert (member.errors, member.missing_phone) == ([], False)


def test_a_dependent_is_flagged_by_their_guardians_phone_not_their_own() -> None:
    [member] = read(cells(name="Mateo", phone="912345678", gname="Camila", gemail="c@example.com"))
    assert (member.errors, member.missing_phone) == ([], True)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"rut": CAMILA_RUT}, [RowError(F.NAME, "required")]),
        ({"name": "Camila", "phone": "912345678"}, []),
        ({"name": "Mateo", "gphone": "912345678"}, [RowError(F.GUARDIAN_NAME, "required")]),
        (
            {"name": "Isidora", "rut": CAMILA_RUT, "phone": "2 2345 6789"},
            [RowError(F.PHONE, "invalid_phone")],
        ),
        ({"name": "Isidora", "rut": "7.654.321-0"}, [RowError(F.RUT, "invalid_rut")]),
        (
            {"name": "Mateo", "grut": CAMILA_RUT, "gphone": "123"},
            [RowError(F.GUARDIAN_PHONE, "invalid_phone")],
        ),
        (
            {"name": "Mateo", "gemail": "nope"},
            [RowError(F.GUARDIAN_EMAIL, "invalid_email")],
        ),
        (
            {"name": "Ana", "rut": CAMILA_RUT, "grut": CAMILA_RUT},
            [RowError(F.GUARDIAN_RUT, "own_guardian")],
        ),
        ({"name": "Ana", "rut": CAMILA_RUT, "plan": "Beca"}, [RowError(F.PLAN, "unknown_plan")]),
        (
            {"name": "Ana", "rut": CAMILA_RUT, "plan": "Mensual 2025", "due": "05/12/2026"},
            [RowError(F.PLAN, "inactive_plan")],
        ),
        (
            {"name": "Ana", "rut": CAMILA_RUT, "plan": "Clase suelta"},
            [RowError(F.PLAN, "dropin_plan")],
        ),
        ({"name": "Ana", "rut": CAMILA_RUT, "plan": "Mensual"}, [RowError(F.DUE_ON, "required")]),
        (
            {"name": "Ana", "rut": CAMILA_RUT, "plan": "Mensual", "due": "pronto"},
            [RowError(F.DUE_ON, "invalid_date")],
        ),
        (
            {"name": "Ana", "rut": CAMILA_RUT, "plan": "Mensual", "due": "05/12/2040"},
            [RowError(F.DUE_ON, "invalid_date")],
        ),
        ({"name": "Ana", "rut": CAMILA_RUT, "plan": "Pack 12 clases"}, []),
    ],
    ids=[
        "no-name",
        "phone-only",
        "guardian-phone-only",
        "landline",
        "bad-rut",
        "bad-guardian-phone",
        "bad-guardian-email",
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
def test_a_row_reports_what_is_wrong_with_it(row: dict[str, str], expected: list[RowError]) -> None:
    assert errors(**row) == expected


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
    mapping = {F.NAME: 0, F.RUT: 1, F.PLAN: 2, F.DUE_ON: 3, F.STARTED_ON: 4}
    rows = [(2, ["Ana", CAMILA_RUT, "Mensual", "01/11/2026", "05/11/2026"])]
    [member] = read_members(rows, mapping, PLANS, TODAY)
    assert member.errors == [RowError(F.DUE_ON, "due_before_start")]


def test_a_later_row_with_the_same_rut_email_or_dependent_is_repeated() -> None:
    members = read(
        cells(name="Camila", rut=CAMILA_RUT),
        cells(name="Mateo", gname="Camila", grut=CAMILA_RUT),
        cells(name="Camila Ortiz", rut="7654321-6", phone="987654321"),
        cells(name="MATEO", grut=CAMILA_RUT),
        cells(name="Sofía", grut=CAMILA_RUT),
        cells(name="Sin RUT", email="sin@example.com"),
        cells(name="Sin RUT", email="SIN@example.com"),
        # One phone for two people: a family's, say. It finds nobody.
        cells(name="Marta", rut=MARTA_RUT, phone="987654321"),
        # With nothing else, the name says who they are; and a guardian named alone.
        cells(name="Diego Soto", phone="911112222"),
        cells(name="diego  soto"),
        cells(name="Tomás", gname="Diego Soto"),
        cells(name="TOMAS", gname="diego soto"),
    )
    assert [m.errors for m in members] == [
        [],
        [],
        [RowError(F.RUT, "repeated")],
        [RowError(F.NAME, "repeated")],
        [],
        [],
        [RowError(F.EMAIL, "repeated")],
        [],
        [],
        [RowError(F.NAME, "repeated")],
        [],
        [RowError(F.NAME, "repeated")],
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
    mapping = {F.NAME: 0, F.RUT: 1, F.PLAN: 2, F.STARTED_ON: 3}
    [member] = read_members([(2, ["Ana", CAMILA_RUT, value, "pronto"])], mapping, plans, TODAY)
    assert (member.plan, member.due_on, member.started_on, member.errors) == (None, None, None, [])


def test_clearing_one_value_leaves_the_others_matched_by_name() -> None:
    plans = PlanFinder([MENSUAL, KIDS], {"beca": None})
    assert plans.cleared("Beca") and not plans.cleared("Mensual")
    assert plans.find("Mensual") == MENSUAL
