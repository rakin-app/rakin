"""History on the Alumnos sheet, and the template to fill in (#297).

Four columns bring a person's history from before Rakin in through the importer the
gym already uses: "Alumno desde", "Fecha de baja", "Motivo de baja" and "Clases antes
de Rakin". A row with a "Fecha de baja" is a former student, created already gone with
no membership. The four are written where the gym's record has none and `ignored`
otherwise, so a second run of a sheet already imported fills them. A real import
records itself as `history_imported` with the file's name and SHA-256, and each person
it gave history as `history_set` with its `import_id`; a dry run records nothing
(docs/design/historical-data.md, sections 3 and 6).
"""

import hashlib
import io
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import create_app
from app.member_import.template import COLUMNS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut, unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_member_import import PLANS, imported, sheet_with, upload
from tests.test_plans import add_staff

pg = pytest.mark.postgres

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    gym_id = seed_gym(db, unique_slug("gym"))
    for plan in PLANS:
        response = client.post("/api/plans", json=plan, headers=as_gym(gym_id))
        assert response.status_code == 201, response.text
    return gym_id


def find(client: TestClient, gym: uuid.UUID, name: str) -> dict[str, Any]:
    """`name`, whether or not they have left."""
    params = {"q": name, "left": "any"}
    items = client.get("/api/people", params=params, headers=as_gym(gym)).json()["items"]
    [found] = [p for p in items if p["name"] == name]
    return dict(found)


def person(client: TestClient, gym: uuid.UUID, name: str) -> dict[str, Any]:
    response = client.get(f"/api/people/{find(client, gym, name)['id']}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return dict(response.json())


def memberships(client: TestClient, gym: uuid.UUID, person_id: str) -> list[Any]:
    response = client.get("/api/memberships", params={"person_id": person_id}, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return list(response.json())


def audit(db: Database, gym: uuid.UUID, action: str) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT id, person_id, actor_id, detail FROM audit_event WHERE action = $1"
            " ORDER BY at, id",
            action,
        ),
    )
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


def ago(**delta: int) -> str:
    return (seeded_today() - timedelta(**delta)).isoformat()


HISTORY = {
    "name": 0,
    "rut": 1,
    "member_since": 2,
    "left_on": 3,
    "left_reason": 4,
    "prior_classes": 5,
}


# --- the template -----------------------------------------------------------------


