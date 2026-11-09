"""Migration 0012's reporting views against real Postgres, read as the API user under RLS.

Most tests give a gym of its own (`seed_gym`: one membership, a period due
2026-11-01 and its 45.000 charge) a ledger history and read the views back as its
owner. The last read the demo gym, as the seed builds it for today.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from alembic import command
from app.seed import load
from app.seed.build import GYM_ID, build
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_seed import overdue

pytestmark = pytest.mark.postgres

VIEWS = ("v_overdue", "v_balance", "v_monthly_income")

# seed_gym's period, in America/Santiago like every gym by default.
DUE = date(2026, 11, 1)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def today(db: Database) -> date:
    """Today in Santiago, as the views compute it."""
    day: date = run(
        db.admin_url, lambda c: c.fetchval("SELECT (now() AT TIME ZONE 'America/Santiago')::date")
    )
    return day


def new_gym(db: Database) -> uuid.UUID:
    """seed_gym, its charge validated as the billing job writes one."""
    gym = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE ledger_entry SET status = 'validated', validated_at = now()"
            " WHERE gym_id = $1 AND kind = 'charge'",
            gym,
        ),
    )
    return gym


def membership_of(db: Database, gym: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """seed_gym's membership and its period."""
    row = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT membership_id, billing_period_id FROM ledger_entry"
            " WHERE gym_id = $1 AND kind = 'charge'",
            gym,
        ),
    )
    return row["membership_id"], row["billing_period_id"]


def entry(
    db: Database,
    gym: uuid.UUID,
    kind: str,
    amount: int,
    *,
    status: str = "validated",
    period: bool = True,
    validated_at: datetime = datetime(2026, 11, 2, 15, tzinfo=UTC),
) -> None:
    """An entry on seed_gym's membership, on its period unless `period` is false."""
    membership, period_id = membership_of(db, gym)
    method = "transfer" if kind == "payment" else None
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, method, validated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            gym,
            membership,
            period_id if period else None,
            amount,
            kind,
            status,
            method,
            None if status == "pending" else validated_at,
        ),
    )


def read(db: Database, gym: uuid.UUID, view: str, person: uuid.UUID | None = None) -> list[Any]:
    """`view` as the API user acting for `person`, the gym's owner by default."""
    who = seeded_owner(gym) if person is None else person
    rows: list[asyncpg.Record] = run(db.api_url, in_gym(gym, f"SELECT * FROM {view}", person=who))
    return [dict(r) for r in rows]


def balance(db: Database, gym: uuid.UUID) -> int:
    [row] = read(db, gym, "v_balance")
    value: int = row["balance_clp"]
    return value


