"""Gastos fijos: rent and bills as monthly templates, recorded in one tap, never
automatically (#315).

A template is fixed (recorded at its amount in one tap) or estimated (recorded through
the form at the bill's figure). Gastos lists, for the month shown, the active ones with
no expense from them that counts and not skipped. Recording or skipping one takes it
off that month's card, and the next month has it again. No job, read or trigger
records an expense: every one is a person's request.
"""

import re
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.api.expense_recurring import due_on
from app.domain.dates import add_months
from app.jobs import daily
from app.jobs.runner import run_due
from app.main import create_app
from app.permissions import Permission
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    DEFAULT_TIMEZONE,
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_expenses import category, holding, void
from tests.test_plans import add_staff

pg = pytest.mark.postgres

APP = Path(__file__).parents[1] / "app"


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
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("gym"))


def this_month() -> date:
    return seeded_today().replace(day=1)


def template(client: TestClient, gym: uuid.UUID, **fields: Any) -> dict[str, Any]:
    """A gasto fijo through the API: the rent, fixed, on the 5th, unless told otherwise."""
    body = {
        "category_id": category(client, gym, "Arriendo"),
        "payee": "Inmobiliaria Los Robles",
        "method": "transfer",
        "amount_clp": 650_000,
        "amount_kind": "fixed",
        "day_of_month": 5,
        **fields,
    }
    response = client.post("/api/expenses/recurring", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def template_since(
    db: Database, gym: uuid.UUID, since: date, name: str = "Internet y teléfono", day: int = 10
) -> str:
    """A fixed template made on `since`, as the owner writes one, so earlier months than
    this one have it."""
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO expense_recurring (gym_id, category_id, payee, amount_clp, amount_kind,"
            " day_of_month, created_by, created_at)"
            " SELECT $1, id, 'Movistar', 32990, 'fixed', $2, $3, $4 FROM expense_category"
            " WHERE gym_id = $1 AND name = $5 RETURNING id",
            gym,
            day,
            seeded_owner(gym),
            # Midday in the gym's timezone: a bare date is midnight UTC, which in
            # Santiago is still the day, and maybe the month, before.
            datetime.combine(since, time(12), tzinfo=ZoneInfo(DEFAULT_TIMEZONE)),
            name,
        ),
    )
    return str(rows[0]["id"])


