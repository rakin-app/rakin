"""Corrections record who, why, and before and after (#277).

An adjustment, a void and a plan voided by mistake each write an `audit_event` row in
their own transaction: who, when, the reason, whose billing, the entries written, and
the period and the membership's balance before and after. The ficha reads them as
"Correcciones"; a coach neither reads nor writes one, and an admin cannot write one as
someone else or in another gym. Nothing changes or deletes a row, except deleting the
person, which takes their corrections along and counts them.
"""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_member_roll import count, forget
from tests.test_plans import add_staff
from tests.test_voids import REASON, balance, ledger, member, ok, pay, refund, void, void_plan

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"sur-{uuid.uuid4().hex[:8]}")


def audit_rows(db: Database, gym: uuid.UUID, person: str) -> list[Any]:
    """The person's audit rows, oldest first, as the owner, whom RLS holds to the gym."""
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT * FROM audit_event WHERE person_id = $1 ORDER BY at, id",
            uuid.UUID(person),
        ),
    )
    return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]


def adjust(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> Any:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "note": "hermano",
    }
    return ok(client.post("/api/ledger/adjustments", json=body, headers=as_gym(gym)), 201)


def corrections(client: TestClient, gym: uuid.UUID, person: str, **kw: Any) -> Any:
    return client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym, **kw))


