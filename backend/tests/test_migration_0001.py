"""Migration 0001 against real Postgres: schema shape, phone identity, roles and RLS.

The migration runs as the bootstrapped owner, a non-superuser; the API's queries run
as the bootstrapped API user. Only seeding across gyms and catalog reads use the
superuser.
"""

import uuid
from collections.abc import Iterator

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    throwaway_database,
)

pytestmark = pytest.mark.postgres

# At head, so including the tables later migrations add.
TENANT_TABLES = {
    "gym",
    "gym_person",
    "staff",
    "plan",
    "membership",
    "billing_period",
    "ledger_entry",
}


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def scratch_db() -> Iterator[Database]:
    """A bootstrapped, unmigrated database of its own, for tests that downgrade."""
    with throwaway_database(require_test_database_url()) as database:
        yield database


@pytest.fixture(scope="module")
def two_gyms(db: Database) -> tuple[uuid.UUID, uuid.UUID]:
    return seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")


def test_upgrade_downgrade_upgrade_round_trips(scratch_db: Database) -> None:
    migrate(scratch_db)
    command.downgrade(scratch_db.alembic(), "base")
    tables = run(
        scratch_db.admin_url,
        lambda c: c.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
    )
    assert [t["tablename"] for t in tables] == ["alembic_version"]
    migrate(scratch_db)


def test_tables_are_owned_by_the_non_superuser_owner(db: Database) -> None:
    owners = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT DISTINCT t.tableowner, r.rolsuper, r.rolbypassrls"
            " FROM pg_tables t JOIN pg_roles r ON r.rolname = t.tableowner"
            " WHERE t.schemaname = 'public'"
        ),
    )
    assert [tuple(o) for o in owners] == [("rakin_owner", False, False)]


def test_no_timestamp_without_time_zone(db: Database) -> None:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
        ),
    )
    assert rows == []


def test_money_columns_are_integers(db: Database) -> None:
    # Views' columns included: a `sum` over bigint is numeric unless cast back (0014).
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT c.column_name, c.data_type, t.table_type FROM information_schema.columns c"
            " JOIN information_schema.tables t USING (table_schema, table_name)"
            " WHERE c.table_schema = 'public' AND c.column_name LIKE '%\\_clp'"
        ),
    )
    tables = {r["column_name"] for r in rows if r["table_type"] == "BASE TABLE"}
    assert tables == {"price_clp", "amount_due_clp", "amount_clp"}
    assert {r["data_type"] for r in rows} == {"bigint"}


