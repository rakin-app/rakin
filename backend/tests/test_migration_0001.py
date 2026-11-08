"""Migration 0001 against real Postgres: schema shape, phone identity, roles and RLS.

Each test module gets a throwaway database created from `TEST_DATABASE_URL`, so the
database that URL names is never migrated or written to.
"""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command

pytestmark = pytest.mark.postgres

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
APP_ROLE = "rakin_app"
TENANT_TABLES = {"gym", "staff", "plan", "membership", "billing_period", "ledger_entry"}

Query = Callable[[asyncpg.Connection], Awaitable[Any]]


def dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logging"] = False
    return config


async def _admin(url: str, sql: str) -> None:
    conn = await asyncpg.connect(dsn(url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """A fresh, empty database on the TEST_DATABASE_URL server."""
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not set")
    name = f"rakin_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin(base, f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(base).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_admin(base, f'DROP DATABASE "{name}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def migrated_url(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url


def run(url: str, query: Query) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(dsn(url))
        try:
            return await query(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


def as_app(gym_id: uuid.UUID | None, sql: str, *args: object) -> Query:
    """Run `sql` as the app role inside a transaction, with `app.gym_id` set if given."""

    async def query(conn: asyncpg.Connection) -> Any:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {APP_ROLE}")
            if gym_id is not None:
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
            return await conn.fetch(sql, *args)

    return query


def seed_gym(url: str, slug: str) -> uuid.UUID:
    """A gym with one person, staff row, plan, membership, period and ledger entry.

    Seeded as the table owner (a superuser here), which RLS does not apply to.
    """

    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            gym_id: uuid.UUID = await conn.fetchval(
                "INSERT INTO gym (name, slug) VALUES ($1, $1) RETURNING id", slug
            )
            person_id = await conn.fetchval(
                "INSERT INTO person (name) VALUES ($1) RETURNING id", f"owner of {slug}"
            )
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'owner')",
                gym_id,
                person_id,
            )
            plan_id = await conn.fetchval(
                "INSERT INTO plan (gym_id, name, kind, price_clp)"
                " VALUES ($1, 'Mensual', 'monthly', 45000) RETURNING id",
                gym_id,
            )
            membership_id = await conn.fetchval(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " VALUES ($1, $2, $3, 'active') RETURNING id",
                gym_id,
                person_id,
                plan_id,
            )
            period_id = await conn.fetchval(
                "INSERT INTO billing_period"
                " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
                " VALUES ($1, $2, '2026-11-01', '2026-11-30', 45000, '2026-11-01') RETURNING id",
                gym_id,
                membership_id,
            )
            await conn.execute(
                "INSERT INTO ledger_entry"
                " (gym_id, membership_id, billing_period_id, amount_clp, kind)"
                " VALUES ($1, $2, $3, 45000, 'charge')",
                gym_id,
                membership_id,
                period_id,
            )
        return gym_id

    result: uuid.UUID = run(url, query)
    return result


@pytest.fixture(scope="module")
def two_gyms(migrated_url: str) -> tuple[uuid.UUID, uuid.UUID]:
    return seed_gym(migrated_url, "academia-sur"), seed_gym(migrated_url, "dojo-norte")


def test_upgrade_downgrade_upgrade_round_trips(database_url: str) -> None:
    # Runs on its own database state before the module's other tests migrate it.
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    tables = run(
        database_url,
        lambda c: c.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"),
    )
    assert [t["tablename"] for t in tables] == ["alembic_version"]
    command.upgrade(config, "head")


def test_no_timestamp_without_time_zone(migrated_url: str) -> None:
    rows = run(
        migrated_url,
        lambda c: c.fetch(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
        ),
    )
    assert rows == []


def test_money_columns_are_integers(migrated_url: str) -> None:
    rows = run(
        migrated_url,
        lambda c: c.fetch(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_name LIKE '%\\_clp'"
        ),
    )
    assert {r["column_name"] for r in rows} == {"price_clp", "amount_due_clp", "amount_clp"}
    assert {r["data_type"] for r in rows} == {"bigint"}


def test_every_gym_scoped_table_has_forced_rls_and_a_policy(migrated_url: str) -> None:
    rows = run(
        migrated_url,
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
    assert {r["relname"] for r in rows} == TENANT_TABLES
    for r in rows:
        assert (r["relrowsecurity"], r["relforcerowsecurity"]) == (True, True), r["relname"]
        assert r["policies"] >= 1, r["relname"]


def test_app_role_cannot_bypass_rls(migrated_url: str) -> None:
    role = run(
        migrated_url,
        lambda c: c.fetchrow(
            "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = $1",
            APP_ROLE,
        ),
    )
    assert role is not None
    assert (role["rolsuper"], role["rolbypassrls"]) == (False, False)
    # Login users are members of the role; the role itself never logs in.
    assert role["rolcanlogin"] is False


def test_app_role_owns_nothing(migrated_url: str) -> None:
    # The owner of a table is exempt from RLS unless forced; the app role owns no table.
    owned = run(
        migrated_url,
        lambda c: c.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner = $1",
            APP_ROLE,
        ),
    )
    assert owned == []


@pytest.mark.parametrize(
    "phone", ["56912345678", "+056912345678", "+56 9 1234 5678", "+1234567890123456", ""]
)
def test_phone_must_be_e164(migrated_url: str, phone: str) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            migrated_url,
            lambda c: c.execute("INSERT INTO person (name, phone) VALUES ('x', $1)", phone),
        )


def test_phone_is_unique(migrated_url: str) -> None:
    insert = "INSERT INTO person (name, phone) VALUES ('x', '+56911112222')"
    run(migrated_url, lambda c: c.execute(insert))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(migrated_url, lambda c: c.execute(insert))


def test_people_without_phone_are_allowed(migrated_url: str) -> None:
    insert = "INSERT INTO person (name) VALUES ('kid')"
    run(migrated_url, lambda c: c.execute(insert))
    run(migrated_url, lambda c: c.execute(insert))


@pytest.mark.parametrize("table", sorted(TENANT_TABLES))
def test_app_sees_only_the_current_gym(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID], table: str
) -> None:
    sur, norte = two_gyms
    column = "id" if table == "gym" else "gym_id"
    sql = f"SELECT DISTINCT {column} AS gym FROM {table}"

    assert [r["gym"] for r in run(migrated_url, as_app(sur, sql))] == [sur]
    assert [r["gym"] for r in run(migrated_url, as_app(norte, sql))] == [norte]