def add_person(db: Database, gym: uuid.UUID, *, role: str | None) -> uuid.UUID:
    """A person in `gym`: staff with `role`, or with a membership, period and charge."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'someone')", person)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'someone')",
            gym,
            person,
        )
        if role is not None:
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)", gym, person, role
            )
            return
        membership = await conn.fetchval(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $2, plan_id, 'active' FROM membership WHERE gym_id = $1"
            " LIMIT 1 RETURNING id",
            gym,
            person,
        )
        period = await conn.fetchval(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, '2026-10-01', '2026-10-31', 30000, '2026-10-01') RETURNING id",
            gym,
            membership,
        )
        await conn.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, validated_at) VALUES ($1, $2, $3, 30000, 'charge', 'validated', now())",
            gym,
            membership,
            period,
        )

    run(db.admin_url, query)
    return person


def test_an_unpaid_period_past_due_is_overdue(db: Database) -> None:
    gym = new_gym(db)
    membership, period = membership_of(db, gym)
    [row] = read(db, gym, "v_overdue")
    assert row["billing_period_id"] == period
    assert row["membership_id"] == membership
    assert row["person_id"] == seeded_owner(gym)
    assert row["membership_status"] == "active"
    assert (row["due_date"], row["amount_due_clp"]) == (DUE, 45_000)
    assert (row["paid_clp"], row["outstanding_clp"]) == (0, 45_000)
    assert row["days_overdue"] == (today(db) - DUE).days
    assert balance(db, gym) == 45_000


def test_a_partial_payment_leaves_the_remainder_overdue(db: Database) -> None:
    gym = new_gym(db)
    entry(db, gym, "payment", 20_000)
    # Neither a proof still waiting nor a rejected one counts.
    entry(db, gym, "payment", 25_000, status="pending")
    entry(db, gym, "payment", 25_000, status="rejected")
    [row] = read(db, gym, "v_overdue")
    assert (row["paid_clp"], row["outstanding_clp"]) == (20_000, 25_000)
    assert balance(db, gym) == 25_000


def test_a_period_settled_by_a_payment_and_an_adjustment_is_not_overdue(db: Database) -> None:
    gym = new_gym(db)
    entry(db, gym, "payment", 40_000)
    entry(db, gym, "adjustment", 5_000)
    assert read(db, gym, "v_overdue") == []
    assert balance(db, gym) == 0


def test_an_overpayment_is_credit_once(db: Database) -> None:
    # As app.api.ledger records it: the whole payment on the period, and the excess
    # carried as a validated adjustment with no period.
    gym = new_gym(db)
    entry(db, gym, "payment", 50_000)
    entry(db, gym, "adjustment", 5_000, period=False)
    assert read(db, gym, "v_overdue") == []
    assert balance(db, gym) == -5_000


def test_a_refund_is_owed_back(db: Database) -> None:
    gym = new_gym(db)
    entry(db, gym, "payment", 45_000)
    entry(db, gym, "refund", 10_000, period=False)
    assert balance(db, gym) == 10_000


def test_a_period_due_today_is_not_overdue_yet(db: Database) -> None:
    gym = new_gym(db)
    membership, _ = membership_of(db, gym)
    due = today(db)

    async def query(conn: asyncpg.Connection) -> None:
        period = await conn.fetchval(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, $3, $3, 45000, $3) RETURNING id",
            gym,
            membership,
            due,
        )
        await conn.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, validated_at) VALUES ($1, $2, $3, 45000, 'charge', 'validated', now())",
            gym,
            membership,
            period,
        )

    run(db.admin_url, query)
    assert [r["due_date"] for r in read(db, gym, "v_overdue")] == [DUE]


def test_monthly_income_is_validated_payments_by_local_month(db: Database) -> None:
    gym = new_gym(db)
    # 23:00 on 31 October in Santiago (UTC-3).
    entry(db, gym, "payment", 10_000, validated_at=datetime(2026, 11, 1, 2, tzinfo=UTC))
    # 00:30 on 1 November there.
    entry(db, gym, "payment", 20_000, validated_at=datetime(2026, 11, 1, 3, 30, tzinfo=UTC))
    entry(db, gym, "payment", 7_000, validated_at=datetime(2026, 11, 20, 15, tzinfo=UTC))
    entry(db, gym, "payment", 99_000, status="pending")
    entry(db, gym, "payment", 99_000, status="rejected")
    entry(db, gym, "adjustment", 99_000)
    rows = sorted(read(db, gym, "v_monthly_income"), key=lambda r: r["month"])
    assert [(r["month"], r["income_clp"], r["payments"]) for r in rows] == [
        (date(2026, 10, 1), 10_000, 1),
        (date(2026, 11, 1), 27_000, 2),
    ]
    assert {r["gym_id"] for r in rows} == {gym}


@pytest.mark.parametrize("view", VIEWS)
def test_a_gym_reads_only_its_own_rows(db: Database, view: str) -> None:
    gym, other = new_gym(db), new_gym(db)
    entry(db, gym, "payment", 10_000)
    entry(db, other, "payment", 10_000)
    assert {r["gym_id"] for r in read(db, gym, view)} == {gym}
    # The other gym's owner, acting in this one, is nobody here.
    assert read(db, gym, view, person=seeded_owner(other)) == []
    assert run(db.api_url, in_gym(None, f"SELECT * FROM {view}")) == []


@pytest.mark.parametrize("view", VIEWS)
def test_a_coach_reads_nothing(db: Database, view: str) -> None:
    gym = new_gym(db)
    entry(db, gym, "payment", 10_000)
    coach = add_person(db, gym, role="coach")
    assert read(db, gym, view) != []
    assert read(db, gym, view, person=coach) == []


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_staff_who_see_money_read_every_membership(db: Database, role: str) -> None:
    gym = new_gym(db)
    add_person(db, gym, role=None)
    staff = add_person(db, gym, role=role)
    assert len(read(db, gym, "v_balance", person=staff)) == 2
    assert len(read(db, gym, "v_overdue", person=staff)) == 2


def test_a_member_reads_only_their_own(db: Database) -> None:
    gym = new_gym(db)
    member = add_person(db, gym, role=None)
    [overdue_row] = read(db, gym, "v_overdue", person=member)
    assert overdue_row["person_id"] == member
    [balance_row] = read(db, gym, "v_balance", person=member)
    assert balance_row["balance_clp"] == 30_000
    assert len(read(db, gym, "v_balance")) == 2


def add_guardian(db: Database, gym: uuid.UUID, dependent: uuid.UUID) -> uuid.UUID:
    """A person in `gym` only as `dependent`'s guardian: no membership, no staff row."""
    guardian = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'guardian')", guardian)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'guardian')",
            gym,
            guardian,
        )
        await conn.execute(
            "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
            " VALUES ($1, $2, $3)",
            gym,
            guardian,
            dependent,
        )

    run(db.admin_url, query)
    return guardian


