"""Deshacer baja (#285): a cancel made by mistake undone, through the database.

A plan "dado de baja" by mistake returns to the status it had: Active, billing from
where it left off (the months since the cancel, at once) or from today, as "Reactivar
plan" bills (#284); or Lapsed, billing nothing, when a period past due plus grace is
unpaid, since the nightly job would lapse it again that night. The database lets a
cancelled row change only with the matching `cancel_undone` audit row written first,
in the same transaction (migration 0092). Refused for a voided plan, for a person who
has left the gym, and beside another live plan of the person.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_lapsed_reassign import ledger, ok, run_lapse, start, status
from tests.test_member_roll import enrolled, leave, memberships, plan
from tests.test_memberships import add_staff
from tests.test_reactivate import PRICE, lapsed_plan, monthly_starts, pay, refusal

pytestmark = pytest.mark.postgres

REASON = "se dio de baja por error"


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
    return seed_gym(db, unique_slug("sur"))


def cancelled_plan(
    client: TestClient,
    db: Database,
    gym: uuid.UUID,
    *,
    months_ago: int = 3,
    paid: bool = True,
    key: str = "first",
) -> tuple[str, str, date]:
    """`lapsed_plan`'s monthly plan, its first month `paid` or not, then dado de baja
    that month, by mistake: billing stopped there. The person, the membership and the
    month's last day."""
    person, membership, end = lapsed_plan(
        client, db, gym, months_ago=months_ago, paid=paid, key=key
    )
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET status = 'cancelled', cancel_reason = 'se mudó',"
            " cancelled_at = now() - interval '1 month' WHERE id = $1",
            uuid.UUID(membership),
        ),
    )
    return person, membership, end


def path(membership: str) -> str:
    return f"/api/memberships/{membership}/uncancel"


def quote(client: TestClient, gym: uuid.UUID, membership: str, **headers: Any) -> Any:
    return client.get(path(membership), headers=as_gym(gym, **headers))


def uncancel(
    client: TestClient,
    gym: uuid.UUID,
    membership: str,
    bill_from: str | None = None,
    person_id: uuid.UUID | None = None,
) -> Any:
    body = {"reason": REASON}
    if bill_from is not None:
        body["bill_from"] = bill_from
    return client.post(path(membership), json=body, headers=as_gym(gym, person_id))


def test_undone_from_where_it_left_off_bills_the_months_since(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership, end = cancelled_plan(client, db, gym)
    expected = monthly_starts(end, today)
    assert len(expected) >= 3

    quoted = ok(quote(client, gym, membership))
    assert quoted["status"] == "active"
    assert [p["period_start"] for p in quoted["last"]["periods"]] == expected
    assert quoted["last"]["total_clp"] == PRICE * len(expected)
    assert status(client, gym, membership) == "cancelled"  # the quote saves nothing

    undone = ok(uncancel(client, gym, membership))
    assert (undone["status"], undone["cancel_reason"], undone["cancelled_at"]) == (
        "active",
        None,
        None,
    )
    periods = ledger(client, gym, membership)["periods"]
    assert sorted(p["period_start"] for p in periods)[1:] == expected

    # Its catch-up fell due while it was cancelled: the job gives it its grace from today.
    run_lapse(db, today + timedelta(days=5))
    assert status(client, gym, membership) == "active"
    run_lapse(db, today + timedelta(days=6))
    assert status(client, gym, membership) == "lapsed"


def test_undone_from_today_bills_no_day_of_the_gap(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership, end = cancelled_plan(client, db, gym, key="signup")
    month_end = add_months(today, 1) - timedelta(days=1)

    quoted = ok(quote(client, gym, membership))
    assert quoted["today"]["bills_from"] == today.isoformat()
    assert quoted["today"]["total_clp"] == PRICE

    undone = ok(uncancel(client, gym, membership, "today"))
    assert undone["status"] == "active"
    assert undone["current_period_end"] == (today - timedelta(days=1)).isoformat()
    assert undone["anchor_day"] == today.day
    periods = sorted(ledger(client, gym, membership)["periods"], key=lambda p: p["period_start"])
    assert [(p["period_start"], p["period_end"]) for p in periods[1:]] == [
        (today.isoformat(), month_end.isoformat())
    ]
    assert periods[0]["period_end"] == end.isoformat()
    assert ledger(client, gym, membership)["owed_clp"] == PRICE

    run_lapse(db, today + timedelta(days=1))
    assert status(client, gym, membership) == "active"


def test_with_a_period_past_grace_unpaid_it_comes_back_lapsed_billing_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = cancelled_plan(client, db, gym, paid=False)
    quoted = ok(quote(client, gym, membership))
    assert quoted["status"] == "lapsed"
    assert quoted["last"]["periods"] == quoted["today"]["periods"] == []

    undone = ok(uncancel(client, gym, membership, "today"))
    assert (undone["status"], undone["cancel_reason"]) == ("lapsed", None)
    assert len(ledger(client, gym, membership)["periods"]) == 1

    # Lapsed again, it is reactivated as any lapsed plan, once its debt is paid.
    [period] = ledger(client, gym, membership)["open_periods"]
    pay(client, gym, membership, period["id"], PRICE)
    reactivated = client.post(
        f"/api/memberships/{membership}/reactivate", json={"reason": "pagó"}, headers=as_gym(gym)
    )
    assert ok(reactivated)["status"] == "active"


def test_an_undo_is_recorded_with_its_status_and_from_when(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership, _ = cancelled_plan(client, db, gym, key="signup")
    ok(uncancel(client, gym, membership, "today"))
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT action, reason, actor_id, detail FROM audit_event WHERE person_id = $1",
            uuid.UUID(person),
        ),
    )
    [row] = rows
    assert (row["action"], row["reason"], row["actor_id"]) == (
        "cancel_undone",
        REASON,
        seeded_owner(gym),
    )
    detail = json.loads(row["detail"])
    assert detail["membership_id"] == membership
    assert detail["status"] == {"before": "cancelled", "after": "active"}
    assert (detail["bill_from"], detail["bills_from"]) == ("today", seeded_today().isoformat())
    assert detail["period_starts"] == [seeded_today().isoformat()]

    [listed] = ok(client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym)))[
        "items"
    ]
    assert (listed["action"], listed["reason"]) == ("cancel_undone", REASON)


