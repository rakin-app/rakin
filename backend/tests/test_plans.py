"""Plans: the five kinds and their parameters, edits, and deactivating instead of deleting.

Each kind takes exactly its own parameters, at the API and in the table (migration
0007): a body or a row that mixes two kinds is refused, not half-stored.
"""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.db_bootstrap import to_dsn
from app.main import create_app
from app.schemas.plans import (
    INT4_MAX,
    MAX_PRICE_CLP,
    PLAN_CREATE,
    PlanUpdate,
    from_row,
    to_columns,
)
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

# One of each kind, as an owner would type it.
MONTHLY: dict[str, Any] = {
    "kind": "monthly",
    "name": "Mensual adultos",
    "price_clp": 45_000,
    "anchor": "signup",
}
PREPAID: dict[str, Any] = {
    "kind": "prepaid",
    "name": "Prepago 6 meses",
    "price_clp": 240_000,
    "period_months": 6,
}
CREDITS: dict[str, Any] = {
    "kind": "credits",
    "name": "Pack 12 clases",
    "price_clp": 45_000,
    "credits": 12,
    "credit_expiry_days": 60,
}
DROPIN: dict[str, Any] = {"kind": "dropin", "name": "Clase suelta", "price_clp": 10_000}
TRIAL: dict[str, Any] = {
    "kind": "trial",
    "name": "Clase de prueba",
    "free_classes": 2,
    "free_days": 14,
}
KINDS: dict[str, dict[str, Any]] = {
    p["kind"]: p for p in (MONTHLY, PREPAID, CREDITS, DROPIN, TRIAL)
}

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize("body", KINDS.values(), ids=KINDS)
def test_each_kind_takes_its_parameters(body: dict[str, Any]) -> None:
    assert PLAN_CREATE.validate_python(body).model_dump(exclude_none=True) == body


@pytest.mark.parametrize(
    "body",
    [
        {**MONTHLY, "anchor": "first"},
        {**TRIAL, "free_days": None},
        {**TRIAL, "free_classes": None},
        {**DROPIN, "price_clp": 0},
    ],
    ids=str,
)
def test_also_accepted(body: dict[str, Any]) -> None:
    PLAN_CREATE.validate_python(body)


@pytest.mark.parametrize(
    "body",
    [
        {**MONTHLY, "anchor": None},
        {**MONTHLY, "anchor": "15"},
        {**MONTHLY, "period_months": 1},  # another kind's parameter
        {k: v for k, v in PREPAID.items() if k != "period_months"},
        {**PREPAID, "period_months": 0},
        {**CREDITS, "credits": None},
        {**CREDITS, "credit_expiry_days": None},
        {**CREDITS, "credits": -1},
        {**DROPIN, "credits": 1},
        {**DROPIN, "price_clp": -1},
        {k: v for k, v in DROPIN.items() if k != "price_clp"},
        {**TRIAL, "free_classes": None, "free_days": None},
        {**TRIAL, "price_clp": 0},  # a trial is free: it has no price
        {**TRIAL, "credits": 2},  # the column, not the field
        {**MONTHLY, "kind": "yearly"},
        {**MONTHLY, "name": "  "},
        {**MONTHLY, "active": False},
        {**MONTHLY, "gym_id": str(uuid.uuid4())},
    ],
    ids=str,
)
def test_create_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PLAN_CREATE.validate_python(body)


# Each bounded field, one past what it may hold: the column's range, or the price cap.
OVERSIZED = [
    {**MONTHLY, "price_clp": MAX_PRICE_CLP + 1},
    {**PREPAID, "period_months": INT4_MAX + 1},
    {**CREDITS, "credits": INT4_MAX + 1},
    {**CREDITS, "credit_expiry_days": INT4_MAX + 1},
    {**TRIAL, "free_classes": INT4_MAX + 1},
    {**TRIAL, "free_days": INT4_MAX + 1},
    {**DROPIN, "price_clp": 2**63},
]


