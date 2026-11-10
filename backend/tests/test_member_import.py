"""Member import against real Postgres: the pilot gym's sheet (anonymised), read, dry-run,
imported, and imported again without a duplicate.

`tests/fixtures/pilot_sheet.csv` has the pilot's columns and the ways its rows go
wrong; `tests/member_import` covers reading and checking rows on their own. The demo
sheet, `app/seed/demo_import.csv` and its XLSX twin, is dry-run against `make seed`'s gym.
"""

import io
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.api import member_import
from app.main import create_app
from app.seed.build import GYM_ID, seed_id
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_join import with_privacy
from tests.test_people import new_phone
from tests.test_plans import add_staff
from tests.test_seed import DESIGN_DAY, load_as_owner

pg = pytest.mark.postgres

PILOT = (Path(__file__).parent / "fixtures" / "pilot_sheet.csv").read_bytes()

PLANS = [
    {"kind": "monthly", "name": "Mensual", "price_clp": 45_000, "anchor": "signup"},
    {"kind": "monthly", "name": "Mensual Kids", "price_clp": 35_000, "anchor": "first"},
    {"kind": "prepaid", "name": "Semestral", "price_clp": 240_000, "period_months": 6},
    {
        "kind": "credits",
        "name": "Pack 12 clases",
        "price_clp": 45_000,
        "credits": 12,
        "credit_expiry_days": 60,
    },
    {"kind": "dropin", "name": "Clase suelta", "price_clp": 10_000},
]

# The pilot sheet's rows that are refused, by row number, and why.
REFUSED = {
    6: [{"field": "email", "code": "invalid_email"}],
    8: [{"field": "plan", "code": "unknown_plan"}],
    10: [{"field": "phone", "code": "invalid_phone"}],
    11: [{"field": "due_on", "code": "required"}],
    12: [{"field": "plan", "code": "dropin_plan"}],
    # Camila again, with no RUT: the name is all that says who she is.
    14: [{"field": "name", "code": "repeated"}],
    15: [{"field": "rut", "code": "invalid_rut"}],
}


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
def gym(db: Database, client: TestClient) -> uuid.UUID:
    """A fresh gym with the pilot's plans, so each test imports the sheet anew."""
    gym_id = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    for plan in PLANS:
        response = client.post("/api/plans", json=plan, headers=as_gym(gym_id))
        assert response.status_code == 201, response.text
    return gym_id


def upload(client: TestClient, gym: uuid.UUID, data: bytes, **headers: str) -> Any:
    return client.post(
        "/api/import/sheet",
        content=data,
        headers={"Content-Type": "text/csv", **as_gym(gym), **headers},
    )


def sheet_of(client: TestClient, gym: uuid.UUID, data: bytes = PILOT) -> dict[str, Any]:
    response = upload(client, gym, data)
    assert response.status_code == 200, response.text
    sheet: dict[str, Any] = response.json()
    return sheet