@pg
def test_the_template_has_the_alumnos_columns_and_the_gyms_plans(
    client: TestClient, gym: uuid.UUID
) -> None:
    response = client.get("/api/import/template.xlsx", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == XLSX
    assert "plantilla-alumnos.xlsx" in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["Alumnos", "Pagos", "Instrucciones", "Planes"]
    alumnos = book["Alumnos"]
    assert [c.value for c in alumnos[1]] == [header for header, _, _ in COLUMNS]
    assert alumnos["A2"].font.color.rgb.endswith("808080")
    # The Plan column offers the active plans a row may start, drop-ins aside.
    planes = book["Planes"]
    assert planes.sheet_state == "hidden"
    assert [r[0].value for r in planes.iter_rows()] == [
        "Mensual",
        "Mensual Kids",
        "Pack 12 clases",
        "Semestral",
    ]
    [rule] = alumnos.data_validations.dataValidation
    assert (rule.type, rule.formula1, str(rule.sqref)) == ("list", "=Planes!$A$1:$A$4", "K2:K2001")
    assert alumnos["K2"].value == "Mensual"


@pg
def test_a_coach_gets_no_template(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    coach = add_staff(db, gym, "coach")
    assert client.get("/api/import/template.xlsx", headers=as_gym(gym, coach)).status_code == 403


@pg
def test_the_template_filled_in_maps_every_column_and_imports(
    client: TestClient, gym: uuid.UUID
) -> None:
    book = load_workbook(
        io.BytesIO(client.get("/api/import/template.xlsx", headers=as_gym(gym)).content)
    )
    alumnos = book["Alumnos"]
    alumnos.delete_rows(2)
    due = (seeded_today() + timedelta(days=12)).strftime("%d-%m-%Y")
    rows = [
        # A student training now, with a start years before Rakin and classes from then.
        {
            "Nombre": "Martina",
            "Apellido": "Soto Pérez",
            "RUT": random_rut(),
            "Plan": "Mensual",
            "Próximo vencimiento": due,
            "Alumno desde": "05-03-2019",
            "Clases antes de Rakin": "320",
        },
        # One who left.
        {
            "Nombre": "Joaquín",
            "Apellido": "Vera",
            "RUT": random_rut(),
            "Alumno desde": "10-01-2017",
            "Fecha de baja": "30-06-2022",
            "Motivo de baja": "Se cambió de ciudad",
        },
    ]
    headers = [header for header, _, _ in COLUMNS]
    for r, row in enumerate(rows, start=2):
        for header, value in row.items():
            alumnos.cell(row=r, column=headers.index(header) + 1, value=value)
    out = io.BytesIO()
    book.save(out)

    response = upload(client, gym, out.getvalue(), **{"Content-Type": XLSX})
    assert response.status_code == 200, response.text
    sheet = response.json()
    # Every header maps by itself, in the template's order.
    assert sheet["mapping"] == {field.value: i for i, (_, field, _) in enumerate(COLUMNS)}

    report = imported(client, gym, sheet, dry_run=False)
    assert [r["errors"] for r in report["rows"]] == [[], []]
    assert report["summary"]["history_set"] == 2
    martina = person(client, gym, "Martina Soto Pérez")
    assert (martina["member_since"], martina["prior_classes"], martina["left_on"]) == (
        "2019-03-05",
        320,
        None,
    )
    assert memberships(client, gym, martina["id"])[0]["plan_name"] == "Mensual"
    joaquin = person(client, gym, "Joaquín Vera")
    assert (joaquin["left_on"], joaquin["left_reason"]) == ("2022-06-30", "Se cambió de ciudad")


# --- former students --------------------------------------------------------------


@pg
def test_a_former_students_row_creates_them_already_gone_with_no_membership(
    client: TestClient, gym: uuid.UUID
) -> None:
    mapping = {**HISTORY, "plan": 6, "due_on": 7}
    sheet = sheet_with(
        ["Joaquín Vera", random_rut(), "2017-01-10", "2022-06-30", "Lesión", "", "Mensual", ""],
        mapping=mapping,
    )
    [row] = imported(client, gym, sheet, dry_run=False)["rows"]
    # The plan is not read, and the report says so.
    assert (row["errors"], row["person"], row["membership"]) == ([], "created", None)
    assert (row["ignored"], row["former"], row["history"]) == (["plan"], True, True)

    joaquin = person(client, gym, "Joaquín Vera")
    assert (joaquin["member_since"], joaquin["left_on"], joaquin["left_reason"]) == (
        "2017-01-10",
        "2022-06-30",
        "Lesión",
    )
    assert memberships(client, gym, joaquin["id"]) == []


@pg
def test_leaving_before_starting_is_refused_and_writes_nothing(
    client: TestClient, gym: uuid.UUID
) -> None:
    sheet = sheet_with(
        ["Joaquín Vera", random_rut(), "2019-01-10", "2018-06-30", "", ""], mapping=HISTORY
    )
    [row] = imported(client, gym, sheet, dry_run=False)["rows"]
    assert row["errors"] == [{"field": "left_on", "code": "left_before_start"}]
    assert (
        client.get("/api/people", params={"q": "Joaquín"}, headers=as_gym(gym)).json()["items"]
        == []
    )


@pg
def test_someone_here_who_has_not_left_is_never_given_a_baja(
    client: TestClient, gym: uuid.UUID
) -> None:
    rut = random_rut()
    imported(
        client, gym, sheet_with(["Ana Paz", rut], mapping={"name": 0, "rut": 1}), dry_run=False
    )

    sheet = sheet_with(["Ana Paz", rut, "", "2024-03-01", "Precio", ""], mapping=HISTORY)
    [row] = imported(client, gym, sheet, dry_run=False)["rows"]
    assert (row["errors"], row["person"], row["history"]) == ([], "existing", False)
    assert row["ignored"] == ["left_on", "left_reason"]
    ana = person(client, gym, "Ana Paz")
    assert (ana["left_on"], ana["left_reason"]) == (None, None)


@pg
def test_a_reason_fills_in_for_someone_who_left_without_one(
    client: TestClient, gym: uuid.UUID
) -> None:
    rut = random_rut()
    first = sheet_with(["Ana Paz", rut, "", "2024-03-01", "", ""], mapping=HISTORY)
    imported(client, gym, first, dry_run=False)
    again = sheet_with(["Ana Paz", rut, "", "2024-03-01", "Horario", ""], mapping=HISTORY)
    [row] = imported(client, gym, again, dry_run=False)["rows"]
    assert (row["ignored"], row["history"]) == ([], True)
    assert person(client, gym, "Ana Paz")["left_reason"] == "Horario"


# --- fill when empty --------------------------------------------------------------


@pg
def test_running_an_imported_sheet_again_fills_empty_history_and_ignores_filled(
    client: TestClient, gym: uuid.UUID
) -> None:
    due = (seeded_today() + timedelta(days=12)).isoformat()
    camila, diego = random_rut(), random_rut()
    plain = {"name": 0, "rut": 1, "plan": 2, "due_on": 3}
    # As the pilot imported its students before there were history columns.
    imported(
        client,
        gym,
        sheet_with(
            ["Camila Ortiz", camila, "Mensual", due],
            ["Diego Soto", diego, "Mensual", due],
            mapping=plain,
        ),
        dry_run=False,
    )
    mapping = {**plain, "member_since": 4, "prior_classes": 5}
    sheet = sheet_with(
        ["Camila Ortiz", camila, "Mensual", due, "2019-03-05", "320"],
        ["Diego Soto", diego, "Mensual", due, "", "40"],
        mapping=mapping,
    )
    rows = imported(client, gym, sheet, dry_run=False)["rows"]
    assert [(r["person"], r["membership"], r["history"], r["ignored"]) for r in rows] == [
        ("existing", "existing", True, []),
        ("existing", "existing", True, []),
    ]
    assert (
        person(client, gym, "Camila Ortiz")["member_since"],
        person(client, gym, "Camila Ortiz")["prior_classes"],
    ) == ("2019-03-05", 320)

    # Filled now: another value is kept out, the same one is nothing to say.
    sheet = sheet_with(
        ["Camila Ortiz", camila, "Mensual", due, "2018-01-01", "320"],
        ["Diego Soto", diego, "Mensual", due, "2020-02-02", "55"],
        mapping=mapping,
    )
    rows = imported(client, gym, sheet, dry_run=False)["rows"]
    assert [(r["history"], r["ignored"]) for r in rows] == [
        (False, ["member_since"]),
        (True, ["prior_classes"]),
    ]
    camila_now, diego_now = person(client, gym, "Camila Ortiz"), person(client, gym, "Diego Soto")
    assert (camila_now["member_since"], camila_now["prior_classes"]) == ("2019-03-05", 320)
    assert (diego_now["member_since"], diego_now["prior_classes"]) == ("2020-02-02", 40)


# --- the import's record ----------------------------------------------------------


@pg
def test_the_sheet_answers_its_hash_and_name(client: TestClient, gym: uuid.UUID) -> None:
    data = b"Nombre;RUT\nAna Paz;11.111.111-1\n"
    response = client.post(
        "/api/import/sheet",
        params={"name": "alumnos meta.csv"},
        content=data,
        headers={"Content-Type": "text/csv", **as_gym(gym)},
    )
    assert response.status_code == 200, response.text
    assert response.json()["file"] == {
        "name": "alumnos meta.csv",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    assert upload(client, gym, data).json()["file"]["name"] is None


@pg
def test_an_import_records_itself_and_each_persons_history_and_a_dry_run_neither(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    sha = hashlib.sha256(b"the file").hexdigest()
    sheet = {
        **sheet_with(
            ["Joaquín Vera", random_rut(), "2017-01-10", "2022-06-30", "Lesión", "12"],
            ["Ana Paz", random_rut(), "", "", "", ""],
            mapping=HISTORY,
        ),
        "file": {"name": "exalumnos.xlsx", "sha256": sha},
    }
    dry = imported(client, gym, sheet, dry_run=True)
    assert dry["import_id"] is None
    assert audit(db, gym, "history_imported") == audit(db, gym, "history_set") == []

    report = imported(client, gym, sheet, dry_run=False)
    [record] = audit(db, gym, "history_imported")
    assert str(record["id"]) == report["import_id"]
    assert record["person_id"] is None and record["actor_id"] is not None
    assert record["detail"] == {
        "file_name": "exalumnos.xlsx",
        "sha256": sha,
        "tabs": ["alumnos"],
        "counts": {
            "alumnos": {
                "rows": 2,
                "imported": 2,
                "refused": 0,
                "people_created": 2,
                "links_created": 0,
                "memberships_created": 0,
                "history_set": 1,
                "former_created": 1,
            }
        },
    }
    joaquin = find(client, gym, "Joaquín Vera")
    [history_set] = audit(db, gym, "history_set")
    assert str(history_set["person_id"]) == joaquin["id"]
    assert history_set["detail"] == {
        "import_id": report["import_id"],
        "member_since": {"before": None, "after": "2017-01-10"},
        "prior_classes": {"before": 0, "after": 12},
        "left_on": {"before": None, "after": "2022-06-30"},
        "left_reason": {"before": None, "after": "Lesión"},
    }

    # The same sheet again writes nothing, so it records nothing.
    again = imported(client, gym, sheet, dry_run=False)
    assert again["import_id"] is None
    assert len(audit(db, gym, "history_imported")) == 1


@pg
def test_a_bad_file_hash_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    sheet = {**sheet_with(["Ana Paz"], mapping={"name": 0}), "file": {"name": "a", "sha256": "x"}}
    body = {**sheet, "plans": {}, "dry_run": True}
    assert client.post("/api/import/members", json=body, headers=as_gym(gym)).status_code == 422


@pg
def test_history_dates_go_back_60_years_and_billing_dates_keep_five(
    client: TestClient, gym: uuid.UUID
) -> None:
    since = date(seeded_today().year - 50, 1, 1).isoformat()
    long_ago = ago(days=6 * 366)
    sheet = sheet_with(
        ["Ana Paz", random_rut(), since],
        ["Ema Paz", random_rut(), "", "Mensual", long_ago],
        mapping={"name": 0, "rut": 1, "member_since": 2, "plan": 3, "due_on": 4},
    )
    rows = imported(client, gym, sheet, dry_run=True)["rows"]
    assert [r["errors"] for r in rows] == [[], [{"field": "due_on", "code": "invalid_date"}]]