@pytest.mark.parametrize("table", sorted(TENANT_TABLES))
def test_app_sees_nothing_without_a_gym(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID], table: str
) -> None:
    assert run(migrated_url, as_app(None, f"SELECT * FROM {table}")) == []


def test_app_cannot_write_into_another_gym(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms
    insert = "INSERT INTO plan (gym_id, name, kind, price_clp) VALUES ($1, 'x', 'dropin', 8000)"
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(migrated_url, as_app(sur, insert, norte))


def test_app_cannot_move_a_row_to_another_gym(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        run(migrated_url, as_app(sur, "UPDATE plan SET gym_id = $1", norte))


def test_membership_cannot_use_another_gyms_plan(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, norte = two_gyms

    async def query(conn: asyncpg.Connection) -> None:
        norte_plan = await conn.fetchval("SELECT id FROM plan WHERE gym_id = $1", norte)
        person = await conn.fetchval("INSERT INTO person (name) VALUES ('y') RETURNING id")
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " VALUES ($1, $2, $3, 'active')",
            sur,
            person,
            norte_plan,
        )

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        run(migrated_url, query)


def test_app_role_cannot_delete_ledger_entries(
    migrated_url: str, two_gyms: tuple[uuid.UUID, uuid.UUID]
) -> None:
    sur, _ = two_gyms
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
        run(migrated_url, as_app(sur, "DELETE FROM ledger_entry"))


def test_job_run_is_unique_per_job_and_date(migrated_url: str) -> None:
    insert = (
        "INSERT INTO job_run (job_name, run_date, status) VALUES ('daily', '2026-11-08', 'running')"
    )
    run(migrated_url, as_app(None, insert))
    with pytest.raises(asyncpg.UniqueViolationError):
        run(migrated_url, as_app(None, insert))
