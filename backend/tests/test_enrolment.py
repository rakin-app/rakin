"""Matrícula (#355): a plan's enrolment fee, charged once as a membership on it starts.

Planes, in Ajustes, sets the fee on a monthly, prepaid, fixed-period or credits plan.
Starting a membership on it, by hand or on Nuevo alumno, writes one cobro extra line
"Matrícula" for the person, due on the day the plan starts, unless "ya pagó matrícula"
says not to. Reactivar, of a person or of a lapsed plan, and a plan change charge none.
Voiding the membership cancels a matrícula with nothing paid on it. The import and the
join link have their own tests, beside theirs.
"""

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.extra_charges import ExtraChargeCreate
from app.schemas.plans import PLAN, PLAN_CREATE, PlanUpdate, for_coach
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_member_roll import enrolled, leave
from tests.test_memberships import PLANS, add_staff, change, person, start
from tests.test_reactivate import lapsed_plan, reactivate

FEE = 30_000

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize("key", ["signup", "prepaid", "credits"])
def test_a_plan_a_member_joins_takes_a_fee(key: str) -> None:
    plan = PLAN_CREATE.validate_python({**PLANS[key], "enrolment_fee_clp": FEE})
    assert plan.model_dump()["enrolment_fee_clp"] == FEE
    assert PLAN_CREATE.validate_python(PLANS[key]).model_dump()["enrolment_fee_clp"] is None


@pytest.mark.parametrize(
    "body",
    [
        {**PLANS["dropin"], "enrolment_fee_clp": FEE},
        {**PLANS["trial"], "enrolment_fee_clp": FEE},
        {**PLANS["signup"], "enrolment_fee_clp": 0},
        {**PLANS["signup"], "enrolment_fee_clp": 100_000_001},
    ],
    ids=["dropin", "trial", "nothing", "too much"],
)
def test_a_fee_is_refused(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PLAN_CREATE.validate_python(body)


def test_a_coach_reads_a_plan_without_its_fee() -> None:
    plan = PLAN_CREATE.validate_python({**PLANS["signup"], "enrolment_fee_clp": FEE})
    stored = {**plan.model_dump(), "id": uuid.uuid4(), "active": True, "created_at": "2026-11-17"}
    assert "enrolment_fee_clp" not in for_coach(PLAN.validate_python(stored)).model_dump()


def test_an_edit_takes_the_fee_off_with_null() -> None:
    body = PlanUpdate.model_validate({"enrolment_fee_clp": None})
    assert body.model_dump(exclude_unset=True) == {"enrolment_fee_clp": None}


def test_a_matricula_is_never_drafted_by_hand() -> None:
    body = {
        "title": "Matrícula",
        "category": "matricula",
        "due_date": "2026-12-01",
        "target": {"kind": "people", "person_ids": [str(uuid.uuid4())]},
        "amount_mode": "fixed",
        "amount_clp": FEE,
    }
    with pytest.raises(ValidationError):
        ExtraChargeCreate.model_validate(body)
    assert ExtraChargeCreate.model_validate({**body, "category": "otro"})


# --- against real Postgres --------------------------------------------------------

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
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:8]}")


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def plan_with_fee(client: TestClient, gym: uuid.UUID, key: str = "signup", **body: Any) -> str:
    created = client.post(
        "/api/plans",
        json={**PLANS[key], "enrolment_fee_clp": FEE, **body},
        headers=as_gym(gym),
    )
    return str(ok(created, 201)["id"])


def matriculas(db: Database, gym: uuid.UUID, person_id: str) -> list[dict[str, Any]]:
    """The person's matrícula lines, cancelled ones too, oldest first."""
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT x.title, x.description, x.due_date, x.membership_id, l.amount_due_clp,"
            " l.cancelled_at IS NOT NULL AS cancelled, l.cancel_reason"
            " FROM extra_line l JOIN extra_charge x ON x.id = l.extra_charge_id"
            " WHERE x.category = 'matricula' AND l.person_id = $1 ORDER BY x.created_at",
            uuid.UUID(person_id),
        ),
    )
    return [dict(row) for row in rows]


