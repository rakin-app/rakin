"""Per-gym roles: each role against each endpoint group, at the API and at RLS.

Permissions follow the role in the gym the request acts in, not the person: the
same person is the owner of one gym and a plain member of another here. The ledger
group is a test router over `LedgerSession`, since its real endpoints come later
(#35-#39); the people API is the staff group.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from alembic import command
from app.main import create_app
from app.roles import LedgerSession, StaffSession
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    throwaway_database,
)
from tests.test_tenancy import PUBLIC_PATHS

pytestmark = pytest.mark.postgres

LEDGER = "SELECT id, gym_id FROM ledger_entry"

router = APIRouter(prefix="/test")


@router.get("/ledger")
async def ledger(session: LedgerSession) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in await session.execute(text(LEDGER))]


@router.get("/ledger-unchecked")
async def ledger_unchecked(session: StaffSession) -> list[dict[str, Any]]:
    # The wrong session for the ledger, as a mistaken endpoint would take: RLS still holds.
    return [dict(r._mapping) for r in await session.execute(text(LEDGER))]


@dataclass(frozen=True)
class Sur:
    gym: uuid.UUID
    norte: uuid.UUID
    by_role: dict[str, uuid.UUID]  # owner, admin, coach, member: who holds it in Sur
    norte_owner_member_of_sur: uuid.UUID


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


async def join(
    conn: asyncpg.Connection, gym: uuid.UUID, person: uuid.UUID, role: str | None
) -> None:
    """This gym's record of `person`, and a staff row in `role`, or a membership."""
    await conn.execute(
        "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, person
    )
    if role is None:
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $1, id, 'active' FROM plan WHERE gym_id = $2",
            person,
            gym,
        )
    else:
        await conn.execute(
            "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)", gym, person, role
        )


@pytest.fixture(scope="module")
def sur(db: Database) -> Sur:
    gym, norte = seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")
    admin, coach, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    both = seeded_owner(norte)

    # As the superuser, which skips RLS, to write across both gyms at once.
    async def query(conn: asyncpg.Connection) -> None:
        for person in (admin, coach, member):
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
        await join(conn, gym, admin, "admin")
        await join(conn, gym, coach, "coach")
        await join(conn, gym, member, None)
        await join(conn, gym, both, None)

    run(db.admin_url, query)
    by_role = {"owner": seeded_owner(gym), "admin": admin, "coach": coach, "member": member}
    return Sur(gym, norte, by_role, both)


@pytest.fixture(scope="module")
def client(db: Database, sur: Sur) -> Iterator[TestClient]:
    app: FastAPI = create_app(make_settings(database_url=db.api_url))
    app.include_router(router)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def sur_ledger(db: Database, sur: Sur) -> set[str]:
    rows = run(
        db.admin_url, lambda c: c.fetch("SELECT id FROM ledger_entry WHERE gym_id = $1", sur.gym)
    )
    return {str(r["id"]) for r in rows}


# --- the API: role x endpoint group -----------------------------------------------

# What each role gets from each group: the staff group is every staff role, the
# ledger group owner and admin.
ALLOWED = {
    ("people", "owner"): True,
    ("people", "admin"): True,
    ("people", "coach"): True,
    ("people", "member"): False,
    ("ledger", "owner"): True,
    ("ledger", "admin"): True,
    ("ledger", "coach"): False,
    ("ledger", "member"): False,
}


def call(client: TestClient, group: str, gym: uuid.UUID, person: uuid.UUID) -> Any:
    # The people group reads the caller's own record, which every gym has of them.
    url = f"/api/people/{person}" if group == "people" else "/test/ledger"
    return client.get(url, headers=as_gym(gym, person))


@pytest.mark.parametrize(("group", "role"), sorted(ALLOWED), ids="-".join)
def test_each_role_in_each_endpoint_group(
    client: TestClient, db: Database, sur: Sur, group: str, role: str
) -> None:
    response = call(client, group, sur.gym, sur.by_role[role])
    if not ALLOWED[(group, role)]:
        assert response.status_code == 403
        return
    assert response.status_code == 200
    if group == "ledger":
        assert {r["id"] for r in response.json()} == sur_ledger(db, sur)


