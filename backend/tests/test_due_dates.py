"""Mover vencimiento (#283): "le doy hasta el 10", a period's due date moved by hand.

A period not paid in full falls due on another day, from its start to its end plus 60
days, with a reason. The nightly lapse and the overdue emails read the due date, so
both follow it; the ficha reads "vence 10 nov (antes 1 nov)"; a `due_date_changed`
audit row records who, when, why and the date before and after. The period's amount
never changes: the database refuses an `UPDATE` of `amount_due_clp`
(`billing_period_amount_fixed`, 0090), since amounts change only by adjustments.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain import billing
from app.domain.billing import BillingPeriod
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
from tests.test_corrections import audit_rows
from tests.test_lapsed_reassign import run_lapse, status
from tests.test_member_roll import enrolled, memberships, plan
from tests.test_overdue_emails import night
from tests.test_plans import add_staff
from tests.test_statements_job import Outbox
from tests.test_voids import ledger, ok, overdue_ids, pay, void

pg = pytest.mark.postgres

WHY = "le doy hasta el 10"

# --- the domain, no database ------------------------------------------------------


def test_a_due_date_goes_from_the_periods_start_to_its_end_plus_60_days() -> None:
    period = BillingPeriod(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount_due_clp=45_000,
        due_date=date(2026, 11, 1),
    )
    assert billing.due_date_bounds(period) == (date(2026, 11, 1), date(2027, 1, 29))


# --- against real Postgres --------------------------------------------------------


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


def member(
    client: TestClient, db: Database, gym: uuid.UUID, days_ago: int
) -> tuple[str, str, dict[str, Any]]:
    """A student with an email, on a monthly plan of 45.000 since `days_ago`, created
    that long ago too, so the lapse judges them by their due date alone. Their id, their
    membership's, and their oldest open period."""
    started_on = seeded_today() - timedelta(days=days_ago)
    body = enrolled(
        client,
        gym,
        name="Prueba Test",
        email=f"prueba-{uuid.uuid4().hex[:8]}@example.cl",
        membership={"plan_id": plan(client, gym), "started_on": started_on.isoformat()},
    )
    [membership] = memberships(client, gym, body["id"])
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET created_at = created_at - make_interval(days => $2)"
            " WHERE id = $1",
            uuid.UUID(membership["id"]),
            days_ago,
        ),
    )
    oldest = ledger(client, gym, membership["id"])["open_periods"][0]
    return body["id"], membership["id"], oldest


def move(client: TestClient, gym: uuid.UUID, period: str, to: date, **kw: Any) -> Any:
    body = {"due_date": to.isoformat(), "reason": WHY}
    return client.patch(
        f"/api/ledger/periods/{period}/due-date", json=body, headers=as_gym(gym, **kw)
    )


def refusal(response: Any) -> Any:
    assert response.status_code == 409, response.text
    return response.json()["detail"]


def period_of(read: Any, period: str) -> Any:
    return next(p for p in read["periods"] if p["id"] == period)


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_a_due_date_moves_and_the_ficha_and_correcciones_read_it(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    today = seeded_today()
    person, membership, oldest = member(client, db, gym, days_ago=2)
    assert oldest["id"] in overdue_ids(client, gym)
    was = date.fromisoformat(oldest["due_date"])
    to = today + timedelta(days=8)

    by = add_staff(db, gym, "admin") if role == "admin" else None
    moved = ok(move(client, gym, oldest["id"], to, **({"person_id": by} if by else {})))
    assert moved == {
        "id": oldest["id"],
        "due_date": to.isoformat(),
        "due_date_was": was.isoformat(),
    }

    # Due later, so not owed today: off Hoy, and nothing owed on the ficha.
    read = ledger(client, gym, membership)
    [open_period] = [p for p in read["open_periods"] if p["id"] == oldest["id"]]
    assert (open_period["due_date"], open_period["due"], open_period["days_overdue"]) == (
        to.isoformat(),
        False,
        0,
    )
    assert read["owed_clp"] == 0
    assert oldest["id"] not in overdue_ids(client, gym)
    # "vence 10 nov (antes 1 nov)"; the amount stays.
    period = period_of(read, oldest["id"])
    assert (period["due_date"], period["due_date_was"]) == (to.isoformat(), was.isoformat())
    assert period["outstanding_clp"] == 45_000

    [row] = [r for r in audit_rows(db, gym, person) if r["action"] == "due_date_changed"]
    actor = by or seeded_owner(gym)
    assert (row["actor_id"], row["reason"]) == (actor, WHY)
    assert row["detail"] == {
        "membership_id": membership,
        "billing_period_id": oldest["id"],
        "due_date": {"before": was.isoformat(), "after": to.isoformat()},
    }
    [shown] = ok(client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym)))[
        "items"
    ]
    assert (shown["action"], shown["period_start"], shown["reason"]) == (
        "due_date_changed",
        oldest["period_start"],
        WHY,
    )
    assert shown["due_date"] == {"before": was.isoformat(), "after": to.isoformat()}
    assert shown["before"] is None

    # Moved twice, it still reads as before the first.
    later = to + timedelta(days=2)
    ok(move(client, gym, oldest["id"], later))
    period = period_of(ledger(client, gym, membership), oldest["id"])
    assert (period["due_date"], period["due_date_was"]) == (later.isoformat(), was.isoformat())
    # Moved back to where it was billed, there is no "antes".
    ok(move(client, gym, oldest["id"], was))
    assert period_of(ledger(client, gym, membership), oldest["id"])["due_date_was"] is None


