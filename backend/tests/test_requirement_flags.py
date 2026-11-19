"""Requisitos where people are marked (#350): the roster's and Entrada's warning, and
Hoy's list of who is short on one. The states themselves are
`tests/domain/test_requirements.py`; the ficha's records, `tests/test_requirements.py`.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_attendance import (
    changed,
    class_type,
    created,
    join,
    plan,
    program,
    roster,
    row,
    session_of,
)
from tests.test_check_in import open_access, search
from tests.test_guardians import add_person
from tests.test_plans import MONTHLY, add_staff

pytestmark = pytest.mark.postgres

DUE = "/api/requirements/due"


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
    return seed_gym(db, unique_slug("gym"))


def requirement(client: TestClient, gym: uuid.UUID, **body: Any) -> str:
    return str(created(client.post("/api/requirements", json=body, headers=as_gym(gym)))["id"])


def record(client: TestClient, gym: uuid.UUID, person: str, req: str, done_on: date) -> None:
    response = client.post(
        f"/api/people/{person}/requirements/{req}",
        json={"done_on": done_on.isoformat()},
        headers=as_gym(gym),
    )
    assert response.status_code == 200, response.text


def flags(found: Any) -> list[tuple[str, str]]:
    return [(r["name"], r["state"]) for r in found["unmet_requirements"]]


def due(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> Any:
    """Hoy's list, without the owner `seed_gym` gives a membership."""
    response = client.get(DUE, headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return [d for d in response.json() if d["person_id"] != str(seeded_owner(gym))]


def test_an_expired_requirement_is_marked_on_the_roster_and_they_can_still_be_marked(
    client: TestClient, gym: uuid.UUID
) -> None:
    today = seeded_today()
    waiver = requirement(client, gym, name="Declaración de riesgos")
    medical = requirement(client, gym, name="Certificado médico", valid_months=12)
    monthly = plan(client, gym, MONTHLY)
    paula = add_person(client, gym, "Paula Contreras")
    tomas = add_person(client, gym, "Tomás Pérez")
    paula_m = join(client, gym, paula, monthly)
    join(client, gym, tomas, monthly)
    record(client, gym, paula, waiver, today)
    # A day past its 12 months.
    lapsed_on = add_months(today, -12) - timedelta(days=1)
    record(client, gym, paula, medical, lapsed_on)
    record(client, gym, tomas, waiver, today)
    record(client, gym, tomas, medical, today)

    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    listed = roster(client, gym, session)
    assert flags(row(listed, "Paula Contreras")) == [("Certificado médico", "expired")]
    [expired] = row(listed, "Paula Contreras")["unmet_requirements"]
    assert expired["expires_on"] == add_months(lapsed_on, 12).isoformat()
    assert flags(row(listed, "Tomás Pérez")) == []

    marked = changed(client, gym, session, mark=[paula_m])
    assert row(marked, "Paula Contreras")["present"] is True
    assert flags(row(marked, "Paula Contreras")) == [("Certificado médico", "expired")]


def test_a_requirement_never_done_is_pendiente_and_one_expiring_soon_is_not_marked(
    client: TestClient, gym: uuid.UUID
) -> None:
    today = seeded_today()
    requirement(client, gym, name="Declaración de riesgos")
    medical = requirement(client, gym, name="Certificado médico", valid_months=12)
    paula = add_person(client, gym, "Paula Contreras")
    join(client, gym, paula, plan(client, gym, MONTHLY))
    # In force for 10 more days: vence pronto, which Hoy shows and the roster does not.
    record(client, gym, paula, medical, add_months(today, -12) + timedelta(days=10))

    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    assert flags(row(roster(client, gym, session), "Paula Contreras")) == [
        ("Declaración de riesgos", "pending")
    ]


def test_a_deactivated_requirement_is_not_marked(client: TestClient, gym: uuid.UUID) -> None:
    waiver = requirement(client, gym, name="Declaración de riesgos")
    join(client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, MONTHLY))
    response = client.patch(
        f"/api/requirements/{waiver}", json={"active": False}, headers=as_gym(gym)
    )
    assert response.status_code == 200, response.text
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    assert flags(row(roster(client, gym, session), "Paula Contreras")) == []


