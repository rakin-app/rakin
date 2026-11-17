"""The Grados tab (#299): belts and stripes with their dates, from the gym's workbook.

A Grados row is written after the Alumnos tab, in the same run and the same dry run, so
it finds a student that tab adds. It never creates anyone: nobody by its RUT, email or
name is `unknown_person`, two of the name `ambiguous_name`. Its rank is the scheme's by
label, else the admin's choice for that value. A grade the person already has is
`existing`, so a second run adds none, and one an earlier row gives is `repeated`. Each
is `source` `import` with the run's `import_id`, and writes no `promoted` event
(docs/design/historical-data.md, section 3). A gym none of whose activities grades reads
no Grados tab, however many ranks its stored scheme has (#352).
"""

import copy
import io
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app.main import create_app
from app.member_import.template import GRADE_COLUMNS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, throwaway_database
from tests.test_grades import BJJ, gym_with
from tests.test_gym_hosts import create, new_gym
from tests.test_import_history import XLSX, audit, find

pg = pytest.mark.postgres

ALUMNOS = [["Nombre", "Apellido", "RUT"], ["Martina", "Soto", "12.345.678-5"]]
GRADES = {"rut": 0, "name": 1, "rank": 2, "sub_rank": 3, "awarded_on": 4, "note": 5}


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
    return graded_gym(client, db)


def graded_gym(client: TestClient, db: Database, scheme: dict[str, Any] = BJJ) -> uuid.UUID:
    """A gym with `scheme` and an activity that grades: belts show while one does (#245),
    and so its Grados tab is read (#352)."""
    gym = gym_with(client, db, scheme)
    response = client.post(
        "/api/activities",
        json={"name": "BJJ", "uses_grades": True, "preset": "bjj"},
        headers=as_gym(gym),
    )
    assert response.status_code == 201, response.text
    return gym