@pytest.mark.parametrize("body", OVERSIZED, ids=str)
def test_create_refuses_a_value_the_column_cannot_hold(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PLAN_CREATE.validate_python(body)


@pytest.mark.parametrize(
    "field", ["price_clp", "period_months", "credits", "credit_expiry_days", "free_days"]
)
def test_update_refuses_a_value_the_column_cannot_hold(field: str) -> None:
    with pytest.raises(ValidationError):
        PlanUpdate.model_validate({field: max(MAX_PRICE_CLP, INT4_MAX) + 1})


def test_update_takes_only_the_fields_sent() -> None:
    body = PlanUpdate.model_validate({"price_clp": 50_000, "free_days": None})
    assert body.model_dump(exclude_unset=True) == {"price_clp": 50_000, "free_days": None}


@pytest.mark.parametrize("field", [{"kind": "dropin"}, {"name": None}, {"active": None}], ids=str)
def test_update_refuses(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PlanUpdate.model_validate(field)


def test_a_trial_is_stored_in_the_credits_columns_and_free() -> None:
    columns = to_columns(PLAN_CREATE.validate_python(TRIAL))
    assert columns == {
        "name": "Clase de prueba",
        "kind": "trial",
        "price_clp": 0,
        "anchor": None,
        "period_months": None,
        "credits": 2,
        "credit_expiry_days": 14,
    }
    assert from_row(columns) == TRIAL


@pytest.mark.parametrize("body", KINDS.values(), ids=KINDS)
def test_every_column_round_trips(body: dict[str, Any]) -> None:
    columns = to_columns(PLAN_CREATE.validate_python(body))
    assert {k: v for k, v in from_row(columns).items() if v is not None} == body


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def norte(db: Database) -> uuid.UUID:
    return seed_gym(db, "dojo-norte")


def add_staff(db: Database, gym: uuid.UUID, role: str) -> uuid.UUID:
    person = uuid.uuid4()

    # As the superuser, which skips RLS.
    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, person
        )
        await conn.execute(
            "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)", gym, person, role
        )

    run(db.admin_url, query)
    return person


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def create(client: TestClient, gym: uuid.UUID, body: dict[str, Any], **kw: Any) -> Any:
    return client.post("/api/plans", json=body, headers=as_gym(gym, **kw))


def patch(client: TestClient, gym: uuid.UUID, plan: str, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/plans/{plan}", json=body, headers=as_gym(gym))


def entered(body: dict[str, Any]) -> dict[str, Any]:
    """A response without the fields the gym did not type, nor nulls."""
    skip = ("id", "active", "created_at")
    return {k: v for k, v in body.items() if k not in skip and v is not None}


def stored(db: Database, plan: str) -> dict[str, Any]:
    row = run(
        db.admin_url, lambda c: c.fetchrow("SELECT * FROM plan WHERE id = $1", uuid.UUID(plan))
    )
    return dict(row)


@pg
@pytest.mark.parametrize("body", KINDS.values(), ids=KINDS)
def test_create_then_read_each_kind(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any]
) -> None:
    response = create(client, sur, body)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert entered(plan) == body
    assert plan["active"] is True

    read = client.get(f"/api/plans/{plan['id']}", headers=as_gym(sur))
    assert read.status_code == 200
    assert read.json() == plan


@pg
def test_a_trial_row_holds_its_free_classes_and_days(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan = create(client, sur, TRIAL).json()
    row = stored(db, plan["id"])
    assert (row["price_clp"], row["credits"], row["credit_expiry_days"]) == (0, 2, 14)
    assert row["gym_id"] == sur


@pg
@pytest.mark.parametrize("body", [{**MONTHLY, "period_months": 1}, {**TRIAL, "price_clp": 0}])
def test_create_refuses_a_mixed_body(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any]
) -> None:
    assert create(client, sur, body).status_code == 422


@pg
@pytest.mark.parametrize("body", OVERSIZED, ids=str)
def test_an_oversized_value_is_a_422_not_a_500(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any]
) -> None:
    assert create(client, sur, body).status_code == 422
    valid = KINDS[body["kind"]]
    plan = create(client, sur, valid).json()
    change = {k: v for k, v in body.items() if v != valid.get(k)}
    assert patch(client, sur, plan["id"], change).status_code == 422


@pg
@pytest.mark.parametrize(
    "body",
    [
        {**MONTHLY, "price_clp": MAX_PRICE_CLP},
        {**CREDITS, "credits": INT4_MAX, "credit_expiry_days": INT4_MAX},
        {**TRIAL, "free_classes": INT4_MAX, "free_days": INT4_MAX},
    ],
    ids=str,
)
def test_the_largest_values_allowed_are_stored(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any]
) -> None:
    response = create(client, sur, body)
    assert response.status_code == 201
    assert entered(response.json()) == body


