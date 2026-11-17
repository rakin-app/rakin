"""Migration 0074: a paid plan names the trial it converted (#27).

The backfill links each paid plan already here to the trial before it, the first paid
plan after a trial and no other trial between them, a cancelled plan's too; a drop-in
converts nothing. A downgrade drops the column.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

pytestmark = pytest.mark.postgres

T0 = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0073")
        yield database


class Seed:
    """Plans and people of one gym, written as the superuser, past RLS."""

    def __init__(self, conn: asyncpg.Connection, gym: uuid.UUID) -> None:
        self.conn, self.gym = conn, gym
        self.plans: dict[str, uuid.UUID] = {}

    async def plan(self, kind: str) -> uuid.UUID:
        if kind not in self.plans:
            terms = {
                "trial": "0, NULL, 2, 14",
                "dropin": "10000, NULL, NULL, NULL",
                "monthly": "45000, 'signup', NULL, NULL",
                "credits": "45000, NULL, 12, 60",
            }[kind]
            self.plans[kind] = await self.conn.fetchval(
                "INSERT INTO plan (gym_id, name, kind, price_clp, anchor, credits,"
                f" credit_expiry_days) VALUES ($1, $2, $2, {terms}) RETURNING id",
                self.gym,
                kind,
            )
        return self.plans[kind]

    async def person(self) -> uuid.UUID:
        person = uuid.uuid4()
        await self.conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
        await self.conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')",
            self.gym,
            person,
        )
        return person

    async def membership(
        self, person: uuid.UUID, kind: str, day: int, status: str = "active"
    ) -> uuid.UUID:
        cancelled = status == "cancelled"
        membership: uuid.UUID = await self.conn.fetchval(
            "INSERT INTO membership (gym_id, person_id, plan_id, status, started_at,"
            " created_at, cancel_reason, cancelled_at)"
            " VALUES ($1, $2, $3, $4, $5, $5, $6, $7) RETURNING id",
            self.gym,
            person,
            await self.plan(kind),
            status,
            T0 + timedelta(days=day),
            "se mudó" if cancelled else None,
            T0 + timedelta(days=day + 1) if cancelled else None,
        )
        return membership


def links(db: Database) -> dict[uuid.UUID, uuid.UUID]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT id, converted_from FROM membership WHERE converted_from IS NOT NULL"
        ),
    )
    return {r["id"]: r["converted_from"] for r in rows}


def test_the_backfill_links_each_paid_plan_to_the_trial_before_it(db: Database) -> None:
    gym = seed_gym(db, "academia-sur")

    async def query(conn: asyncpg.Connection) -> dict[str, uuid.UUID]:
        seed = Seed(conn, gym)
        ana, bea, caro, dani, eva = [await seed.person() for _ in range(5)]
        ids = {
            # A trial, then a monthly plan since cancelled: converted.
            "ana_trial": await seed.membership(ana, "trial", 0, "lapsed"),
            "ana_paid": await seed.membership(ana, "monthly", 10, "cancelled"),
            "ana_later": await seed.membership(ana, "credits", 40),
            # A trial still running beside the plan that converted it: it ends.
            "eva_trial": await seed.membership(eva, "trial", 0, "trial"),
            "eva_paid": await seed.membership(eva, "monthly", 3),
            # A trial, a drop-in, a second trial, then a pack: the second trial.
            "bea_trial": await seed.membership(bea, "trial", 0, "lapsed"),
            "bea_visit": await seed.membership(bea, "dropin", 5, "cancelled"),
            "bea_trial2": await seed.membership(bea, "trial", 20, "lapsed"),
            "bea_paid": await seed.membership(bea, "credits", 30),
            # A plan and no trial; a trial and no plan.
            "caro_paid": await seed.membership(caro, "monthly", 0),
            "dani_trial": await seed.membership(dani, "trial", 0, "trial"),
        }
        return ids

    ids = run(db.admin_url, query)
    migrate(db)

    assert links(db) == {
        ids["ana_paid"]: ids["ana_trial"],
        ids["bea_paid"]: ids["bea_trial2"],
        ids["eva_paid"]: ids["eva_trial"],
    }
    states = {
        r["id"]: (r["status"], r["cancel_reason"], r["cancelled_at"])
        for r in run(
            db.admin_url,
            lambda c: c.fetch("SELECT id, status, cancel_reason, cancelled_at FROM membership"),
        )
    }
    assert states[ids["eva_trial"]] == ("cancelled", "pasó a un plan", T0 + timedelta(days=3))
    # A trial linked but lapsed stays as it was; one never converted runs on.
    assert states[ids["ana_trial"]] == ("lapsed", None, None)
    assert states[ids["dani_trial"]] == ("trial", None, None)


def test_a_downgrade_drops_the_column(db: Database) -> None:
    migrate(db)
    command.downgrade(db.alembic(), "0073")

    columns = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'membership' AND column_name = 'converted_from'"
        ),
    )
    assert columns == 0
    migrate(db)