def test_every_gym_scoped_table_has_forced_rls_and_a_policy(db: Database) -> None:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   count(p.polname) AS policies
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_policy p ON p.polrelid = c.oid
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND (c.relname = 'gym' OR EXISTS (
                  SELECT FROM information_schema.columns col
                  WHERE col.table_schema = 'public' AND col.table_name = c.relname
                    AND col.column_name = 'gym_id'))
            GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity
            """
        ),
    )
    # auth_session (0004) too; tests/test_auth.py covers its policies.
    # `guardian_link` (0010) and `plan_event` (0013) are empty in `seed_gym`;
    # tests/test_guardians.py and tests/test_lapse_job.py isolate them, and
    # tests/test_notices.py `message_log` and `mail_unsubscribe` (0015),
    # tests/test_class_types.py `program` and `class_type` (0016), and
    # tests/test_custom_fields.py `person_field_value` (0017).
    assert {r["relname"] for r in rows} == TENANT_TABLES | {
        "auth_session",
        "class_type",
        "guardian_link",
        "mail_unsubscribe",
        "message_log",
        "person_field_value",
        "plan_event",
        "program",
    }
    for r in rows:
        assert (r["relrowsecurity"], r["relforcerowsecurity"]) == (True, True), r["relname"]
        assert r["policies"] >= 1, r["relname"]


def test_api_user_cannot_bypass_rls(db: Database) -> None:
    role = run(
        db.api_url,
        lambda c: c.fetchrow(
            "SELECT r.rolsuper, r.rolbypassrls, pg_has_role(current_user, 'rakin_app', 'MEMBER')"
            " AS member FROM pg_roles r WHERE r.rolname = current_user"
        ),
    )
    assert tuple(role) == (False, False, True)


def test_app_role_cannot_log_in_or_bypass_rls(db: Database) -> None:
    role = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'rakin_app'"
        ),
    )
    assert tuple(role) == (False, False, False)


@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_app_role_has_no_privilege_on_alembic_version(db: Database, privilege: str) -> None:
    allowed = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT has_table_privilege('rakin_app', 'alembic_version', $1)", privilege
        ),
    )
    assert allowed is False


def test_api_user_cannot_rewrite_the_migration_head(db: Database) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(db.api_url, lambda c: c.execute("UPDATE alembic_version SET version_num = 'x'"))


@pytest.mark.parametrize(
    "phone", ["56912345678", "+056912345678", "+56 9 1234 5678", "+1234567890123456", ""]
)
def test_phone_must_be_e164(db: Database, phone: str) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.api_url,
            lambda c: c.execute("INSERT INTO person (name, phone) VALUES ('x', $1)", phone),
        )


def test_phone_is_unique(db: Database) -> None:
    insert = "INSERT INTO person (name, phone) VALUES ('x', '+56911112222')"
    run(db.api_url, lambda c: c.execute(insert))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(db.api_url, lambda c: c.execute(insert))


def test_people_without_phone_are_allowed(db: Database) -> None:
    insert = "INSERT INTO person (name) VALUES ('kid')"
    run(db.api_url, lambda c: c.execute(insert))
    run(db.api_url, lambda c: c.execute(insert))


@pytest.mark.parametrize("user", ["api", "owner"])
@pytest.mark.parametrize("table", sorted(TENANT_TABLES))
def test_only_the_current_gym_is_visible(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID], table: str, user: str
) -> None:
    url = db.api_url if user == "api" else db.owner_url
    sur, norte = two_gyms
    column = "id" if table == "gym" else "gym_id"
    sql = f"SELECT DISTINCT {column} AS gym FROM {table}"

    # As the gym's owner: the API sees the ledger only for an owner or admin (0006).
    for gym in (sur, norte):
        assert [r["gym"] for r in run(url, in_gym(gym, sql, person=seeded_owner(gym)))] == [gym]


@pytest.mark.parametrize("user", ["api", "owner"])
@pytest.mark.parametrize("table", sorted(TENANT_TABLES))
def test_nothing_is_visible_without_a_gym(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID], table: str, user: str
) -> None:
    # FORCE ROW LEVEL SECURITY: the owner is held to the policy just like the API.
    url = db.api_url if user == "api" else db.owner_url
    assert run(url, in_gym(None, f"SELECT * FROM {table}")) == []


def test_api_cannot_write_into_another_gym(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms
    insert = "INSERT INTO plan (gym_id, name, kind, price_clp) VALUES ($1, 'x', 'dropin', 8000)"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(db.api_url, in_gym(sur, insert, norte))


def test_api_cannot_move_a_row_to_another_gym(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(db.api_url, in_gym(sur, "UPDATE plan SET gym_id = $1", norte))


def test_membership_cannot_use_another_gyms_plan(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms

    # As the superuser, which skips RLS: only the foreign key stands in the way.
    async def query(conn: asyncpg.Connection) -> None:
        norte_plan = await conn.fetchval("SELECT id FROM plan WHERE gym_id = $1", norte)
        person = await conn.fetchval("INSERT INTO person (name) VALUES ('y') RETURNING id")
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'y')", sur, person
        )
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " VALUES ($1, $2, $3, 'active')",
            sur,
            person,
            norte_plan,
        )

    with pytest.raises(asyncpg.ForeignKeyViolationError, match="membership_gym_id_plan_id_fkey"):
        run(db.admin_url, query)


def test_api_cannot_delete_ledger_entries(
    db: Database, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, _ = two_gyms
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(db.api_url, in_gym(sur, "DELETE FROM ledger_entry"))


def test_job_run_is_unique_per_job_and_date(db: Database) -> None:
    insert = (
        "INSERT INTO job_run (job_name, run_date, status) VALUES ('daily', '2026-11-08', 'running')"
    )
    run(db.api_url, lambda c: c.execute(insert))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(db.api_url, lambda c: c.execute(insert))
