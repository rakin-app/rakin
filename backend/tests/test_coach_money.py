"""Coaches never see money, in the screens or in what the API sends them (#205).

The owner "will not share finances with part-time coaches" (`app.roles`). The ledger
endpoints refuse a coach outright; the ones a coach may read, such as plans and
memberships, leave out prices and discounts for them. This walks every GET the API
has, as the demo gym's coach, and looks for a money key anywhere in the answer.
"""

import re
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.seed import Loaded, load
from app.seed.build import GYM_ID, seed_id
from app.seed.data import COACH
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, throwaway_database

pg = pytest.mark.postgres

COACH_ID = seed_id("person", COACH)

# Amounts, prices, discounts, balances and ledger references, by key name.
MONEY = re.compile(r"clp|amount|price|discount|balance|owed|ledger|paid", re.IGNORECASE)

# Not the gym's staff screens, so not this rule's: the person's own student page (a
# coach who trains pays like anyone), the public pages a link opens, and the plumbing.
NOT_STAFF = re.compile(
    r"^(/api/me/|/api/join/\{token\}|/api/mail/|/api/auth/|/api/blobs/|/api/host"
    r"|/healthz|/internal/)"
)


def money_keys(value: Any, path: str = "") -> list[str]:
    """Every key in a JSON value that names money, as a dotted path."""
    if isinstance(value, dict):
        found = []
        for key, inner in value.items():
            where = f"{path}.{key}" if path else key
            if MONEY.search(key):
                found.append(where)
            found += money_keys(inner, where)
        return found
    if isinstance(value, list):
        return [k for item in value for k in money_keys(item, f"{path}[]")]
    return []


def test_money_keys_finds_nested_keys() -> None:
    body = [{"name": "x", "price_clp": 1, "membership": {"discount_pct": 0, "overdue": True}}]
    assert money_keys(body) == ["[].price_clp", "[].membership.discount_pct"]


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def loaded(db: Database) -> Loaded:
    async def go(conn: asyncpg.Connection) -> Loaded:
        return await load(conn, None)

    result: Loaded = run(db.owner_url, go)
    return result


@pytest.fixture(scope="module")
def client(db: Database, loaded: Loaded) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def ids(loaded: Loaded) -> dict[str, str]:
    """A real id for each path or query parameter the staff GETs take."""
    seed = loaded.seed
    membership = seed.memberships[0]
    plan = next(p for p in seed.plans if p["price_clp"])
    unknown = str(uuid.uuid4())  # for the endpoints a coach is refused anyway
    return {
        "person_id": str(membership["person_id"]),
        "membership_id": str(membership["id"]),
        "plan_id": str(plan["id"]),
        "session_id": str(seed.sessions[0]["id"]),
        "class_type_id": str(seed.class_types[0]["id"]),
        "program_id": str(seed.programs[0]["id"]),
        "group_id": unknown,
        "charge_id": unknown,
        "line_id": unknown,
    }


def staff_gets(client: TestClient, values: dict[str, str]) -> Iterator[str]:
    """Every staff GET in the API, its parameters filled in."""
    for path, operations in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        get = operations.get("get")
        if get is None or NOT_STAFF.match(path):
            continue
        query = {
            p["name"]: values[p["name"]]
            for p in get.get("parameters", [])
            if p["in"] == "query" and p.get("required")
        }
        url = path.format(**values)
        if query:
            url += "?" + "&".join(f"{k}={v}" for k, v in query.items())
        yield url


@pg
def test_no_get_a_coach_can_call_sends_money(client: TestClient, loaded: Loaded) -> None:
    headers = as_gym(GYM_ID, COACH_ID)
    answered, leaks = [], {}
    for url in staff_gets(client, ids(loaded)):
        response = client.get(url, headers=headers)
        # A 404 or 422 would mean the walk filled a parameter wrong and checked nothing.
        assert response.status_code in (200, 403), (url, response.status_code, response.text)
        if response.status_code == 200:
            answered.append(url)
            if found := money_keys(response.json()):
                leaks[url] = found
    assert leaks == {}
    # The screens a coach works in: the walk did reach them.
    assert {"/api/plans", "/api/people", "/api/sessions"} <= set(answered)
    assert any(url.startswith("/api/memberships?") for url in answered)


@pg
def test_an_admin_still_sees_prices_and_discounts(client: TestClient, loaded: Loaded) -> None:
    values = ids(loaded)
    plan = client.get(f"/api/plans/{values['plan_id']}", headers=as_gym(GYM_ID, admin(loaded)))
    assert plan.json()["price_clp"] > 0
    membership = client.get(
        f"/api/memberships/{values['membership_id']}", headers=as_gym(GYM_ID, admin(loaded))
    )
    assert "discount_pct" in membership.json()


def admin(loaded: Loaded) -> uuid.UUID:
    return uuid.UUID(
        str(next(s["person_id"] for s in loaded.seed.staff if s["role"] in ("owner", "admin")))
    )
