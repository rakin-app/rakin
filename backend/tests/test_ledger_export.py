"""The month's ledger for the accountant, as CSV and XLSX (#40).

Each test takes a gym of its own and dates its entries into March 2020, a month no
other entry reaches, so the export's rows and totals are exactly what the test wrote:
a charge billed in February for March, a payment claimed in February and validated in
March, one validated in April, a void, a refund, an adjustment, a cobro extra's
payment, a proof waiting and one rejected.
"""

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import ledger_export
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import DEFAULT_TIMEZONE, Database, migrate, run, seed_gym, throwaway_database
from tests.test_guardians import add_person
from tests.test_plans import add_staff

pg = pytest.mark.postgres

MONTH = date(2020, 3, 1)
TZ = ZoneInfo(DEFAULT_TIMEZONE)


def at(day: date, hour: int = 12) -> datetime:
    """`hour` o'clock on `day`, in the gym's timezone."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=TZ)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("academia-sur"))


def insert(db: Database, gym: uuid.UUID, table: str, **columns: Any) -> uuid.UUID:
    """A row of `table` in `gym`, as the owner role, which RLS scopes to the gym."""
    names = ["gym_id", *columns]
    marks = ", ".join(f"${i}" for i in range(1, len(names) + 1))

    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            row_id: uuid.UUID = await conn.fetchval(
                f"INSERT INTO {table} ({', '.join(names)}) VALUES ({marks}) RETURNING id",
                gym,
                *columns.values(),
            )
            return row_id

    row_id: uuid.UUID = run(db.owner_url, query)
    return row_id


def membership(db: Database, gym: uuid.UUID, person: str) -> uuid.UUID:
    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            found: uuid.UUID = await conn.fetchval(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " SELECT gym_id, $1, id, 'active' FROM plan WHERE name = 'Mensual' RETURNING id",
                uuid.UUID(person),
            )
            return found

    found: uuid.UUID = run(db.owner_url, query)
    return found


def march(db: Database, gym: uuid.UUID, member: uuid.UUID, amount: int, hour: int) -> uuid.UUID:
    """March's period for `member`, and its charge, billed in late February at `hour`."""
    period = insert(
        db,
        gym,
        "billing_period",
        membership_id=member,
        period_start=MONTH,
        period_end=date(2020, 3, 31),
        amount_due_clp=amount,
        due_date=MONTH,
    )
    entry(db, gym, member, period, "charge", amount, at(date(2020, 2, 24), hour))
    return period


def entry(
    db: Database,
    gym: uuid.UUID,
    member: uuid.UUID | None,
    period: uuid.UUID | None,
    kind: str,
    amount: int,
    made: datetime,
    *,
    status: str = "validated",
    validated: datetime | None = None,
    **columns: Any,
) -> uuid.UUID:
    return insert(
        db,
        gym,
        "ledger_entry",
        membership_id=member,
        billing_period_id=period,
        kind=kind,
        amount_clp=amount,
        status=status,
        created_at=made,
        validated_at=(validated or made) if status == "validated" else None,
        **columns,
    )


