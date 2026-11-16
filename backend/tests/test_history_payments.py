"""Historial de pagos: what a student paid before Rakin, never read by billing (#295).

`history_payment` (0053) holds them, beside the ledger and never in it. The ficha's
Historial card reads them by year; "Pagos anteriores" writes a form's months in one
transaction, each before the person's first plan (`covers_plan`). Eliminar deletes one
with a reason, kept whole in a `history_removed` row. Owner and admin only, at the API
and at the database. No job, view, KPI, Hoy list or export reads them, and deleting the
person deletes them with the rest.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import add_months
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_former_students import added
from tests.test_member_roll import count, enrolled, forget, memberships, plan
from tests.test_overdue_emails import night
from tests.test_plans import add_staff
from tests.test_statements_job import Outbox

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
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def month(year: int, number: int, day: int = 5) -> dict[str, Any]:
    """The form's line for a month: paid on its `day`, for the month."""
    return {
        "paid_on": date(year, number, day).isoformat(),
        "covers_month": date(year, number, 1).isoformat(),
        "amount_clp": 25_000,
        "method": "transfer",
        "plan_name": "Mensual 3x semana",
    }


def a_year(year: int) -> list[dict[str, Any]]:
    return [month(year, n) for n in range(1, 13)]


def add(
    client: TestClient,
    gym: uuid.UUID,
    person: str,
    payments: list[dict[str, Any]],
    by: uuid.UUID | None = None,
) -> Any:
    return client.post(
        f"/api/people/{person}/history/payments",
        json={"payments": payments},
        headers=as_gym(gym, by),
    )


def read(client: TestClient, gym: uuid.UUID, person: str, by: uuid.UUID | None = None) -> Any:
    return client.get(f"/api/people/{person}/history/payments", headers=as_gym(gym, by))


def remove(
    client: TestClient, gym: uuid.UUID, person: str, payment: str, reason: str = "mal tipeado"
) -> Any:
    return client.post(
        f"/api/people/{person}/history/payments/{payment}/remove",
        json={"reason": reason},
        headers=as_gym(gym),
    )