def card(
    client: TestClient, gym: uuid.UUID, month: date | None = None, by: uuid.UUID | None = None
) -> Any:
    params = {} if month is None else {"month": month.isoformat()}
    response = client.get("/api/expenses/recurring/month", params=params, headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    return response.json()


def due_ids(client: TestClient, gym: uuid.UUID, month: date | None = None) -> list[str]:
    return [t["id"] for t in card(client, gym, month)["due"]]


def record(
    client: TestClient,
    gym: uuid.UUID,
    *ids: str,
    month: date | None = None,
    by: uuid.UUID | None = None,
) -> Any:
    return client.post(
        "/api/expenses/recurring/record",
        json={"month": (month or this_month()).isoformat(), "ids": list(ids)},
        headers=as_gym(gym, by),
    )


def skip(client: TestClient, gym: uuid.UUID, recurring_id: str, month: date) -> Any:
    return client.post(
        f"/api/expenses/recurring/{recurring_id}/skip",
        json={"month": month.isoformat()},
        headers=as_gym(gym),
    )


def expenses_in(db: Database, gym: uuid.UUID) -> int:
    rows = run(db.owner_url, in_gym(gym, "SELECT count(*) AS n FROM expense"))
    return int(rows[0]["n"])


def test_a_template_is_recorded_on_its_day_or_today_if_earlier() -> None:
    november = date(2026, 11, 1)
    assert due_on(november, 5, date(2026, 11, 20)) == date(2026, 11, 5)
    assert due_on(november, 25, date(2026, 11, 20)) == date(2026, 11, 20)
    # A day the month does not have is its last.
    assert due_on(date(2026, 2, 1), 31, date(2026, 11, 20)) == date(2026, 2, 28)
    assert due_on(date(2026, 9, 1), 31, date(2026, 11, 20)) == date(2026, 9, 30)


@pg
def test_templates_are_added_edited_and_paused(client: TestClient, gym: uuid.UUID) -> None:
    rent = template(client, gym)
    power = template(
        client,
        gym,
        category_id=category(client, gym, "Luz"),
        payee="Enel",
        amount_clp=84_000,
        amount_kind="estimated",
        day_of_month=20,
    )
    assert (rent["category_name"], rent["active"], rent["category_archived"]) == (
        "Arriendo",
        True,
        False,
    )
    listed = client.get("/api/expenses/recurring", headers=as_gym(gym)).json()
    assert [t["id"] for t in listed] == [rent["id"], power["id"]]

    edited = client.patch(
        f"/api/expenses/recurring/{rent['id']}",
        json={"amount_clp": 680_000, "payee": None},
        headers=as_gym(gym),
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["amount_clp"], edited.json()["payee"]) == (680_000, None)

    # Paused, it is last of the list and off every card; resumed, it is back.
    paused = client.patch(
        f"/api/expenses/recurring/{rent['id']}", json={"active": False}, headers=as_gym(gym)
    )
    assert paused.json()["active"] is False
    listed = client.get("/api/expenses/recurring", headers=as_gym(gym)).json()
    assert [t["id"] for t in listed] == [power["id"], rent["id"]]
    assert due_ids(client, gym) == [power["id"]]
    assert record(client, gym, rent["id"]).json()["detail"]["code"] == "paused"
    client.patch(
        f"/api/expenses/recurring/{rent['id']}", json={"active": True}, headers=as_gym(gym)
    )
    assert due_ids(client, gym) == [rent["id"], power["id"]]


@pg
@pytest.mark.parametrize(
    "fields",
    [
        {"day_of_month": 0},
        {"day_of_month": 32},
        {"amount_clp": 0},
        {"amount_kind": "monthly"},
        {"category_id": str(uuid.uuid4())},
    ],
)
def test_a_bad_template_is_refused(
    client: TestClient, gym: uuid.UUID, fields: dict[str, Any]
) -> None:
    body = {
        "category_id": category(client, gym, "Arriendo"),
        "amount_clp": 650_000,
        "amount_kind": "fixed",
        "day_of_month": 5,
        **fields,
    }
    response = client.post("/api/expenses/recurring", json=body, headers=as_gym(gym))
    assert response.status_code == 422, response.text
    # A template always has its amount, kind, day and category.
    rent = template(client, gym)
    for field in ("amount_clp", "amount_kind", "day_of_month", "category_id", "active"):
        response = client.patch(
            f"/api/expenses/recurring/{rent['id']}", json={field: None}, headers=as_gym(gym)
        )
        assert response.status_code == 422, field


@pg
def test_a_fixed_one_records_in_one_tap_at_its_amount_and_leaves_the_card(
    client: TestClient, gym: uuid.UUID
) -> None:
    rent = template(client, gym)
    assert due_ids(client, gym) == [rent["id"]]
    today = seeded_today()
    [due] = card(client, gym)["due"]
    assert due["due_on"] == due_on(this_month(), 5, today).isoformat()

    response = record(client, gym, rent["id"])
    assert response.status_code == 201, response.text
    [expense] = response.json()
    assert (
        expense["amount_clp"],
        expense["category_name"],
        expense["payee"],
        expense["method"],
        expense["recurring_id"],
        expense["spent_on"],
    ) == (650_000, "Arriendo", "Inmobiliaria Los Robles", "transfer", rent["id"], due["due_on"])
    assert expense["created_by_name"].startswith("owner of")
    assert due_ids(client, gym) == []

    # A second tap, or a stale page, records nothing more.
    again = record(client, gym, rent["id"])
    assert (again.status_code, again.json()) == (201, [])
    listed = client.get("/api/expenses", headers=as_gym(gym)).json()
    assert [e["id"] for e in listed["items"]] == [expense["id"]]


@pg
def test_registrar_los_fijos_records_every_fixed_one_and_no_estimated(
    client: TestClient, gym: uuid.UUID
) -> None:
    rent = template(client, gym)
    internet = template(
        client,
        gym,
        category_id=category(client, gym, "Internet y teléfono"),
        payee="Movistar",
        amount_clp=32_990,
        day_of_month=1,
    )
    power = template(
        client,
        gym,
        category_id=category(client, gym, "Luz"),
        amount_clp=84_000,
        amount_kind="estimated",
        day_of_month=20,
    )
    assert record(client, gym, rent["id"], power["id"]).json()["detail"]["code"] == "estimated"
    # Refused whole: the rent was not recorded either.
    assert len(due_ids(client, gym)) == 3

    response = record(client, gym, rent["id"], internet["id"])
    assert response.status_code == 201, response.text
    assert sorted(e["amount_clp"] for e in response.json()) == [32_990, 650_000]
    assert due_ids(client, gym) == [power["id"]]


@pg
def test_an_estimated_one_is_recorded_through_the_form_at_the_bills_figure(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    power = template(
        client,
        gym,
        category_id=category(client, gym, "Luz"),
        payee="Enel",
        amount_clp=84_000,
        amount_kind="estimated",
        day_of_month=1,
    )
    body = {
        "spent_on": seeded_today().isoformat(),
        "amount_clp": 91_240,
        "category_id": power["category_id"],
        "payee": "Enel",
        "recurring_id": power["id"],
    }
    response = client.post("/api/expenses", json=body, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    assert (response.json()["amount_clp"], response.json()["recurring_id"]) == (
        91_240,
        power["id"],
    )
    assert due_ids(client, gym) == []

    # One that counts per template and month, at the database: a second is a 409.
    second = client.post("/api/expenses", json=body, headers=as_gym(gym))
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "already_recorded"
    # Another gym's template is refused.
    foreign = template(client, seed_gym(db, unique_slug("other")))
    elsewhere = client.post(
        "/api/expenses", json={**body, "recurring_id": foreign["id"]}, headers=as_gym(gym)
    )
    assert elsewhere.json()["detail"]["code"] == "no_recurring"


@pg
def test_a_template_recorded_or_skipped_this_month_leaves_the_card_and_is_back_next_month(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    last_month = add_months(this_month(), -1)
    two_back = add_months(this_month(), -2)
    internet = template_since(db, gym, add_months(this_month(), -6))
    rent = template_since(db, gym, add_months(this_month(), -6), name="Arriendo", day=5)

    # Last month: the internet recorded, the rent skipped. Both leave that month's card.
    assert record(client, gym, internet, month=last_month).status_code == 201
    assert skip(client, gym, rent, last_month).status_code == 204
    assert skip(client, gym, rent, last_month).status_code == 204
    shown = card(client, gym, last_month)
    assert shown["due"] == []
    assert [t["id"] for t in shown["skipped"]] == [rent]

    # This month, and the one before last, have both again.
    assert sorted(due_ids(client, gym)) == sorted([internet, rent])
    assert sorted(due_ids(client, gym, two_back)) == sorted([internet, rent])

    # A skip taken back puts it on the card again.
    undone = client.delete(
        f"/api/expenses/recurring/{rent}/skip/{last_month.isoformat()}", headers=as_gym(gym)
    )
    assert undone.status_code == 204
    assert due_ids(client, gym, last_month) == [rent]

    # Recorded last month, it is dated its day of that month.
    expenses = client.get(
        "/api/expenses", params={"month": last_month.isoformat()}, headers=as_gym(gym)
    ).json()["items"]
    assert [e["spent_on"] for e in expenses] == [last_month.replace(day=10).isoformat()]


@pg
def test_a_month_before_the_template_existed_does_not_list_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    template_since(db, gym, add_months(this_month(), -1))
    assert len(due_ids(client, gym, add_months(this_month(), -1))) == 1
    assert due_ids(client, gym, add_months(this_month(), -2)) == []


@pg
def test_a_voided_expense_from_a_template_puts_it_back_on_the_card(
    client: TestClient, gym: uuid.UUID
) -> None:
    rent = template(client, gym)
    [expense] = record(client, gym, rent["id"]).json()
    assert due_ids(client, gym) == []
    assert void(client, gym, expense["id"]).status_code == 200
    assert due_ids(client, gym) == [rent["id"]]
    # And it records again: the voided one does not count.
    assert len(record(client, gym, rent["id"]).json()) == 1


@pg
def test_moving_an_expense_into_a_month_its_template_is_recorded_in_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    last_month = add_months(this_month(), -1)
    internet = template_since(db, gym, add_months(this_month(), -3))
    [earlier] = record(client, gym, internet, month=last_month).json()
    record(client, gym, internet)
    moved = client.patch(
        f"/api/expenses/{earlier['id']}",
        json={"spent_on": seeded_today().isoformat()},
        headers=as_gym(gym),
    )
    assert moved.status_code == 409
    assert moved.json()["detail"]["code"] == "already_recorded"


@pg
def test_an_archived_category_keeps_its_template_off_one_tap(
    client: TestClient, gym: uuid.UUID
) -> None:
    rent = template(client, gym)
    client.post(f"/api/expenses/categories/{rent['category_id']}/archive", headers=as_gym(gym))
    [due] = card(client, gym)["due"]
    assert due["category_archived"] is True
    response = record(client, gym, rent["id"])
    assert response.json()["detail"]["code"] == "category_archived"


@pg
def test_a_later_month_or_not_a_month_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    rent = template(client, gym)
    later = add_months(this_month(), 1)
    for month in (later, this_month() + timedelta(days=1)):
        response = client.get(
            "/api/expenses/recurring/month",
            params={"month": month.isoformat()},
            headers=as_gym(gym),
        )
        assert response.status_code == 422
        assert record(client, gym, rent["id"], month=month).status_code == 422
        assert skip(client, gym, rent["id"], month).status_code == 422


@pg
def test_no_job_or_read_records_an_expense(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    template_since(db, gym, add_months(this_month(), -6))
    template(client, gym)
    template(client, gym, category_id=category(client, gym, "Luz"), amount_kind="estimated")
    reader = holding(db, gym, Permission.EXPENSES_READ)

    for back in range(6):
        card(client, gym, add_months(this_month(), -back))
    card(client, gym, by=reader)
    client.get("/api/expenses/recurring", headers=as_gym(gym))
    client.get("/api/expenses", headers=as_gym(gym))

    # The nightly jobs, over a month of days, including every template's day.
    async def nights(conn: asyncpg.Connection) -> None:
        start = add_months(this_month(), -1)
        for n in range(40):
            await run_due(conn, daily.JOBS, start + timedelta(days=n))

    run(db.owner_url, nights)
    assert expenses_in(db, gym) == 0


def test_only_a_persons_request_inserts_an_expense() -> None:
    """The code that writes an expense: the two API modules, a person's requests each,
    and the seed's demo data. No job, trigger or other module does."""
    writes = re.compile(r"INSERT INTO expense\b(?!_)|\"expense\"|'expense'")
    found = sorted(
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if writes.search(path.read_text(encoding="utf-8"))
    )
    assert found == ["api/expense_recurring.py", "api/expenses.py", "seed/build.py"]
    assert not any("expense" in p.read_text(encoding="utf-8") for p in (APP / "jobs").rglob("*.py"))
    migrations = Path(__file__).parents[1] / "alembic" / "versions"
    triggers = [
        p.name
        for p in migrations.glob("*.py")
        if re.search(r"INSERT INTO expense\b(?!_)", p.read_text(encoding="utf-8"))
    ]
    assert triggers == []


@pg
def test_the_same_permissions_as_expenses(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    rent = template(client, gym)
    reader = holding(db, gym, Permission.EXPENSES_READ)
    writer = holding(db, gym, Permission.EXPENSES_WRITE, Permission.EXPENSES_READ)
    admin = add_staff(db, gym, "admin")
    coach = add_staff(db, gym, "coach")
    month = this_month().isoformat()
    reads = [
        ("GET", "/api/expenses/recurring", None),
        ("GET", "/api/expenses/recurring/month", None),
    ]
    writes = [
        ("POST", "/api/expenses/recurring", {}),
        ("PATCH", f"/api/expenses/recurring/{rent['id']}", {"active": False}),
        ("POST", "/api/expenses/recurring/record", {"month": month, "ids": [rent["id"]]}),
        ("POST", f"/api/expenses/recurring/{rent['id']}/skip", {"month": month}),
        ("DELETE", f"/api/expenses/recurring/{rent['id']}/skip/{month}", None),
    ]

    def statuses(person: uuid.UUID, ops: list[Any]) -> set[int]:
        return {
            client.request(method, path, json=body, headers=as_gym(gym, person)).status_code
            for method, path, body in ops
        }

    for person in (admin, coach):
        assert statuses(person, reads + writes) == {403}
    assert statuses(reader, reads) == {200}
    assert statuses(reader, writes) == {403}
    assert record(client, gym, rent["id"], by=writer).status_code == 201

    # At the database, as the app role: an Administrador reads no template or skip.
    skip(client, gym, rent["id"], add_months(this_month(), -1))
    for table in ("expense_recurring", "expense_skip"):
        assert run(db.api_url, in_gym(gym, f"SELECT 1 FROM {table}", person=admin)) == []


@pg
def test_another_gyms_template_is_not_found(client: TestClient, db: Database) -> None:
    mine, theirs = seed_gym(db, unique_slug("a")), seed_gym(db, unique_slug("b"))
    rent = template(client, theirs)
    assert due_ids(client, mine) == []
    assert record(client, mine, rent["id"]).status_code == 422
    assert skip(client, mine, rent["id"], this_month()).status_code == 404
    response = client.patch(
        f"/api/expenses/recurring/{rent['id']}", json={"active": False}, headers=as_gym(mine)
    )
    assert response.status_code == 404
