"""The gym's ledger book, as "Libro de pagos" reads it (#39).

Every entry of a month newest first, with whose membership it is, the guardian who
pays for them and its period; the filters; and the KPIs: what the month collected
and expects, and what is pending and overdue today.

Each test takes a gym of its own (`seed_gym`, whose pending charge is in the current
month's book) and bills its members with `bill`, whose entries are made now.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_guardians import add_person, as_owner, bill, new_kid
from tests.test_membership_ledger import slug
from tests.test_plans import add_staff

pg = pytest.mark.postgres

# A month long gone, which only the entries a test dates into it reach.
PAST = date(2020, 3, 1)


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
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def book(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None, **params: Any) -> Any:
    return client.get("/api/ledger/book", params=params, headers=as_gym(gym, person))


def read(client: TestClient, gym: uuid.UUID, **params: Any) -> Any:
    response = book(client, gym, **params)
    assert response.status_code == 200, response.text
    return response.json()


def names(found: Any) -> list[tuple[str, str, int]]:
    return [(e["person"]["name"], e["kind"], e["amount_clp"]) for e in found["items"]]


def dated_entry(
    db: Database,
    gym: uuid.UUID,
    membership: str,
    kind: str,
    amount: int,
    when: datetime,
    *,
    status: str = "validated",
) -> None:
    """An entry made, and if validated validated, at `when`."""

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, status,"
                " validated_at, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                gym,
                uuid.UUID(membership),
                amount,
                kind,
                status,
                when if status == "validated" else None,
                when,
            )

    run(db.owner_url, query)


def dated_period(db: Database, gym: uuid.UUID, membership: str, due: date, amount: int) -> None:
    as_owner(
        db,
        gym,
        "INSERT INTO billing_period (gym_id, membership_id, period_start, period_end,"
        " amount_due_clp, due_date) VALUES ($1, $2, $3::date, $3::date + 29, $4, $3::date)",
        gym,
        uuid.UUID(membership),
        due,
        amount,
    )


def set_status(db: Database, gym: uuid.UUID, membership: str, status: str) -> None:
    # A cancellation carries its reason and time (migration 0009).
    as_owner(
        db,
        gym,
        "UPDATE membership SET status = $2::text,"
        " cancel_reason = CASE WHEN $2::text = 'cancelled' THEN 'test' END,"
        " cancelled_at = CASE WHEN $2::text = 'cancelled' THEN now() END WHERE id = $1",
        uuid.UUID(membership),
        status,
    )


@pg
def test_the_month_is_every_entry_newest_first_with_its_member_and_period(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    # 9 days late and part-paid.
    bill(db, sur, ana, [(-9, 45000, 10000, 0)])

    found = read(client, sur)

    today = seeded_today()
    assert found["month"] == today.replace(day=1).isoformat()
    assert found["timezone"] == "America/Santiago"
    mine = [e for e in found["items"] if e["person"]["name"] == "Ana"]
    # `bill` writes both in one transaction, so at one time; order is the pages' test.
    assert sorted((e["kind"], e["status"], e["amount_clp"]) for e in mine) == [
        ("charge", "validated", 45000),
        ("payment", "validated", 10000),
    ]
    [charge] = [e for e in mine if e["kind"] == "charge"]
    assert charge["plan_name"] == "Mensual"
    assert charge["guardian"] is None
    period = charge["period"]
    due = date.fromisoformat(period["due_date"])
    assert period["outstanding_clp"] == 35000
    assert period["days_overdue"] == max((today - due).days, 0)
    # The seeded owner's pending charge is in the month too.
    assert {e["person"]["name"] for e in found["items"]} == {"Ana", f"owner of {slug(db, sur)}"}
    assert found["total"] == len(found["items"])


@pg
def test_a_recorded_payment_names_who_validated_it_and_how_it_came(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 0, 0)])
    period = client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(sur)).json()
    body = {
        "membership_id": membership,
        "billing_period_id": period["open_periods"][0]["id"],
        "amount_clp": 30000,
        "method": "transfer",
    }
    assert client.post("/api/ledger/payments", json=body, headers=as_gym(sur)).status_code == 201

    [payment, charge] = [e for e in read(client, sur)["items"] if e["person"]["name"] == "Ana"]

    assert (payment["method"], payment["validated_by_name"]) == (
        "transfer",
        f"owner of {slug(db, sur)}",
    )
    # Paid in full: nothing outstanding, and so never late.
    assert (charge["period"]["outstanding_clp"], charge["period"]["days_overdue"]) == (0, 0)


@pg
def test_a_dependents_entries_carry_their_guardian_and_are_the_kids_filter(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    bill(db, sur, juan, [(-3, 30000, 0, 0)])
    bill(db, sur, marta, [(-3, 45000, 0, 0)])

    everything = read(client, sur)
    kids = read(client, sur, filter="kids")

    [juans] = [e for e in everything["items"] if e["person"]["name"] == "Juan"]
    assert juans["guardian"] == {"id": marta, "name": "Marta"}
    assert names(kids) == [("Juan", "charge", 30000)]
    assert kids["total"] == 1


@pg
def test_pending_is_the_review_queue_of_any_month(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 0, 20000)])
    dated_entry(
        db, sur, membership, "payment", 7000, datetime(2020, 3, 5, tzinfo=UTC), status="pending"
    )
    # Reviewed long ago, so not waiting.
    dated_entry(db, sur, membership, "payment", 9000, datetime(2020, 3, 6, tzinfo=UTC))

    found = read(client, sur, filter="pending")

    assert names(found) == [("Ana", "payment", 20000), ("Ana", "payment", 7000)]
    assert {e["status"] for e in found["items"]} == {"pending"}


@pg
def test_overdue_is_the_charges_active_members_owe_past_their_due_date(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    eva = add_person(client, sur, "Eva")
    # Ana: one period late, one paid, one not due yet.
    bill(db, sur, ana, [(-12, 45000, 5000, 0), (-40, 45000, 45000, 0), (4, 45000, 0, 0)])
    # Bea is late but lapsed: the owner's "Vencido" counts active members only.
    set_status(db, sur, bill(db, sur, bea, [(-30, 45000, 0, 0)]), "lapsed")
    # Eva is due today: not late yet.
    bill(db, sur, eva, [(0, 45000, 0, 0)])

    found = read(client, sur, filter="overdue")

    assert names(found) == [("Ana", "charge", 45000)]
    [late] = found["items"]
    assert late["period"]["outstanding_clp"] == 40000
    assert late["period"]["days_overdue"] >= 12


@pg
def test_another_month_shows_its_own_entries_and_every_month_with_entries_is_offered(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 0, 0)])
    # Late on March 31 in Santiago, which is April 1 in UTC: Santiago's March.
    dated_entry(db, sur, membership, "payment", 9000, datetime(2020, 4, 1, 2, 30, tzinfo=UTC))
    dated_entry(db, sur, membership, "charge", 30000, datetime(2020, 3, 1, 12, tzinfo=UTC))

    march = read(client, sur, month="2020-03-17")
    current = read(client, sur)

    assert march["month"] == "2020-03-01"
    assert names(march) == [("Ana", "payment", 9000), ("Ana", "charge", 30000)]
    # A carried credit or any entry with no period has none to show.
    assert march["items"][0]["period"] is None
    assert ("Ana", "payment", 9000) not in names(current)
    assert current["months"] == [seeded_today().replace(day=1).isoformat(), "2020-03-01"]
    # A month with no entries is still a month to show, and offered.
    empty = read(client, sur, month="2019-01-01")
    assert (empty["items"], empty["total"]) == ([], 0)
    assert "2019-01-01" in empty["months"]


@pg
def test_pages_are_newest_first_and_total_counts_every_page(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-1, 30000, 0, 0)])
    for day in range(1, 6):
        dated_entry(
            db, sur, membership, "payment", 1000 * day, datetime(2020, 3, day, 15, tzinfo=UTC)
        )

    first = read(client, sur, month=PAST.isoformat(), limit=2)
    second = read(client, sur, month=PAST.isoformat(), limit=2, offset=2)

    assert [e["amount_clp"] for e in first["items"]] == [5000, 4000]
    assert [e["amount_clp"] for e in second["items"]] == [3000, 2000]
    assert first["total"] == second["total"] == 5
    assert book(client, sur, limit=0).status_code == 422
    assert book(client, sur, limit=201).status_code == 422
    assert book(client, sur, filter="refunds").status_code == 422


@pg
def test_kpis_are_the_months_collected_and_expected_and_todays_pending_and_overdue(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    cata = add_person(client, sur, "Cata")
    # Ana: two late periods, 10 and 40 days, 70.000 short. Bea: 4 days late and a claim
    # in review. Cata: frozen, and late, which does not count.
    ana_m = bill(db, sur, ana, [(-40, 45000, 0, 0), (-10, 45000, 20000, 0)])
    bill(db, sur, bea, [(-4, 30000, 0, 12000)])
    cata_m = bill(db, sur, cata, [(-20, 30000, 0, 5000)])
    set_status(db, sur, cata_m, "frozen")
    # March 2020: two payments validated in it, and two periods falling due in it.
    dated_entry(db, sur, ana_m, "payment", 45000, datetime(2020, 3, 10, 15, tzinfo=UTC))
    dated_entry(db, sur, ana_m, "payment", 15000, datetime(2020, 3, 20, 15, tzinfo=UTC))
    dated_entry(
        db, sur, ana_m, "payment", 8000, datetime(2020, 3, 21, 15, tzinfo=UTC), status="pending"
    )
    dated_period(db, sur, ana_m, date(2020, 3, 5), 45000)
    dated_period(db, sur, cata_m, date(2020, 3, 28), 30000)

    kpis = read(client, sur, month=PAST.isoformat())["kpis"]

    assert (kpis["collected_clp"], kpis["collected_payments"]) == (60000, 2)
    # Ana's March period; Cata's is not expected while she is frozen.
    assert kpis["expected_clp"] == 45000
    # Pending and overdue are today's, whichever month is shown.
    assert (kpis["pending_clp"], kpis["pending_payments"]) == (12000 + 5000 + 8000, 3)
    assert kpis["overdue_clp"] == 70000 + 30000
    assert kpis["overdue_members"] == 2
    # Ana's oldest is 40 days late, Bea's 4: each member counts once.
    assert kpis["overdue_avg_days"] == pytest.approx(22, abs=1)
    # The seeded member, Ana and Bea are active; Cata is frozen.
    assert (kpis["active_memberships"], kpis["frozen_memberships"]) == (3, 1)


@pg
def test_expected_is_what_active_and_lapsed_memberships_owe_for_the_month(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # One membership of each status, each with a period falling due in March 2020.
    amounts = {"active": 1000, "lapsed": 2000, "cancelled": 4000, "trial": 8000, "frozen": 16000}
    for status, amount in amounts.items():
        membership = bill(db, sur, add_person(client, sur, status.title()), [])
        dated_period(db, sur, membership, date(2020, 3, 10), amount)
        set_status(db, sur, membership, status)

    kpis = read(client, sur, month=PAST.isoformat())["kpis"]

    # A lapsed member still owes what was billed; a cancelled one is not expected.
    assert kpis["expected_clp"] == amounts["active"] + amounts["lapsed"]


@pg
def test_an_empty_month_has_zero_kpis(client: TestClient, sur: uuid.UUID) -> None:
    kpis = read(client, sur, month="2019-01-01")["kpis"]

    assert kpis["collected_clp"] == kpis["expected_clp"] == kpis["overdue_clp"] == 0
    assert kpis["overdue_avg_days"] == 0


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_read_it(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    person = seeded_owner(sur) if role == "owner" else add_staff(db, sur, role)

    assert book(client, sur, person).status_code == 200


@pg
def test_a_coach_cannot_read_it(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    assert book(client, sur, add_staff(db, sur, "coach")).status_code == 403


@pg
def test_another_gyms_entries_are_not_in_it(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"academia-norte-{uuid.uuid4().hex[:6]}")
    bill(db, norte, add_person(client, norte, "Bea"), [(-5, 30000, 0, 9000)])

    found = read(client, sur)
    pending = read(client, sur, filter="pending")

    assert "Bea" not in {e["person"]["name"] for e in found["items"]}
    assert pending["total"] == 0
    assert found["kpis"]["pending_payments"] == 0
