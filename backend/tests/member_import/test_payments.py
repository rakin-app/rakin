"""Pagos rows read with no database (#298): the mapping suggested, amounts, months and
methods read, the row's own checks made."""

from datetime import date

import pytest

from app.member_import.payments import (
    Payment,
    PaymentField,
    PaymentRowError,
    parse_amount,
    parse_month,
    read_payment,
    suggest_payment_mapping,
)
from app.member_import.template import PAYMENT_COLUMNS
from app.schemas.ledger import Method

P = PaymentField
TODAY = date(2026, 11, 9)
MAPPING = {f: i for i, (_, f, _) in enumerate(PAYMENT_COLUMNS)}


def row(
    paid_on: str = "03-04-2024",
    amount: str = "25000",
    month: str = "04-2024",
    method: str = "",
    *,
    rut: str = "",
    email: str = "",
    name: str = "Martina Soto",
    plan: str = "",
    note: str = "",
) -> Payment:
    cells = [rut, email, name, paid_on, amount, month, method, plan, note]
    return read_payment(2, cells, MAPPING, TODAY)


def errors(payment: Payment) -> list[tuple[str, str]]:
    return [(e.field.value, e.code) for e in payment.errors]


def test_the_templates_headers_map_by_themselves() -> None:
    assert suggest_payment_mapping([h for h, _, _ in PAYMENT_COLUMNS]) == MAPPING


def test_a_gyms_own_headers_are_suggested() -> None:
    headers = ["Alumno", "Fecha", "Valor", "Mes", "Forma de pago", "Observaciones", "Mensualidad"]
    assert suggest_payment_mapping(headers) == {
        P.NAME: 0,
        P.PAID_ON: 1,
        P.AMOUNT: 2,
        P.COVERS_MONTH: 3,
        P.METHOD: 4,
        P.NOTE: 5,
        P.PLAN_NAME: 6,
    }


@pytest.mark.parametrize(
    ("raw", "pesos"),
    [
        ("25000", 25_000),
        ("25.000", 25_000),
        ("$25.000", 25_000),
        ("$ 25.000", 25_000),
        ("25.000,00", 25_000),
        ("25,000", 25_000),
        ("1.250.000", 1_250_000),
        ("25000 CLP", 25_000),
        ("0", None),
        ("-25000", None),
        ("25.5", None),
        ("25.00.0", None),
        ("veinte mil", None),
        ("100000001", None),
    ],
)
def test_an_amount_is_whole_pesos_above_zero(raw: str, pesos: int | None) -> None:
    assert parse_amount(raw) == pesos


@pytest.mark.parametrize(
    "raw", ["04-2024", "4/2024", "2024-04", "2024-04-01", "15-04-2024", "2024-04-15 00:00:00"]
)
def test_the_month_paid_for_is_a_month_or_a_dates(raw: str) -> None:
    assert parse_month(raw, TODAY) == date(2024, 4, 1)


def test_a_full_row_is_the_payment_the_ficha_would_write() -> None:
    payment = row(method="Transferencia", plan="Mensual 3x semana", note="  por  caja ")
    assert payment.errors == []
    assert payment.entry is not None
    assert payment.entry.model_dump() == {
        "paid_on": date(2024, 4, 3),
        "amount_clp": 25_000,
        "method": Method.TRANSFER,
        "covers_month": date(2024, 4, 1),
        "plan_name": "Mensual 3x semana",
        "note": "por caja",
    }


@pytest.mark.parametrize(
    ("raw", "method"),
    [("Efectivo", Method.CASH), ("TRANSF.", Method.TRANSFER), ("Depósito", Method.TRANSFER)],
)
def test_the_method_is_read_in_spanish(raw: str, method: Method) -> None:
    entry = row(method=raw).entry
    assert entry is not None and entry.method is method


def test_only_the_day_and_the_amount_are_required() -> None:
    entry = row(month="").entry
    assert entry is not None and (entry.covers_month, entry.method) == (None, None)
    assert errors(row(paid_on="", amount="")) == [
        ("paid_on", "required"),
        ("amount_clp", "required"),
    ]


def test_an_amount_of_zero_is_refused() -> None:
    payment = row(amount="0")
    assert errors(payment) == [("amount_clp", "invalid_amount")]
    assert payment.entry is None


@pytest.mark.parametrize(
    ("cells", "refused"),
    [
        ({"paid_on": "31-02-2024"}, ("paid_on", "invalid_date")),
        # After the gym's today, and further back than 60 years.
        ({"paid_on": "10-11-2026"}, ("paid_on", "invalid_date")),
        ({"month": "01-1960"}, ("covers_month", "invalid_date")),
        ({"month": "13-2024"}, ("covers_month", "invalid_date")),
        ({"method": "Tarjeta"}, ("method", "invalid_method")),
        ({"plan": "x" * 201}, ("plan_name", "too_long")),
        ({"note": "x" * 501}, ("note", "too_long")),
        ({"rut": "12.345.678-9"}, ("rut", "invalid_rut")),
        ({"email": "nadie@"}, ("email", "invalid_email")),
        ({"name": ""}, ("name", "required")),
    ],
)
def test_a_bad_cell_is_refused_on_its_field(
    cells: dict[str, str], refused: tuple[str, str]
) -> None:
    payment = row(**cells)
    assert errors(payment) == [refused]
    assert payment.entry is None


def test_a_rut_or_an_email_alone_names_someone() -> None:
    payment = row(name="", rut="12.345.678-5")
    assert (payment.errors, payment.rut, payment.key) == ([], "12345678-5", ("rut", "12345678-5"))
    assert row(name="", email="Ana@Example.cl").key == ("email", "ana@example.cl")
    assert row(name="").errors == [PaymentRowError(P.NAME, "required")]