@pg
def test_an_adjustment_records_the_period_and_balance_before_and_after(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    period = ledger(client, gym, membership)["open_periods"][0]
    balance_before = balance(db, membership)
    admin = add_staff(db, gym, "admin")

    body = {
        "membership_id": membership,
        "billing_period_id": period["id"],
        "amount_clp": 5_000,
        "note": "hermano",
    }
    recorded = ok(
        client.post("/api/ledger/adjustments", json=body, headers=as_gym(gym, admin)), 201
    )
    [row] = audit_rows(db, gym, person)
    assert (row["action"], row["actor_id"], row["reason"]) == ("ledger_corrected", admin, "hermano")
    assert row["detail"] == {
        "purpose": None,
        "membership_id": membership,
        "billing_period_id": period["id"],
        "entry_ids": [recorded["adjustment"]["id"]],
        "before": {"outstanding_clp": 45_000, "balance_clp": balance_before},
        "after": {
            "outstanding_clp": recorded["period"]["outstanding_clp"],
            "balance_clp": balance(db, membership),
        },
    }
    assert row["detail"]["after"]["outstanding_clp"] == 40_000
    assert row["detail"]["after"]["balance_clp"] == balance_before - 5_000

    # A surcharge is owed on top: more after than before.
    adjust(client, gym, membership, period["id"], -2_000)
    surcharge = audit_rows(db, gym, person)[-1]["detail"]
    assert (surcharge["before"]["outstanding_clp"], surcharge["after"]["outstanding_clp"]) == (
        40_000,
        42_000,
    )


@pg
def test_a_void_records_what_it_took_off(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership = member(client, gym)
    period = ledger(client, gym, membership)["open_periods"][0]["id"]
    balance_before = balance(db, membership)

    recorded = ok(void(client, gym, membership, period), 201)
    [row] = audit_rows(db, gym, person)
    assert (row["actor_id"], row["reason"]) == (seeded_owner(gym), REASON)
    detail = row["detail"]
    assert (detail["purpose"], detail["billing_period_id"]) == ("void", period)
    assert detail["entry_ids"] == [recorded["void"]["id"]]
    assert detail["before"] == {"outstanding_clp": 45_000, "balance_clp": balance_before}
    assert detail["after"] == {"outstanding_clp": 0, "balance_clp": balance_before - 45_000}
    assert "plan_void" not in detail


@pg
def test_a_plan_void_records_one_row_per_period_it_voids(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    owing = ledger(client, gym, membership)["open_periods"]
    assert len(owing) >= 2
    balance_before = balance(db, membership)

    ok(void_plan(client, gym, membership))
    # One transaction's time for all of them: in the order the periods were voided.
    starts = {p["id"]: p["period_start"] for p in owing}
    rows = sorted(
        audit_rows(db, gym, person), key=lambda r: starts[r["detail"]["billing_period_id"]]
    )
    assert [r["detail"]["billing_period_id"] for r in rows] == [p["id"] for p in owing]
    assert all(r["detail"]["plan_void"] and r["detail"]["purpose"] == "void" for r in rows)
    # Each one's before is the last one's after: the balance goes down a period at a time.
    running = balance_before
    for row, period in zip(rows, owing, strict=True):
        assert row["detail"]["before"] == {
            "outstanding_clp": period["outstanding_clp"],
            "balance_clp": running,
        }
        running -= period["outstanding_clp"]
        assert row["detail"]["after"] == {"outstanding_clp": 0, "balance_clp": running}
    assert running == balance(db, membership)


@pg
def test_the_ficha_lists_corrections_newest_first(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    first, second = (p["id"] for p in ledger(client, gym, membership)["open_periods"][:2])
    admin = add_staff(db, gym, "admin")
    adjust(client, gym, membership, first, 5_000)
    ok(void(client, gym, membership, second, person_id=admin), 201)

    found = ok(corrections(client, gym, person, person_id=admin))
    assert found["total"] == 2
    newest, oldest = found["items"]
    assert (newest["purpose"], newest["reason"], newest["plan_void"]) == ("void", REASON, False)
    assert newest["actor_name"] == "x"  # `add_staff`'s name
    assert newest["before"]["outstanding_clp"] == 45_000
    assert newest["after"]["outstanding_clp"] == 0
    assert newest["plan_name"] is not None and newest["period_start"] is not None
    assert (oldest["purpose"], oldest["reason"]) == (None, "hermano")

    # Another person's are not theirs; another gym sees none.
    other, _ = member(client, gym)
    assert ok(corrections(client, gym, other)) == {"total": 0, "items": []}
    elsewhere = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    assert ok(corrections(client, elsewhere, person))["total"] == 0


@pg
def test_a_coach_neither_reads_nor_writes_corrections(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    ok(void(client, gym, membership, ledger(client, gym, membership)["open_periods"][0]["id"]), 201)
    coach = add_staff(db, gym, "coach")
    assert corrections(client, gym, person, person_id=coach).status_code == 403

    log = "SELECT count(*) FROM audit_event"
    assert int(run(db.api_url, in_gym(gym, log, person=coach))[0][0]) == 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, insert_sql(), coach, uuid.UUID(person), person=coach))


def insert_sql(action: str = "ledger_corrected") -> str:
    return (
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, reason)"
        f" VALUES (current_setting('app.gym_id')::uuid, $1, $2, '{action}', 'x')"
    )


@pg
def test_an_admin_writes_a_correction_only_as_themselves_in_their_gym(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, _ = member(client, gym)
    them = uuid.UUID(person)
    admin = add_staff(db, gym, "admin")
    other_admin = add_staff(db, gym, "admin")
    refused = asyncpg.InsufficientPrivilegeError

    # As themselves, a correction of one of the gym's people: allowed.
    run(db.api_url, in_gym(gym, insert_sql(), admin, them, person=admin))
    # As another admin of the gym.
    with pytest.raises(refused):
        run(db.api_url, in_gym(gym, insert_sql(), other_admin, them, person=admin))
    # In another gym, where they are not staff, or of a person not of this gym.
    elsewhere = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    other_gym = (
        "INSERT INTO audit_event (gym_id, actor_id, person_id, action, reason)"
        " VALUES ($1, $2, $3, 'ledger_corrected', 'x')"
    )
    with pytest.raises(refused):
        run(db.api_url, in_gym(gym, other_gym, elsewhere, admin, them, person=admin))
    with pytest.raises(refused):
        run(db.api_url, in_gym(elsewhere, insert_sql(), admin, them, person=admin))
    with pytest.raises(refused):
        run(db.api_url, in_gym(gym, insert_sql(), admin, seeded_owner(elsewhere), person=admin))
    # Not a correction: a deletion is the owner role's to log (0044).
    with pytest.raises(asyncpg.PostgresError):
        run(db.api_url, in_gym(gym, insert_sql("person_deleted"), admin, them, person=admin))

    # And nothing changes or deletes a row, the owner role included.
    for sql in (
        "UPDATE audit_event SET reason = 'y'",
        "DELETE FROM audit_event",
    ):
        with pytest.raises(refused):
            run(db.api_url, in_gym(gym, sql, person=admin))
        with pytest.raises(asyncpg.RestrictViolationError):
            run(db.owner_url, in_gym(gym, sql))
    with pytest.raises(asyncpg.RestrictViolationError):
        run(db.owner_url, in_gym(gym, "TRUNCATE audit_event"))
    assert count(db, gym, "SELECT count(*) FROM audit_event WHERE person_id = $1", them) == 1


@pg
def test_deleting_a_person_removes_their_corrections_and_counts_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    periods = ledger(client, gym, membership)["open_periods"]
    payment = pay(client, gym, membership, periods[0]["id"])
    refund(client, gym, payment)
    adjust(client, gym, membership, periods[0]["id"], 5_000)
    ok(void_plan(client, gym, membership))
    written = len(audit_rows(db, gym, person))
    assert written == 1 + len(periods)
    # Someone else's stay.
    other, other_membership = member(client, gym)
    ok(
        void(
            client,
            gym,
            other_membership,
            ledger(client, gym, other_membership)["open_periods"][0]["id"],
        ),
        201,
    )

    assert forget(client, gym, person).status_code == 204
    assert audit_rows(db, gym, person) == []
    assert len(audit_rows(db, gym, other)) == 1
    [deleted] = run(
        db.owner_url,
        in_gym(gym, "SELECT * FROM audit_event WHERE action = 'person_deleted'"),
    )
    assert deleted["person_id"] is None
    assert json.loads(deleted["detail"])["corrections"] == written
    assert person not in deleted["detail"]


@pg
def test_upgrade_and_downgrade_0048() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0047")
        migrate(scratch)
        gym = seed_gym(scratch, "sur")
        owner = seeded_owner(gym)

        async def log(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, person_id, action, reason)"
                " VALUES ($1, $2, $2, 'ledger_corrected', 'x'),"
                " ($1, $2, NULL, 'person_deleted', 'y')",
                gym,
                owner,
            )

        run(scratch.admin_url, log)
        # The corrections go with their actions; a deletion's row stays.
        command.downgrade(scratch.alembic(), "0047")
        kept = run(scratch.admin_url, lambda c: c.fetch("SELECT action FROM audit_event"))
        assert [r["action"] for r in kept] == ["person_deleted"]
        migrate(scratch)
