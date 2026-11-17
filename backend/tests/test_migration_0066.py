"""Migration 0066: the policies ask permissions, not role names (#309).

A downgrade puts every policy and `undo_import` back as 0065 left them, and an upgrade
after it rewrites them again. `undo_import` follows the titular flag: whoever holds the
account runs it, whatever their row's role says.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    throwaway_database,
)

pytestmark = pytest.mark.postgres

POLICIES = (
    "SELECT tablename, policyname, permissive, cmd, roles::text, qual, with_check"
    " FROM pg_policies ORDER BY tablename, policyname"
)
UNDO_SOURCE = "SELECT prosrc FROM pg_proc WHERE proname = 'undo_import'"


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0065")
        yield database


def schema(db: Database) -> tuple[list[tuple[Any, ...]], str]:
    async def query(conn: asyncpg.Connection) -> tuple[list[tuple[Any, ...]], str]:
        policies = [tuple(r) for r in await conn.fetch(POLICIES)]
        return policies, await conn.fetchval(UNDO_SOURCE)

    result: tuple[list[tuple[Any, ...]], str] = run(db.admin_url, query)
    return result


def test_a_downgrade_puts_back_every_policy_and_an_upgrade_rewrites_them(db: Database) -> None:
    before = schema(db)
    migrate(db)
    after = schema(db)
    assert after != before
    assert not any("role" in f"{p[5]} {p[6]}" for p in after[0])
    assert "account_holder" in after[1]

    command.downgrade(db.alembic(), "0065")
    assert schema(db) == before
    migrate(db)
    assert schema(db) == after


def test_the_titular_undoes_an_import_whatever_their_role(db: Database) -> None:
    migrate(db)
    gym = seed_gym(db, "academia-sur")
    owner, successor = seeded_owner(gym), uuid.uuid4()

    # The account passes to an admin; the first owner's row still says `owner`.
    async def hand_over(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", successor)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
                gym,
                successor,
            )
            await make_staff(conn, gym, successor, "admin")
            await conn.execute(
                "UPDATE staff SET account_holder = false WHERE person_id = $1", owner
            )
            await conn.execute(
                "UPDATE staff SET account_holder = true WHERE person_id = $1", successor
            )

    run(db.admin_url, hand_over)
    undo = "SELECT undo_import($1, 'Archivo equivocado')"

    assert run(db.api_url, in_gym(gym, undo, uuid.uuid4(), person=successor)) == [("not_found",)]
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="only the owner"):
        run(db.api_url, in_gym(gym, undo, uuid.uuid4(), person=owner))
