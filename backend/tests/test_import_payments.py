"""The Pagos tab (#298): payments from before Rakin, from the gym's workbook.

A Pagos row is read after the Alumnos tab, in the same run and the same dry run, so it
finds a student that tab adds. It never creates anyone: nobody by its RUT, email or name
is `unknown_person`. A month on or after the person's first plan is `covers_plan`, as on
the ficha. A payment they already have (day, amount and month) is `existing`, so a second
run adds none, and one an earlier row gives is `repeated`. Each is `source` `import` with
the run's `import_id`, and no billing reader sees it (docs/design/historical-data.md,
section 3).
"""

import io
import time
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.domain.dates import add_months
from app.main import create_app
from app.member_import.template import PAYMENT_COLUMNS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_history_payments import readers
from tests.test_import_grades import upload, workbook
from tests.test_import_history import audit, find
from tests.test_member_roll import enrolled, plan
from tests.test_people import new_rut

pg = pytest.mark.postgres

HEADERS = [header for header, _, _ in PAYMENT_COLUMNS]
PAYMENTS = {f.value: i for i, (_, f, _) in enumerate(PAYMENT_COLUMNS)}


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
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def send(
    client: TestClient, gym: uuid.UUID, sheet: dict[str, Any], *, dry_run: bool
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rows": sheet["rows"],
        "mapping": sheet["mapping"],
        "dry_run": dry_run,
        "file": sheet["file"],
    }
    if sheet["pagos"] is not None:
        body["pagos"] = {"rows": sheet["pagos"]["rows"], "mapping": sheet["pagos"]["mapping"]}
    response = client.post("/api/import/members", json=body, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    report: dict[str, Any] = response.json()
    return report


def payments_tab(*rows: list[str]) -> dict[str, Any]:
    """A sheet as the upload answers it, Pagos tab only, in the template's columns."""
    return {
        "rows": [],
        "mapping": {},
        "file": None,
        "pagos": {
            "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
            "mapping": PAYMENTS,
        },
    }


def paid(
    who: str, paid_on: str, amount: str = "25000", month: str = "", *, by: str = "rut"
) -> list[str]:
    """A Pagos row, in the template's columns: who by RUT, else by name."""
    rut, name = (who, "") if by == "rut" else ("", who)
    return [rut, "", name, paid_on, amount, month, "", "", ""]


def outcomes(report: dict[str, Any]) -> list[Any]:
    return [(r["row"], r["payment"], r["errors"]) for r in report["pagos"]["rows"]]


def stored(db: Database, gym: uuid.UUID) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT person_id, paid_on, amount_clp, method, covers_month, plan_name, source,"
            " import_id FROM history_payment ORDER BY paid_on, amount_clp",
        ),
    )
    return [dict(r) for r in rows]


