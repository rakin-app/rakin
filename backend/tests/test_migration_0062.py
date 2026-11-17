"""Migration 0062: today's roles onto the Academia preset (#308).

Each gym already here gets Administrador and Coach; each `admin` and `coach` row an
open appointment to its role from the day the row was created, in the gym's timezone;
each `owner` row the titular flag. A downgrade takes it all out, and an upgrade after
it maps the roles again.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, make_staff, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres

# 02:00 UTC on 1 March is still 28 February in Santiago (UTC-3 then).
CREATED_AT = datetime(2026, 3, 1, 2, 0, tzinfo=UTC)
CREATED_ON = date(2026, 2, 28)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0061")
        yield database


def admin(db: Database, sql: str, *args: object) -> list[Any]:
    """As the superuser, whom RLS does not hold."""
    return list(run(db.admin_url, lambda c: c.fetch(sql, *args)))


def staff(db: Database, gym: uuid.UUID, role: str) -> uuid.UUID:
    """Someone on `gym`'s staff in `role` since `CREATED_AT`, as 0061 kept them."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, $2)", person, role)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, $3)",
            gym,
            person,
            role,
        )
        await make_staff(conn, gym, person, role)
        await conn.execute(
            "UPDATE staff SET created_at = $2 WHERE person_id = $1", person, CREATED_AT
        )

    run(db.admin_url, query)
    return person


def titles(db: Database) -> set[tuple[Any, ...]]:
    rows = admin(db, "SELECT gym_id, name, permissions, public, preset FROM gym_title")
    return {
        (r["gym_id"], r["name"], frozenset(r["permissions"]), r["public"], r["preset"])
        for r in rows
    }


def appointments(db: Database) -> set[tuple[Any, ...]]:
    rows = admin(
        db,
        "SELECT st.gym_id, st.person_id, t.name, st.title_name, st.starts_on, st.ends_on"
        " FROM staff_title st JOIN gym_title t ON t.id = st.title_id",
    )
    return {tuple(r) for r in rows}


def holders(db: Database) -> set[uuid.UUID]:
    return {r["person_id"] for r in admin(db, "SELECT person_id FROM staff WHERE account_holder")}


ADMINISTRADOR = frozenset(
    {
        "money_read",
        "money_write",
        "members_manage",
        "members_add",
        "attendance",
        "gym_setup",
        "team_manage",
    }
)
COACH = frozenset({"attendance", "members_add"})


def test_every_role_is_mapped_and_the_migration_round_trips(db: Database) -> None:
    sur, norte = seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")
    carla, beto = staff(db, sur, "admin"), staff(db, sur, "coach")
    pia = staff(db, norte, "coach")

    def mapped() -> None:
        assert titles(db) == {
            (gym, name, permissions, public, "academia")
            for gym in (sur, norte)
            for name, permissions, public in (
                ("Administrador", ADMINISTRADOR, False),
                ("Coach", COACH, True),
            )
        }
        assert appointments(db) == {
            (sur, carla, "Administrador", "Administrador", CREATED_ON, None),
            (sur, beto, "Coach", "Coach", CREATED_ON, None),
            (norte, pia, "Coach", "Coach", CREATED_ON, None),
        }
        assert holders(db) == {seeded_owner(sur), seeded_owner(norte)}

    migrate(db, "0062")
    mapped()

    command.downgrade(db.alembic(), "0061")
    tables = admin(db, "SELECT to_regclass('gym_title'), to_regclass('staff_title')")
    assert tuple(tables[0]) == (None, None)
    columns = admin(
        db,
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'staff' AND column_name = 'account_holder'",
    )
    assert columns == []
    # The roles themselves were never touched.
    roles = admin(db, "SELECT person_id, role FROM staff")
    assert {tuple(r) for r in roles} == {
        (seeded_owner(sur), "owner"),
        (seeded_owner(norte), "owner"),
        (carla, "admin"),
        (beto, "coach"),
        (pia, "coach"),
    }

    migrate(db, "0062")
    mapped()


def test_a_gym_made_after_it_starts_with_the_preset(db: Database) -> None:
    migrate(db, "0062")
    gym = seed_gym(db, "academia-sur")
    assert {name for g, name, *_ in titles(db) if g == gym} == {"Administrador", "Coach"}