@pytest.mark.parametrize("group", ["people", "ledger"])
def test_the_role_is_the_one_in_the_current_gym(client: TestClient, sur: Sur, group: str) -> None:
    # Owner at Norte, so allowed there; a member at Sur, so refused there.
    person = sur.norte_owner_member_of_sur
    assert call(client, group, sur.norte, person).status_code == 200
    assert call(client, group, sur.gym, person).status_code == 403


@pytest.mark.parametrize(("role", "sees"), [("admin", True), ("coach", False)])
def test_rls_hides_the_ledger_from_an_endpoint_that_forgot_the_role(
    client: TestClient, db: Database, sur: Sur, role: str, sees: bool
) -> None:
    response = client.get("/test/ledger-unchecked", headers=as_gym(sur.gym, sur.by_role[role]))
    assert response.status_code == 200
    assert {r["id"] for r in response.json()} == (sur_ledger(db, sur) if sees else set())


def test_every_gym_operation_refuses_a_member(client: TestClient, sur: Sur) -> None:
    # A member's session has a gym but no staff role: every staff endpoint is a 403, so
    # one added without a role-checked session fails here.
    allowed = []
    app: FastAPI = client.app  # type: ignore[assignment]
    member = as_gym(sur.gym, sur.by_role["member"])
    for path, operations in app.openapi()["paths"].items():
        if path in PUBLIC_PATHS or path.startswith("/test/"):
            continue
        url = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            if client.request(method, url, headers=member).status_code != 403:
                allowed.append(f"{method.upper()} {path}")
    assert allowed == []


# --- RLS on its own (migration 0006) ----------------------------------------------


@pytest.mark.parametrize(
    ("role", "sees"), [("owner", True), ("admin", True), ("coach", False), ("member", False)]
)
def test_the_api_reads_the_ledger_only_as_owner_or_admin(
    db: Database, sur: Sur, role: str, sees: bool
) -> None:
    rows = run(db.api_url, in_gym(sur.gym, LEDGER, person=sur.by_role[role]))
    assert {str(r["id"]) for r in rows} == (sur_ledger(db, sur) if sees else set())


def test_the_api_reads_no_ledger_for_no_person(db: Database, sur: Sur) -> None:
    assert run(db.api_url, in_gym(sur.gym, LEDGER)) == []


def test_an_owner_elsewhere_reads_no_ledger_here(db: Database, sur: Sur) -> None:
    # Norte's owner, acting in Sur, where they are a member.
    assert run(db.api_url, in_gym(sur.gym, LEDGER, person=sur.norte_owner_member_of_sur)) == []


def test_the_owner_role_still_reads_the_ledger_for_no_person(db: Database, sur: Sur) -> None:
    # The seed and the nightly jobs act for no one; the gym alone scopes them.
    rows = run(db.owner_url, in_gym(sur.gym, LEDGER))
    assert {str(r["id"]) for r in rows} == sur_ledger(db, sur)


PAYMENT = (
    "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, method)"
    " SELECT gym_id, id, 45000, 'payment', 'cash' FROM membership WHERE gym_id = $1 LIMIT 1"
)


def test_a_coach_cannot_write_the_ledger(db: Database, sur: Sur) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(db.api_url, in_gym(sur.gym, PAYMENT, sur.gym, person=sur.by_role["coach"]))


def test_a_coach_cannot_settle_an_entry(db: Database, sur: Sur) -> None:
    before = sur_ledger(db, sur)
    run(db.api_url, in_gym(sur.gym, PAYMENT, sur.gym, person=sur.by_role["admin"]))
    [entry] = sur_ledger(db, sur) - before
    settle = "UPDATE ledger_entry SET status = 'validated' WHERE id = $1 RETURNING id"

    assert (
        run(db.api_url, in_gym(sur.gym, settle, uuid.UUID(entry), person=sur.by_role["coach"]))
        == []
    )
    status = "SELECT status FROM ledger_entry WHERE id = $1"
    assert run(db.admin_url, lambda c: c.fetchval(status, uuid.UUID(entry))) == "pending"


def test_downgrade_to_0005_gives_the_api_the_ledger_by_gym_again() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        gym = seed_gym(scratch, "academia-sur")
        command.downgrade(scratch.alembic(), "0005")
        assert len(run(scratch.api_url, in_gym(gym, LEDGER))) == 1
        migrate(scratch)
        assert run(scratch.api_url, in_gym(gym, LEDGER)) == []
