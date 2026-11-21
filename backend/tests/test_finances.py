"""Finanzas: money in and money out side by side, the month's result and the year (#316).

Entradas is Pagos' Cobrado for the same month, split into plans and cobros extra;
Salidas the month's expenses that count, by category; Resultado the difference. A void
leaves the month. Whoever sees expenses and not payments gets Salidas only, with no
income figure anywhere in the answer.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.main import create_app
from app.permissions import Permission
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, migrate, seed_gym, seeded_today, throwaway_database
from tests.test_expenses import category, holding, recorded, void
from tests.test_extra_charges import create, draft, line_of, ok
from tests.test_guardians import add_person, bill
from tests.test_ledger_book import dated_entry
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer

pg = pytest.mark.postgres

# A month long gone, which only what a test dates into it reaches.
PAST = date(2020, 3, 1)


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


def finances(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None, **query: Any) -> Any:
    response = client.get("/api/finances", params=query, headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def year(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None, **query: Any) -> Any:
    response = client.get("/api/finances/year", params=query, headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def cobrado(client: TestClient, gym: uuid.UUID, month: date | None = None) -> Any:
    params = {} if month is None else {"month": month.isoformat()}
    return ok(client.get("/api/ledger/book", params=params, headers=as_gym(gym)))["kpis"]


def paid_extra(client: TestClient, gym: uuid.UUID, amount: int) -> None:
    """A cobro extra for one new person, paid today in cash."""
    person = add_person(client, gym, f"Persona {uuid.uuid4().hex[:6]}")
    charge = create(client, gym, draft([person], amount_clp=amount))
    line = line_of(charge, person)["id"]
    ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/payments",
            json={"amount_clp": amount, "method": "cash"},
            headers=as_gym(gym),
        ),
        201,
    )


def has_income(found: Any) -> bool:
    """Whether any income figure is anywhere in an answer, keyed by name."""
    if isinstance(found, dict):
        return any(
            (key.startswith("income") or key.startswith("result")) and value is not None
            for key, value in found.items()
        ) or any(has_income(v) for v in found.values())
    if isinstance(found, list):
        return any(has_income(v) for v in found)
    return False


@pg
def test_entradas_is_pagos_cobrado_split_into_plans_and_cobros_extra(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # The seeded gym's own payments, plus a plan's payment and refund and a cobro extra.
    membership = bill(db, gym, add_person(client, gym, "Ana"), [])
    now = datetime.now(UTC)
    payment = dated_entry(db, gym, membership, "payment", 45_000, now)
    dated_entry(db, gym, membership, "refund", 5_000, now, refund_of=payment)
    paid_extra(client, gym, 25_000)

    kpis = cobrado(client, gym)
    found = finances(client, gym)

    income = found["income"]
    assert income["total_clp"] == kpis["collected_clp"]
    assert income["extra_clp"] == kpis["collected_extra_clp"] == 25_000
    assert income["plans_clp"] == kpis["collected_clp"] - 25_000
    # The same in the year's row for the month.
    [this_month] = [m for m in year(client, gym)["months"] if m["month"] == found["month"]]
    assert this_month["income_clp"] == kpis["collected_clp"]


@pg
def test_another_month_is_its_own_cobrado(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    membership = bill(db, gym, add_person(client, gym, "Bea"), [])
    dated_entry(db, gym, membership, "payment", 30_000, datetime(2020, 3, 10, 15, tzinfo=UTC))
    dated_entry(db, gym, membership, "payment", 15_000, datetime(2020, 4, 10, 15, tzinfo=UTC))

    found = finances(client, gym, month=PAST.isoformat())

    assert found["income"] == {"total_clp": 30_000, "plans_clp": 30_000, "extra_clp": 0}
    assert found["income"]["total_clp"] == cobrado(client, gym, PAST)["collected_clp"]


@pg
def test_salidas_is_the_months_expenses_by_category_and_resultado_the_difference(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    membership = bill(db, gym, add_person(client, gym, "Cata"), [])
    dated_entry(db, gym, membership, "payment", 1_000_000, datetime(2020, 3, 10, 15, tzinfo=UTC))
    luz = category(client, gym, "Luz")
    recorded(client, gym, spent_on="2020-03-05", amount_clp=650_000)
    recorded(client, gym, spent_on="2020-03-20", amount_clp=84_000, category_id=luz)
    recorded(client, gym, spent_on="2020-03-31", amount_clp=16_000, category_id=luz)
    # Another month's, which March leaves out.
    recorded(client, gym, spent_on="2020-04-01", amount_clp=99_000)

    found = finances(client, gym, month=PAST.isoformat())

    assert [(c["name"], c["amount_clp"], c["count"]) for c in found["categories"]] == [
        ("Arriendo", 650_000, 1),
        ("Luz", 100_000, 2),
    ]
    assert found["expenses_clp"] == 750_000
    assert found["result_clp"] == 1_000_000 - 750_000


@pg
def test_a_void_leaves_the_months_salidas(client: TestClient, gym: uuid.UUID) -> None:
    kept = recorded(client, gym, amount_clp=650_000)
    voided = recorded(
        client, gym, amount_clp=32_990, category_id=category(client, gym, "Internet y teléfono")
    )
    before = finances(client, gym)
    assert before["expenses_clp"] == 650_000 + 32_990

    assert void(client, gym, voided["id"]).status_code == 200
    after = finances(client, gym)

    assert after["expenses_clp"] == kept["amount_clp"]
    assert [c["name"] for c in after["categories"]] == ["Arriendo"]
    assert after["result_clp"] == before["result_clp"] + 32_990
    this_year = year(client, gym)
    assert this_year["expenses_clp"] == 650_000
    assert [c["amount_clp"] for c in this_year["categories"]] == [650_000]


@pg
def test_the_year_is_twelve_months_with_totals_and_each_categorys_months(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    membership = bill(db, gym, add_person(client, gym, "Dani"), [])
    dated_entry(db, gym, membership, "payment", 400_000, datetime(2020, 2, 10, 15, tzinfo=UTC))
    dated_entry(db, gym, membership, "payment", 500_000, datetime(2020, 3, 10, 15, tzinfo=UTC))
    luz = category(client, gym, "Luz")
    recorded(client, gym, spent_on="2020-02-05", amount_clp=650_000)
    recorded(client, gym, spent_on="2020-03-05", amount_clp=650_000)
    recorded(client, gym, spent_on="2020-03-20", amount_clp=84_000, category_id=luz)
    # The next year's, which 2020 leaves out.
    recorded(client, gym, spent_on="2021-01-05", amount_clp=700_000)

    found = year(client, gym, year=2020)

    assert [m["month"] for m in found["months"]] == [
        add_months(date(2020, 1, 1), i).isoformat() for i in range(12)
    ]
    by_month = {m["month"]: m for m in found["months"]}
    assert by_month["2020-01-01"] == {
        "month": "2020-01-01",
        "income_clp": 0,
        "expenses_clp": 0,
        "result_clp": 0,
    }
    assert (by_month["2020-02-01"]["income_clp"], by_month["2020-02-01"]["result_clp"]) == (
        400_000,
        -250_000,
    )
    assert by_month["2020-03-01"]["expenses_clp"] == 734_000
    assert (found["income_clp"], found["expenses_clp"]) == (900_000, 1_384_000)
    assert found["result_clp"] == 900_000 - 1_384_000

    [rent, power] = found["categories"]
    assert (rent["name"], rent["amount_clp"]) == ("Arriendo", 1_300_000)
    assert rent["months"] == [0, 650_000, 650_000] + [0] * 9
    assert (power["name"], power["months"][2]) == ("Luz", 84_000)


@pg
def test_without_money_read_no_income_figure_is_in_the_answer(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    membership = bill(db, gym, add_person(client, gym, "Eva"), [])
    dated_entry(db, gym, membership, "payment", 45_000, datetime.now(UTC))
    recorded(client, gym, amount_clp=650_000)
    secretaria = holding(db, gym, Permission.EXPENSES_READ)

    month = finances(client, gym, secretaria)
    whole_year = year(client, gym, secretaria)

    assert month["income"] is None and month["result_clp"] is None
    assert month["expenses_clp"] == 650_000
    assert whole_year["income_clp"] is None and whole_year["result_clp"] is None
    assert whole_year["expenses_clp"] == 650_000
    assert not has_income(month) and not has_income(whole_year)
    # The titular, who holds both, sees them.
    assert has_income(finances(client, gym))


@pg
def test_it_needs_expenses_read(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    administrador = add_staff(db, gym, "admin")
    cobranza = holding(db, gym, Permission.MONEY_READ)
    for person in (administrador, cobranza):
        for path in ("/api/finances", "/api/finances/year"):
            assert client.get(path, headers=as_gym(gym, person)).status_code == 403
    assert (
        finances(client, gym, holding(db, gym, Permission.MONEY_READ, Permission.EXPENSES_READ))[
            "income"
        ]
        is not None
    )


@pg
def test_a_later_month_or_year_or_a_day_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    current = date.fromisoformat(finances(client, gym)["current_month"])
    assert current == seeded_today().replace(day=1)
    later = client.get(
        "/api/finances", params={"month": add_months(current, 1).isoformat()}, headers=as_gym(gym)
    )
    assert later.status_code == 422 and later.json()["detail"]["code"] == "future"
    day = client.get(
        "/api/finances", params={"month": current.replace(day=2).isoformat()}, headers=as_gym(gym)
    )
    assert day.status_code == 422 and day.json()["detail"]["code"] == "not_a_month"
    next_year = client.get(
        "/api/finances/year", params={"year": current.year + 1}, headers=as_gym(gym)
    )
    assert next_year.status_code == 422


@pg
def test_another_gyms_money_is_not_in_it(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, unique_slug("other"))
    recorded(client, other, amount_clp=123_000)
    membership = bill(db, other, add_person(client, other, "Fran"), [])
    dated_entry(db, other, membership, "payment", 77_000, datetime.now(UTC))
    before = cobrado(client, gym)["collected_clp"]

    found = finances(client, gym)

    assert found["expenses_clp"] == 0 and found["categories"] == []
    assert found["income"]["total_clp"] == before