@pg
def test_a_due_date_moved_past_tonights_lapse_keeps_the_plan_active_until_its_own_grace(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    # Due 6 days ago, past its 5 days of grace: tonight's run lapses it.
    _, kept, kept_period = member(client, db, gym, days_ago=6)
    _, lapses, _ = member(client, db, gym, days_ago=6)
    to = today + timedelta(days=3)
    ok(move(client, gym, kept_period["id"], to))

    run_lapse(db, today)
    assert status(client, gym, lapses) == "lapsed"
    assert status(client, gym, kept) == "active"
    # Its new due date plus the grace, and the night after it lapses.
    run_lapse(db, to + timedelta(days=5))
    assert status(client, gym, kept) == "active"
    run_lapse(db, to + timedelta(days=6))
    assert status(client, gym, kept) == "lapsed"


@pg
def test_the_overdue_emails_follow_the_new_due_date(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person, _, period = member(client, db, gym, days_ago=0)
    to = today + timedelta(days=4)
    ok(move(client, gym, period["id"], to))

    outbox = Outbox()
    for offset in range(0, 6):
        night(db, today + timedelta(days=offset), outbox)
    sent = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT payload ->> 'on' AS on, payload ->> 'due_date' AS due,"
            " payload ->> 'days_overdue' AS days FROM message_log"
            " WHERE person_id = $1 AND template = 'payment_overdue' ORDER BY sent_at",
            uuid.UUID(person),
        ),
    )
    # Nothing on the day it was billed to fall due: on its new due date, and the day after.
    assert [(r["on"], r["due"], r["days"]) for r in sent] == [
        (to.isoformat(), to.isoformat(), "0"),
        ((to + timedelta(days=1)).isoformat(), to.isoformat(), "1"),
    ]


@pg
def test_a_period_paid_in_full_or_voided_keeps_its_due_date(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    to = seeded_today() + timedelta(days=5)
    _, membership, paid = member(client, db, gym, days_ago=40)
    pay(client, gym, membership, paid["id"])
    assert refusal(move(client, gym, paid["id"], to))["code"] == "paid"

    _, membership, voided = member(client, db, gym, days_ago=40)
    ok(void(client, gym, membership, voided["id"]), 201)
    assert refusal(move(client, gym, voided["id"], to))["code"] == "paid"


@pg
def test_a_due_date_stays_within_the_period_and_60_days_after_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, _, period = member(client, db, gym, days_ago=2)
    start = date.fromisoformat(period["period_start"])
    end = date.fromisoformat(period["period_end"])
    latest = end + timedelta(days=60)

    for day in (start - timedelta(days=1), latest + timedelta(days=1)):
        refused = refusal(move(client, gym, period["id"], day))
        assert refused["code"] == "out_of_range"
        assert (refused["earliest"], refused["latest"]) == (start.isoformat(), latest.isoformat())
    assert refusal(move(client, gym, period["id"], date.fromisoformat(period["due_date"])))[
        "code"
    ] == ("unchanged")
    # A reason is required.
    body = {"due_date": latest.isoformat(), "reason": "  "}
    response = client.patch(
        f"/api/ledger/periods/{period['id']}/due-date", json=body, headers=as_gym(gym)
    )
    assert response.status_code == 422
    assert not [r for r in audit_rows(db, gym, person) if r["action"] == "due_date_changed"]
    # Both ends are allowed.
    ok(move(client, gym, period["id"], latest))
    ok(move(client, gym, period["id"], start + timedelta(days=1)))


@pg
def test_a_coach_cannot_move_a_due_date_nor_anyone_another_gyms(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, _, period = member(client, db, gym, days_ago=2)
    to = seeded_today() + timedelta(days=5)
    coach = add_staff(db, gym, "coach")
    assert move(client, gym, period["id"], to, person_id=coach).status_code == 403
    other = seed_gym(db, unique_slug("norte"))
    assert move(client, other, period["id"], to).status_code == 404
    assert move(client, gym, str(uuid.uuid4()), to).status_code == 404


@pg
def test_the_database_refuses_a_change_to_a_periods_amount_due(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, period = member(client, db, gym, days_ago=2)
    period_id = uuid.UUID(period["id"])
    change = "UPDATE billing_period SET amount_due_clp = amount_due_clp - 5000 WHERE id = $1"
    # Neither the app nor the owner, who runs the migrations and the jobs.
    with pytest.raises(asyncpg.RestrictViolationError, match="amount due cannot change"):
        run(db.api_url, in_gym(gym, change, period_id, person=seeded_owner(gym)))
    with pytest.raises(asyncpg.RestrictViolationError):
        run(db.owner_url, in_gym(gym, change, period_id))
    # Its dates still move, as a freeze moves them.
    run(
        db.owner_url,
        in_gym(gym, "SELECT shift_billing_periods($1, $2, 7)", uuid.UUID(membership), date.min),
    )
    [row] = run(
        db.owner_url,
        in_gym(gym, "SELECT amount_due_clp, due_date FROM billing_period WHERE id = $1", period_id),
    )
    assert row["amount_due_clp"] == 45_000
    assert row["due_date"] == date.fromisoformat(period["due_date"]) + timedelta(days=7)
    # A freeze moved it, not "Mover vencimiento": no "antes".
    assert period_of(ledger(client, gym, membership), period["id"])["due_date_was"] is None


def test_upgrade_and_downgrade_0090() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0089")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0089")
        migrate(scratch)
