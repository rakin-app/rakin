"""Deshacer importación (#300): undo the history an import wrote, owner only, with a reason.

Importar lists the gym's recent imports. The owner undoes one: its history payments and
grades, found by their `import_id`, are deleted, and the fields it set on people
(`member_since`, `prior_classes`, `left_on`, `left_reason`) go back to what it found,
where they still hold what it wrote. One changed since is kept, and the confirmation
counts it. People it created stay. The undo is recorded as `import_undone`, once
(docs/design/historical-data.md, sections 6 and 8).
"""

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_grades import gym_with
from tests.test_import_grades import GRADES, stored_grades
from tests.test_import_history import HISTORY, audit, find, person
from tests.test_import_payments import PAYMENTS, paid, stored
from tests.test_plans import add_staff

pg = pytest.mark.postgres


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
    return gym_with(client, db)


def tab(rows: list[list[str]], mapping: dict[str, int]) -> dict[str, Any]:
    return {
        "rows": [{"number": n, "cells": cells} for n, cells in enumerate(rows, start=2)],
        "mapping": mapping,
    }


def load(
    client: TestClient,
    gym: uuid.UUID,
    alumnos: list[list[str]] | None = None,
    pagos: list[list[str]] | None = None,
    grados: list[list[str]] | None = None,
    name: str = "historia.xlsx",
) -> str:
    """Import the tabs given, for real; the import's id."""
    body: dict[str, Any] = {
        **tab(alumnos or [], HISTORY),
        "dry_run": False,
        "file": {"name": name, "sha256": "0" * 64},
    }
    if pagos is not None:
        body["pagos"] = tab(pagos, PAYMENTS)
    if grados is not None:
        body["grados"] = {**tab(grados, GRADES), "ranks": {}}
    response = client.post("/api/import/members", json=body, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    report = response.json()
    for name_ in ("pagos", "grados"):
        if report.get(name_):
            assert all(not r["errors"] for r in report[name_]["rows"]), report[name_]
    import_id: str = report["import_id"]
    assert import_id is not None
    return import_id


def counts(client: TestClient, gym: uuid.UUID, import_id: str, by: uuid.UUID | None = None) -> Any:
    return client.get(f"/api/import/{import_id}/undo", headers=as_gym(gym, by))


def undo(
    client: TestClient,
    gym: uuid.UUID,
    import_id: str,
    reason: str = "columna corrida",
    by: uuid.UUID | None = None,
) -> Any:
    return client.post(
        f"/api/import/{import_id}/undo", json={"reason": reason}, headers=as_gym(gym, by)
    )


def recent(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> Any:
    return client.get("/api/import/recent", headers=as_gym(gym, by))


def grade(rut: str, rank: str, day: str) -> list[str]:
    """A Grados row in `GRADES`' columns."""
    return [rut, "", rank, "", day, ""]


def history_of(db: Database, gym: uuid.UUID, person_id: str) -> tuple[Any, ...]:
    [row] = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT member_since, prior_classes, left_on, left_reason FROM gym_person"
            " WHERE person_id = $1",
            uuid.UUID(person_id),
        ),
    )
    return tuple(row)