def send(
    client: TestClient,
    gym: uuid.UUID,
    sheet: dict[str, Any],
    *,
    dry_run: bool,
    plans: dict[str, str | None] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    body = {
        "rows": sheet["rows"],
        "mapping": sheet["mapping"],
        "plans": plans or {},
        "dry_run": dry_run,
    }
    return client.post("/api/import/members", json=body, headers=headers or as_gym(gym))


def imported(client: TestClient, gym: uuid.UUID, sheet: dict[str, Any], **kw: Any) -> Any:
    response = send(client, gym, sheet, **kw)
    assert response.status_code == 200, response.text
    return response.json()


def plan_id(client: TestClient, gym: uuid.UUID, name: str) -> str:
    plans = client.get("/api/plans", headers=as_gym(gym)).json()
    return str(next(p["id"] for p in plans if p["name"] == name))


def people(db: Database, gym: uuid.UUID) -> int:
    rows = run(db.owner_url, in_gym(gym, "SELECT count(*) FROM gym_person"))
    count: int = rows[0][0]
    return count


def people_count(client: TestClient, gym: uuid.UUID, name: str) -> int:
    items = client.get("/api/people", params={"q": name}, headers=as_gym(gym)).json()["items"]
    return sum(p["name"] == name for p in items)


def find(client: TestClient, gym: uuid.UUID, name: str) -> dict[str, Any]:
    items = client.get("/api/people", params={"q": name}, headers=as_gym(gym)).json()["items"]
    [person] = [p for p in items if p["name"] == name]
    return dict(person)


def membership_of(client: TestClient, gym: uuid.UUID, name: str) -> dict[str, Any]:
    person = find(client, gym, name)
    [membership] = client.get(
        "/api/memberships", params={"person_id": person["id"]}, headers=as_gym(gym)
    ).json()
    return dict(membership)


# --- reading the file -------------------------------------------------------------


@pg
def test_the_sheet_comes_back_as_rows_with_a_suggested_mapping(
    client: TestClient, gym: uuid.UUID
) -> None:
    sheet = sheet_of(client, gym)
    assert sheet["headers"][1:3] == ["Nombre", "Apellido"]
    assert len(sheet["rows"]) == 13
    assert sheet["rows"][0] == {
        "number": 2,
        "cells": [
            "1",
            "Camila",
            "Ortiz Rojas",
            "12.345.678-5",
            "14/03/1988",
            "9 8765 4321",
            "camila.ortiz@example.cl",
            "Mensual",
            "05/12/2026",
            "",
            "",
            "cinturón azul",
        ],
    }
    assert sheet["mapping"] == {
        "name": 1,
        "last_name": 2,
        "rut": 3,
        "dob": 4,
        "phone": 5,
        "email": 6,
        "plan": 7,
        "due_on": 8,
        "guardian_name": 9,
        "guardian_phone": 10,
    }


@pg
def test_an_xlsx_reads_the_same_as_its_csv(client: TestClient, gym: uuid.UUID) -> None:
    csv_sheet = sheet_of(client, gym)
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.append(csv_sheet["headers"])
    for row in csv_sheet["rows"]:
        worksheet.append(row["cells"])
    out = io.BytesIO()
    workbook.save(out)
    response = upload(
        client,
        gym,
        out.getvalue(),
        **{"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    )
    assert response.status_code == 200, response.text
    xlsx_sheet = response.json()
    # Numbered without the empty row, which the workbook never had.
    assert [r["cells"] for r in xlsx_sheet["rows"]] == [r["cells"] for r in csv_sheet["rows"]]
    assert xlsx_sheet["mapping"] == csv_sheet["mapping"]


@pg
def test_an_unreadable_or_empty_file_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    for data, code in [(b"PK\x03\x04broken", "unreadable"), (b"Nombre\n", "empty")]:
        response = upload(client, gym, data)
        assert (response.status_code, response.json()["detail"]) == (422, {"code": code})


@pg
def test_a_file_over_the_limit_is_refused(
    client: TestClient, gym: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(member_import, "MAX_UPLOAD_BYTES", 100)
    response = upload(client, gym, PILOT)
    assert (response.status_code, response.json()["detail"]) == (413, {"code": "too_large"})


# --- dry run, import, and again ---------------------------------------------------


@pg
def test_a_dry_run_reports_each_rows_errors_and_writes_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    before = people(db, gym)
    report = imported(client, gym, sheet_of(client, gym), dry_run=True)

    assert report["dry_run"] is True
    assert {r["row"]: r["errors"] for r in report["rows"] if r["errors"]} == REFUSED
    assert report["summary"] == {
        "rows": 13,
        "imported": 6,
        "refused": 7,
        # Camila, Mateo, Sofía, Diego, Tomás and his father Rodrigo, Agustín.
        "people_created": 7,
        "links_created": 3,
        "memberships_created": 5,
        # Every contact has a phone; Diego and Agustín have no RUT and no email.
        "missing_phone": 0,
        "missing_identity": 2,
    }
    assert [r["row"] for r in report["rows"]] == [2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15]
    assert people(db, gym) == before


@pg
def test_the_import_creates_people_guardian_links_and_memberships(
    client: TestClient, gym: uuid.UUID
) -> None:
    sheet = sheet_of(client, gym)
    dry = imported(client, gym, sheet, dry_run=True)
    report = imported(client, gym, sheet, dry_run=False)
    # The dry run said exactly what the import did.
    assert report["rows"] == dry["rows"]
    assert report["summary"] == dry["summary"]

    camila = find(client, gym, "Camila Ortiz Rojas")
    assert (camila["phone"], camila["rut"], camila["dependents"]) == (
        "+56987654321",
        "12345678-5",
        2,
    )
    for kid in ("Mateo Ortiz", "Sofía Ortiz"):
        row = find(client, gym, kid)
        assert (row["phone"], row["guardian"]["id"]) == (None, camila["id"])
    tomas = find(client, gym, "Tomás Fuentes")
    rodrigo = find(client, gym, "Rodrigo Fuentes")
    assert (tomas["guardian"]["id"], rodrigo["phone"], rodrigo["membership"]) == (
        rodrigo["id"],
        "+56912340004",
        None,
    )
    assert find(client, gym, "Agustín Castro")["membership"] is None

    # Monthly: paid through the day before it falls due, billing on that day.
    mensual = membership_of(client, gym, "Camila Ortiz Rojas")
    assert (mensual["plan_name"], mensual["status"]) == ("Mensual", "active")
    assert (mensual["current_period_end"], mensual["anchor_day"]) == ("2026-12-04", 5)
    kids = membership_of(client, gym, "Sofía Ortiz")
    assert (kids["plan_name"], kids["current_period_end"], kids["anchor_day"]) == (
        "Mensual Kids",
        "2026-11-30",
        1,
    )
    semestral = membership_of(client, gym, "Diego Soto Muñoz")
    assert (semestral["current_period_end"], semestral["anchor_day"]) == ("2027-03-14", None)


@pg
def test_running_it_again_creates_nothing_twice(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    sheet = sheet_of(client, gym)
    first = imported(client, gym, sheet, dry_run=False)
    count = people(db, gym)

    again = imported(client, gym, sheet, dry_run=False)
    assert people(db, gym) == count
    assert again["summary"] == {
        **first["summary"],
        "people_created": 0,
        "links_created": 0,
        "memberships_created": 0,
    }
    for row in again["rows"]:
        if not row["errors"]:
            outcomes = [row[k] for k in ("person", "guardian", "link", "membership")]
            assert set(outcomes) <= {"existing", None}, row
            # The same sheet again differs from nothing it wrote.
            assert row["ignored"] == [], row
    assert len(membership_of(client, gym, "Camila Ortiz Rojas")["id"]) == 36


@pg
def test_fixing_the_refused_rows_imports_only_them(client: TestClient, gym: uuid.UUID) -> None:
    sheet = sheet_of(client, gym)
    imported(client, gym, sheet, dry_run=False)
    # The admin says what "Beca 50%" is, and the run imports Benjamín and nobody new else.
    report = imported(
        client, gym, sheet, dry_run=False, plans={"Beca 50%": plan_id(client, gym, "Mensual")}
    )
    benjamin = next(r for r in report["rows"] if r["row"] == 8)
    assert (benjamin["errors"], benjamin["person"], benjamin["membership"]) == (
        [],
        "created",
        "created",
    )
    assert report["summary"]["people_created"] == 1
    assert membership_of(client, gym, "Benjamín Fuentes")["plan_name"] == "Mensual"


@pg
@pytest.mark.parametrize(
    ("value", "row_number", "name"),
    [("Mensual", 2, "Camila Ortiz Rojas"), ("Beca 50%", 8, "Benjamín Fuentes")],
    ids=["name-matched", "unmatched"],
)
def test_a_plan_value_cleared_on_purpose_imports_the_person_with_no_membership(
    client: TestClient, gym: uuid.UUID, value: str, row_number: int, name: str
) -> None:
    report = imported(client, gym, sheet_of(client, gym), dry_run=False, plans={value: None})
    row = next(r for r in report["rows"] if r["row"] == row_number)
    assert (row["errors"], row["person"], row["membership"]) == ([], "created", None)
    assert find(client, gym, name)["membership"] is None


@pg
def test_a_live_membership_keeps_its_plan_and_dates_and_says_so(
    client: TestClient, gym: uuid.UUID
) -> None:
    imported(client, gym, sheet_of(client, gym), dry_run=False)
    mapping = {"name": 0, "phone": 1, "plan": 2, "due_on": 3}

    def again(plan: str, due_on: str) -> Any:
        sheet = {
            "rows": [{"number": 2, "cells": ["Camila Ortiz Rojas", "987654321", plan, due_on]}],
            "mapping": mapping,
        }
        [row] = imported(client, gym, sheet, dry_run=True)["rows"]
        return (row["membership"], row["ignored"])

    assert again("Mensual", "05/12/2026") == ("existing", [])
    assert again("Semestral", "05/12/2026") == ("existing", ["plan"])
    assert again("Mensual", "20/12/2026") == ("existing", ["due_on"])
    assert membership_of(client, gym, "Camila Ortiz Rojas")["current_period_end"] == "2026-12-04"


@pg
@pytest.mark.parametrize(
    ("guardian_column", "named"),
    [("guardian_rut", "7.654.321-6"), ("guardian_name", "PAULA DIAZ")],
    ids=["by-rut", "by-name-alone"],
)
def test_a_guardians_own_row_goes_first_wherever_it_is(
    client: TestClient, gym: uuid.UUID, guardian_column: str, named: str
) -> None:
    # Lucas's row names his mother, above her own row.
    rows = [["Lucas Díaz", "", named], ["Paula Díaz", "7654321-6", ""]]
    sheet = {
        "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
        "mapping": {"name": 0, "rut": 1, guardian_column: 2},
    }
    report = imported(client, gym, sheet, dry_run=False)
    assert [(r["errors"], r["person"]) for r in report["rows"]] == [
        ([], "created"),
        ([], "created"),
    ]
    assert (report["rows"][0]["guardian"], report["rows"][0]["link"]) == ("existing", "created")
    assert find(client, gym, "Lucas Díaz")["guardian"]["name"] == "Paula Díaz"
    assert people_count(client, gym, "Paula Díaz") == 1


@pg
def test_someone_already_in_the_gym_is_found_by_rut_and_left_as_they_are(
    client: TestClient, gym: uuid.UUID
) -> None:
    body = {"rut": "12.345.678-5", "name": "Cami Ortiz", "email": "cami@example.cl"}
    assert client.post("/api/people", json=body, headers=as_gym(gym)).status_code == 201
    report = imported(client, gym, sheet_of(client, gym), dry_run=False)

    assert report["rows"][0]["person"] == "existing"
    # Kept as the gym has her, and the report names each sheet field that leaves unapplied.
    assert report["rows"][0]["ignored"] == ["name", "phone", "email", "dob"]
    cami = find(client, gym, "Cami Ortiz")
    assert cami["dependents"] == 2
    assert cami["membership"]["plan_name"] == "Mensual"


@pg
def test_another_gyms_member_joins_this_gym_with_what_the_sheet_says(
    client: TestClient, gym: uuid.UUID, db: Database
) -> None:
    other = seed_gym(db, f"other-{uuid.uuid4().hex[:8]}")
    rut, phone = random_rut(), new_phone()
    body = {"rut": rut, "phone": new_phone(), "name": "Nombre en otro gimnasio"}
    known = client.post("/api/people", json=body, headers=as_gym(other)).json()["id"]
    # Someone else's phone there finds nobody: Pedro is new.
    shared = {"rut": random_rut(), "phone": phone, "name": "Pedro en otro gimnasio"}
    assert client.post("/api/people", json=shared, headers=as_gym(other)).status_code == 201

    sheet = {
        "rows": [
            {"number": 2, "cells": ["Ana Rojas", rut, phone]},
            {"number": 3, "cells": ["Pedro Gil", "", phone]},
        ],
        "mapping": {"name": 0, "rut": 1, "phone": 2},
    }
    report = imported(client, gym, sheet, dry_run=False)
    assert [r["person"] for r in report["rows"]] == ["created", "created"]
    ana = find(client, gym, "Ana Rojas")
    assert (ana["id"], ana["phone"]) == (known, phone)
    assert find(client, gym, "Pedro Gil")["id"] not in (known,)


@pg
def test_a_link_the_database_refuses_fails_that_row_alone(
    client: TestClient, gym: uuid.UUID, db: Database
) -> None:
    mother, teen, other = random_rut(), random_rut(), random_rut()
    # Lucas, with a RUT, is Paula's dependent; then a kid names Lucas as guardian, and
    # Lucas is named again with another guardian.
    rows = [
        ["Paula Díaz", mother, "", ""],
        ["Lucas Díaz", teen, "Paula Díaz", mother],
        ["Emilia Díaz", "", "Lucas Díaz", teen],
        ["Pedro Gil", other, "", ""],
        ["Lucas Díaz", teen, "Pedro Gil", other],
    ]
    sheet = {
        "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
        "mapping": {"name": 0, "rut": 1, "guardian_name": 2, "guardian_rut": 3},
    }
    before = people(db, gym)
    report = imported(client, gym, sheet, dry_run=False)

    assert [r["errors"] for r in report["rows"]] == [
        [],
        [],
        [{"field": "guardian_name", "code": "one_level"}],
        [],
        [{"field": "rut", "code": "repeated"}],
    ]
    assert report["rows"][1]["link"] == "created"
    # Emilia's row wrote nothing: Paula, Lucas and Pedro are the only people added.
    assert people(db, gym) == before + 3

    lucas_again = {
        "rows": [{"number": 2, "cells": ["Lucas Díaz", teen, "Pedro Gil", other]}],
        "mapping": sheet["mapping"],
    }
    [row] = imported(client, gym, lucas_again, dry_run=False)["rows"]
    assert row["errors"] == [{"field": "guardian_name", "code": "has_guardian"}]


@pg
def test_a_new_guardian_needs_a_name(client: TestClient, gym: uuid.UUID) -> None:
    sheet = {
        "rows": [{"number": 2, "cells": ["Emilia", new_phone()]}],
        "mapping": {"name": 0, "guardian_phone": 1},
    }
    [row] = imported(client, gym, sheet, dry_run=False)["rows"]
    assert row["errors"] == [{"field": "guardian_name", "code": "required"}]


@pg
@pytest.mark.parametrize(
    "mapping",
    [{"phone": 0}, {"name": 0, "phone": 0}, {"name": 60}],
    ids=["no-name", "one-column-twice", "column-out-of-range"],
)
def test_a_mapping_is_refused(client: TestClient, gym: uuid.UUID, mapping: dict[str, int]) -> None:
    sheet = {"rows": [{"number": 2, "cells": ["Ana"]}], "mapping": mapping}
    assert send(client, gym, sheet, dry_run=True).status_code == 422


# --- who may ----------------------------------------------------------------------


@pg
def test_a_coach_may_not_import(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    coach = add_staff(db, gym, "coach")
    headers = as_gym(gym, coach)
    assert upload(client, gym, PILOT, **headers).status_code == 403
    sheet = {"rows": [{"number": 2, "cells": ["Ana"]}], "mapping": {"name": 0}}
    assert send(client, gym, sheet, dry_run=True, headers=headers).status_code == 403


# --- the demo sheet ---------------------------------------------------------------

DEMO = Path(__file__).parents[1] / "app" / "seed"

# The demo sheet's refused rows, by row number, one of each kind of refusal.
DEMO_REFUSED = {
    34: [{"field": "name", "code": "required"}],
    35: [{"field": "phone", "code": "invalid_phone"}],
    36: [{"field": "plan", "code": "unknown_plan"}],
    37: [{"field": "due_on", "code": "due_before_start"}],
    38: [{"field": "rut", "code": "repeated"}],
}


@pytest.fixture(scope="module")
def demo_gym(db: Database) -> dict[str, str]:
    """`make seed`'s Academia Sur, acted in as its owner."""
    load_as_owner(db, DESIGN_DAY)
    return as_gym(GYM_ID, seed_id("person", "martin"))  # Martín Fuentes


@pg
@pytest.mark.parametrize("name", ["demo_import.csv", "demo_import.xlsx"])
def test_the_demo_sheet_dry_runs_against_the_seeded_gym(
    client: TestClient, demo_gym: dict[str, str], name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sheet's dates are fixed, and the import refuses a start or due date more than
    # 5 years from today: as written they all hold until 4 November 2029. Today is held
    # at the day the sheet was written.
    monkeypatch.setattr(member_import, "gym_today", lambda tz: date(2026, 11, 9))
    response = upload(client, GYM_ID, (DEMO / name).read_bytes(), **demo_gym)
    assert response.status_code == 200, response.text
    sheet = response.json()
    assert "Observaciones" in sheet["headers"]
    assert len(sheet["mapping"]) == len(sheet["headers"]) - 2  # not N° nor Observaciones
    report = send(client, GYM_ID, sheet, dry_run=True, headers=demo_gym).json()

    assert report["summary"] == {
        "rows": 38,
        "imported": 33,
        "refused": 5,
        # 32 rows' people and 2 guardians named only on their children's rows.
        "people_created": 34,
        "links_created": 8,
        "memberships_created": 28,
        "missing_phone": 0,
        # Gonzalo Painemal and Isidora Contreras: found again by name.
        "missing_identity": 2,
    }
    assert {r["row"]: r["errors"] for r in report["rows"] if r["errors"]} == DEMO_REFUSED
    rows = report["rows"]
    # Felipe Díaz is in the seed: found by his RUT, and "Ya existen" lists the email.
    kept = {r["row"]: (r["name"], r["person"], r["ignored"]) for r in rows if r["ignored"]}
    assert kept == {39: ("Felipe Díaz", "existing", ["email"])}
    by_name = {r["name"]: r for r in rows}
    # A guardian already in the seed, and a teenager with their own phone and a guardian.
    assert (by_name["Julián Ortiz"]["guardian"], by_name["Julián Ortiz"]["link"]) == (
        "existing",
        "created",
    )
    assert [by_name["Valentín Godoy"][k] for k in ("person", "guardian", "link")] == [
        "created",
        "created",
        "created",
    ]


# --- rows with no RUT and no email (#165) ------------------------------------------


def sheet_with(*rows: list[str], mapping: dict[str, int]) -> dict[str, Any]:
    return {
        "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
        "mapping": mapping,
    }


def person_rut(db: Database, person_id: str) -> str | None:
    rows = run(
        db.admin_url,
        lambda c: c.fetch("SELECT rut FROM person WHERE id = $1", uuid.UUID(person_id)),
    )
    rut: str | None = rows[0]["rut"]
    return rut


NAME_DOB_PHONE = {"name": 0, "dob": 1, "phone": 2}


@pg
def test_a_row_with_no_rut_or_email_imports_flagged_falta_rut_and_is_found_again(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    sheet = sheet_with(["Diego Soto", "", "9 1111 0001"], mapping=NAME_DOB_PHONE)
    [first] = imported(client, gym, sheet, dry_run=False)["rows"]
    assert (first["errors"], first["person"], first["missing_identity"]) == ([], "created", True)
    diego = find(client, gym, "Diego Soto")
    assert diego["missing_rut"] is True
    listed = client.get("/api/people?missing_rut=true", headers=as_gym(gym)).json()["items"]
    assert [p["id"] for p in listed] == [diego["id"]]

    count = people(db, gym)
    [again] = imported(client, gym, sheet, dry_run=False)["rows"]
    assert again["person"] == "existing"
    assert people(db, gym) == count


@pg
def test_two_of_one_name_are_told_apart_by_birth_date_then_phone_or_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rows = [
        ["Ana Pérez", "1990-01-01", "9 1111 0002"],
        ["Ana Pérez", "2001-05-05", "9 1111 0003"],
    ]
    first = imported(client, gym, sheet_with(*rows, mapping=NAME_DOB_PHONE), dry_run=False)
    assert [r["person"] for r in first["rows"]] == ["created", "created"]
    count = people(db, gym)

    def again(*cells: str) -> Any:
        [row] = imported(
            client, gym, sheet_with(list(cells), mapping=NAME_DOB_PHONE), dry_run=True
        )["rows"]
        return row

    assert again("Ana Pérez", "2001-05-05", "")["person"] == "existing"
    assert again("Ana Pérez", "", "+56911110002")["person"] == "existing"
    refused = again("Ana Pérez", "", "")
    assert refused["errors"] == [{"field": "name", "code": "ambiguous_name"}]
    assert people(db, gym) == count


@pg
def test_a_guardian_named_alone_is_found_in_this_gym_by_name_and_phone(
    client: TestClient, gym: uuid.UUID
) -> None:
    mapping = {"name": 0, "phone": 1, "guardian_name": 2, "guardian_phone": 3}
    parents = [["Marta Vera", "9 1111 0004", "", ""], ["Marta Vera", "9 1111 0005", "", ""]]
    imported(client, gym, sheet_with(*parents, mapping=mapping), dry_run=False)

    kids = [
        ["Tomás Vera", "", "Marta Vera", "9 1111 0005"],
        ["Sofía Vera", "", "MARTA VERA", ""],
    ]
    tomas, sofia = imported(client, gym, sheet_with(*kids, mapping=mapping), dry_run=False)["rows"]
    assert (tomas["errors"], tomas["guardian"]) == ([], "existing")
    assert sofia["errors"] == [{"field": "guardian_name", "code": "ambiguous_name"}]
    guardian = find(client, gym, "Tomás Vera")["guardian"]["id"]
    phone = client.get(f"/api/people/{guardian}", headers=as_gym(gym)).json()["phone"]
    assert phone == "+56911110005"


@pg
def test_a_name_never_finds_anyone_in_another_gym(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"other-{uuid.uuid4().hex[:8]}")
    theirs = imported(
        client, other, sheet_with(["Lucía Rojas", "", ""], mapping=NAME_DOB_PHONE), dry_run=False
    )["rows"][0]
    assert theirs["person"] == "created"
    [ours] = imported(
        client, gym, sheet_with(["Lucía Rojas", "", ""], mapping=NAME_DOB_PHONE), dry_run=False
    )["rows"]
    assert ours["person"] == "created"
    assert find(client, gym, "Lucía Rojas")["id"] != find(client, other, "Lucía Rojas")["id"]


@pg
def test_a_rut_given_later_becomes_who_they_are_and_says_nothing_of_other_gyms(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"other-{uuid.uuid4().hex[:8]}")
    taken = random_rut()
    elsewhere = client.post(
        "/api/people", json={"rut": taken, "name": "Otra"}, headers=as_gym(other)
    ).json()["id"]
    plain = {"name": 0}
    imported(client, gym, sheet_with(["Pablo Soto"], ["Rosa Soto"], mapping=plain), dry_run=False)
    pablo, rosa = find(client, gym, "Pablo Soto")["id"], find(client, gym, "Rosa Soto")["id"]

    free = random_rut()
    keyed = {"name": 0, "rut": 1}
    report = imported(
        client,
        gym,
        sheet_with(["Pablo Soto", free], ["Rosa Soto", taken], mapping=keyed),
        dry_run=False,
    )
    # The same answer whether the RUT was free or someone's in another gym.
    assert [(r["errors"], r["person"], r["ignored"]) for r in report["rows"]] == [
        ([], "existing", []),
        ([], "existing", []),
    ]
    assert find(client, gym, "Pablo Soto")["id"] == pablo
    assert (person_rut(db, pablo), find(client, gym, "Pablo Soto")["rut"]) == (free, free)
    # Taken elsewhere: this gym's record holds it; who they are is unchanged (a merge).
    assert (person_rut(db, rosa), find(client, gym, "Rosa Soto")["rut"]) == (None, taken)
    assert person_rut(db, elsewhere) == taken
    assert find(client, gym, "Rosa Soto")["missing_rut"] is False


@pg
def test_a_rut_typed_on_the_ficha_becomes_who_they_are_when_nobody_has_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = seed_gym(db, f"other-{uuid.uuid4().hex[:8]}")
    taken = random_rut()
    client.post("/api/people", json={"rut": taken, "name": "Otra"}, headers=as_gym(other))
    imported(
        client, gym, sheet_with(["Pablo Gil"], ["Rosa Gil"], mapping={"name": 0}), dry_run=False
    )
    pablo, rosa = find(client, gym, "Pablo Gil")["id"], find(client, gym, "Rosa Gil")["id"]

    free = random_rut()
    answers = [
        client.patch(f"/api/people/{person}", json={"rut": rut}, headers=as_gym(gym))
        for person, rut in ((pablo, free), (rosa, taken))
    ]
    assert [a.status_code for a in answers] == [200, 200]
    assert set(answers[0].json()) == set(answers[1].json())
    assert (person_rut(db, pablo), person_rut(db, rosa)) == (free, None)


@pg
def test_a_join_request_with_a_rut_keys_someone_the_gym_had_by_name(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    imported(client, gym, sheet_with(["Ana Pérez"], mapping={"name": 0}), dry_run=False)
    ana = find(client, gym, "Ana Pérez")["id"]
    with_privacy(client, gym)
    link = client.post("/api/join-link", json={}, headers=as_gym(gym)).json()["token"]
    rut = random_rut()
    body = {
        "first_name": "Ana",
        "last_name": "Pérez",
        "rut": rut,
        "phone": new_phone(),
        "email": f"{uuid.uuid4().hex[:8]}@example.cl",
        "dob": "1990-05-20",
        "consent": True,
    }
    assert client.post(f"/api/join/{link}", json=body).status_code == 202
    [request] = client.get("/api/join-requests", headers=as_gym(gym)).json()["items"]
    approved = client.post(
        f"/api/join-requests/{request['id']}/approve", json={}, headers=as_gym(gym)
    )

    assert approved.json()["person_id"] == ana
    assert person_rut(db, ana) == rut