@pg
def test_concurrent_edits_do_not_lose_each_other(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # Another transaction changes the price and holds the row; a PATCH of the name
    # meanwhile must wait for it and keep its price, not write back the one it read.
    plan = create(client, sur, MONTHLY).json()

    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            tx = conn.transaction()
            await tx.start()
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(sur))
            await conn.execute(
                "UPDATE plan SET price_clp = 50000 WHERE id = $1", uuid.UUID(plan["id"])
            )
            edit = asyncio.create_task(
                asyncio.to_thread(patch, client, sur, plan["id"], {"name": "Renombrado"})
            )
            await asyncio.sleep(0.5)
            assert not edit.done()  # waiting on the row lock
            await tx.commit()
            return await asyncio.wait_for(edit, 10)
        finally:
            await conn.close()

    response = asyncio.run(go())
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["price_clp"]) == ("Renombrado", 50_000)


@pg
def test_list_puts_active_plans_first_and_filters(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "lista")  # its own gym, so the list is exactly what this test made
    seeded = client.get("/api/plans", headers=as_gym(gym)).json()
    b = create(client, gym, {**DROPIN, "name": "B"}).json()
    a = create(client, gym, {**DROPIN, "name": "A"}).json()
    old = create(client, gym, {**DROPIN, "name": "0 old"}).json()
    patch(client, gym, old["id"], {"active": False})

    listed = client.get("/api/plans", headers=as_gym(gym)).json()
    assert [p["name"] for p in listed] == ["A", "B", *(p["name"] for p in seeded), "0 old"]
    assert all(p["kind"] == "dropin" for p in listed if p["id"] in (a["id"], b["id"]))

    active = client.get("/api/plans?active=true", headers=as_gym(gym)).json()
    assert old["id"] not in {p["id"] for p in active}
    inactive = client.get("/api/plans?active=false", headers=as_gym(gym)).json()
    assert [p["id"] for p in inactive] == [old["id"]]


@pg
@pytest.mark.parametrize(
    ("body", "change"),
    [
        (MONTHLY, {"price_clp": 50_000, "anchor": "first"}),
        (PREPAID, {"period_months": 12, "name": "Prepago anual"}),
        (CREDITS, {"credits": 8, "credit_expiry_days": 30}),
        (DROPIN, {"price_clp": 12_000}),
        (TRIAL, {"free_classes": None}),
        (TRIAL, {"free_days": 7, "free_classes": 1}),
    ],
    ids=str,
)
def test_edit_the_kinds_own_parameters(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any], change: dict[str, Any]
) -> None:
    plan = create(client, sur, body).json()
    response = patch(client, sur, plan["id"], change)
    assert response.status_code == 200, response.text
    expected = {k: v for k, v in {**body, **change}.items() if v is not None}
    assert entered(response.json()) == expected
    assert client.get(f"/api/plans/{plan['id']}", headers=as_gym(sur)).json() == response.json()


@pg
@pytest.mark.parametrize(
    ("body", "change", "field"),
    [
        (MONTHLY, {"period_months": 3}, "period_months"),  # another kind's parameter
        (MONTHLY, {"anchor": None}, "anchor"),
        (CREDITS, {"credit_expiry_days": None}, "credit_expiry_days"),
        (DROPIN, {"free_days": 3}, "free_days"),
        (TRIAL, {"price_clp": 1000}, "price_clp"),
        (TRIAL, {"free_classes": None, "free_days": None}, None),
        (PREPAID, {"kind": "monthly"}, "kind"),
    ],
    ids=str,
)
def test_an_edit_must_leave_a_complete_plan_of_its_kind(
    client: TestClient,
    db: Database,
    sur: uuid.UUID,
    body: dict[str, Any],
    change: dict[str, Any],
    field: str | None,
) -> None:
    plan = create(client, sur, body).json()
    before = stored(db, plan["id"])
    response = patch(client, sur, plan["id"], change)
    assert response.status_code == 422
    if field is not None:
        assert [e["loc"] for e in response.json()["detail"]] == [["body", field]]
    assert stored(db, plan["id"]) == before


@pg
def test_deactivate_and_reactivate(client: TestClient, sur: uuid.UUID) -> None:
    plan = create(client, sur, MONTHLY).json()
    off = patch(client, sur, plan["id"], {"active": False})
    assert off.status_code == 200
    assert off.json() == {**plan, "active": False}
    on = patch(client, sur, plan["id"], {"active": True, "price_clp": 1})
    assert on.json() == {**plan, "price_clp": 1}


@pg
def test_there_is_no_delete(client: TestClient, sur: uuid.UUID) -> None:
    plan = create(client, sur, DROPIN).json()
    assert client.delete(f"/api/plans/{plan['id']}", headers=as_gym(sur)).status_code == 405
    assert client.get(f"/api/plans/{plan['id']}", headers=as_gym(sur)).status_code == 200