@pg
def test_twelve_months_in_one_form_are_one_year_with_its_total(
    client: TestClient, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    response = add(client, gym, ana["id"], a_year(2024))
    assert response.status_code == 201, response.text
    [year] = response.json()["years"]
    assert (year["year"], year["count"], year["total_clp"]) == (2024, 12, 300_000)
    # Newest first, each with where it came from.
    lines = year["payments"]
    assert [p["covers_month"] for p in lines] == [f"2024-{n:02}-01" for n in range(12, 0, -1)]
    assert {(p["source"], p["import_name"]) for p in lines} == {("manual", None)}
    assert {p["created_by_name"][:9] for p in lines} == {"owner of "}
    assert read(client, gym, ana["id"]).json() == response.json()


@pg
def test_years_are_newest_first_by_the_month_paid_for(client: TestClient, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    add(client, gym, ana["id"], a_year(2023)[:3])
    # December 2023, paid in January: 2023's.
    late = {**month(2024, 1), "covers_month": "2023-12-01", "amount_clp": 30_000}
    # Unknown month: the year it was paid.
    unknown = {"paid_on": "2025-02-10", "amount_clp": 10_000}
    add(client, gym, ana["id"], [late, unknown])
    years = read(client, gym, ana["id"]).json()["years"]
    assert [(y["year"], y["count"], y["total_clp"]) for y in years] == [
        (2025, 1, 10_000),
        (2023, 4, 105_000),
    ]
    assert years[0]["payments"][0]["method"] is None


@pg
def test_one_bad_month_writes_none_of_the_form(client: TestClient, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    tomorrow = (seeded_today() + timedelta(days=1)).isoformat()
    payments = [*a_year(2024), {**month(2024, 1), "paid_on": tomorrow}]
    assert add(client, gym, ana["id"], payments).status_code == 422
    too_old = add_months(seeded_today(), -12 * 60) - timedelta(days=1)
    assert (
        add(client, gym, ana["id"], [{"paid_on": too_old.isoformat(), "amount_clp": 1}]).status_code
        == 422
    )
    assert (
        add(client, gym, ana["id"], [{**month(2024, 1), "covers_month": "2024-01-02"}]).status_code
        == 422
    )
    assert add(client, gym, ana["id"], [{**month(2024, 1), "amount_clp": 0}]).status_code == 422
    assert add(client, gym, ana["id"], []).status_code == 422
    assert read(client, gym, ana["id"]).json()["years"] == []
    assert add(client, gym, str(uuid.uuid4()), a_year(2024)).status_code == 404


@pg
def test_a_month_inside_their_plan_is_refused_with_covers_plan(
    client: TestClient, gym: uuid.UUID
) -> None:
    # Their plan started on the 15th of last month.
    this_month = seeded_today().replace(day=1)
    started_on = add_months(this_month, -1).replace(day=15)
    ana = enrolled(
        client, gym, membership={"plan_id": plan(client, gym), "started_on": started_on.isoformat()}
    )
    earlier = add_months(this_month, -2)
    # This month is their plan's: the whole form is refused, naming it.
    response = add(
        client,
        gym,
        ana["id"],
        [month(earlier.year, earlier.month), month(this_month.year, this_month.month, 1)],
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "covers_plan"
    assert detail["plan_from"] == started_on.isoformat()
    assert detail["months"] == [this_month.isoformat()]
    assert read(client, gym, ana["id"]).json()["years"] == []
    # With no month, the day it was paid says: their plan's first day is the plan's.
    on_start = {"paid_on": started_on.isoformat(), "amount_clp": 1_000}
    assert add(client, gym, ana["id"], [on_start]).json()["detail"]["code"] == "covers_plan"
    day_before = {"paid_on": (started_on - timedelta(days=1)).isoformat(), "amount_clp": 1_000}
    written = add(client, gym, ana["id"], [month(earlier.year, earlier.month), day_before])
    assert written.status_code == 201, written.text
    assert written.json()["plan_from"] == started_on.isoformat()


@pg
def test_a_former_student_has_no_boundary_but_today(client: TestClient, gym: uuid.UUID) -> None:
    carla = added(client, gym)
    today = seeded_today()
    response = add(client, gym, carla["id"], [{"paid_on": today.isoformat(), "amount_clp": 5_000}])
    assert response.status_code == 201, response.text
    assert response.json()["plan_from"] is None


@pg
def test_a_payment_equal_to_one_there_is_written_again(client: TestClient, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    add(client, gym, ana["id"], [month(2024, 3)])
    response = add(client, gym, ana["id"], [month(2024, 3)])
    assert response.status_code == 201
    assert response.json()["years"][0]["count"] == 2


@pg
def test_a_coach_neither_reads_nor_writes_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    add(client, gym, ana["id"], [month(2024, 3)])
    coach = add_staff(db, gym, "coach")
    assert read(client, gym, ana["id"], coach).status_code == 403
    assert add(client, gym, ana["id"], [month(2024, 4)], coach).status_code == 403
    # Nor past the API: RLS gives a coach no row and refuses their insert.
    rows = run(db.api_url, in_gym(gym, "SELECT * FROM history_payment", person=coach))
    assert rows == []
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                gym,
                "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
                " created_by) VALUES ($1, $2, '2024-01-05', 1, 'manual', $3)",
                gym,
                uuid.UUID(ana["id"]),
                coach,
                person=coach,
            ),
        )
    deleted = run(db.api_url, in_gym(gym, "DELETE FROM history_payment RETURNING id", person=coach))
    assert deleted == []
    # An admin does both.
    admin = add_staff(db, gym, "admin")
    assert add(client, gym, ana["id"], [month(2024, 4)], admin).status_code == 201
    assert read(client, gym, ana["id"], admin).json()["years"][0]["count"] == 2
    # As themselves only, and never another gym's.
    owner = uuid.uuid5(gym, "owner")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                gym,
                "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
                " created_by) VALUES ($1, $2, '2024-01-05', 1, 'manual', $3)",
                gym,
                uuid.UUID(ana["id"]),
                owner,
                person=admin,
            ),
        )
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    assert read(client, other, ana["id"]).status_code == 404


@pg
def test_no_update_even_for_the_owner(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    add(client, gym, ana["id"], [month(2024, 3)])
    owner = uuid.uuid5(gym, "owner")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, "UPDATE history_payment SET amount_clp = 1", person=owner))


