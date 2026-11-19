"""Migration 0076: platform operators, their sign-in and their log (#436).

As the API's role, `rakin_app`: the platform's tables are out of reach, and every
function that reads a gym refuses a session that is not an operator's live one. The
log keeps every row, the owner's attempts to change one included.
"""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres

TERMS = "2026-11-18"


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def digest(word: str) -> bytes:
    return hashlib.sha256(word.encode()).digest()


def operator(db: Database, email: str = "ops@example.cl") -> uuid.UUID:
    operator_id: uuid.UUID = run(
        db.owner_url,
        lambda c: c.fetchval(
            "INSERT INTO platform_operator (email, name) VALUES ($1, 'Ops') RETURNING id", email
        ),
    )
    return operator_id


def signed_in(db: Database, email: str = "ops@example.cl") -> bytes:
    """A live session's hash, signed in through the API's functions."""
    link, session = digest(uuid.uuid4().hex), digest(uuid.uuid4().hex)

    async def query(conn: asyncpg.Connection) -> None:
        now = datetime.now(UTC)
        assert await conn.fetch(
            "SELECT * FROM platform_issue_link($1, $2, NULL, $3)",
            email,
            link,
            now + timedelta(minutes=15),
        )
        assert await conn.fetchval("SELECT platform_redeem_link($1, NULL, $2)", link, session)

    run(db.api_url, query)
    return session


def as_app(db: Database, sql: str, *args: Any) -> Any:
    return run(db.api_url, lambda c: c.fetch(sql, *args))


def test_the_role_is_bootstrapped_as_the_auth_one_is(db: Database) -> None:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT rolbypassrls, rolsuper, rolcanlogin FROM pg_roles"
            " WHERE rolname = 'rakin_platform'"
        ),
    )
    assert tuple(row) == (True, False, False)


@pytest.mark.parametrize(
    "table", ["platform_operator", "operator_link", "operator_session", "platform_event"]
)
def test_the_app_reads_none_of_the_platform_tables(db: Database, table: str) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(db, f"SELECT * FROM {table}")


def test_the_app_writes_no_operator(db: Database) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(db, "INSERT INTO platform_operator (email, name) VALUES ('x@example.cl', 'X')")


def test_the_app_cannot_call_the_gate_itself(db: Database) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(db, "SELECT platform_operator_of($1, NULL)", digest("x"))


def test_the_gyms_need_a_live_operator_session(db: Database) -> None:
    seed_gym(db, unique_slug("g"))
    operator(db)
    session = signed_in(db)
    assert len(as_app(db, "SELECT * FROM platform_gyms($1, $2)", session, TERMS)) == 1

    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
        as_app(db, "SELECT * FROM platform_gyms($1, $2)", digest("bogus"), TERMS)

    as_app(db, "SELECT platform_end_session($1)", session)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
        as_app(db, "SELECT * FROM platform_gyms($1, $2)", session, TERMS)


def test_a_session_past_its_hours_or_of_a_revoked_operator_is_dead(db: Database) -> None:
    operator_id = operator(db)
    expired, revoked = signed_in(db), signed_in(db)
    run(
        db.owner_url,
        lambda c: c.execute(
            "UPDATE operator_session SET expires_at = now() - interval '1 second'"
            " WHERE token_hash = $1",
            expired,
        ),
    )
    assert as_app(db, "SELECT * FROM platform_live_session($1)", expired) == []
    assert len(as_app(db, "SELECT * FROM platform_live_session($1)", revoked)) == 1

    run(
        db.owner_url,
        lambda c: c.execute(
            "UPDATE platform_operator SET revoked_at = now() WHERE id = $1", operator_id
        ),
    )
    assert as_app(db, "SELECT * FROM platform_live_session($1)", revoked) == []
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        as_app(db, "SELECT * FROM platform_gyms($1, $2)", revoked, TERMS)


def test_a_session_lasts_eight_hours_from_sign_in(db: Database) -> None:
    operator(db)
    session = signed_in(db)
    [row] = run(
        db.owner_url,
        lambda c: c.fetch(
            "SELECT expires_at - created_at AS lasts, fresh_at = created_at AS fresh"
            " FROM operator_session WHERE token_hash = $1",
            session,
        ),
    )
    assert (row["lasts"], row["fresh"]) == (timedelta(hours=8), True)


def test_no_link_for_an_address_that_is_no_live_operator(db: Database) -> None:
    operator(db, "ops@example.cl")
    expires = datetime.now(UTC) + timedelta(minutes=15)
    for address in ("nadie@example.cl", "otro@example.cl"):
        found = as_app(
            db,
            "SELECT * FROM platform_issue_link($1, $2, NULL, $3)",
            address,
            digest(address),
            expires,
        )
        assert found == []
    # Case and spaces aside, it is the operator's.
    assert as_app(
        db,
        "SELECT name FROM platform_issue_link($1, $2, NULL, $3)",
        " Ops@Example.CL ",
        digest("ops"),
        expires,
    ) == [("Ops",)]
    assert run(db.owner_url, lambda c: c.fetchval("SELECT count(*) FROM operator_link")) == 1