@pg
def test_another_gyms_plan_is_not_found(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    plan = create(client, sur, DROPIN).json()
    assert client.get(f"/api/plans/{plan['id']}", headers=as_gym(norte)).status_code == 404
    assert patch(client, norte, plan["id"], {"active": False}).status_code == 404
    assert plan["id"] not in {
        p["id"] for p in client.get("/api/plans", headers=as_gym(norte)).json()
    }
    assert client.get(f"/api/plans/{plan['id']}", headers=as_gym(sur)).json()["active"] is True


@pg
@pytest.mark.parametrize(("role", "writes"), [("admin", True), ("coach", False)])
def test_coaches_read_plans_and_only_owner_or_admin_change_them(
    client: TestClient, db: Database, sur: uuid.UUID, role: str, writes: bool
) -> None:
    person = add_staff(db, sur, role)
    plan = create(client, sur, DROPIN).json()
    headers = as_gym(sur, person)

    assert client.get("/api/plans", headers=headers).status_code == 200
    assert client.get(f"/api/plans/{plan['id']}", headers=headers).status_code == 200
    created = client.post("/api/plans", json=DROPIN, headers=headers)
    edited = client.patch(f"/api/plans/{plan['id']}", json={"active": False}, headers=headers)
    assert (created.status_code, edited.status_code) == ((201, 200) if writes else (403, 403))


# --- the table on its own (migration 0007) ----------------------------------------

INSERT = (
    "INSERT INTO plan (gym_id, name, kind, price_clp, anchor, period_months, credits,"
    " credit_expiry_days) VALUES ($1, 'x', $2, $3, $4, $5, $6, $7)"
)


@pg
@pytest.mark.parametrize(
    "values",
    [
        ("monthly", 1, None, None, None, None),  # no anchor
        ("monthly", 1, "signup", 3, None, None),
        ("prepaid", 1, None, None, None, None),
        ("prepaid", 1, "first", 3, None, None),
        ("credits", 1, None, None, 10, None),
        ("dropin", 1, None, None, 1, None),
        ("trial", 0, None, None, None, None),
        ("trial", 1000, None, None, 2, None),
        ("trial", 0, None, 1, 2, None),
    ],
    ids=str,
)
def test_the_table_refuses_a_row_that_mixes_kinds(
    db: Database, sur: uuid.UUID, values: tuple[Any, ...]
) -> None:
    with pytest.raises(asyncpg.CheckViolationError, match="plan_parameters_per_kind"):
        run(db.owner_url, in_gym(sur, INSERT, sur, *values))


def any_plan(db: Database, gym: uuid.UUID) -> uuid.UUID:
    rows = run(db.owner_url, in_gym(gym, "SELECT id FROM plan LIMIT 1"))
    plan: uuid.UUID = rows[0]["id"]
    return plan


@pg
@pytest.mark.parametrize("who", ["owner", "superuser"])
def test_no_role_deletes_a_plan(db: Database, sur: uuid.UUID, who: str) -> None:
    plan = any_plan(db, sur)
    url = db.owner_url if who == "owner" else db.admin_url
    with pytest.raises(asyncpg.RestrictViolationError, match="plans cannot be deleted"):
        run(url, in_gym(sur, "DELETE FROM plan WHERE id = $1", plan))
    with pytest.raises(asyncpg.RestrictViolationError, match="plans cannot be deleted"):
        run(url, in_gym(sur, "TRUNCATE plan CASCADE"))  # plan first, so its trigger fires first


@pg
def test_the_api_role_cannot_delete_a_plan(db: Database, sur: uuid.UUID) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(sur, "DELETE FROM plan WHERE id = $1", any_plan(db, sur)))


@pg
def test_upgrade_anchors_existing_monthly_plans_on_signup_and_downgrades() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0006")

        async def seed(conn: asyncpg.Connection) -> None:
            await conn.execute("INSERT INTO gym (id, name, slug) VALUES ($1, 'g', 'g')", gym)
            await conn.execute(
                "INSERT INTO plan (gym_id, name, kind, price_clp) VALUES"
                " ($1, 'M', 'monthly', 1), ($1, 'D', 'dropin', 1)",
                gym,
            )

        gym = uuid.uuid4()
        run(scratch.admin_url, seed)
        migrate(scratch)
        anchors = "SELECT kind, anchor FROM plan ORDER BY kind"
        rows = run(scratch.admin_url, lambda c: c.fetch(anchors))
        assert [tuple(r) for r in rows] == [("dropin", None), ("monthly", "signup")]

        command.downgrade(scratch.alembic(), "0006")
        run(scratch.admin_url, lambda c: c.execute("DELETE FROM plan"))
        migrate(scratch)