@pg
def test_undoing_an_import_removes_exactly_its_payments_and_grades_and_restores_its_fields(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana_rut, joaquin_rut = random_rut(), random_rut()
    first = load(
        client,
        gym,
        alumnos=[
            ["Ana Paz", ana_rut, "2019-03-05", "", "", "120"],
            ["Joaquín Vera", joaquin_rut, "2017-01-10", "2022-06-30", "Lesión", ""],
        ],
        pagos=[
            paid(ana_rut, "05-03-2024", month="03-2024"),
            paid(ana_rut, "05-04-2024", month="04-2024"),
        ],
        grados=[grade(ana_rut, "Azul", "12-08-2023")],
        name="malo.xlsx",
    )
    # A later import's payment and grade, and one typed on the ficha, all stay.
    second = load(
        client,
        gym,
        pagos=[paid(joaquin_rut, "05-03-2021", month="03-2021")],
        grados=[grade(joaquin_rut, "Blanca", "10-03-2019")],
    )
    ana = find(client, gym, "Ana Paz")["id"]
    joaquin = find(client, gym, "Joaquín Vera")["id"]
    typed = client.post(
        f"/api/people/{ana}/history/payments",
        json={"payments": [{"paid_on": "2023-01-05", "amount_clp": 20000}]},
        headers=as_gym(gym),
    )
    assert typed.status_code == 201, typed.text

    preview = counts(client, gym, first)
    assert preview.status_code == 200, preview.text
    assert preview.json() == {"payments": 2, "grades": 1, "people": 2, "kept": 0}

    response = undo(client, gym, first)
    assert response.status_code == 204, response.text

    assert sorted((p["source"], str(p["import_id"])) for p in stored(db, gym)) == [
        ("import", second),
        ("manual", "None"),
    ]
    assert [(g["rank_key"], str(g["import_id"])) for g in stored_grades(db, gym)] == [
        ("white", second)
    ]
    assert history_of(db, gym, ana) == (None, 0, None, None)
    assert history_of(db, gym, joaquin) == (None, 0, None, None)
    # The people it created stay.
    assert person(client, gym, "Joaquín Vera")["id"] == joaquin

    [record] = audit(db, gym, "import_undone")
    assert (record["person_id"], record["actor_id"]) == (None, seeded_owner(gym))
    assert record["detail"] == {
        "import_id": first,
        "payments": 2,
        "grades": 1,
        "people": 2,
        "kept": 0,
    }
    reason = run(
        db.owner_url,
        in_gym(gym, "SELECT reason FROM audit_event WHERE action = 'import_undone'"),
    )
    assert reason[0]["reason"] == "columna corrida"
    # Each person's own record says what went back, as an edit on the ficha would.
    put_back = {
        str(r["person_id"]): r["detail"]
        for r in audit(db, gym, "history_set")
        if r["detail"].get("undo_of") == first
    }
    assert put_back[ana] == {
        "undo_of": first,
        "member_since": {"before": "2019-03-05", "after": None},
        "prior_classes": {"before": 120, "after": 0},
    }
    assert put_back[joaquin]["left_on"] == {"before": "2022-06-30", "after": None}

    listed = recent(client, gym)
    assert listed.status_code == 200, listed.text
    [newest, oldest] = listed.json()
    assert (newest["id"], newest["undone"]) == (second, None)
    assert newest["tabs"] == ["pagos", "grados"]
    assert (oldest["id"], oldest["file_name"]) == (first, "malo.xlsx")
    assert oldest["by"].startswith("owner of")
    assert oldest["counts"]["pagos"]["payments_created"] == 2
    undone = oldest["undone"]
    assert (undone["reason"], undone["payments"], undone["grades"], undone["people"]) == (
        "columna corrida",
        2,
        1,
        2,
    )


@pg
def test_a_field_edited_after_the_import_is_kept(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rut = random_rut()
    imported = load(client, gym, alumnos=[["Ana Paz", rut, "2019-03-05", "", "", "120"]])
    ana = find(client, gym, "Ana Paz")["id"]
    edited = client.put(
        f"/api/people/{ana}/history",
        json={"member_since": "2018-01-02", "prior_classes": 120},
        headers=as_gym(gym),
    )
    assert edited.status_code == 200, edited.text

    assert counts(client, gym, imported).json() == {
        "payments": 0,
        "grades": 0,
        "people": 1,
        "kept": 1,
    }
    assert undo(client, gym, imported).status_code == 204
    # The edit stays; what the import alone set goes back.
    assert history_of(db, gym, ana)[:2] == (date(2018, 1, 2), 0)
    [record] = audit(db, gym, "import_undone")
    assert record["detail"]["kept"] == 1


@pg
def test_an_admin_cannot_undo_and_an_import_is_undone_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    imported = load(client, gym, alumnos=[["Ana Paz", random_rut(), "2019-03-05", "", "", ""]])
    admin = add_staff(db, gym, "admin")
    coach = add_staff(db, gym, "coach")

    # An admin sees the list, and neither what an undo would remove nor the undo.
    assert recent(client, gym, admin).status_code == 200
    assert recent(client, gym, coach).status_code == 403
    assert counts(client, gym, imported, admin).status_code == 403
    assert undo(client, gym, imported, by=admin).status_code == 403
    assert audit(db, gym, "import_undone") == []

    # The function holds the app role to the owner too, whatever endpoint calls it.
    async def as_admin(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(admin))
            return await conn.fetchval("SELECT undo_import($1, 'x')", uuid.UUID(imported))

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, as_admin)

    assert undo(client, gym, imported, reason="  ").status_code == 422
    assert undo(client, gym, imported).status_code == 204
    again = undo(client, gym, imported)
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == {"code": "undone"}
    assert len(audit(db, gym, "import_undone")) == 1

    assert undo(client, gym, str(uuid.uuid4())).status_code == 404
    assert counts(client, gym, str(uuid.uuid4())).status_code == 404
    # Another gym's import is not this one's.
    other = gym_with(client, db)
    assert counts(client, other, imported).status_code == 404
    assert undo(client, other, imported).status_code == 404


@pg
def test_upgrade_and_downgrade_0056() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0055")
        migrate(scratch)
        gym = seed_gym(scratch, "sur")
        owner = seeded_owner(gym)

        async def log(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, action, reason, detail)"
                " VALUES ($1, $2, 'import_undone', 'x', '{\"import_id\": \"a\"}'),"
                " ($1, $2, 'history_imported', NULL, '{}')",
                gym,
                owner,
            )

        run(scratch.admin_url, log)
        command.downgrade(scratch.alembic(), "0055")
        kept = run(scratch.admin_url, lambda c: c.fetch("SELECT action FROM audit_event"))
        assert [r["action"] for r in kept] == ["history_imported"]
        migrate(scratch)