def test_a_link_and_its_code_are_spent_together(db: Database) -> None:
    operator(db)
    link, code = digest("link"), digest("code")
    now = datetime.now(UTC)
    as_app(
        db,
        "SELECT * FROM platform_issue_link($1, $2, $3, $4)",
        "ops@example.cl",
        link,
        code,
        now + timedelta(minutes=15),
    )
    redeem = "SELECT platform_redeem_link($1, $2, $3) AS ok"
    assert as_app(db, redeem, None, code, digest("s1")) == [(True,)]
    assert as_app(db, redeem, link, None, digest("s2")) == [(False,)]


def test_asking_again_ends_the_earlier_code(db: Database) -> None:
    operator(db)
    now = datetime.now(UTC)
    for word in ("first", "second"):
        as_app(
            db,
            "SELECT * FROM platform_issue_link($1, $2, $3, $4)",
            "ops@example.cl",
            digest(word),
            digest(f"code {word}"),
            now + timedelta(minutes=15),
        )
    redeem = "SELECT platform_redeem_link(NULL, $1, $2) AS ok"
    assert as_app(db, redeem, digest("code first"), digest("s1")) == [(False,)]
    assert as_app(db, redeem, digest("code second"), digest("s2")) == [(True,)]


def test_an_expired_link_starts_nothing(db: Database) -> None:
    operator(db)
    now = datetime.now(UTC)
    as_app(
        db,
        "SELECT * FROM platform_issue_link($1, $2, NULL, $3)",
        "ops@example.cl",
        digest("old"),
        now + timedelta(minutes=15),
    )
    redeem = "SELECT platform_redeem_link($1, NULL, $2) AS ok"
    run(
        db.owner_url,
        lambda c: c.execute(
            "UPDATE operator_link SET expires_at = now() - interval '1 second'"
            " WHERE token_hash = $1",
            digest("old"),
        ),
    )
    assert as_app(db, redeem, digest("old"), digest("s")) == [(False,)]


def test_refresh_spends_a_code_of_the_sessions_operator(db: Database) -> None:
    operator(db, "ops@example.cl")
    operator(db, "otra@example.cl")
    session = signed_in(db)
    now = datetime.now(UTC)
    for address, code in (("ops@example.cl", "mine"), ("otra@example.cl", "theirs")):
        as_app(
            db,
            "SELECT * FROM platform_issue_link($1, $2, $3, $4)",
            address,
            digest(f"link {code}"),
            digest(code),
            now + timedelta(minutes=15),
        )
    # Signed in a while ago: the proof is stale until a code renews it.
    run(
        db.owner_url,
        lambda c: c.execute(
            "UPDATE operator_session SET fresh_at = now() - interval '1 hour'"
            " WHERE token_hash = $1",
            session,
        ),
    )
    refresh = "SELECT platform_refresh($1, $2) AS ok"
    assert as_app(db, refresh, session, digest("theirs")) == [(False,)]
    assert as_app(db, refresh, session, digest("mine")) == [(True,)]
    assert as_app(db, refresh, session, digest("mine")) == [(False,)]
    [row] = as_app(
        db,
        "SELECT fresh_at > now() - interval '1 minute' AS fresh FROM platform_live_session($1)",
        session,
    )
    assert row["fresh"]


def test_signing_in_and_out_is_logged(db: Database) -> None:
    operator_id = operator(db)
    session = signed_in(db)
    as_app(db, "SELECT platform_end_session($1)", session)
    as_app(db, "SELECT platform_end_session($1)", session)  # once ended, nothing more
    rows = run(
        db.owner_url,
        lambda c: c.fetch("SELECT operator_id, action FROM platform_event ORDER BY at, action"),
    )
    assert [tuple(r) for r in rows] == [
        (operator_id, "operator_signed_in"),
        (operator_id, "operator_signed_out"),
    ]


def test_the_log_is_append_only_even_for_the_owner(db: Database) -> None:
    operator(db)
    signed_in(db)
    for sql in (
        "UPDATE platform_event SET action = 'operator_signed_out'",
        "DELETE FROM platform_event",
        "TRUNCATE platform_event",
    ):
        with pytest.raises(asyncpg.RestrictViolationError):
            run(db.owner_url, in_gym(None, sql))
    for sql in ("UPDATE platform_event SET gym_id = NULL", "DELETE FROM platform_event"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            as_app(db, sql)


def test_an_event_with_no_operator_is_the_command_lines(db: Database) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.owner_url,
            lambda c: c.execute("INSERT INTO platform_event (action) VALUES ('operator_granted')"),
        )
    run(
        db.owner_url,
        lambda c: c.execute(
            "INSERT INTO platform_event (action, detail)"
            """ VALUES ('operator_granted', '{"by": "cli"}')"""
        ),
    )


def test_a_downgrade_removes_it_all(db: Database) -> None:
    command.downgrade(db.alembic(), "0075")
    names = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT proname FROM pg_proc WHERE proname LIKE 'platform%'"
            " UNION ALL SELECT relname FROM pg_class WHERE relname IN"
            " ('platform_operator', 'operator_link', 'operator_session', 'platform_event')"
        ),
    )
    assert names == []
    migrate(db)


def test_the_functions_keep_one_clock_the_databases(db: Database) -> None:
    # No gate takes a time from the API: a skewed API clock cannot make a session live
    # to one function and dead to the next.
    timed = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT proname FROM pg_proc WHERE proname LIKE 'platform%'"
            " AND 'timestamptz'::regtype = ANY (proargtypes::regtype[])"
        ),
    )
    # Only the link's own expiry, which the API signs into the token, is given.
    assert [r["proname"] for r in timed] == ["platform_issue_link"]