def test_a_guardian_reads_their_dependents_rows(db: Database) -> None:
    # Through ledger_entry_own (0010), across every join each view makes.
    gym = new_gym(db)
    dependent = add_person(db, gym, role=None)
    add_person(db, gym, role=None)  # someone else's kid
    guardian = add_guardian(db, gym, dependent)

    async def pay(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, method, validated_at)"
            " SELECT gym_id, membership_id, billing_period_id, 10000, 'payment', 'validated',"
            " 'transfer', '2026-10-05T15:00:00Z' FROM ledger_entry"
            " WHERE kind = 'charge' AND membership_id IN"
            " (SELECT id FROM membership WHERE person_id = $1)",
            dependent,
        )

    run(db.admin_url, pay)
    [overdue_row] = read(db, gym, "v_overdue", person=guardian)
    assert overdue_row["person_id"] == dependent
    assert overdue_row["outstanding_clp"] == 20_000
    [balance_row] = read(db, gym, "v_balance", person=guardian)
    assert balance_row["membership_id"] == overdue_row["membership_id"]
    assert balance_row["balance_clp"] == 20_000
    [income] = read(db, gym, "v_monthly_income", person=guardian)
    assert (income["month"], income["income_clp"]) == (date(2026, 10, 1), 10_000)


def test_a_second_charge_does_not_list_a_period_twice(db: Database) -> None:
    gym = new_gym(db)
    entry(db, gym, "charge", 45_000)
    assert len(read(db, gym, "v_overdue")) == 1


def test_monthly_income_says_whom_it_is_income_for(db: Database) -> None:
    comment = run(
        db.admin_url, lambda c: c.fetchval("SELECT obj_description('v_monthly_income'::regclass)")
    )
    assert "only for an owner or admin" in comment


def test_the_table_owner_reads_the_gym_in_app_gym_id(db: Database) -> None:
    # The nightly jobs and the weekly email act for no person (0006).
    gym = new_gym(db)
    entry(db, gym, "payment", 10_000)
    for view in VIEWS:
        rows = run(db.owner_url, in_gym(gym, f"SELECT * FROM {view}"))
        assert {r["gym_id"] for r in rows} == {gym}, view
        assert run(db.owner_url, in_gym(None, f"SELECT * FROM {view}")) == [], view


def test_the_demo_gym_overdue_is_the_design(db: Database) -> None:
    day = today(db)
    run(db.owner_url, lambda c: load(c, day))
    seed = build(day)
    names = {p["id"]: p["name"] for p in seed.people}
    owner = next(s["person_id"] for s in seed.staff if s["role"] == "owner")
    rows = read(db, GYM_ID, "v_overdue", person=owner)
    active = {
        names[r["person_id"]]: (r["days_overdue"], r["outstanding_clp"])
        for r in rows
        if r["membership_status"] == "active"
    }
    assert active == overdue(seed)
    # The members who lapsed owe their last period still.
    assert {r["membership_status"] for r in rows} == {"active", "lapsed"}


def test_the_demo_gym_credit_is_a_negative_balance(db: Database) -> None:
    day = today(db)
    run(db.owner_url, lambda c: load(c, day))
    owner = next(s["person_id"] for s in build(day).staff if s["role"] == "owner")
    balances = [r["balance_clp"] for r in read(db, GYM_ID, "v_balance", person=owner)]
    assert sorted(balances)[0] == -5_000
    assert len([b for b in balances if b < 0]) == 1


def test_downgrade_drops_the_views() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        command.downgrade(database.alembic(), "0011")
        found = run(
            database.admin_url,
            lambda c: c.fetch("SELECT viewname FROM pg_views WHERE schemaname = 'public'"),
        )
        assert found == []
        migrate(database)
