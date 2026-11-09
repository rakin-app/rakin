"""Tenancy: the per-request `app.gym_id`, and two gyms that never see each other.

The app under test is the real one with a test router mounted: its endpoints read
every gym-scoped table through `TenantSession`. `tests.auth.FakeAuth` stands in for the
auth layer and puts the `X-Test-Gym` header's gym in `request.state.tenant`.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.tenancy import TenantSession
from tests.auth import FakeAuth, as_gym
from tests.conftest import UNREACHABLE_DB, make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

# Paths that act in no gym. Every other operation must answer 401 without a tenant.
# The local BlobStore's URLs carry their own signature instead of a session.
PUBLIC_PATHS = {"/healthz", "/api/blobs/{key}"}

TENANT_TABLES = (
    "gym",
    "gym_person",
    "staff",
    "plan",
    "membership",
    "billing_period",
    "ledger_entry",
)

router = APIRouter(prefix="/test")


@router.get("/rows/{table}")
async def rows(table: str, session: TenantSession) -> list[dict[str, Any]]:
    if table not in (*TENANT_TABLES, "person"):
        raise HTTPException(404)
    # The API may read only a person's id and phone (migration 0004).
    columns = "id, phone" if table == "person" else "*"
    result = await session.execute(
        text(f"SELECT to_jsonb(t) AS row FROM (SELECT {columns} FROM {table}) t")
    )
    return [r.row for r in result]


@router.get("/setting")
async def setting(session: TenantSession) -> dict[str, Any]:
    result = await session.execute(
        text("SELECT current_setting('app.gym_id', true) AS gym, pg_backend_pid() AS pid")
    )
    return dict(result.one()._mapping)


@router.get("/unscoped-setting")
async def unscoped_setting(request: Request) -> dict[str, Any]:
    # Straight from the pool, as code that forgot `TenantSession` would.
    async with request.app.state.engine.connect() as conn:
        result = await conn.execute(
            text("SELECT current_setting('app.gym_id', true) AS gym, pg_backend_pid() AS pid")
        )
        return dict(result.one()._mapping)


@router.post("/plans")
async def create_plan(session: TenantSession, fail: bool = False) -> None:
    await session.execute(
        text(
            "INSERT INTO plan (gym_id, name, kind, price_clp)"
            " VALUES (current_setting('app.gym_id')::uuid, 'Drop-in', 'dropin', 8000)"
        )
    )
    if fail:
        raise HTTPException(409, "after the insert")


def tenant_app(database_url: str) -> FastAPI:
    # One pooled connection, so consecutive requests provably share it.
    app = create_app(make_settings(database_url=database_url, db_pool_size=1))
    app.include_router(router)
    app.add_middleware(FakeAuth)
    return app


def unscoped_routes(app: FastAPI) -> list[str]:
    """Operations outside `PUBLIC_PATHS` that answer a request with no tenant.

    Asked of the running app rather than its route objects: every operation in the
    OpenAPI schema is called with no authenticated gym, and anything but a 401 means
    it ran without resolving one. Path parameters get a placeholder; the tenant is
    resolved before parameters are validated, so it never gets as far as a 422.
    """
    found = []
    with TestClient(app, raise_server_exceptions=False) as client:
        for path, operations in app.openapi()["paths"].items():
            if path in PUBLIC_PATHS:
                continue
            url = re.sub(r"\{[^}]+\}", "x", path)
            for method in operations:
                if client.request(method, url).status_code != 401:
                    found.append(f"{method.upper()} {path}")
    return found


def test_every_operation_is_public_or_gym_scoped() -> None:
    assert unscoped_routes(create_app(make_settings(database_url=UNREACHABLE_DB))) == []


def test_the_route_check_catches_an_operation_without_a_tenant() -> None:
    assert unscoped_routes(tenant_app(UNREACHABLE_DB)) == ["GET /test/unscoped-setting"]


def test_no_tenant_is_a_401_before_any_database_work() -> None:
    # The database is unreachable: a 401 rather than a 500 means no session was opened.
    with TestClient(tenant_app(UNREACHABLE_DB)) as client:
        response = client.get("/test/rows/plan")
    assert response.status_code == 401


# --- against real Postgres -------------------------------------------------------


@dataclass(frozen=True)
class Gyms:
    sur: uuid.UUID
    norte: uuid.UUID
    shared: uuid.UUID  # a member of both gyms
    orphan: uuid.UUID  # in no gym


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def gyms(db: Database) -> Gyms:
    sur, norte = seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")
    shared, orphan = uuid.uuid4(), uuid.uuid4()

    # As the superuser, which skips RLS, to write across both gyms at once.
    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "INSERT INTO person (id, name) VALUES ($1, 'shared'), ($2, 'orphan')", shared, orphan
        )
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) SELECT id, $1, 'shared' FROM gym",
            shared,
        )
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $1, id, 'active' FROM plan",
            shared,
        )

    run(db.admin_url, query)
    return Gyms(sur, norte, shared, orphan)


@pytest.fixture(scope="module")
def client(db: Database, gyms: Gyms) -> Iterator[TestClient]:
    with TestClient(tenant_app(db.api_url)) as c:
        yield c


def gym_ids(client: TestClient, gym_id: uuid.UUID, table: str) -> set[str]:
    response = client.get(f"/test/rows/{table}", headers=as_gym(gym_id))
    assert response.status_code == 200
    column = "id" if table == "gym" else "gym_id"
    return {row[column] for row in response.json()}


def people(client: TestClient, gym_id: uuid.UUID) -> set[uuid.UUID]:
    response = client.get("/test/rows/person", headers=as_gym(gym_id))
    assert response.status_code == 200
    return {uuid.UUID(row["id"]) for row in response.json()}


def staff_of(client: TestClient, gym_id: uuid.UUID) -> uuid.UUID:
    [row] = client.get("/test/rows/staff", headers=as_gym(gym_id)).json()
    return uuid.UUID(row["person_id"])


pg = pytest.mark.postgres


@pg
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_an_endpoint_sees_only_its_gyms_rows(client: TestClient, gyms: Gyms, table: str) -> None:
    assert gym_ids(client, gyms.sur, table) == {str(gyms.sur)}
    assert gym_ids(client, gyms.norte, table) == {str(gyms.norte)}


@pg
def test_people_are_visible_only_in_gyms_they_belong_to(client: TestClient, gyms: Gyms) -> None:
    sur_owner, norte_owner = staff_of(client, gyms.sur), staff_of(client, gyms.norte)

    assert people(client, gyms.sur) == {sur_owner, gyms.shared}
    assert people(client, gyms.norte) == {norte_owner, gyms.shared}


@pg
def test_the_gym_is_set_for_the_transaction_only(client: TestClient, gyms: Gyms) -> None:
    scoped = client.get("/test/setting", headers=as_gym(gyms.sur)).json()
    unscoped = client.get("/test/unscoped-setting", headers=as_gym(gyms.sur)).json()

    assert scoped["gym"] == str(gyms.sur)
    # Same pooled connection, and the setting did not outlive the request's transaction.
    assert unscoped["pid"] == scoped["pid"]
    assert unscoped["gym"] in (None, "")


@pg
def test_a_write_commits_and_a_failed_request_rolls_back(
    client: TestClient, gyms: Gyms, db: Database
) -> None:
    count = "SELECT count(*) AS n FROM plan WHERE kind = 'dropin'"

    def dropins() -> int:
        return int(run(db.api_url, in_gym(gyms.norte, count))[0]["n"])

    before = dropins()
    assert client.post("/test/plans", headers=as_gym(gyms.norte)).status_code == 200
    assert dropins() == before + 1
    assert client.post("/test/plans?fail=true", headers=as_gym(gyms.norte)).status_code == 409
    assert dropins() == before + 1


# --- the person policy, query by query (migration 0003) ---------------------------


@pg
@pytest.mark.parametrize("user", ["api", "owner"])
def test_no_person_is_visible_without_a_gym(db: Database, gyms: Gyms, user: str) -> None:
    url = db.api_url if user == "api" else db.owner_url
    assert run(url, in_gym(None, "SELECT id FROM person")) == []


@pg
def test_a_person_in_another_gym_cannot_be_read_by_id(db: Database, gyms: Gyms) -> None:
    norte_owner = run(db.api_url, in_gym(gyms.norte, "SELECT person_id FROM staff"))[0][0]
    assert (
        run(db.api_url, in_gym(gyms.sur, "SELECT id FROM person WHERE id = $1", norte_owner)) == []
    )


@pg
def test_no_gym_can_update_a_person(db: Database, gyms: Gyms) -> None:
    # Not even one of its own: a gym edits its `gym_person` record (migration 0004).
    rename = "UPDATE person SET name = 'x' WHERE id = $1"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(db.api_url, in_gym(gyms.sur, rename, gyms.shared))


@pg
@pytest.mark.parametrize("column", ["name", "email", "rut", "dob", "created_at"])
def test_a_gym_reads_only_a_persons_id_and_phone(db: Database, gyms: Gyms, column: str) -> None:
    # What another gym entered, or when the phone was first seen, would leak.
    query = f"SELECT {column} FROM person WHERE id = $1"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(db.api_url, in_gym(gyms.sur, query, gyms.shared))


@pg
def test_a_person_can_be_created_and_joined_in_one_transaction(db: Database, gyms: Gyms) -> None:
    person_id = uuid.uuid4()

    async def join(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gyms.sur))
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'new')", person_id)
            assert await conn.fetch("SELECT FROM person WHERE id = $1", person_id) == []
            # The gym's record of them is what joins them (migration 0004).
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'new')",
                gyms.sur,
                person_id,
            )
            return await conn.fetch("SELECT id FROM person WHERE id = $1", person_id)

    assert [r["id"] for r in run(db.api_url, join)] == [person_id]
    assert run(db.api_url, in_gym(gyms.norte, "SELECT FROM person WHERE id = $1", person_id)) == []


@pg
def test_returning_a_new_person_before_they_join_is_refused(db: Database, gyms: Gyms) -> None:
    # RETURNING is held to the read policy: generate ids client-side instead.
    insert = "INSERT INTO person (name) VALUES ('new') RETURNING id"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(db.api_url, in_gym(gyms.sur, insert))