def seed_month(client: TestClient, db: Database, gym: uuid.UUID) -> dict[str, str]:
    """March 2020 as the module says; the people's names by role."""
    ana = add_person(client, gym, "Ana Rojas", rut="11111111-1")
    beto = add_person(client, gym, "Beto Soto")
    carla = add_person(client, gym, "Carla Díaz")
    ana_m, beto_m, carla_m = (membership(db, gym, p) for p in (ana, beto, carla))

    ana_p = march(db, gym, ana_m, 45_000, 9)
    paid = entry(
        db,
        gym,
        ana_m,
        ana_p,
        "payment",
        30_000,
        at(date(2020, 3, 4)),
        validated=at(date(2020, 3, 5)),
        method="transfer",
        bank_tx_ref="TX-0001",
    )
    entry(db, gym, ana_m, ana_p, "adjustment", 5_000, at(date(2020, 3, 10)), note="=1+1 hermano")
    entry(
        db,
        gym,
        ana_m,
        ana_p,
        "refund",
        10_000,
        at(date(2020, 3, 20)),
        refund_of=paid,
        method="cash",
    )

    beto_p = march(db, gym, beto_m, 45_000, 10)
    entry(
        db,
        gym,
        beto_m,
        beto_p,
        "adjustment",
        45_000,
        at(date(2020, 3, 3)),
        purpose="void",
        note="cobrado por error",
    )

    carla_p = march(db, gym, carla_m, 40_000, 11)
    # Claimed in February, validated in March: March's, as "Cobrado" counts it.
    entry(
        db,
        gym,
        carla_m,
        carla_p,
        "payment",
        15_000,
        at(date(2020, 2, 28)),
        validated=at(date(2020, 3, 2)),
        method="transfer",
    )
    # Made in March, validated in April: April's.
    entry(
        db,
        gym,
        carla_m,
        carla_p,
        "payment",
        7_000,
        at(date(2020, 3, 31)),
        validated=at(date(2020, 4, 2)),
        method="cash",
    )
    entry(
        db,
        gym,
        carla_m,
        carla_p,
        "payment",
        20_000,
        at(date(2020, 3, 15)),
        status="pending",
        method="transfer",
    )
    entry(
        db,
        gym,
        carla_m,
        carla_p,
        "payment",
        9_000,
        at(date(2020, 3, 16)),
        status="rejected",
        method="transfer",
        note="ilegible",
    )

    rifa = insert(
        db,
        gym,
        "extra_charge",
        title="Rifa de otoño",
        category="rifa",
        due_date=date(2020, 3, 25),
        amount_mode="fixed",
        amount_clp=5_000,
        target_kind="people",
    )
    line = insert(
        db,
        gym,
        "extra_line",
        extra_charge_id=rifa,
        person_id=uuid.UUID(carla),
        due_date=date(2020, 3, 25),
        amount_due_clp=5_000,
    )
    entry(
        db,
        gym,
        None,
        None,
        "payment",
        5_000,
        at(date(2020, 3, 12)),
        method="cash",
        extra_line_id=line,
    )
    return {"ana": ana, "beto": beto, "carla": carla}


def download(client: TestClient, gym: uuid.UUID, fmt: str, person: uuid.UUID | None = None) -> Any:
    return client.get(
        "/api/ledger/export",
        params={"month": "2020-03-17", "format": fmt},
        headers=as_gym(gym, person),
    )


def csv_rows(client: TestClient, gym: uuid.UUID) -> list[list[str]]:
    response = download(client, gym, "csv")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="pagos-2020-03.csv"' in response.headers["content-disposition"]
    assert response.content.startswith("﻿".encode())
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))


def sections(rows: list[list[str]]) -> tuple[list[list[str]], list[list[str]], dict[str, int]]:
    """The CSV's entries (with their header), pending proofs and totals."""
    blank = [i for i, r in enumerate(rows) if not r]
    entries = rows[: blank[0]]
    pending: list[list[str]] = []
    if len(blank) == 3:
        assert rows[blank[0] + 1] == [ledger_export.PENDING_TITLE]
        pending = rows[blank[0] + 2 : blank[1]]
    # The totals, then how each entry is dated, each after a blank line.
    assert rows[blank[-2] + 1] == [ledger_export.TOTALS_TITLE]
    totals = {label: int(amount) for label, amount in rows[blank[-2] + 2 : blank[-1]]}
    assert rows[blank[-1] + 1 :] == [[ledger_export.FILED_BY]]
    return entries, pending, totals


