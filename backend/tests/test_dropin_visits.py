"""Drop-in visitors on the roster (#130): marked and charged for a single class.

A visit is a one-day membership on a drop-in plan, ended as it starts, with its one
period and charge (docs/adr/0002-drop-in-visits.md). A coach adds the visitor and the
charge is written for them (`dropin_charge`, migration 0061); only an owner or admin
records that they paid. Unmarking the visit the day it was added voids the charge,
never deleting it (`dropin_void`).
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_attendance import (
    change,
    changed,
    class_type,
    created,
    plan,
    program,
    roster,
    row,
    session_of,
)
from tests.test_guardians import add_person
from tests.test_people import new_phone
from tests.test_plans import DROPIN, MONTHLY, TRIAL, add_staff

pytestmark = pytest.mark.postgres

PRICE = DROPIN["price_clp"]


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


@pytest.fixture
def coach(db: Database, gym: uuid.UUID) -> uuid.UUID:
    return add_staff(db, gym, "coach")


@pytest.fixture
def dropin(client: TestClient, gym: uuid.UUID) -> str:
    return plan(client, gym, DROPIN)


@pytest.fixture
def adults(client: TestClient, gym: uuid.UUID) -> str:
    return program(client, gym, "Adultos")


@pytest.fixture
def session(client: TestClient, gym: uuid.UUID, adults: str) -> str:
    return session_of(client, gym, class_type(client, gym, adults))


def visit(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    plan_id: str,
    by: uuid.UUID | None = None,
    **body: Any,
) -> Any:
    payload = {"name": "Visita Uno", "phone": new_phone(), "plan_id": plan_id, **body}
    return client.post(f"/api/sessions/{session}/visitors", json=payload, headers=as_gym(gym, by))


def ledger(db: Database, gym: uuid.UUID, membership: str) -> list[tuple[str, int, str | None]]:
    """The membership's entries, oldest first: kind, amount and purpose."""
    rows = run(
        db.admin_url,
        in_gym(
            gym,
            "SELECT kind, amount_clp, purpose FROM ledger_entry WHERE membership_id = $1"
            " ORDER BY created_at, kind",
            uuid.UUID(membership),
        ),
    )
    return [(r["kind"], r["amount_clp"], r["purpose"]) for r in rows]


def membership_of(db: Database, membership: str) -> Any:
    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetchrow(
            "SELECT m.status, m.cancel_reason, m.voided_at, m.person_id, pl.kind,"
            " b.period_start, b.period_end, b.amount_due_clp"
            " FROM membership m JOIN plan pl ON pl.id = m.plan_id"
            " LEFT JOIN billing_period b ON b.membership_id = m.id WHERE m.id = $1",
            uuid.UUID(membership),
        )

    return run(db.admin_url, query)


def visitor_row(listed: Any, name: str = "Visita Uno") -> Any:
    return row(listed, name)


def test_a_coach_adds_a_visitor_present_and_charged_once(
    client: TestClient, db: Database, gym: uuid.UUID, coach: uuid.UUID, dropin: str, session: str
) -> None:
    response = visit(client, gym, session, dropin, coach)
    listed = created(response)

    guest = visitor_row(listed)
    assert (guest["present"], guest["plan_kind"], guest["plan_name"]) == (
        True,
        "dropin",
        "Clase suelta",
    )
    assert listed["present"] == 1
    held = membership_of(db, guest["membership_id"])
    assert (held["status"], held["cancel_reason"], held["voided_at"]) == (
        "cancelled",
        "clase suelta",
        None,
    )
    assert held["period_start"] == held["period_end"]
    assert held["amount_due_clp"] == PRICE
    assert ledger(db, gym, guest["membership_id"]) == [("charge", PRICE, None)]


