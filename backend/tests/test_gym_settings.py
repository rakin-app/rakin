"""Gym settings: the input rules, the defaults a new gym reads, and what a change touches.

Roles are covered with the other endpoint groups in `tests/test_roles.py`.
"""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.gym import GymSettingsUpdate
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

BANK = {
    "bank": "Banco Estado",
    "account_type": "Cuenta Vista",
    "holder": "Academia Sur SpA",
    "rut": "76.432.109-K",
    "number": "000012348821",
    "email": "pagos@academiasur.example.com",
}
# As stored and read back.
BANK_STORED = {**BANK, "rut": "76432109-K"}

# --- input rules, no database -----------------------------------------------------


def test_update_normalises_the_bank_rut_and_takes_only_the_fields_sent() -> None:
    body = GymSettingsUpdate.model_validate({"bank_account": BANK, "grace_days": 7})
    assert body.model_dump(exclude_unset=True) == {
        "bank_account": BANK_STORED,
        "grace_days": 7,
    }


@pytest.mark.parametrize(
    "field",
    [
        {"name": "  "},
        {"name": None},
        {"slug": "otro"},
        {"timezone": "Chile/Somewhere"},
        {"timezone": None},
        {"grace_days": -1},
        {"grace_days": 61},
        {"grace_days": "5"},
        {"grace_days": True},
        {"grace_days": None},
        {"reminder_every_days": 0},
        {"channels": {"whatsapp": "yes"}},
        {"channels": {"email": False}},
        {"channels": None},
        {"bank_account": {**BANK, "rut": "76.432.109-1"}},
        {"bank_account": {**BANK, "number": "12 34 ab"}},
        {"bank_account": {**BANK, "account_type": "Chequera"}},
        {"bank_account": {**BANK, "email": "pagos"}},
        {"bank_account": {k: v for k, v in BANK.items() if k != "holder"}},
        {"settings": {}},
    ],
    ids=str,
)
def test_update_refuses(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GymSettingsUpdate.model_validate(field)


def test_the_bank_details_may_be_cleared() -> None:
    body = GymSettingsUpdate.model_validate({"bank_account": None})
    assert body.model_dump(exclude_unset=True) == {"bank_account": None}


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres

URL = "/api/gym/settings"


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


def stored(db: Database, gym: uuid.UUID) -> dict[str, Any]:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow("SELECT name, timezone, settings FROM gym WHERE id = $1", gym),
    )
    return {
        "name": row["name"],
        "timezone": row["timezone"],
        "settings": json.loads(row["settings"]),
    }


@pg
def test_a_new_gym_reads_the_defaults(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-nuevo")
    response = client.get(URL, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json() == {
        "name": "dojo-nuevo",
        "slug": "dojo-nuevo",
        "timezone": "America/Santiago",
        "grace_days": 5,
        "reminder_every_days": 3,
        "channels": {"whatsapp": True},
        "bank_account": None,
    }


@pg
def test_a_change_is_read_back_and_stored(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "academia-sur")
    body = {
        "name": "Academia Sur",
        "timezone": "America/Punta_Arenas",
        "grace_days": 10,
        "reminder_every_days": 2,
        "channels": {"whatsapp": False},
        "bank_account": BANK,
    }
    response = client.patch(URL, json=body, headers=as_gym(gym))
    assert response.status_code == 200
    expected = {**body, "slug": "academia-sur", "bank_account": BANK_STORED}
    assert response.json() == expected
    assert client.get(URL, headers=as_gym(gym)).json() == expected

    row = stored(db, gym)
    assert (row["name"], row["timezone"]) == ("Academia Sur", "America/Punta_Arenas")
    assert row["settings"]["grace_days"] == 10


@pg
def test_a_change_leaves_other_settings_alone(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-grados")
    grading = {"scheme": "bjj", "belts": ["blanco", "azul"]}

    async def add_grading(conn: Any) -> None:
        await conn.execute(
            "UPDATE gym SET settings = settings || $2::jsonb WHERE id = $1",
            gym,
            json.dumps({"grading": grading, "bank_account": BANK_STORED}),
        )

    run(db.admin_url, add_grading)
    response = client.patch(URL, json={"grace_days": 0}, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json()["grace_days"] == 0
    # Fields not sent keep their values.
    assert response.json()["bank_account"] == BANK_STORED
    assert stored(db, gym)["settings"]["grading"] == grading


@pg
def test_clearing_the_bank_details_removes_them(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-sin-banco")
    client.patch(URL, json={"bank_account": BANK}, headers=as_gym(gym))
    response = client.patch(URL, json={"bank_account": None}, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json()["bank_account"] is None
    assert "bank_account" not in stored(db, gym)["settings"]


@pg
def test_an_empty_change_changes_nothing(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-quieto")
    before = stored(db, gym)
    response = client.patch(URL, json={}, headers=as_gym(gym))
    assert response.status_code == 200
    assert stored(db, gym) == before


@pg
def test_a_change_reaches_only_the_current_gym(client: TestClient, db: Database) -> None:
    sur, norte = seed_gym(db, "sur-aislado"), seed_gym(db, "norte-aislado")
    before = stored(db, norte)
    client.patch(URL, json={"name": "Sur", "bank_account": BANK}, headers=as_gym(sur))
    assert stored(db, norte) == before
    assert client.get(URL, headers=as_gym(norte)).json()["bank_account"] is None


@pg
def test_an_invalid_change_is_a_422(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-invalido")
    before = stored(db, gym)
    response = client.patch(URL, json={"timezone": "Mars/Olympus"}, headers=as_gym(gym))
    assert response.status_code == 422
    assert stored(db, gym) == before
