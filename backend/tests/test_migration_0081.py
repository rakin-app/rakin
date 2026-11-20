"""Migration 0081: the record of each acceptance of the terms (#499).

A row is never changed or deleted, whoever tries, the table owner too, but for the time
its copy was emailed, once. The API reads and writes it only through its functions, the
titular alone accepting, and the hash is taken in the database over what it stores. A
gym already here with a signature counts as having accepted before, and a downgrade puts
0077's, 0078's and 0079's functions back.
"""

import hashlib
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres

VERSION = "2026-11-20"


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def accept(db: Database, gym: uuid.UUID, person: uuid.UUID, html: str = "<p>x</p>") -> Any:
    return run(
        db.api_url,
        in_gym(
            gym,
            "SELECT * FROM app_accept_terms($1, $1, $2, $2, 'acepto', 'acepto', '{Hetzner}',"
            " '{}'::jsonb, 'a@b.cl', now(), '203.0.113.1', 'ua')",
            VERSION,
            html,
            person=person,
        ),
    )


def state(db: Database, gym: uuid.UUID) -> str:
    [row] = run(db.api_url, in_gym(gym, "SELECT app_terms_state($1, $1) AS s", VERSION))
    return str(row["s"])


def test_the_titular_accepts_and_the_hash_is_of_what_is_stored(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"), accepted=False)
    assert state(db, gym) == "pending"
    html = "<p>Términos ñ</p>"
    [made] = accept(db, gym, seeded_owner(gym), html)
    [row] = run(
        db.admin_url,
        lambda c: c.fetch("SELECT * FROM terms_acceptance WHERE id = $1", made["id"]),
    )
    assert bytes(row["service_sha256"]) == hashlib.sha256(html.encode()).digest()
    assert state(db, gym) == "current"


def test_only_the_titular_accepts(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"), accepted=False)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="only the titular"):
        accept(db, gym, uuid.uuid4())
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="only the titular"):
        run(db.api_url, in_gym(gym, "SELECT * FROM app_terms_acceptances()", person=uuid.uuid4()))


def test_the_api_never_reads_the_table_itself(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    for table in ("terms_acceptance", "gym_terms"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(gym, f"SELECT * FROM {table}"))
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(gym, f"DELETE FROM {table}"))


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE terms_acceptance SET processor_version = '2026-01-01'",
        "UPDATE terms_acceptance SET copy_sent_at = now(), service_html = 'otro'",
        "DELETE FROM terms_acceptance",
        "TRUNCATE terms_acceptance",
    ],
)
def test_a_row_is_never_changed_even_by_the_owner(db: Database, sql: str) -> None:
    gym = seed_gym(db, unique_slug("norte"))
    with pytest.raises(asyncpg.RestrictViolationError, match="never changed or deleted"):
        run(db.owner_url, in_gym(gym, sql))


def test_the_copy_is_marked_sent_once(db: Database) -> None:
    gym = seed_gym(db, unique_slug("norte"), accepted=False)
    [made] = accept(db, gym, seeded_owner(gym))

    def sent(message: str) -> bool:
        [row] = run(
            db.api_url,
            in_gym(gym, "SELECT app_terms_copy_sent($1, $2) AS sent", made["id"], message),
        )
        return bool(row["sent"])

    assert sent("<1@rakin.app>")
    assert not sent("<2@rakin.app>")
    [row] = run(
        db.admin_url,
        lambda c: c.fetch("SELECT copy_message_id FROM terms_acceptance WHERE id = $1", made["id"]),
    )
    assert row["copy_message_id"] == "<1@rakin.app>"


def test_another_gym_sees_none_of_them(db: Database) -> None:
    ours = seed_gym(db, unique_slug("norte"))
    other = seed_gym(db, unique_slug("sur"))
    rows = run(
        db.api_url,
        in_gym(other, "SELECT * FROM app_terms_acceptances()", person=seeded_owner(other)),
    )
    assert len(rows) == 1
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.owner_url,
            in_gym(
                other,
                "INSERT INTO terms_acceptance (gym_id, channel, processor_version, signed_on)"
                " VALUES ($1, 'outside', $2, current_date)",
                ours,
                VERSION,
            ),
        )


def test_a_gym_signed_before_is_outdated_and_the_downgrade_restores_the_panel() -> None:
    with throwaway_database(require_test_database_url()) as db:
        migrate(db, "0080")
        gym = seed_gym(db, unique_slug("meta"))
        run(
            db.owner_url,
            in_gym(
                gym,
                "INSERT INTO processor_terms (gym_id, version, signed_on)"
                " VALUES ($1, '2026-11-19', '2026-11-19')",
                gym,
            ),
        )
        migrate(db)
        assert state(db, gym) == "outdated"

        command.downgrade(db.alembic(), "0080")
        functions = run(
            db.admin_url,
            lambda c: c.fetch(
                "SELECT p.proname, pg_get_function_identity_arguments(p.oid) AS args"
                " FROM pg_proc p WHERE p.proname LIKE 'platform_%' OR p.proname LIKE 'app_terms%'"
            ),
        )
        found = {(f["proname"], f["args"]) for f in functions}
        assert ("platform_gyms", "session bytea, current_terms text") in found
        assert ("platform_gym", "session bytea, gym uuid") in found
        assert not any(name.startswith("app_terms") for name, _ in found)
        tables = run(
            db.admin_url,
            lambda c: c.fetch("SELECT to_regclass('terms_acceptance') AS t"),
        )
        assert tables[0]["t"] is None
        command.upgrade(db.alembic(), "head")
        assert state(db, gym) == "outdated"