def test_a_coach_not_in_visible_to_sees_no_mark_for_a_sensitive_requirement(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    admin = add_staff(db, gym, "admin")
    requirement(client, gym, name="Inducción")
    requirement(client, gym, name="Certificado médico", valid_months=12, sensitive=True)
    requirement(client, gym, name="Ficha de salud", sensitive=True, visible_to="admin")
    paula = add_person(client, gym, "Paula Contreras")
    join(client, gym, paula, plan(client, gym, MONTHLY))
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))

    everything = [
        ("Inducción", "pending"),
        ("Certificado médico", "pending"),
        ("Ficha de salud", "pending"),
    ]
    assert flags(row(roster(client, gym, session), "Paula Contreras")) == everything
    assert flags(row(roster(client, gym, session, admin), "Paula Contreras")) == [
        ("Inducción", "pending"),
        ("Ficha de salud", "pending"),
    ]
    assert flags(row(roster(client, gym, session, coach), "Paula Contreras")) == [
        ("Inducción", "pending")
    ]
    # Nor on Hoy.
    assert [[r["name"] for r in d["requirements"]] for d in due(client, gym, coach)] == [
        ["Inducción"]
    ]


def test_entrada_names_what_someone_lacks_before_the_tap(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    requirement(client, gym, name="Inducción")
    requirement(client, gym, name="Certificado médico", sensitive=True)
    door = open_access(client, gym, program(client, gym, "Adultos"))["id"]
    join(client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, MONTHLY))

    [paula] = search(client, gym, door, "paula")
    assert flags(paula) == [("Inducción", "pending"), ("Certificado médico", "pending")]
    response = client.get(
        f"/api/check-in/{door}/search", params={"q": "paula"}, headers=as_gym(gym, coach)
    )
    assert response.status_code == 200, response.text
    assert flags(response.json()[0]) == [("Inducción", "pending")]


def test_hoy_lists_the_unmet_first_then_the_expiring_and_leaves_out_who_has_no_live_plan(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    waiver = requirement(client, gym, name="Declaración de riesgos")
    medical = requirement(client, gym, name="Certificado médico", valid_months=12)
    monthly = plan(client, gym, MONTHLY)

    def member(name: str, waived: bool = True, medical_on: date | None = today) -> str:
        person = add_person(client, gym, name)
        if waived:
            record(client, gym, person, waiver, today)
        if medical_on is not None:
            record(client, gym, person, medical, medical_on)
        return person

    # Expiring in 20 days, and in 5.
    ana = member("Ana Soto", medical_on=add_months(today, -12) + timedelta(days=20))
    bea = member("Bea Rojas", medical_on=add_months(today, -12) + timedelta(days=5))
    # No waiver; and an expired certificate.
    carla = member("Carla Díaz", waived=False)
    diego = member("Diego Vera", medical_on=add_months(today, -12) - timedelta(days=1))
    # All al día.
    elena = member("Elena Muñoz")
    # Short on both, but with no live membership: none at all, and a lapsed one.
    member("Felipe Ríos", waived=False, medical_on=None)
    gonzalo = member("Gonzalo Paz", waived=False, medical_on=None)
    for person in (ana, bea, carla, diego, elena):
        join(client, gym, person, monthly)
    lapsed = join(client, gym, gonzalo, monthly)
    run(
        db.owner_url,
        in_gym(gym, "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(lapsed)),
    )

    listed = due(client, gym)
    assert [(d["name"], [(r["name"], r["state"]) for r in d["requirements"]]) for d in listed] == [
        ("Carla Díaz", [("Declaración de riesgos", "pending")]),
        ("Diego Vera", [("Certificado médico", "expired")]),
        ("Bea Rojas", [("Certificado médico", "expiring")]),
        ("Ana Soto", [("Certificado médico", "expiring")]),
    ]
    assert listed[2]["person_id"] == bea
    assert listed[2]["requirements"][0]["expires_on"] == (
        add_months(add_months(today, -12) + timedelta(days=5), 12).isoformat()
    )


def test_a_gym_that_asks_for_nothing_has_nothing_due(client: TestClient, gym: uuid.UUID) -> None:
    join(client, gym, add_person(client, gym, "Paula Contreras"), plan(client, gym, MONTHLY))
    assert due(client, gym) == []
    session = session_of(client, gym, class_type(client, gym, program(client, gym, "Adultos")))
    assert flags(row(roster(client, gym, session), "Paula Contreras")) == []


def test_a_member_may_not_read_whats_due(client: TestClient, gym: uuid.UUID) -> None:
    paula = add_person(client, gym, "Paula Contreras")
    assert client.get(DUE, headers=as_gym(gym, uuid.UUID(paula))).status_code == 403
