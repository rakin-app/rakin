"""Gastos recuperados con cobros extra: an expense names the cobro that pays it back (#318).

A trip's bus and hotel name the cobro extra the group pays them back through. The
cobro's detail sets what it cost beside what it collected, to whoever holds both
`money_read` and `expenses_read`, and Finanzas says, under Resultado, how much of the
month went through such cobros. Both stay gross: linking, unlinking and voiding change
no line, balance or reader of money.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.permissions import Permission
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, seed_gym, throwaway_database
from tests.test_expenses import change, holding, log, month, record, recorded, void
from tests.test_extra_charges import create, draft, get, line_of, ok
from tests.test_finances import finances
from tests.test_guardians import add_person
from tests.test_history_payments import readers
from tests.test_proofs import RecordingMailer

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=RecordingMailer())
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("gym"))


def trip(client: TestClient, gym: uuid.UUID) -> tuple[dict[str, Any], list[str]]:
    """A trip to a final for three people, 60.000 each, one of them paid in full."""
    people = [add_person(client, gym, f"Viajera {uuid.uuid4().hex[:6]}") for _ in range(3)]
    charge = create(
        client,
        gym,
        draft(people, title="Viaje al nacional", category="gasto_compartido", amount_clp=60_000),
    )
    line = line_of(charge, people[0])["id"]
    ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/payments",
            json={"amount_clp": 60_000, "method": "transfer"},
            headers=as_gym(gym),
        ),
        201,
    )
    return get(client, gym, charge["id"]), people


def cobro(client: TestClient, gym: uuid.UUID, charge_id: str, by: uuid.UUID | None = None) -> Any:
    return ok(client.get(f"/api/extra-charges/{charge_id}", headers=as_gym(gym, by)))


@pg
def test_the_cobro_shows_its_expenses_beside_what_it_collected(
    client: TestClient, gym: uuid.UUID
) -> None:
    charge, _ = trip(client, gym)
    assert cobro(client, gym, charge["id"])["expenses"] == {
        "count": 0,
        "expenses_clp": 0,
        "collected_clp": 60_000,
        "difference_clp": 60_000,
    }

    recorded(client, gym, amount_clp=120_000, payee="Buses Sur", extra_charge_id=charge["id"])
    recorded(client, gym, amount_clp=50_000, payee="Hostal", extra_charge_id=charge["id"])
    void(client, gym, recorded(client, gym, amount_clp=9, extra_charge_id=charge["id"])["id"])
    recorded(client, gym, amount_clp=650_000)  # rent: names no cobro

    assert cobro(client, gym, charge["id"])["expenses"] == {
        "count": 2,
        "expenses_clp": 170_000,
        "collected_clp": 60_000,
        "difference_clp": -110_000,
    }


@pg
def test_the_cobros_figures_need_expenses_read(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    charge, _ = trip(client, gym)
    recorded(client, gym, amount_clp=120_000, extra_charge_id=charge["id"])
    cobranza = holding(db, gym, Permission.MONEY_READ)
    tesorera = holding(db, gym, Permission.MONEY_READ, Permission.EXPENSES_READ)

    found = cobro(client, gym, charge["id"], cobranza)
    assert found["expenses"] is None
    assert found["collected_clp"] == 60_000
    assert cobro(client, gym, charge["id"], tesorera)["expenses"]["expenses_clp"] == 120_000


@pg
def test_linking_changes_no_line_or_balance(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    charge, people = trip(client, gym)

    def billing() -> Any:
        found = cobro(client, gym, charge["id"])
        found.pop("expenses")
        lines = [
            ok(client.get(f"/api/people/{p}/extra-lines", headers=as_gym(gym))) for p in people
        ]
        return found, lines, readers(client, db, gym)

    before = billing()
    bus = recorded(client, gym, amount_clp=120_000, extra_charge_id=charge["id"])
    hotel = recorded(client, gym, amount_clp=50_000)
    ok(change(client, gym, hotel["id"], extra_charge_id=charge["id"]))
    ok(change(client, gym, bus["id"], extra_charge_id=None))
    void(client, gym, hotel["id"])

    assert billing() == before


@pg
def test_an_expense_names_its_cobro_and_an_edit_logs_the_link(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    charge, _ = trip(client, gym)
    bus = recorded(client, gym, amount_clp=120_000, extra_charge_id=charge["id"])
    assert (bus["extra_charge_id"], bus["extra_charge_title"]) == (
        charge["id"],
        "Viaje al nacional",
    )

    ok(change(client, gym, bus["id"], extra_charge_id=None))
    [listed] = [e for e in ok(month(client, gym))["items"] if e["id"] == bus["id"]]
    assert listed["extra_charge_id"] is None and listed["extra_charge_title"] is None

    [edit] = [e for e in log(db, gym) if e["action"] == "expense_changed"]
    assert edit["detail"]["before"] == {"extra_charge_id": charge["id"]}
    assert edit["detail"]["after"] == {"extra_charge_id": None}


@pg
def test_a_cobro_the_person_cannot_read_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    charge, _ = trip(client, gym)
    other_gym = seed_gym(db, unique_slug("otro"))
    elsewhere, _ = trip(client, other_gym)

    for missing in (elsewhere["id"], str(uuid.uuid4())):
        refused = record(client, gym, extra_charge_id=missing)
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "no_extra_charge"
        rent = recorded(client, gym)
        assert change(client, gym, rent["id"], extra_charge_id=missing).status_code == 422

    # Recording expenses is not reading cobros: naming one takes `money_read`.
    tesorera = holding(db, gym, Permission.EXPENSES_READ, Permission.EXPENSES_WRITE)
    assert record(client, gym, tesorera, extra_charge_id=charge["id"]).status_code == 422
    # And one recorded by who reads both shows them that it names a cobro, not which.
    bus = recorded(client, gym, amount_clp=120_000, extra_charge_id=charge["id"])
    [listed] = [e for e in ok(month(client, gym, tesorera))["items"] if e["id"] == bus["id"]]
    assert listed["extra_charge_id"] == charge["id"]
    assert listed["extra_charge_title"] is None


@pg
def test_finanzas_says_what_of_the_month_was_recovered(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    assert finances(client, gym)["recovered"] is None
    charge, _ = trip(client, gym)
    # Collected on a cobro no expense names yet: nothing recovered.
    assert finances(client, gym)["recovered"] is None

    recorded(client, gym, amount_clp=120_000, extra_charge_id=charge["id"])
    void(client, gym, recorded(client, gym, amount_clp=9, extra_charge_id=charge["id"])["id"])
    recorded(client, gym, amount_clp=650_000)
    found = finances(client, gym)
    assert found["recovered"] == {"paid_clp": 120_000, "collected_clp": 60_000}
    # Both stay gross: Salidas holds the bus and the rent, Entradas the trip's payment.
    assert found["expenses_clp"] == 770_000
    assert found["income"]["extra_clp"] >= 60_000

    secretaria = holding(db, gym, Permission.EXPENSES_READ)
    assert finances(client, gym, secretaria)["recovered"] is None
