"""A gym to run the nightly jobs against, written as the owner (`tests.pg`).

The jobs work on every gym in the database, so each test makes a gym of its own with
only the plans and memberships it names, and reads back only its own.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import asyncpg

from tests.pg import Database, in_gym, run

PLANS: dict[str, dict[str, Any]] = {
    "signup": {"kind": "monthly", "price_clp": 45_000, "anchor": "signup"},
    "first": {"kind": "monthly", "price_clp": 40_000, "anchor": "first"},
    "prepaid": {"kind": "prepaid", "price_clp": 240_000, "period_months": 6},
    "credits": {"kind": "credits", "price_clp": 45_000, "credits": 12, "credit_expiry_days": 60},
    "dropin": {"kind": "dropin", "price_clp": 10_000},
    "trial": {"kind": "trial", "price_clp": 0, "credits": 2, "credit_expiry_days": 14},
}


class Gym:
    """A gym with one member and every plan in `PLANS`, written as the owner."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.id = uuid.uuid4()
        self.person = uuid.uuid4()
        self.plans = {key: uuid.uuid4() for key in PLANS}

        async def query(conn: asyncpg.Connection) -> None:
            async with conn.transaction():
                await self._in_gym(conn)
                await conn.execute(
                    "INSERT INTO gym (id, name, slug) VALUES ($1, $2, $2)", self.id, str(self.id)
                )
                await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'Ana')", self.person)
                await conn.execute(
                    "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Ana')",
                    self.id,
                    self.person,
                )
                for key, plan in PLANS.items():
                    columns = ", ".join(plan)
                    values = ", ".join(f"${i}" for i in range(4, len(plan) + 4))
                    await conn.execute(
                        f"INSERT INTO plan (id, gym_id, name, {columns})"
                        f" VALUES ($1, $2, $3, {values})",
                        self.plans[key],
                        self.id,
                        key,
                        *plan.values(),
                    )

        run(db.owner_url, query)

    async def _in_gym(self, conn: asyncpg.Connection) -> None:
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(self.id))

    def member(
        self,
        plan: str,
        started_on: date,
        *,
        status: str = "active",
        anchor_day: int | None = None,
        current_period_end: date | None = None,
        discount_pct: int = 0,
        created_on: date | None = None,
    ) -> uuid.UUID:
        """A membership started on `started_on`, and created then too unless `created_on`
        says another day: the lapse job gives a backdated one its grace from that day."""
        membership_id = uuid.uuid4()
        if PLANS[plan]["kind"] == "monthly" and anchor_day is None:
            anchor_day = 1 if PLANS[plan]["anchor"] == "first" else started_on.day
        extra = (
            {"cancel_reason": "se mudó", "cancelled_at": datetime.now(UTC)}
            if status == "cancelled"
            else {}
        )
        columns = ", ".join(extra)
        values = ", ".join(f"${i}" for i in range(11, len(extra) + 11))
        self.sql(
            "INSERT INTO membership (id, gym_id, person_id, plan_id, status, anchor_day,"
            " started_at, created_at, current_period_end, discount_pct"
            + (f", {columns}) " if extra else ") ")
            + "VALUES ($1, $2, $3, $4, $5, $6,"
            " ($7::date::timestamp AT TIME ZONE 'America/Santiago'),"
            " (coalesce($10, $7)::date::timestamp AT TIME ZONE 'America/Santiago'), $8, $9"
            + (f", {values})" if extra else ")"),
            membership_id,
            self.id,
            self.person,
            self.plans[plan],
            status,
            anchor_day,
            started_on,
            current_period_end,
            discount_pct,
            created_on,
            *extra.values(),
        )
        return membership_id

    def sql(self, sql: str, *args: object) -> list[asyncpg.Record]:
        rows: list[asyncpg.Record] = run(self.db.owner_url, in_gym(self.id, sql, *args))
        return rows

    def periods(self, membership_id: uuid.UUID) -> list[tuple[date, date, int, date]]:
        rows = self.sql(
            "SELECT period_start, period_end, amount_due_clp, due_date FROM billing_period"
            " WHERE membership_id = $1 ORDER BY period_start",
            membership_id,
        )
        return [tuple(r) for r in rows]

    def charges(self, membership_id: uuid.UUID) -> list[tuple[date, int, str]]:
        rows = self.sql(
            "SELECT b.period_start, e.amount_clp, e.status FROM ledger_entry e"
            " JOIN billing_period b ON b.id = e.billing_period_id"
            " WHERE e.membership_id = $1 AND e.kind = 'charge' ORDER BY b.period_start",
            membership_id,
        )
        return [tuple(r) for r in rows]

    def membership(self, membership_id: uuid.UUID) -> asyncpg.Record:
        (row,) = self.sql(
            "SELECT plan_id, anchor_day, next_plan_id, next_plan_from FROM membership"
            " WHERE id = $1",
            membership_id,
        )
        return row

    def bill(self, membership_id: uuid.UUID, start: date, end: date, amount: int) -> None:
        self.sql(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, $3, $4, $5, $3)",
            self.id,
            membership_id,
            start,
            end,
            amount,
        )