@pg
def test_removing_a_line_keeps_it_whole_in_the_audit_row(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    [year] = add(client, gym, ana["id"], [month(2024, 3), month(2024, 4)]).json()["years"]
    april = year["payments"][0]
    assert april["covers_month"] == "2024-04-01"

    response = remove(client, gym, ana["id"], april["id"], reason="ese mes no pagó")
    assert response.status_code == 200, response.text
    assert response.json()["years"][0]["count"] == 1
    [row] = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT actor_id, reason, detail FROM audit_event"
            " WHERE person_id = $1 AND action = 'history_removed'",
            uuid.UUID(ana["id"]),
        ),
    )
    assert row["actor_id"] == uuid.uuid5(gym, "owner")
    assert row["reason"] == "ese mes no pagó"
    payment = json.loads(row["detail"])["payment"]
    assert payment | {"created_at": None} == {
        "id": april["id"],
        "person_id": ana["id"],
        "paid_on": "2024-04-05",
        "amount_clp": 25_000,
        "method": "transfer",
        "covers_month": "2024-04-01",
        "plan_name": "Mensual 3x semana",
        "note": None,
        "source": "manual",
        "import_id": None,
        "created_by": str(uuid.uuid5(gym, "owner")),
        "created_at": None,
    }
    # Not a correction of their billing.
    corrections = client.get(f"/api/ledger/people/{ana['id']}/corrections", headers=as_gym(gym))
    assert corrections.json() == {"total": 0, "items": []}
    # Once: it is gone; a reason is needed; a coach cannot.
    assert remove(client, gym, ana["id"], april["id"]).status_code == 404
    march = response.json()["years"][0]["payments"][0]["id"]
    assert remove(client, gym, ana["id"], march, reason=" ").status_code == 422
    coach = add_staff(db, gym, "coach")
    refused = client.post(
        f"/api/people/{ana['id']}/history/payments/{march}/remove",
        json={"reason": "x"},
        headers=as_gym(gym, coach),
    )
    assert refused.status_code == 403
    # Another person's line is not theirs to remove.
    bea = enrolled(client, gym)
    assert remove(client, gym, bea["id"], march).status_code == 404


@pg
def test_forgetting_the_person_deletes_their_history_and_counts_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # A former student whose only money is history can be deleted.
    carla = added(client, gym)
    [year] = add(client, gym, carla["id"], a_year(2021)).json()["years"]
    remove(client, gym, carla["id"], year["payments"][0]["id"])

    assert forget(client, gym, carla["id"]).status_code == 204
    person = uuid.UUID(carla["id"])
    assert count(db, gym, "SELECT count(*) FROM history_payment WHERE person_id = $1", person) == 0
    assert count(db, gym, "SELECT count(*) FROM audit_event WHERE person_id = $1", person) == 0
    [deleted] = run(
        db.owner_url,
        in_gym(gym, "SELECT detail FROM audit_event WHERE action = 'person_deleted'"),
    )
    detail = json.loads(deleted["detail"])
    assert (detail["history_payments"], detail["history_removed"], detail["corrections"]) == (
        11,
        1,
        0,
    )
    # The log stays append-only to the app role: only the definer deletes a row.
    owner = uuid.uuid5(gym, "owner")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, "DELETE FROM audit_event", person=owner))


# --- nobody else reads it ---------------------------------------------------------