def graded_off(client: TestClient, db: Database) -> tuple[uuid.UUID, dict[str, str]]:
    """A gym created on the BJJ preset, its only activity then set not to grade: its
    scheme keeps the preset's ranks. With the headers that act as its owner."""
    gym_id = create(
        db, new_gym(f"apagado-{uuid.uuid4().hex[:6]}").model_copy(update={"grading": "bjj"})
    ).gym_id
    owner = run(
        db.owner_url,
        in_gym(gym_id, "SELECT person_id FROM staff WHERE role = 'owner'"),
    )[0]["person_id"]
    headers = as_gym(gym_id, owner)
    [activity] = client.get("/api/activities", headers=headers).json()
    response = client.patch(
        f"/api/activities/{activity['id']}", json={"uses_grades": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/gym/grading-scheme", headers=headers).json()["ranks"]
    return gym_id, headers


def workbook(**tabs: Sequence[Sequence[object]]) -> bytes:
    book = Workbook()
    first = book.active
    assert first is not None
    book.remove(first)
    for title, rows in tabs.items():
        worksheet = book.create_sheet(title)
        for row in rows:
            worksheet.append(list(row))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def upload(client: TestClient, gym: uuid.UUID, data: bytes, **params: str) -> dict[str, Any]:
    response = client.post(
        "/api/import/sheet",
        params=params,
        content=data,
        headers={"Content-Type": XLSX, **as_gym(gym)},
    )
    assert response.status_code == 200, response.text
    sheet: dict[str, Any] = response.json()
    return sheet


def send(
    client: TestClient,
    gym: uuid.UUID,
    sheet: dict[str, Any],
    *,
    dry_run: bool,
    ranks: dict[str, str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rows": sheet["rows"],
        "mapping": sheet["mapping"],
        "dry_run": dry_run,
        "file": sheet["file"],
    }
    if sheet["grados"] is not None:
        body["grados"] = {
            "rows": sheet["grados"]["rows"],
            "mapping": sheet["grados"]["mapping"],
            "ranks": ranks or {},
        }
    response = client.post("/api/import/members", json=body, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    report: dict[str, Any] = response.json()
    return report


def grades_tab(*rows: list[str]) -> dict[str, Any]:
    """A sheet as the upload answers it, Grados tab only, mapped as `GRADES`."""
    return {
        "rows": [],
        "mapping": {},
        "file": None,
        "grados": {
            "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
            "mapping": GRADES,
        },
    }


def grading(client: TestClient, gym: uuid.UUID, name: str) -> dict[str, Any]:
    person_id = find(client, gym, name)["id"]
    response = client.get(f"/api/people/{person_id}/grades", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def stored_grades(db: Database, gym: uuid.UUID) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT rank_key, sub_rank, awarded_on, source, import_id, membership_id, note"
            " FROM grade_event ORDER BY awarded_on",
        ),
    )
    return [dict(r) for r in rows]


def promoted(db: Database, gym: uuid.UUID) -> int:
    rows = run(db.owner_url, in_gym(gym, "SELECT count(*) FROM plan_event WHERE kind = 'promoted'"))
    count: int = rows[0][0]
    return count


def outcomes(report: dict[str, Any]) -> list[Any]:
    return [(r["row"], r["grade"], r["errors"]) for r in report["grados"]["rows"]]


def add(client: TestClient, gym: uuid.UUID, name: str, **fields: Any) -> str:
    response = client.post("/api/people", json={"name": name, **fields}, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@pg
def test_a_grades_row_finds_a_student_the_alumnos_tab_adds_and_sets_their_rank(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    data = workbook(
        Alumnos=ALUMNOS,
        Grados=[
            [header for header, _, _ in GRADE_COLUMNS],
            ["12.345.678-5", "", "", "Blanca", "4", "10-03-2019", ""],
            ["", "", "Martina Soto", "Azul", "2 grados", "12-08-2023", "Graduación de invierno"],
            ["12345678-5", "", "", "Azul", "1", "15-01-2022", ""],
        ],
    )
    sheet = upload(client, gym, data, name="academia.xlsx")
    assert sheet["grados"]["mapping"] == {f: i for i, (_, f, _) in enumerate(GRADE_COLUMNS)}

    dry = send(client, gym, sheet, dry_run=True)
    assert dry["summary"]["people_created"] == 1
    assert dry["grados"]["summary"] == {
        "rows": 3,
        "imported": 3,
        "refused": 0,
        "grades_created": 3,
    }
    assert stored_grades(db, gym) == []

    done = send(client, gym, sheet, dry_run=False)
    assert [r[1] for r in outcomes(done)] == ["created"] * 3
    current = grading(client, gym, "Martina Soto")["current"]
    assert (current["rank_label"], current["sub_rank_label"], current["awarded_on"]) == (
        "Azul",
        "2 grados",
        "2023-08-12",
    )
    stored = stored_grades(db, gym)
    assert {(g["source"], g["import_id"], g["membership_id"]) for g in stored} == {
        ("import", uuid.UUID(done["import_id"]), None)
    }
    assert stored[-1]["note"] == "Graduación de invierno"
    # A belt from 2023 congratulates nobody.
    assert promoted(db, gym) == 0
    [record] = audit(db, gym, "history_imported")
    assert record["id"] == uuid.UUID(done["import_id"])
    assert record["detail"]["tabs"] == ["alumnos", "grados"]
    assert record["detail"]["counts"]["grados"] == done["grados"]["summary"]


@pg
def test_running_it_twice_adds_no_grade_the_second_time(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    add(client, gym, "Diego Rojas", rut="11.111.111-1")
    sheet = grades_tab(
        ["11.111.111-1", "", "Azul", "", "01-02-2024", ""],
        ["11.111.111-1", "", "Morada", "1", "01-02-2025", ""],
    )
    first = send(client, gym, sheet, dry_run=False)
    assert first["grados"]["summary"]["grades_created"] == 2

    second = send(client, gym, sheet, dry_run=False)
    assert outcomes(second) == [(2, "existing", []), (3, "existing", [])]
    assert second["grados"]["summary"]["grades_created"] == 0
    assert len(stored_grades(db, gym)) == 2
    # Nothing written, so nothing recorded.
    assert second["import_id"] is None
    assert len(audit(db, gym, "history_imported")) == 1


@pg
def test_an_equal_row_earlier_in_the_sheet_makes_the_second_repeated(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    add(client, gym, "Diego Rojas", rut="11.111.111-1")
    sheet = grades_tab(
        ["11.111.111-1", "", "Azul", "0", "01-02-2024", ""],
        ["", "Diego Rojas", "azul", "", "2024-02-01", ""],
        ["11.111.111-1", "", "Azul", "1", "01-02-2024", ""],
    )
    report = send(client, gym, sheet, dry_run=True)
    assert outcomes(report) == [
        (2, "created", []),
        (3, None, [{"field": "rank", "code": "repeated"}]),
        (4, "created", []),
    ]


@pg
def test_a_label_chosen_on_the_mapping_step_matches_and_an_unmatched_one_is_refused(
    client: TestClient, db: Database
) -> None:
    scheme = copy.deepcopy(BJJ)
    scheme["ranks"][3]["label"] = "Marrón"
    gym = graded_gym(client, db, scheme)
    add(client, gym, "Diego Rojas", rut="11.111.111-1")
    sheet = grades_tab(
        ["11.111.111-1", "", "Café", "", "01-02-2024", ""],
        ["11.111.111-1", "", "Celeste", "", "01-02-2023", ""],
    )
    refused = send(client, gym, sheet, dry_run=True)
    assert outcomes(refused) == [
        (2, None, [{"field": "rank", "code": "unknown_rank"}]),
        (3, None, [{"field": "rank", "code": "unknown_rank"}]),
    ]

    chosen = send(client, gym, sheet, dry_run=False, ranks={"Café": "brown"})
    assert outcomes(chosen) == [
        (2, "created", []),
        (3, None, [{"field": "rank", "code": "unknown_rank"}]),
    ]
    assert grading(client, gym, "Diego Rojas")["current"]["rank_label"] == "Marrón"


@pg
def test_a_row_that_names_nobody_or_two_people_is_refused_and_creates_no_one(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Two of one name, told apart by their birth dates, which a grade row does not give.
    camilas = {
        "rows": [
            {"number": 2, "cells": ["Camila Pérez", "2001-01-01"]},
            {"number": 3, "cells": ["Camila Pérez", "2002-02-02"]},
        ],
        "mapping": {"name": 0, "dob": 1},
        "dry_run": False,
    }
    response = client.post("/api/import/members", json=camilas, headers=as_gym(gym))
    assert response.json()["summary"]["people_created"] == 2, response.text
    before = len(client.get("/api/people", headers=as_gym(gym)).json()["items"])
    sheet = grades_tab(
        ["", "Camila Pérez", "Azul", "", "01-02-2024", ""],
        ["", "Nadie Aquí", "Azul", "", "01-02-2024", ""],
        ["22.222.222-2", "", "Azul", "", "01-02-2024", ""],
    )
    report = send(client, gym, sheet, dry_run=False)
    assert outcomes(report) == [
        (2, None, [{"field": "name", "code": "ambiguous_name"}]),
        (3, None, [{"field": "name", "code": "unknown_person"}]),
        (4, None, [{"field": "rut", "code": "unknown_person"}]),
    ]
    assert report["import_id"] is None
    assert len(client.get("/api/people", headers=as_gym(gym)).json()["items"]) == before
    assert stored_grades(db, gym) == []


@pg
def test_a_kid_is_found_by_their_name(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    guardian = add(client, gym, "Paula Pérez", rut="11.111.111-1")
    response = client.post(
        f"/api/people/{guardian}/dependents",
        json={"name": "Tomás Pérez"},
        headers=as_gym(gym),
    )
    assert response.status_code == 201, response.text
    report = send(
        client, gym, grades_tab(["", "tomas perez", "Gris", "", "01-02-2024", ""]), dry_run=False
    )
    assert outcomes(report) == [(2, "created", [])]
    assert grading(client, gym, "Tomás Pérez")["current"]["rank_label"] == "Gris"


@pg
def test_a_csv_is_the_grados_tab_when_the_upload_says(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    sheet = upload(client, gym, b"Nombre,Grado,Fecha\nMartina,Azul,01-02-2024\n", tab="grados")
    assert (sheet["rows"], sheet["mapping"]) == ([], {})
    assert sheet["grados"]["mapping"] == {"name": 0, "rank": 1, "awarded_on": 2}


@pg
def test_a_grados_tab_needs_its_rank_day_and_who(client: TestClient, gym: uuid.UUID) -> None:
    for mapping in ({"name": 0, "rank": 1}, {"rank": 1, "awarded_on": 2}):
        body = {
            "grados": {"rows": [{"number": 2, "cells": ["a", "b", "c"]}], "mapping": mapping},
            "dry_run": True,
        }
        response = client.post("/api/import/members", json=body, headers=as_gym(gym))
        assert response.status_code == 422, mapping
    response = client.post("/api/import/members", json={"dry_run": True}, headers=as_gym(gym))
    assert response.status_code == 422


@pg
def test_the_template_has_a_grados_tab_with_the_schemes_ranks(
    client: TestClient, gym: uuid.UUID
) -> None:
    response = client.get("/api/import/template.xlsx", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == [
        "Alumnos",
        "Pagos",
        "Grados",
        "Instrucciones",
        "Planes",
        "Lista de grados",
    ]
    grados = book["Grados"]
    assert [c.value for c in grados[1]] == [header for header, _, _ in GRADE_COLUMNS]
    assert [c.value for c in grados[2]][2:5] == ["Martina Soto Pérez", "Azul", "1"]
    # A number in Sub-grado counts stripes, and the instructions say so with an example.
    notes = [r[1].value for r in book["Instrucciones"].iter_rows() if r[0].value == "Sub-grado"]
    assert notes == [
        "Opcional: cuántos grados (rayas) tiene, o el sub-grado por su nombre."
        " Ej.: Azul y 2 = azul con 2 grados. Vacío = sin grados."
    ]
    listed = book["Lista de grados"]
    assert listed.sheet_state == "hidden"
    labels = [r[0].value for r in listed.iter_rows()]
    assert labels[:5] == ["Blanca", "Azul", "Morada", "Café", "Negra"]
    [rule] = grados.data_validations.dataValidation
    assert (rule.formula1, str(rule.sqref)) == (
        f"='Lista de grados'!$A$1:$A${len(labels)}",
        "D2:D2001",
    )

    # The filled template reads back with the example rows and maps with no change.
    sheet = upload(client, gym, response.content)
    assert sheet["grados"]["mapping"] == {f: i for i, (_, f, _) in enumerate(GRADE_COLUMNS)}
    report = send(client, gym, sheet, dry_run=True)
    assert outcomes(report) == [(2, "created", [])]


@pg
def test_a_gym_that_does_not_grade_gets_no_grados_tab(client: TestClient, db: Database) -> None:
    gym = gym_with(client, db, None)
    response = client.get("/api/import/template.xlsx", headers=as_gym(gym))
    assert "Grados" not in load_workbook(io.BytesIO(response.content)).sheetnames


@pg
def test_a_gym_whose_only_graded_activity_is_off_gets_no_grados_tab(
    client: TestClient, db: Database
) -> None:
    _, headers = graded_off(client, db)
    response = client.get("/api/import/template.xlsx", headers=headers)
    assert response.status_code == 200, response.text
    book = load_workbook(io.BytesIO(response.content))
    assert "Grados" not in book.sheetnames and "Lista de grados" not in book.sheetnames
    notes = [str(r[1].value) for r in book["Instrucciones"].iter_rows() if r[1].value]
    assert not any("rayas" in note for note in notes)


@pg
def test_a_grados_tab_where_no_activity_grades_is_ignored_and_writes_no_grade(
    client: TestClient, db: Database
) -> None:
    gym, headers = graded_off(client, db)
    data = workbook(
        Alumnos=ALUMNOS,
        Grados=[
            ["RUT", "Nombre", "Grado", "Fecha"],
            ["12.345.678-5", "Martina Soto", "Azul", "12-08-2023"],
        ],
    )
    response = client.post(
        "/api/import/sheet", content=data, headers={"Content-Type": XLSX, **headers}
    )
    assert response.status_code == 200, response.text
    sheet = response.json()
    assert (sheet["grados"], sheet["grados_ignored"]) == (None, True)
    assert len(sheet["rows"]) == 1

    # Sent anyway, as an older page would: the people import, the grades do not.
    body = {
        "rows": sheet["rows"],
        "mapping": sheet["mapping"],
        "dry_run": False,
        "file": sheet["file"],
        "grados": {
            "rows": [
                {"number": 2, "cells": ["12.345.678-5", "Martina Soto", "Azul", "12-08-2023"]}
            ],
            "mapping": {"rut": 0, "name": 1, "rank": 2, "awarded_on": 3},
            "ranks": {},
        },
    }
    response = client.post("/api/import/members", json=body, headers=headers)
    assert response.status_code == 200, response.text
    report = response.json()
    assert (report["summary"]["people_created"], report["grados"]) == (1, None)
    assert stored_grades(db, gym) == []