def test_the_charge_is_in_the_payment_book_until_it_is_paid(
    client: TestClient, db: Database, gym: uuid.UUID, coach: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin, coach)))

    book = client.get("/api/ledger/book", headers=as_gym(gym)).json()
    charge = next(i for i in book["items"] if i["membership_id"] == guest["membership_id"])
    assert (charge["kind"], charge["amount_clp"], charge["plan_name"]) == (
        "charge",
        PRICE,
        "Clase suelta",
    )
    assert charge["period"]["outstanding_clp"] == PRICE

    period = membership_of(db, guest["membership_id"])
    periods = client.get(
        f"/api/ledger/memberships/{guest['membership_id']}", headers=as_gym(gym)
    ).json()
    paid = client.post(
        "/api/ledger/payments",
        json={
            "membership_id": guest["membership_id"],
            "billing_period_id": periods["periods"][0]["id"],
            "amount_clp": period["amount_due_clp"],
            "method": "cash",
        },
        headers=as_gym(gym),
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["period"]["closed"] is True


def test_an_owner_records_the_payment_with_the_visit(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin, paid="transfer")))

    assert ledger(db, gym, guest["membership_id"]) == [
        ("charge", PRICE, None),
        ("payment", PRICE, None),
    ]
    method = run(
        db.admin_url,
        in_gym(
            gym,
            "SELECT method, status FROM ledger_entry WHERE membership_id = $1 AND kind = 'payment'",
            uuid.UUID(guest["membership_id"]),
        ),
    )
    assert (method[0]["method"], method[0]["status"]) == ("transfer", "validated")


def test_a_coach_may_not_record_the_payment(
    client: TestClient, db: Database, gym: uuid.UUID, coach: uuid.UUID, dropin: str, session: str
) -> None:
    response = visit(client, gym, session, dropin, coach, paid="cash")

    assert response.status_code == 403
    assert [m["plan_kind"] for m in roster(client, gym, session)["members"]] == ["monthly"]


def test_an_existing_phone_is_that_person(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    phone = new_phone()
    known = add_person(client, gym, "Camila Reyes", phone=phone)

    guest = visitor_row(
        created(visit(client, gym, session, dropin, name="Cami", phone=phone)), "Camila Reyes"
    )

    assert guest["person_id"] == known


def test_a_shared_phone_is_the_one_of_that_name_else_someone_new(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, adults: str
) -> None:
    phone = new_phone()
    mother = add_person(client, gym, "Paula Soto", phone=phone)
    add_person(client, gym, "Diego Soto", phone=phone)
    first = session_of(client, gym, class_type(client, gym, adults))
    second = session_of(client, gym, class_type(client, gym, adults, "Avanzado"))

    named = visitor_row(
        created(visit(client, gym, first, dropin, name="paula  sóto", phone=phone)), "Paula Soto"
    )
    other = visitor_row(
        created(visit(client, gym, second, dropin, name="Tomás Soto", phone=phone)), "Tomás Soto"
    )

    assert named["person_id"] == mother
    assert other["person_id"] != mother


def test_someone_on_the_roster_already_is_a_409_naming_the_membership(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    phone = new_phone()
    person = add_person(client, gym, "Ana Muñoz", phone=phone)
    monthly = plan(client, gym, MONTHLY)
    body = {"person_id": person, "plan_id": monthly}
    membership = created(client.post("/api/memberships", json=body, headers=as_gym(gym)))["id"]

    response = visit(client, gym, session, dropin, name="Ana Muñoz", phone=phone)

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "already_member", "membership_id": membership}


def test_a_visit_twice_at_one_class_is_the_first(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    phone = new_phone()
    first = visitor_row(created(visit(client, gym, session, dropin, phone=phone)))

    again = visit(client, gym, session, dropin, phone=phone)

    assert again.status_code == 409
    assert again.json()["detail"]["membership_id"] == first["membership_id"]


def test_the_visitor_is_on_no_later_roster_but_counts_their_class(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, adults: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin)))
    later = session_of(client, gym, class_type(client, gym, adults, "Avanzado"))

    assert "Visita Uno" not in [m["name"] for m in roster(client, gym, later)["members"]]
    counts = client.get(f"/api/people/{guest['person_id']}/attendance", headers=as_gym(gym))
    assert (counts.json()["total"], counts.json()["last_30_days"]) == (1, 1)


def test_the_visit_cannot_be_marked_at_another_class(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, adults: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin)))
    later = session_of(client, gym, class_type(client, gym, adults, "Avanzado"))

    response = change(client, gym, later, mark=[guest["membership_id"]])

    assert response.status_code == 422
    assert ledger(db, gym, guest["membership_id"]) == [("charge", PRICE, None)]