def readers(client: TestClient, db: Database, gym: uuid.UUID) -> dict[str, Any]:
    """What every reader of money shows for the gym: the views, the book's KPIs, Hoy's
    lists and the accountant's export."""

    def view(name: str) -> list[tuple[Any, ...]]:
        rows = run(db.owner_url, in_gym(gym, f"SELECT * FROM {name} ORDER BY 1, 2"))
        return sorted(tuple(r) for r in rows)

    def api(path: str) -> Any:
        response = client.get(path, headers=as_gym(gym))
        assert response.status_code == 200, (path, response.text)
        return response.json()

    export = client.get("/api/ledger/export?format=csv", headers=as_gym(gym))
    assert export.status_code == 200
    return {
        "v_balance": view("v_balance"),
        "v_overdue": view("v_overdue"),
        "v_monthly_income": view("v_monthly_income"),
        "book": api("/api/ledger/book")["kpis"],
        "overdue": api("/api/ledger/overdue"),
        "inactive": api("/api/inactive"),
        "reminders": api("/api/reminders"),
        "proofs": api("/api/ledger/proofs"),
        "export": export.content,
    }


@pg
def test_billing_views_hoy_and_the_export_are_the_same_with_and_without_history(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = today - timedelta(days=40)
    monthly = plan(client, gym)
    people = [
        enrolled(
            client,
            gym,
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            membership={"plan_id": monthly, "started_on": started_on.isoformat()},
        )
        for _ in range(2)
    ]
    ana, bea = people
    # Ana paid every month of the two years before Rakin; Bea is the same with none.
    first = add_months(started_on.replace(day=1), -24)
    history = [
        {
            "paid_on": add_months(first, n).isoformat(),
            "covers_month": add_months(first, n).isoformat(),
            "amount_clp": 45_000,
        }
        for n in range(24)
    ]
    assert add(client, gym, ana["id"], history).status_code == 201

    # The nightly jobs: billing, then lapse and the overdue emails, day after day.
    async def bill(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, today)

    run(db.owner_url, bill)
    outbox = Outbox()
    for offset in range(-3, 1):
        night(db, today + timedelta(days=offset), outbox)

    def standing(person: dict[str, Any]) -> tuple[Any, ...]:
        [membership] = memberships(client, gym, person["id"])
        periods = run(
            db.owner_url,
            in_gym(
                gym,
                "SELECT period_start, period_end, due_date, amount_due_clp FROM billing_period"
                " WHERE membership_id = $1 ORDER BY period_start",
                uuid.UUID(membership["id"]),
            ),
        )
        return (
            membership["status"],
            [tuple(p) for p in periods],
            len(outbox.to(person["email"])),
        )

    assert standing(ana) == standing(bea)
    assert standing(ana)[1] != []

    # Every reader, before and after more history: Bea's, and a former student's.
    before = readers(client, db, gym)
    assert add(client, gym, bea["id"], history).status_code == 201
    carla = added(client, gym)
    assert add(client, gym, carla["id"], a_year(2020)).status_code == 201
    assert readers(client, db, gym) == before
    footnote = before["export"].decode("utf-8-sig").splitlines()[-1]
    assert footnote.endswith('No incluye el historial anterior a Rakin."')


@pg
def test_not_on_the_students_page(client: TestClient, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    add(client, gym, ana["id"], a_year(2024))
    me = uuid.UUID(ana["id"])
    assert read(client, gym, ana["id"], me).status_code == 403
    page = client.get("/api/me/page", headers=as_gym(gym, me))
    assert page.status_code == 200
    assert "Mensual 3x semana" not in page.text and "history" not in page.json()


@pg
def test_upgrade_and_downgrade_0053() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        gym = seed_gym(scratch, "sur")
        owner = uuid.uuid5(gym, "owner")

        async def log(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, source,"
                " created_by) VALUES ($1, $2, '2024-01-05', 1, 'manual', $2)",
                gym,
                owner,
            )
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, person_id, action)"
                " VALUES ($1, $2, $2, 'history_removed'), ($1, $2, $2, 'history_set')",
                gym,
                owner,
            )

        run(scratch.admin_url, log)
        # The removals go with their action, and the payments with their table.
        command.downgrade(scratch.alembic(), "0052")
        kept = run(scratch.admin_url, lambda c: c.fetch("SELECT action FROM audit_event"))
        assert [r["action"] for r in kept] == ["history_set"]
        migrate(scratch)
