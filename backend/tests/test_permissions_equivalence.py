"""Permissions behind the roles changed nobody's access (#308).

Every operation of the app is called as the owner, an admin and a coach, and must
answer the status it answered before permissions moved underneath the roles:
`fixtures/role_statuses.json`, recorded by this module run against the code of the
commit #308 started from (`python -m tests.test_permissions_equivalence <url>`). The
module imports nothing #308 added, so it runs there unchanged.

Path parameters get a placeholder of their type, and no body is sent, so an operation
the person may use answers its own 404 or 422 and one they may not a 403. An operation
added after #308 has no recorded status and is skipped, unless it joins the recording
with the statuses it answers, as `GET /api/summary` did (#505) and Gastos's and
Finanzas' did (#314, #316: the titular alone, an admin and a coach a 403) once the app
had grown past what the 90% coverage check allows, and Gastos fijos' (#315) and the
expenses' CSV (#317) did; one whose access changes on purpose (#310 onwards) records
the module again.
"""

import json
import re
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, make_staff, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_tenancy import PUBLIC_PATHS

pytestmark = pytest.mark.postgres

RECORDED = Path(__file__).with_name("fixtures") / "role_statuses.json"
ROLES = ("owner", "admin", "coach")
# Nobody's id, so an operation on one finds nothing.
NOBODY = "00000000-0000-4000-8000-000000000000"


def operations(app: FastAPI) -> list[tuple[str, str, str]]:
    """Each operation outside `PUBLIC_PATHS` and the platform's panel: its key, method
    and placeholder URL. The panel's routes answer no gym role at all, only an operator
    (#433), so a gym's roles have nothing to answer the same there."""
    found = []
    for path, ops in app.openapi()["paths"].items():
        if path in PUBLIC_PATHS or path.startswith("/api/platform/"):
            continue
        for method, op in ops.items():
            formats = {
                p["name"]: p.get("schema", {})
                for p in op.get("parameters", [])
                if p["in"] == "path"
            }

            def placeholder(match: re.Match[str], formats: dict[str, Any] = formats) -> str:
                schema = formats.get(match.group(1), {})
                if schema.get("format") == "uuid":
                    return NOBODY
                return "0" if schema.get("type") == "integer" else "x"

            url = re.sub(r"\{([^}]+)\}", placeholder, path)
            found.append((f"{method.upper()} {path}", method, url))
    return found


def staff_gym(db: Database) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """A gym with its owner, an admin and a coach, each with their record."""
    gym = seed_gym(db, "academia-sur")
    people = {"owner": seeded_owner(gym), "admin": uuid.uuid4(), "coach": uuid.uuid4()}

    async def query(conn: asyncpg.Connection) -> None:
        for role in ("admin", "coach"):
            person = people[role]
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, $2)", person, role)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, $3)",
                gym,
                person,
                role,
            )
            await make_staff(conn, gym, person, role)

    run(db.admin_url, query)
    return gym, people


def statuses(db: Database) -> dict[str, dict[str, int]]:
    """What each operation answers each role, in the database `db`."""
    gym, people = staff_gym(db)
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    answers: dict[str, dict[str, int]] = {}
    with TestClient(app, raise_server_exceptions=False) as client:
        for key, method, url in operations(app):
            answers[key] = {
                role: client.request(method, url, headers=as_gym(gym, people[role])).status_code
                for role in ROLES
            }
    return answers


@pytest.fixture(scope="module")
def answered() -> Iterator[dict[str, dict[str, int]]]:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db)
        yield statuses(db)


def recorded() -> dict[str, dict[str, int]]:
    return json.loads(RECORDED.read_text())  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "operation", [key for key, _, _ in operations(create_app(make_settings()))]
)
def test_each_operation_answers_each_role_as_before(
    answered: dict[str, dict[str, int]], operation: str
) -> None:
    before = recorded().get(operation)
    if before is None:
        pytest.skip(f"{operation} came after #308")
    assert answered[operation] == before


def test_the_recording_covers_the_app_as_it_was() -> None:
    # Most of the app was there before #308: a recording that misses much of it is stale.
    keys = {key for key, _, _ in operations(create_app(make_settings()))}
    assert len(keys & recorded().keys()) > 0.9 * len(keys)


if __name__ == "__main__":
    # The recording: `python -m tests.test_permissions_equivalence <superuser url>`.
    with throwaway_database(sys.argv[1]) as database:
        migrate(database)
        answers = statuses(database)
    RECORDED.write_text(json.dumps(answers, indent=2, sort_keys=True) + "\n")
    print(f"{len(answers)} operations recorded in {RECORDED}")