def test_unmarking_the_same_day_voids_the_charge_and_deletes_nothing(
    client: TestClient, db: Database, gym: uuid.UUID, coach: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin, coach)))

    response = change(client, gym, session, coach, unmark=[guest["membership_id"]])

    assert response.status_code == 200, response.text
    assert "Visita Uno" not in [m["name"] for m in response.json()["members"]]
    assert ledger(db, gym, guest["membership_id"]) == [
        ("charge", PRICE, None),
        ("adjustment", PRICE, "void"),
    ]
    assert membership_of(db, guest["membership_id"])["voided_at"] is not None
    audit = run(
        db.admin_url,
        in_gym(
            gym,
            "SELECT actor_id, action, detail->'after'->>'outstanding_clp' AS after"
            " FROM audit_event WHERE detail->>'membership_id' = $1",
            guest["membership_id"],
        ),
    )
    assert [(a["actor_id"], a["action"], a["after"]) for a in audit] == [
        (coach, "ledger_corrected", "0")
    ]
    book = client.get("/api/ledger/book?filter=overdue", headers=as_gym(gym)).json()
    assert guest["membership_id"] not in [i["membership_id"] for i in book["items"]]

    # Sent again, as an offline phone resends its queue: nothing more.
    changed(client, gym, session, unmark=[guest["membership_id"]])
    assert len(ledger(db, gym, guest["membership_id"])) == 2


def test_a_paid_visit_stays_marked(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin, paid="cash")))

    response = change(client, gym, session, unmark=[guest["membership_id"]])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paid"
    assert visitor_row(roster(client, gym, session))["present"] is True


def test_a_visit_added_on_an_earlier_day_stays_marked(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin)))

    async def yesterday(conn: asyncpg.Connection) -> None:
        # Past the trigger that keeps a cancelled membership as it is (0009).
        await conn.execute("ALTER TABLE membership DISABLE TRIGGER membership_cancelled_is_final")
        await conn.execute(
            "UPDATE membership SET created_at = created_at - interval '1 day' WHERE id = $1",
            uuid.UUID(guest["membership_id"]),
        )
        await conn.execute("ALTER TABLE membership ENABLE TRIGGER membership_cancelled_is_final")

    run(db.admin_url, yesterday)

    response = change(client, gym, session, unmark=[guest["membership_id"]])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "past"
    assert ledger(db, gym, guest["membership_id"]) == [("charge", PRICE, None)]


def test_deleting_the_class_voids_an_unpaid_visit(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin)))

    deleted = client.delete(f"/api/sessions/{session}", headers=as_gym(gym))

    assert deleted.status_code == 204, deleted.text
    assert ledger(db, gym, guest["membership_id"]) == [
        ("charge", PRICE, None),
        ("adjustment", PRICE, "void"),
    ]


@pytest.mark.parametrize(
    ("body", "kind"),
    [({"kind": "trial"}, "not_a_dropin_plan"), ({"active": False}, "inactive_plan")],
    ids=["trial-plan", "inactive"],
)
def test_the_plan_is_an_active_drop_in(
    client: TestClient,
    db: Database,
    gym: uuid.UUID,
    session: str,
    body: dict[str, Any],
    kind: str,
) -> None:
    if body.get("kind") == "trial":
        plan_id = plan(client, gym, TRIAL)
    else:
        plan_id = plan(client, gym, {**DROPIN, "name": "Suelta vieja"})
        edited = client.patch(f"/api/plans/{plan_id}", json=body, headers=as_gym(gym))
        assert edited.status_code == 200, edited.text

    response = visit(client, gym, session, plan_id)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == kind


def test_a_cancelled_class_takes_no_visitor(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    cancelled = client.post(f"/api/sessions/{session}/cancel", headers=as_gym(gym))
    assert cancelled.status_code == 200, cancelled.text

    assert visit(client, gym, session, dropin).status_code == 409


def test_only_staff_charge_or_void_a_visit(
    client: TestClient, db: Database, gym: uuid.UUID, dropin: str, session: str
) -> None:
    guest = visitor_row(created(visit(client, gym, session, dropin)))
    member = uuid.UUID(guest["person_id"])

    async def as_member(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(member))
            await conn.execute("SELECT dropin_void($1, 'x')", uuid.UUID(guest["membership_id"]))

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, as_member)