def started_on_plan(
    client: TestClient, gym: uuid.UUID, plan_id: str, **body: Any
) -> tuple[str, dict[str, Any]]:
    person_id = person(client, gym)
    return person_id, ok(start(client, gym, plan_id, person_id, **body), 201)


@pg
def test_a_plan_keeps_its_fee_and_an_edit_changes_or_removes_it(
    client: TestClient, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    url = f"/api/plans/{plan_id}"
    assert ok(client.get(url, headers=as_gym(gym)))["enrolment_fee_clp"] == FEE
    edited = client.patch(url, json={"enrolment_fee_clp": 25_000}, headers=as_gym(gym))
    assert ok(edited)["enrolment_fee_clp"] == 25_000
    removed = client.patch(url, json={"enrolment_fee_clp": None}, headers=as_gym(gym))
    assert ok(removed)["enrolment_fee_clp"] is None

    dropin = ok(client.post("/api/plans", json=PLANS["dropin"], headers=as_gym(gym)), 201)
    refused = client.patch(
        f"/api/plans/{dropin['id']}", json={"enrolment_fee_clp": FEE}, headers=as_gym(gym)
    )
    assert refused.status_code == 422, refused.text


@pg
def test_a_coach_reads_the_plans_without_their_fees(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    coach = add_staff(db, gym, "coach")
    plans = ok(client.get("/api/plans", headers=as_gym(gym, coach)))
    [plan] = [p for p in plans if p["id"] == plan_id]
    assert "enrolment_fee_clp" not in plan
    assert "price_clp" not in plan


@pg
def test_the_table_refuses_a_fee_on_a_drop_in(db: Database, gym: uuid.UUID) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.owner_url,
            in_gym(
                gym,
                "INSERT INTO plan (gym_id, name, kind, price_clp, enrolment_fee_clp)"
                " VALUES (current_setting('app.gym_id')::uuid, 'Suelta', 'dropin', 1, 1)",
            ),
        )


@pg
def test_starting_a_plan_with_a_fee_charges_one_matricula_due_that_day(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    day = seeded_today() - timedelta(days=3)
    person_id, membership = started_on_plan(client, gym, plan_id, started_on=day.isoformat())

    [line] = matriculas(db, gym, person_id)
    assert line["title"] == "Matrícula · Alumna"
    assert line["description"] == "Mensual"
    assert (line["amount_due_clp"], line["due_date"]) == (FEE, day)
    assert str(line["membership_id"]) == membership["id"]
    # As any cobro extra: on the ficha's "Cobros extra pendientes" and in the cobros.
    [owed] = ok(client.get(f"/api/people/{person_id}/extra-lines", headers=as_gym(gym)))
    assert (owed["category"], owed["outstanding_clp"]) == ("matricula", FEE)
    [charge] = ok(client.get("/api/extra-charges", headers=as_gym(gym)))
    assert (charge["category"], charge["due_clp"], charge["lines"]) == ("matricula", FEE, 1)


@pg
def test_ya_pago_matricula_starts_the_plan_without_one(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    person_id, _ = started_on_plan(client, gym, plan_id, charge_enrolment=False)
    assert matriculas(db, gym, person_id) == []


@pg
def test_a_plan_with_no_fee_charges_none(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    plan_id = ok(client.post("/api/plans", json=PLANS["signup"], headers=as_gym(gym)), 201)["id"]
    person_id, _ = started_on_plan(client, gym, plan_id)
    assert matriculas(db, gym, person_id) == []


@pg
def test_nuevo_alumno_with_a_plan_charges_it_unless_told_not_to(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    charged = enrolled(client, gym, name="Ana Soto", membership={"plan_id": plan_id})
    paid = enrolled(
        client,
        gym,
        name="Rosa Vidal",
        membership={"plan_id": plan_id, "charge_enrolment": False},
    )
    assert [m["amount_due_clp"] for m in matriculas(db, gym, charged["id"])] == [FEE]
    assert matriculas(db, gym, paid["id"]) == []


@pg
def test_reactivar_a_person_on_the_plan_charges_no_matricula_again(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    member = enrolled(client, gym, membership={"plan_id": plan_id})
    ok(leave(client, gym, member["id"]))

    back = client.post(
        f"/api/people/{member['id']}/return",
        json={"membership": {"plan_id": plan_id, "charge_enrolment": True}},
        headers=as_gym(gym),
    )

    ok(back)
    assert len(matriculas(db, gym, member["id"])) == 1


@pg
def test_reactivar_a_lapsed_plan_charges_no_matricula(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person_id, membership, _ = lapsed_plan(client, db, gym)
    plan_id = ok(client.get(f"/api/memberships/{membership}", headers=as_gym(gym)))["plan_id"]
    ok(client.patch(f"/api/plans/{plan_id}", json={"enrolment_fee_clp": FEE}, headers=as_gym(gym)))

    ok(reactivate(client, gym, membership, "today"))

    assert matriculas(db, gym, person_id) == []


@pg
def test_a_plan_change_charges_no_matricula(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    first = ok(client.post("/api/plans", json=PLANS["signup"], headers=as_gym(gym)), 201)["id"]
    person_id, membership = started_on_plan(client, gym, first)
    ok(change(client, gym, membership["id"], plan_with_fee(client, gym, "prepaid")))
    assert matriculas(db, gym, person_id) == []


@pg
def test_voiding_the_plan_cancels_its_unpaid_matricula(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    person_id, membership = started_on_plan(client, gym, plan_id)

    voided = client.post(
        f"/api/memberships/{membership['id']}/void",
        json={"reason": "plan equivocado"},
        headers=as_gym(gym),
    )

    ok(voided)
    [line] = matriculas(db, gym, person_id)
    assert (line["cancelled"], line["cancel_reason"]) == (True, "plan equivocado")
    assert ok(client.get(f"/api/people/{person_id}/extra-lines", headers=as_gym(gym))) == []


@pg
def test_a_paid_matricula_stays_when_the_plan_is_voided(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    person_id, membership = started_on_plan(client, gym, plan_id)
    [charge] = ok(client.get("/api/extra-charges", headers=as_gym(gym)))
    [line] = ok(client.get(f"/api/extra-charges/{charge['id']}", headers=as_gym(gym)))["people"]
    paid = client.post(
        f"/api/extra-charges/{charge['id']}/lines/{line['id']}/payments",
        json={"amount_clp": FEE, "method": "cash"},
        headers=as_gym(gym),
    )
    ok(paid, 201)

    ok(
        client.post(
            f"/api/memberships/{membership['id']}/void",
            json={"reason": "plan equivocado"},
            headers=as_gym(gym),
        )
    )

    [kept] = matriculas(db, gym, person_id)
    assert kept["cancelled"] is False


@pg
def test_the_table_holds_a_membership_to_one_matricula(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan_with_fee(client, gym)
    _, membership = started_on_plan(client, gym, plan_id)
    insert = (
        "INSERT INTO extra_charge (gym_id, title, category, due_date, amount_mode, amount_clp,"
        " target_kind, membership_id) VALUES (current_setting('app.gym_id')::uuid, 'Matrícula',"
        " $1, current_date, 'fixed', 1, 'people', $2)"
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        run(db.owner_url, in_gym(gym, insert, "matricula", uuid.UUID(membership["id"])))
    # Only a matrícula names a membership, and a matrícula always does.
    with pytest.raises(asyncpg.CheckViolationError):
        run(db.owner_url, in_gym(gym, insert, "otro", uuid.UUID(membership["id"])))
    with pytest.raises(asyncpg.CheckViolationError):
        run(db.owner_url, in_gym(gym, insert, "matricula", None))