# --- the database's gate (0092) -------------------------------------------------------

UNDO = (
    "UPDATE membership SET status = 'active', cancel_reason = NULL, cancelled_at = NULL"
    " WHERE id = $1"
)


def audit_row(action: str, membership: uuid.UUID, after: str = "active") -> str:
    detail = json.dumps({"membership_id": str(membership), "status": {"after": after}})
    return (
        "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, reason, detail)"
        " SELECT current_setting('app.gym_id')::uuid, now(),"
        " current_setting('app.person_id')::uuid, m.person_id,"
        f" '{action}', 'por error', '{detail}'::jsonb FROM membership m WHERE m.id = $1"
    )


def as_app(
    db: Database, gym: uuid.UUID, *statements: tuple[str, uuid.UUID], person: uuid.UUID
) -> None:
    """`statements` in one transaction, as the API runs them, acting as `person`."""

    async def go(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(person))
            for sql, arg in statements:
                await conn.execute(sql, arg)

    run(db.api_url, go)


def test_the_database_refuses_an_undo_without_its_audit_row(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = cancelled_plan(client, db, gym)
    _, other, _ = cancelled_plan(client, db, gym, key="signup")
    m, o = uuid.UUID(membership), uuid.UUID(other)
    owner = seeded_owner(gym)
    refused: list[tuple[tuple[str, uuid.UUID], ...]] = [
        # No audit row at all.
        ((UNDO, m),),
        # A row of another action: a due date moved does not open it.
        ((audit_row("due_date_changed", m), m), (UNDO, m)),
        ((audit_row("membership_reactivated", m), m), (UNDO, m)),
        # A row for another membership.
        ((audit_row("cancel_undone", o), o), (UNDO, m)),
        # A row saying another status.
        ((audit_row("cancel_undone", m, after="lapsed"), m), (UNDO, m)),
        # The right row, but changing more than the three columns.
        (
            (audit_row("cancel_undone", m), m),
            (UNDO.replace("cancelled_at = NULL", "cancelled_at = NULL, anchor_day = 9"), m),
        ),
        # The right row, but leaving it cancelled with its reason cleared.
        (
            (audit_row("cancel_undone", m), m),
            ("UPDATE membership SET cancel_reason = NULL, cancelled_at = NULL WHERE id = $1", m),
        ),
    ]
    for statements in refused:
        with pytest.raises(asyncpg.PostgresError) as error:
            as_app(db, gym, *statements, person=owner)
        assert isinstance(error.value, asyncpg.RestrictViolationError | asyncpg.CheckViolationError)
    assert status(client, gym, membership) == "cancelled"

    # A row written in an earlier transaction does not open it either.
    as_app(db, gym, (audit_row("cancel_undone", m), m), person=owner)
    with pytest.raises(asyncpg.RestrictViolationError):
        as_app(db, gym, (UNDO, m), person=owner)

    # Another admin's row does not open it for the owner.
    admin = add_staff(db, gym, "admin")

    async def two_actors(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(admin))
            await conn.execute(audit_row("cancel_undone", m), m)
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(owner))
            await conn.execute(UNDO, m)

    with pytest.raises(asyncpg.RestrictViolationError):
        run(db.api_url, two_actors)
    assert status(client, gym, membership) == "cancelled"

    # The matching row, in the same transaction, by the same person: it goes through.
    as_app(db, gym, (audit_row("cancel_undone", m), m), (UNDO, m), person=owner)
    assert status(client, gym, membership) == "active"