def history(client: TestClient, gym: uuid.UUID, person: str) -> dict[str, Any]:
    response = client.get(f"/api/people/{person}/history/payments", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


@pg
def test_payments_naming_students_the_alumnos_tab_adds_import_with_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    data = workbook(
        Alumnos=[["Nombre", "Apellido", "RUT"], ["Martina", "Soto", "12.345.678-5"]],
        Pagos=[
            HEADERS,
            ["12.345.678-5", "", "", "03-04-2024", "$25.000", "04-2024", "Transferencia", "", ""],
            ["", "", "Martina Soto", "05-05-2024", "25.000", "2024-05-01", "Efectivo", "", ""],
            ["12345678-5", "", "", "2024-06-04", "27000", "", "", "Mensual 3x semana", "tarde"],
        ],
    )
    sheet = upload(client, gym, data, name="academia.xlsx")
    assert sheet["pagos"]["mapping"] == PAYMENTS

    dry = send(client, gym, sheet, dry_run=True)
    assert dry["summary"]["people_created"] == 1
    assert dry["pagos"]["summary"] == {
        "rows": 3,
        "imported": 3,
        "refused": 0,
        "payments_created": 3,
        "amount_clp": 77_000,
    }
    assert dry["import_id"] is None
    # The dry run wrote nothing, its import's record included.
    assert stored(db, gym) == []
    assert audit(db, gym, "history_imported") == []

    done = send(client, gym, sheet, dry_run=False)
    assert [r[1] for r in outcomes(done)] == ["created"] * 3
    martina = find(client, gym, "Martina Soto")["id"]
    rows = stored(db, gym)
    assert {(r["person_id"], r["source"], r["import_id"]) for r in rows} == {
        (uuid.UUID(martina), "import", uuid.UUID(done["import_id"]))
    }
    assert [(r["paid_on"], r["amount_clp"], r["method"], r["covers_month"]) for r in rows] == [
        (date(2024, 4, 3), 25_000, "transfer", date(2024, 4, 1)),
        (date(2024, 5, 5), 25_000, "cash", date(2024, 5, 1)),
        (date(2024, 6, 4), 27_000, None, None),
    ]
    [year] = history(client, gym, martina)["years"]
    assert (year["year"], year["count"], year["total_clp"]) == (2024, 3, 77_000)
    assert {p["import_name"] for p in year["payments"]} == {"academia.xlsx"}
    [record] = audit(db, gym, "history_imported")
    assert record["id"] == uuid.UUID(done["import_id"])
    assert record["detail"]["tabs"] == ["alumnos", "pagos"]
    assert record["detail"]["counts"]["pagos"] == done["pagos"]["summary"]


@pg
def test_an_unknown_student_a_zero_and_a_month_inside_the_plan_are_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = today - timedelta(days=40)
    ana = enrolled(
        client,
        gym,
        name="Ana Rojas",
        membership={"plan_id": plan(client, gym), "started_on": started_on.isoformat()},
    )
    rut = ana["rut"]
    plan_month = started_on.replace(day=1)
    before = add_months(plan_month, -1)
    sheet = payments_tab(
        paid(rut, before.strftime("%d-%m-%Y"), month=before.strftime("%m-%Y")),
        paid("Nadie Aquí", "05-03-2024", by="name"),
        paid(new_rut(), "05-03-2024"),
        paid(rut, "05-03-2024", amount="0"),
        # The month the plan began is the plan's, as on the ficha.
        paid(rut, before.strftime("%d-%m-%Y"), month=plan_month.strftime("%m-%Y")),
        # With no month, the day says.
        paid(rut, started_on.strftime("%d-%m-%Y")),
    )
    people = len(client.get("/api/people", headers=as_gym(gym)).json()["items"])
    report = send(client, gym, sheet, dry_run=False)
    assert outcomes(report) == [
        (2, "created", []),
        (3, None, [{"field": "name", "code": "unknown_person"}]),
        (4, None, [{"field": "rut", "code": "unknown_person"}]),
        (5, None, [{"field": "amount_clp", "code": "invalid_amount"}]),
        (6, None, [{"field": "covers_month", "code": "covers_plan"}]),
        (7, None, [{"field": "paid_on", "code": "covers_plan"}]),
    ]
    assert len(client.get("/api/people", headers=as_gym(gym)).json()["items"]) == people
    assert [(r["covers_month"], r["amount_clp"]) for r in stored(db, gym)] == [(before, 25_000)]


@pg
def test_running_the_same_workbook_twice_adds_no_payment_the_second_time(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    data = workbook(
        Alumnos=[["Nombre", "RUT"], ["Diego Rojas", "11.111.111-1"]],
        Pagos=[HEADERS, paid("11.111.111-1", "05-01-2024", month="01-2024")],
    )
    sheet = upload(client, gym, data, name="academia.xlsx")
    first = send(client, gym, sheet, dry_run=False)
    assert first["pagos"]["summary"]["payments_created"] == 1

    second = send(client, gym, sheet, dry_run=False)
    assert outcomes(second) == [(2, "existing", [])]
    assert second["pagos"]["summary"]["payments_created"] == 0
    assert len(stored(db, gym)) == 1
    # Nothing written, so nothing recorded.
    assert second["import_id"] is None
    assert len(audit(db, gym, "history_imported")) == 1


@pg
def test_an_equal_row_earlier_in_the_sheet_makes_the_second_repeated(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    diego = enrolled(client, gym, name="Diego Rojas")
    sheet = payments_tab(
        paid(diego["rut"], "05-01-2024", month="01-2024"),
        paid("Diego Rojas", "2024-01-05", amount="25.000", month="2024-01", by="name"),
        # Another month, another amount, another day: each its own payment.
        paid(diego["rut"], "05-01-2024", month="02-2024"),
        paid(diego["rut"], "05-01-2024", amount="20000", month="01-2024"),
        paid(diego["rut"], "06-01-2024", month="01-2024"),
    )
    report = send(client, gym, sheet, dry_run=True)
    assert outcomes(report) == [
        (2, "created", []),
        (3, None, [{"field": "paid_on", "code": "repeated"}]),
        (4, "created", []),
        (5, "created", []),
        (6, "created", []),
    ]


@pg
def test_billing_the_book_and_the_export_are_unchanged_by_imported_payments(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = today - timedelta(days=40)
    ana = enrolled(
        client,
        gym,
        membership={"plan_id": plan(client, gym), "started_on": started_on.isoformat()},
    )
    first = add_months(started_on.replace(day=1), -24)
    before = readers(client, db, gym)
    sheet = payments_tab(
        *(
            paid(
                ana["rut"],
                add_months(first, n).strftime("%d-%m-%Y"),
                amount="45000",
                month=add_months(first, n).strftime("%m-%Y"),
            )
            for n in range(24)
        )
    )
    report = send(client, gym, sheet, dry_run=False)
    assert report["pagos"]["summary"]["payments_created"] == 24
    assert readers(client, db, gym) == before


@pg
def test_a_pagos_tab_needs_its_day_amount_and_who(client: TestClient, gym: uuid.UUID) -> None:
    for mapping in (
        {"name": 0, "paid_on": 1},
        {"name": 0, "amount_clp": 2},
        {"paid_on": 1, "amount_clp": 2},
    ):
        body = {
            "pagos": {"rows": [{"number": 2, "cells": ["a", "b", "c"]}], "mapping": mapping},
            "dry_run": True,
        }
        response = client.post("/api/import/members", json=body, headers=as_gym(gym))
        assert response.status_code == 422, mapping


@pg
def test_a_csv_is_the_pagos_tab_when_the_upload_says(client: TestClient, gym: uuid.UUID) -> None:
    sheet = upload(client, gym, b"Alumno;Fecha;Monto\nMartina;05-01-2024;25.000\n", tab="pagos")
    assert (sheet["rows"], sheet["grados"]) == ([], None)
    assert sheet["pagos"]["mapping"] == {"name": 0, "paid_on": 1, "amount_clp": 2}


@pg
def test_the_template_has_a_pagos_tab_that_maps_and_imports_by_itself(
    client: TestClient, gym: uuid.UUID
) -> None:
    response = client.get("/api/import/template.xlsx", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content))
    pagos = book["Pagos"]
    assert [c.value for c in pagos[1]] == HEADERS
    assert pagos["A2"].font.color.rgb.endswith("808080")
    [rule] = pagos.data_validations.dataValidation
    assert (rule.formula1, str(rule.sqref)) == ('"Efectivo,Transferencia,Otro"', "G2:G20001")
    instructions = [r[0] for r in book["Instrucciones"].iter_rows(values_only=True)]
    assert "¿Tu planilla tiene un alumno por fila y un mes por columna? Pásala a filas así:" in (
        instructions
    )

    # The filled template reads back and maps with no change: its example payment is the
    # Alumnos tab's example student's.
    sheet = upload(client, gym, response.content)
    assert sheet["pagos"]["mapping"] == PAYMENTS
    report = send(client, gym, sheet, dry_run=True)
    assert outcomes(report) == [(2, "created", [])]


@pg
def test_a_dry_run_of_twenty_thousand_payments_answers_in_reasonable_time(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Five years of a 300-student gym, monthly (docs/design/historical-data.md).
    students = [enrolled(client, gym, name=f"Alumno {n}")["rut"] for n in range(300)]
    start = date(2020, 1, 1)
    rows = [
        paid(
            rut,
            add_months(start, m).strftime("%d-%m-%Y"),
            month=add_months(start, m).strftime("%m-%Y"),
        )
        for rut in students
        for m in range(67)
    ][:20_000]
    sheet = payments_tab(*rows)
    began = time.monotonic()
    report = send(client, gym, sheet, dry_run=True)
    took = time.monotonic() - began
    assert report["pagos"]["summary"]["payments_created"] == 20_000
    assert took < 60, took
    print(f"dry run of 20,000 payments: {took:.1f}s")