@pg
def test_the_csv_lists_the_months_entries_and_its_totals_match_the_book(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    seed_month(client, db, sur)
    entries, pending, totals = sections(csv_rows(client, sur))

    assert entries[0][:11] == list(ledger_export.HEADERS)
    # By the day each counts on: charges by their period, payments by their validation.
    assert [(r[0], r[1], r[5], r[7], r[8]) for r in entries[1:]] == [
        ("01-03-2020", "Ana Rojas", "Cargo", "45000", "Validado"),
        ("01-03-2020", "Beto Soto", "Cargo", "45000", "Validado"),
        ("01-03-2020", "Carla Díaz", "Cargo", "40000", "Validado"),
        ("02-03-2020", "Carla Díaz", "Pago", "15000", "Validado"),
        ("03-03-2020", "Beto Soto", "Anulación", "45000", "Validado"),
        ("05-03-2020", "Ana Rojas", "Pago", "30000", "Validado"),
        ("10-03-2020", "Ana Rojas", "Ajuste", "5000", "Validado"),
        ("12-03-2020", "Carla Díaz", "Pago", "5000", "Validado"),
        ("16-03-2020", "Carla Díaz", "Pago", "9000", "Rechazado"),
        ("20-03-2020", "Ana Rojas", "Devolución", "10000", "Validado"),
    ]
    ana_paid = entries[6]
    assert ana_paid[2:5] == ["11111111-1", "Mensual", "01-03-2020 al 31-03-2020"]
    assert (ana_paid[6], ana_paid[9]) == ("Transferencia", "TX-0001")
    # A cobro extra's payment by its category and title, with no period.
    rifa = entries[8]
    assert (rifa[3], rifa[4], rifa[6]) == ("Rifa: Rifa de otoño", "", "Efectivo")
    # A note that looks like a formula stays text.
    assert entries[7][10] == "'=1+1 hermano"

    assert [(r[0], r[1], r[7], r[8]) for r in pending] == [
        ("15-03-2020", "Carla Díaz", "20000", "Por validar")
    ]

    book = client.get(
        "/api/ledger/book", params={"month": "2020-03-01"}, headers=as_gym(sur)
    ).json()["kpis"]
    assert totals["Total cargado"] == 130_000
    assert totals["Total pagado"] == 50_000
    assert totals["De lo pagado, cobros extra"] == 5_000 == book["collected_extra_clp"]
    assert totals["Total ajustado (a favor +, en contra -)"] == 5_000
    assert totals["Total anulado"] == 45_000
    assert totals["Total devuelto"] == 10_000 == book["refunded_clp"]
    assert totals["Cobrado neto (pagado menos devuelto)"] == 40_000 == book["collected_clp"]
    # Ana owes 45.000 less 30.000 and 5.000, plus the 10.000 given back; Beto nothing;
    # Carla 40.000 less 15.000 and April's 7.000.
    assert totals["Saldo pendiente de los cargos del mes"] == 20_000 + 0 + 18_000


@pg
def test_the_xlsx_has_a_sheet_each_with_dates_and_integers_typed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    seed_month(client, db, sur)
    response = download(client, sur, "xlsx")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == ledger_export.XLSX_MEDIA_TYPE
    assert 'filename="pagos-2020-03.xlsx"' in response.headers["content-disposition"]

    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Movimientos", "Por validar", "Totales"]
    sheet = book["Movimientos"]
    header = [c.value for c in sheet[1]]
    assert header[:11] == list(ledger_export.HEADERS)
    first = sheet[2]
    assert first[0].value == datetime(2020, 3, 1)
    assert first[0].number_format == ledger_export.XLSX_DATE
    assert first[7].value == 45_000 and first[7].data_type == "n"
    amounts = [r[7].value for r in sheet.iter_rows(min_row=2)]
    assert amounts == [45_000, 45_000, 40_000, 15_000, 45_000, 30_000, 5_000, 5_000, 9_000, 10_000]
    note = sheet.cell(row=8, column=11)
    assert (note.value, note.data_type) == ("=1+1 hermano", "s")

    pending = [[c.value for c in r] for r in book["Por validar"].iter_rows(min_row=2)]
    assert [(r[1], r[7], r[8]) for r in pending] == [("Carla Díaz", 20_000, "Por validar")]
    lines = [(r[0].value, r[1].value) for r in book["Totales"].iter_rows(min_row=2)]
    totals = dict(lines[: lines.index((None, None))])
    assert totals["Cobrado neto (pagado menos devuelto)"] == 40_000
    assert lines[-1] == (ledger_export.FILED_BY, None)


@pg
def test_no_email_phone_or_sensitive_field_is_exported(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    people = seed_month(client, db, sur)
    fields = {}
    for label, sensitive in (("Talla de polera", False), ("Diagnóstico", True)):
        response = client.post(
            "/api/custom-fields",
            json={"label": label, "type": "text", "sensitive": sensitive},
            headers=as_gym(sur),
        )
        assert response.status_code == 201, response.text
        fields[label] = response.json()["key"]
    response = client.patch(
        f"/api/people/{people['ana']}/fields",
        json={"values": {fields["Talla de polera"]: "M", fields["Diagnóstico"]: "asma"}},
        headers=as_gym(sur),
    )
    assert response.status_code == 200, response.text
    record = client.get(f"/api/people/{people['ana']}", headers=as_gym(sur)).json()

    for fmt in ("csv", "xlsx"):
        response = download(client, sur, fmt)
        assert response.status_code == 200
        if fmt == "csv":
            text = response.content.decode("utf-8-sig")
        else:
            book = load_workbook(io.BytesIO(response.content))
            text = "\n".join(
                str(c.value) for ws in book for r in ws.iter_rows() for c in r if c.value
            )
        assert "Talla de polera" in text and "M" in text
        assert "Diagnóstico" not in text and "asma" not in text
        assert record["email"] not in text and "@" not in text
        assert record["phone"] not in text and record["phone"].lstrip("+") not in text

    entries, _, _ = sections(csv_rows(client, sur))
    assert entries[0][11:] == ["Talla de polera"]
    assert {r[1]: r[11] for r in entries[1:]}["Ana Rojas"] == "M"


@pg
def test_a_validated_payment_with_no_validation_time_is_filed_by_the_day_it_was_made(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    people = seed_month(client, db, sur)
    ana = membership(db, sur, people["ana"])
    period = march(db, sur, ana, 30_000, 13)
    insert(
        db,
        sur,
        "ledger_entry",
        membership_id=ana,
        billing_period_id=period,
        kind="payment",
        amount_clp=12_000,
        status="validated",
        method="cash",
        created_at=at(date(2020, 3, 18)),
        validated_at=None,
    )
    entries, _, totals = sections(csv_rows(client, sur))
    assert ("18-03-2020", "Ana Rojas", "Pago", "12000", "Validado") in [
        (r[0], r[1], r[5], r[7], r[8]) for r in entries[1:]
    ]
    assert totals["Total pagado"] == 50_000 + 12_000


@pg
def test_rls_keeps_it_to_the_gym_and_a_coach_gets_403(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    other = seed_gym(db, unique_slug("academia-norte"))
    seed_month(client, db, other)
    entries, pending, totals = sections(csv_rows(client, sur))
    assert (entries[1:], pending) == ([], [])
    assert set(totals.values()) == {0}

    coach = add_staff(db, other, "coach")
    for fmt in ("csv", "xlsx"):
        assert download(client, other, fmt, coach).status_code == 403
    admin = add_staff(db, other, "admin")
    assert download(client, other, "xlsx", admin).status_code == 200


@pg
def test_the_month_defaults_to_the_gyms_current_one(client: TestClient, sur: uuid.UUID) -> None:
    response = client.get("/api/ledger/export", headers=as_gym(sur))
    assert response.status_code == 200
    today = client.get("/api/ledger/book", headers=as_gym(sur)).json()["month"]
    assert f'filename="pagos-{today[:7]}.csv"' in response.headers["content-disposition"]


def test_a_period_and_concept_read_as_the_accountant_reads_them() -> None:
    assert ledger_export.concept("Mensual", None, None) == "Mensual"
    assert ledger_export.concept(None, "gasto_compartido", "Bus") == "Gasto compartido: Bus"
    assert ledger_export.period_text((date(2026, 11, 1), date(2026, 11, 30))) == (
        "01-11-2026 al 30-11-2026"
    )
    assert ledger_export.kind_label("adjustment", voids=True) == "Anulación"
    assert [ledger_export.safe_text(s) for s in ("+56", "@x", "-1", "Ana")] == [
        "'+56",
        "'@x",
        "'-1",
        "Ana",
    ]
    assert ledger_export.csv_cell(-5_000) == "-5000"
    assert ledger_export.csv_cell(date(2026, 1, 2) + timedelta(days=1)) == "03-01-2026"