def test_the_database_refuses_undoing_a_voided_plan(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Voided as started by mistake: nothing was paid on it.
    _, membership, _ = cancelled_plan(client, db, gym, paid=False)
    voided = client.post(
        f"/api/memberships/{membership}/void", json={"reason": "por error"}, headers=as_gym(gym)
    )
    ok(voided)
    m = uuid.UUID(membership)
    with pytest.raises(asyncpg.RestrictViolationError):
        as_app(db, gym, (audit_row("cancel_undone", m), m), (UNDO, m), person=seeded_owner(gym))


# --- what the API refuses ----------------------------------------------------------------


def test_refused_for_a_voided_plan(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    _, membership, _ = cancelled_plan(client, db, gym, paid=False)
    ok(
        client.post(
            f"/api/memberships/{membership}/void", json={"reason": "por error"}, headers=as_gym(gym)
        )
    )
    for response in (quote(client, gym, membership), uncancel(client, gym, membership)):
        assert refusal(response)["code"] == "voided"
    assert status(client, gym, membership) == "cancelled"


def test_refused_beside_another_live_plan(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership, _ = cancelled_plan(client, db, gym)
    other = plan(client, gym, "signup")
    ok(start(client, gym, person, other, seeded_today()), 201)
    for response in (quote(client, gym, membership), uncancel(client, gym, membership)):
        refused = refusal(response)
        assert (refused["code"], refused["plan_name"]) == ("live_plan", "Mensual")
    assert status(client, gym, membership) == "cancelled"


def test_refused_for_a_person_who_left_the_gym(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership, _ = cancelled_plan(client, db, gym)
    ok(leave(client, gym, person))
    for response in (quote(client, gym, membership), uncancel(client, gym, membership)):
        assert refusal(response)["code"] == "has_left"


def test_only_a_cancelled_monthly_or_prepaid_plan_is_undone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan(client, gym, "signup")
    person = enrolled(client, gym, membership={"plan_id": plan_id})["id"]
    [active] = memberships(client, gym, person)
    assert refusal(uncancel(client, gym, active["id"]))["code"] == "not_cancelled"

    pack = plan(client, gym, "credits")
    holder = enrolled(client, gym, name="Luis Mora", membership={"plan_id": pack})["id"]
    [membership] = memberships(client, gym, holder)
    cancel = client.post(
        f"/api/memberships/{membership['id']}/cancel",
        json={"reason": "se mudó"},
        headers=as_gym(gym),
    )
    ok(cancel)
    assert refusal(quote(client, gym, membership["id"]))["code"] == "not_recurring"

    # Undone once, it is not undone again.
    _, cancelled, _ = cancelled_plan(client, db, gym)
    ok(uncancel(client, gym, cancelled))
    assert refusal(uncancel(client, gym, cancelled))["code"] == "not_cancelled"


def test_a_freeze_the_cancel_called_off_stays_called_off(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """A plan cancelled the day it started, through the API, with a freeze booked ahead:
    undone, it bills on from where it left off, and the freeze stays called off."""
    today = seeded_today()
    plan_id = plan(client, gym, "signup")
    person = enrolled(client, gym, membership={"plan_id": plan_id})["id"]
    [membership] = memberships(client, gym, person)
    booked = {
        "from_date": (today + timedelta(days=10)).isoformat(),
        "to_date": (today + timedelta(days=20)).isoformat(),
        "reason": "viaje",
    }
    ok(client.post(f"/api/memberships/{membership['id']}/freeze", json=booked, headers=as_gym(gym)))
    ok(
        client.post(
            f"/api/memberships/{membership['id']}/cancel",
            json={"reason": "se mudó"},
            headers=as_gym(gym),
        )
    )
    quoted = ok(quote(client, gym, membership["id"]))
    # Billed past today already: no gap to skip, nothing more to bill now.
    assert quoted["last"] == quoted["today"]
    assert quoted["last"]["periods"] == []

    undone = ok(uncancel(client, gym, membership["id"], "today"))
    assert undone["status"] == "active"
    assert undone["current_period_end"] == membership["current_period_end"]
    assert undone["anchor_day"] == membership["anchor_day"]
    assert undone["freeze"] is None
    assert len(ledger(client, gym, membership["id"])["periods"]) == 1


def test_an_undo_needs_a_reason_and_an_owner_or_admin(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = cancelled_plan(client, db, gym)
    blank = client.post(path(membership), json={"reason": "  "}, headers=as_gym(gym))
    assert blank.status_code == 422, blank.text
    coach = add_staff(db, gym, "coach")
    assert quote(client, gym, membership, person_id=coach).status_code == 403
    assert uncancel(client, gym, membership, person_id=coach).status_code == 403
    admin = add_staff(db, gym, "admin")
    assert ok(uncancel(client, gym, membership, person_id=admin))["status"] == "active"


def test_unknown_or_another_gyms_membership_is_a_404(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = cancelled_plan(client, db, gym)
    elsewhere = seed_gym(db, unique_slug("norte"))
    assert quote(client, elsewhere, membership).status_code == 404
    assert uncancel(client, elsewhere, membership).status_code == 404
    assert uncancel(client, gym, str(uuid.uuid4())).status_code == 404
