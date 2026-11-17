"""Memberships: starting one on each kind, changing plan next period, cancelling for good.

Dates are the gym's: a membership starts on a local calendar day, and its stored
`started_at` is that day's first instant there (migration 0009 for the rest).
"""

import dataclasses
import json
import random
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import add_months, local_date, start_of_local_day
from app.domain.membership import PlanKind, PlanTerms
from app.domain.membership import start as domain_start
from app.main import create_app
from app.schemas.memberships import STARTED_ON_WINDOW_YEARS
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
from tests.pg import (
    Database,
    in_gym,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_today,
    throwaway_database,
)
from tests.test_billing_job import generate
from tests.test_guardians import add_person, new_kid
from tests.test_proofs import RecordingMailer, sent_notices

pytestmark = pytest.mark.postgres

NOV_15 = "2026-11-15"

PLANS: dict[str, dict[str, Any]] = {
    "signup": {"kind": "monthly", "name": "Mensual", "price_clp": 45_000, "anchor": "signup"},
    "first": {"kind": "monthly", "name": "Mensual día 1", "price_clp": 45_000, "anchor": "first"},
    "prepaid": {"kind": "prepaid", "name": "Semestral", "price_clp": 240_000, "period_months": 6},
    "credits": {
        "kind": "credits",
        "name": "Pack 12",
        "price_clp": 45_000,
        "credits": 12,
        "credit_expiry_days": 60,
    },
    "trial": {"kind": "trial", "name": "Prueba", "free_classes": 2, "free_days": 14},
    "dropin": {"kind": "dropin", "name": "Clase suelta", "price_clp": 10_000},
}


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def norte(db: Database) -> uuid.UUID:
    return seed_gym(db, "dojo-norte")


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(db: Database, mailer: RecordingMailer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def plan(client: TestClient, gym: uuid.UUID, key: str) -> str:
    response = client.post("/api/plans", json=PLANS[key], headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def person(client: TestClient, gym: uuid.UUID) -> str:
    phone = f"+569{random.randrange(10**7, 10**8)}"
    response = client.post(
        "/api/people",
        json={"rut": random_rut(), "phone": phone, "name": "Alumna"},
        headers=as_gym(gym),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def start(
    client: TestClient, gym: uuid.UUID, plan_id: str, person_id: str | None = None, **body: Any
) -> Any:
    return client.post(
        "/api/memberships",
        json={"person_id": person_id or person(client, gym), "plan_id": plan_id, **body},
        headers=as_gym(gym),
    )


def started(client: TestClient, gym: uuid.UUID, key: str, **body: Any) -> dict[str, Any]:
    response = start(client, gym, plan(client, gym, key), started_on=NOV_15, **body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def unbilled(
    client: TestClient, db: Database, gym: uuid.UUID, key: str, started_on: date
) -> dict[str, Any]:
    """A membership on a new `key` plan from `started_on`, as `POST /api/memberships`
    starts one but with nothing billed yet, which that request bills at once (#196):
    for a test that writes the periods it needs."""
    plan_id = uuid.UUID(plan(client, gym, key))
    person_id = uuid.UUID(person(client, gym))

    async def query(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            row = await conn.fetchrow(
                "SELECT p.kind, p.anchor, p.credits, p.credit_expiry_days, g.timezone"
                " FROM plan p JOIN gym g ON g.id = p.gym_id WHERE p.id = $1",
                plan_id,
            )
            terms = PlanTerms(
                PlanKind(row["kind"]), row["anchor"], row["credits"], row["credit_expiry_days"]
            )
            begun = domain_start(terms, started_on)
            membership: uuid.UUID = await conn.fetchval(
                "INSERT INTO membership (gym_id, person_id, plan_id, status, anchor_day,"
                " started_at, current_period_end, credits_remaining)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                gym,
                person_id,
                plan_id,
                begun.status.value,
                begun.anchor_day,
                start_of_local_day(started_on, row["timezone"]),
                begun.current_period_end,
                begun.credits_remaining,
            )
            return membership

    membership = run(db.owner_url, query)
    response = client.get(f"/api/memberships/{membership}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return dict(response.json())


def change(client: TestClient, gym: uuid.UUID, membership: str, plan_id: str) -> Any:
    return client.post(
        f"/api/memberships/{membership}/plan-change",
        json={"plan_id": plan_id},
        headers=as_gym(gym),
    )


def cancel(client: TestClient, gym: uuid.UUID, membership: str, reason: str = "se mudó") -> Any:
    return client.post(
        f"/api/memberships/{membership}/cancel", json={"reason": reason}, headers=as_gym(gym)
    )


def stored(db: Database, membership: str) -> dict[str, Any]:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow("SELECT * FROM membership WHERE id = $1", uuid.UUID(membership)),
    )
    return dict(row)


# --- starting ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "status", "anchor_day", "period_end", "credits"),
    [
        ("signup", "active", 15, "2026-11-14", None),
        ("first", "active", 1, "2026-11-14", None),
        ("prepaid", "active", None, "2026-11-14", None),
        ("credits", "active", None, "2027-01-13", 12),
        ("trial", "trial", None, "2026-11-28", 2),
    ],
)
def test_start_each_kind(
    client: TestClient,
    db: Database,
    sur: uuid.UUID,
    key: str,
    status: str,
    anchor_day: int | None,
    period_end: str,
    credits: int | None,
) -> None:
    membership = started(client, sur, key)
    assert membership["plan_kind"] == PLANS[key]["kind"]
    assert membership["plan_name"] == PLANS[key]["name"]
    assert (
        membership["status"],
        membership["anchor_day"],
        membership["started_on"],
        membership["current_period_end"],
        membership["credits_remaining"],
    ) == (status, anchor_day, NOV_15, period_end, credits)
    assert (membership["next_plan"], membership["cancel_reason"]) == (None, None)

    row = stored(db, membership["id"])
    assert row["started_at"] == start_of_local_day(date(2026, 11, 15), "America/Santiago")
    read = client.get(f"/api/memberships/{membership['id']}", headers=as_gym(sur))
    assert read.json() == membership


def test_start_defaults_to_today_in_the_gyms_timezone(client: TestClient, db: Database) -> None:
    # UTC+14: its date is ahead of UTC's for most of the day.
    gym = seed_gym(db, "kiritimati")
    run(
        db.admin_url,
        lambda c: c.execute("UPDATE gym SET timezone = 'Pacific/Kiritimati' WHERE id = $1", gym),
    )
    before = local_date(datetime.now(UTC), "Pacific/Kiritimati")
    response = start(client, gym, plan(client, gym, "signup"))
    after = local_date(datetime.now(UTC), "Pacific/Kiritimati")

    assert response.status_code == 201, response.text
    started_on = date.fromisoformat(response.json()["started_on"])
    assert started_on in {before, after}
    assert response.json()["anchor_day"] == started_on.day


@pytest.mark.parametrize("started_on", ["0001-01-01", "9999-12-31", "2015-01-01", "2040-01-01"])
def test_start_refuses_a_day_years_from_today(
    client: TestClient, sur: uuid.UUID, started_on: str
) -> None:
    # Not a 500 from date arithmetic past the edge of `date`'s range.
    response = start(client, sur, plan(client, sur, "credits"), started_on=started_on)
    assert response.status_code == 422
    assert "within 5 years" in response.text


def test_start_takes_a_day_within_the_window(client: TestClient, sur: uuid.UUID) -> None:
    # system date: the window is reckoned from UTC's today, as `MembershipCreate` does.
    near = add_months(datetime.now(UTC).date(), -12 * STARTED_ON_WINDOW_YEARS + 1)
    response = start(client, sur, plan(client, sur, "signup"), started_on=near.isoformat())
    assert response.status_code == 201, response.text


def test_a_dropin_is_not_a_membership(client: TestClient, sur: uuid.UUID) -> None:
    response = start(client, sur, plan(client, sur, "dropin"))
    assert response.status_code == 422
    assert "drop-in" in response.json()["detail"]


def test_start_refuses_a_deactivated_plan(client: TestClient, sur: uuid.UUID) -> None:
    plan_id = plan(client, sur, "signup")
    client.patch(f"/api/plans/{plan_id}", json={"active": False}, headers=as_gym(sur))
    response = start(client, sur, plan_id)
    assert (response.status_code, response.json()["detail"]) == (422, "plan is deactivated")


def test_start_refuses_another_gyms_plan_and_person(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    other_plan = plan(client, norte, "signup")
    other_person = person(client, norte)
    assert start(client, sur, other_plan).json()["detail"] == "plan not found"
    response = start(client, sur, plan(client, sur, "signup"), other_person)
    assert (response.status_code, response.json()["detail"]) == (422, "person not found")


def test_a_persons_memberships_latest_first(client: TestClient, sur: uuid.UUID) -> None:
    person_id = person(client, sur)
    older = start(client, sur, plan(client, sur, "trial"), person_id, started_on="2026-10-01")
    newer = start(client, sur, plan(client, sur, "signup"), person_id, started_on=NOV_15)
    listed = client.get("/api/memberships", params={"person_id": person_id}, headers=as_gym(sur))
    assert [m["id"] for m in listed.json()] == [newer.json()["id"], older.json()["id"]]


def test_another_gyms_membership_is_not_found(
    client: TestClient, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    for response in (
        client.get(f"/api/memberships/{membership['id']}", headers=as_gym(norte)),
        cancel(client, norte, membership["id"]),
        change(client, norte, membership["id"], plan(client, norte, "prepaid")),
    ):
        assert response.status_code == 404
    assert client.get(f"/api/memberships/{membership['id']}", headers=as_gym(sur)).json() == (
        membership
    )


# --- changing plan ------------------------------------------------------------------


def add_period(db: Database, gym: uuid.UUID, membership: str, start: str, end: str) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO billing_period"
            " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
            " VALUES ($1, $2, $3, $4, 45000, $3)",
            gym,
            uuid.UUID(membership),
            date.fromisoformat(start),
            date.fromisoformat(end),
        ),
    )


def test_a_plan_change_waits_for_the_first_period_not_yet_billed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    membership = unbilled(client, db, sur, "signup", date.fromisoformat(NOV_15))
    prepaid = plan(client, sur, "prepaid")

    # Nothing billed or paid yet: the first period is on the new plan.
    response = change(client, sur, membership["id"], prepaid)
    assert response.status_code == 200, response.text
    pending = {"plan_id": prepaid, "plan_name": "Semestral", "starts_on": NOV_15}
    assert response.json()["next_plan"] == pending
    assert response.json()["plan_id"] == membership["plan_id"]

    # Billed ahead: the billed period keeps the current plan.
    add_period(db, sur, membership["id"], NOV_15, "2026-12-14")
    response = change(client, sur, membership["id"], prepaid)
    assert response.json()["next_plan"] == {**pending, "starts_on": "2026-12-15"}
    row = stored(db, membership["id"])
    assert (row["next_plan_id"], row["next_plan_from"]) == (
        uuid.UUID(prepaid),
        date(2026, 12, 15),
    )


def test_the_current_plan_withdraws_a_pending_change(client: TestClient, sur: uuid.UUID) -> None:
    membership = started(client, sur, "signup")
    change(client, sur, membership["id"], plan(client, sur, "first"))
    response = change(client, sur, membership["id"], membership["plan_id"])
    assert response.status_code == 200
    assert response.json() == membership


@pytest.mark.parametrize(("source", "to"), [("signup", "credits"), ("trial", "signup")])
def test_only_monthly_and_prepaid_change_plan(
    client: TestClient, sur: uuid.UUID, source: str, to: str
) -> None:
    membership = started(client, sur, source)
    response = change(client, sur, membership["id"], plan(client, sur, to))
    assert response.status_code == 422
    assert "monthly or prepaid" in response.json()["detail"]


def test_a_plan_change_refuses_a_deactivated_plan(client: TestClient, sur: uuid.UUID) -> None:
    membership = started(client, sur, "signup")
    plan_id = plan(client, sur, "prepaid")
    client.patch(f"/api/plans/{plan_id}", json={"active": False}, headers=as_gym(sur))
    assert change(client, sur, membership["id"], plan_id).status_code == 422


def quote(client: TestClient, gym: uuid.UUID, membership: str, plan_id: str) -> Any:
    return client.get(
        f"/api/memberships/{membership}/plan-change",
        params={"plan_id": plan_id},
        headers=as_gym(gym),
    )


@pytest.mark.parametrize(
    ("key", "discount", "period_end", "amount"),
    [
        ("prepaid", 0, "2027-06-14", 240_000),
        # A plan billed on the 1st: its first period runs to the end of the month.
        ("first", 0, "2026-12-31", 45_000),
        ("signup", 10, "2027-01-14", 40_500),
    ],
)
def test_a_plan_change_is_quoted_before_it_is_saved(
    client: TestClient,
    db: Database,
    sur: uuid.UUID,
    key: str,
    discount: int,
    period_end: str,
    amount: int,
) -> None:
    membership = unbilled(client, db, sur, "signup", date.fromisoformat(NOV_15))
    add_period(db, sur, membership["id"], NOV_15, "2026-12-14")
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET discount_pct = $2 WHERE id = $1",
            uuid.UUID(membership["id"]),
            discount,
        ),
    )
    to = plan(client, sur, key)

    response = quote(client, sur, membership["id"], to)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "starts_on": "2026-12-15",
        "period_end": period_end,
        "amount_due_clp": amount,
    }
    # Nothing saved; saving takes effect on the day quoted.
    assert stored(db, membership["id"])["next_plan_id"] is None
    saved = change(client, sur, membership["id"], to).json()
    assert saved["next_plan"]["starts_on"] == "2026-12-15"


def test_a_plan_change_quote_is_refused_as_the_change_would_be(
    client: TestClient, sur: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    # The plan it is on: nothing to quote.
    assert quote(client, sur, membership["id"], membership["plan_id"]).status_code == 409
    assert quote(client, sur, membership["id"], plan(client, sur, "credits")).status_code == 422
    unknown = quote(client, sur, membership["id"], str(uuid.uuid4()))
    assert unknown.status_code == 422
    cancel(client, sur, membership["id"])
    assert quote(client, sur, membership["id"], plan(client, sur, "prepaid")).status_code == 409
    assert quote(client, sur, str(uuid.uuid4()), plan(client, sur, "prepaid")).status_code == 404


def test_a_frozen_membership_is_quoted_and_changes_plan(client: TestClient, sur: uuid.UUID) -> None:
    # The API lets a frozen membership change plan (#249 follows it).
    membership = started(client, sur, "signup")
    frozen = client.post(
        f"/api/memberships/{membership['id']}/freeze",
        json={"to_date": add_months(seeded_today(), 1).isoformat(), "reason": "lesión"},
        headers=as_gym(sur),
    )
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"
    prepaid = plan(client, sur, "prepaid")
    quoted = quote(client, sur, membership["id"], prepaid)
    assert quoted.status_code == 200, quoted.text
    saved = change(client, sur, membership["id"], prepaid)
    assert saved.status_code == 200
    assert saved.json()["next_plan"]["starts_on"] == quoted.json()["starts_on"]


# --- discounts (#25) ----------------------------------------------------------------


def discount(client: TestClient, gym: uuid.UUID, membership: str, body: Any) -> Any:
    return client.put(
        f"/api/memberships/{membership}/discount", json={"discount": body}, headers=as_gym(gym)
    )


def charges(client: TestClient, gym: uuid.UUID, membership: str) -> list[tuple[Any, ...]]:
    """The membership's charges on its ledger, oldest first: the period, the amount, and
    the discount it was billed at."""
    response = client.get(f"/api/ledger/memberships/{membership}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return sorted(
        (e["period_start"], e["amount_clp"], e["discount_pct"], e["discount_reason"])
        for e in response.json()["entries"]
        if e["kind"] == "charge"
    )


def test_a_plan_starts_with_a_discount_and_its_reason(client: TestClient, sur: uuid.UUID) -> None:
    membership = started(client, sur, "signup", discount={"pct": 50, "reason": "Hermanos"})

    assert (membership["discount_pct"], membership["discount_reason"]) == (50, "Hermanos")
    assert charges(client, sur, membership["id"]) == [(NOV_15, 22_500, 50, "Hermanos")]


def test_a_discount_bills_from_the_next_period_and_keeps_the_billed_ones(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    url = f"/api/memberships/{membership['id']}/discount"

    quoted = client.get(url, params={"pct": 10}, headers=as_gym(sur))
    assert quoted.status_code == 200, quoted.text
    assert quoted.json() == {
        "starts_on": "2026-12-15",
        "period_end": "2027-01-14",
        "amount_due_clp": 40_500,
    }
    saved = discount(client, sur, membership["id"], {"pct": 10, "reason": " Beca "})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["discount_pct"], saved.json()["discount_reason"]) == (10, "Beca")

    generate(db, date(2026, 12, 10))
    assert charges(client, sur, membership["id"]) == [
        (NOV_15, 45_000, 0, None),
        ("2026-12-15", 40_500, 10, "Beca"),
    ]

    # Taken off, the next period is billed in full; December keeps its discount.
    cleared = discount(client, sur, membership["id"], None)
    assert (cleared.json()["discount_pct"], cleared.json()["discount_reason"]) == (0, None)
    generate(db, date(2027, 1, 10))
    assert charges(client, sur, membership["id"])[1:] == [
        ("2026-12-15", 40_500, 10, "Beca"),
        ("2027-01-15", 45_000, 0, None),
    ]


def test_each_discount_set_changed_or_taken_off_is_a_correction(
    client: TestClient, sur: uuid.UUID
) -> None:
    membership = started(client, sur, "signup", discount={"pct": 50, "reason": "Hermanos"})
    member = membership["id"]
    discount(client, sur, member, {"pct": 30, "reason": "Beca"})
    # The discount it has: nothing changes, nothing is recorded.
    discount(client, sur, member, {"pct": 30, "reason": "Beca"})
    discount(client, sur, member, None)

    response = client.get(
        f"/api/ledger/people/{membership['person_id']}/corrections", headers=as_gym(sur)
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert [r["action"] for r in rows] == ["discount_changed"] * 3
    # Newest first: taken off, changed, set as the plan started.
    assert [(r["reason"], r["discount"]) for r in rows] == [
        (
            "Beca",
            {
                "before": {"pct": 30, "reason": "Beca"},
                "after": {"pct": 0, "reason": None},
                "starts_on": "2026-12-15",
            },
        ),
        (
            "Beca",
            {
                "before": {"pct": 50, "reason": "Hermanos"},
                "after": {"pct": 30, "reason": "Beca"},
                "starts_on": "2026-12-15",
            },
        ),
        (
            "Hermanos",
            {
                "before": {"pct": 0, "reason": None},
                "after": {"pct": 50, "reason": "Hermanos"},
                "starts_on": NOV_15,
            },
        ),
    ]
    assert all(r["actor_name"] and r["plan_name"] == "Mensual" for r in rows)


@pytest.mark.parametrize(
    "body",
    [
        {"pct": 10},
        {"pct": 10, "reason": "  "},
        {"pct": 0, "reason": "Beca"},
        {"pct": 101, "reason": "Beca"},
    ],
)
def test_a_discount_needs_a_percentage_and_a_reason(
    client: TestClient, sur: uuid.UUID, body: dict[str, Any]
) -> None:
    membership = started(client, sur, "signup")
    assert discount(client, sur, membership["id"], body).status_code == 422
    assert start(client, sur, membership["plan_id"], discount=body).status_code == 422


@pytest.mark.parametrize("key", ["credits", "trial"])
def test_only_a_plan_that_bills_again_takes_a_discount(
    client: TestClient, sur: uuid.UUID, key: str
) -> None:
    membership = started(client, sur, key)
    body = {"pct": 10, "reason": "Beca"}
    assert discount(client, sur, membership["id"], body).status_code == 409
    url = f"/api/memberships/{membership['id']}/discount"
    assert client.get(url, params={"pct": 10}, headers=as_gym(sur)).status_code == 409


def test_a_cancelled_plan_takes_no_discount(client: TestClient, sur: uuid.UUID) -> None:
    membership = started(client, sur, "signup")
    assert cancel(client, sur, membership["id"]).status_code == 200
    body = {"pct": 10, "reason": "Beca"}
    assert discount(client, sur, membership["id"], body).status_code == 409


def test_a_frozen_plan_is_quoted_after_what_it_billed(client: TestClient, sur: uuid.UUID) -> None:
    membership = started(client, sur, "signup")
    frozen = client.post(
        f"/api/memberships/{membership['id']}/freeze",
        json={"to_date": "2026-12-01", "reason": "lesión"},
        headers=as_gym(sur),
    )
    assert frozen.status_code == 200, frozen.text
    url = f"/api/memberships/{membership['id']}/discount"
    quoted = client.get(url, params={"pct": 20}, headers=as_gym(sur))
    assert quoted.status_code == 200, quoted.text
    assert quoted.json()["amount_due_clp"] == 36_000
    body = {"pct": 20, "reason": "Beca"}
    assert discount(client, sur, membership["id"], body).status_code == 200


@pytest.mark.parametrize(("role", "writes"), [("admin", True), ("coach", False)])
def test_only_owner_or_admin_set_a_discount_and_coaches_never_see_it(
    client: TestClient, db: Database, sur: uuid.UUID, role: str, writes: bool
) -> None:
    membership = started(client, sur, "signup", discount={"pct": 50, "reason": "Hermanos"})
    headers = as_gym(sur, add_staff(db, sur, role))
    url = f"/api/memberships/{membership['id']}"

    codes = (
        client.get(f"{url}/discount", params={"pct": 10}, headers=headers).status_code,
        client.put(
            f"{url}/discount", json={"discount": {"pct": 10, "reason": "x"}}, headers=headers
        ).status_code,
    )
    assert codes == ((200, 200) if writes else (403, 403))
    read = client.get(url, headers=headers).json()
    assert ("discount_reason" in read) is writes
    assert ("discount_pct" in read) is writes


# --- cancelling ---------------------------------------------------------------------


def test_cancel_is_terminal_with_its_reason(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    change(client, sur, membership["id"], plan(client, sur, "prepaid"))

    response = cancel(client, sur, membership["id"], "  Se cambió de ciudad ")
    assert response.status_code == 200, response.text
    cancelled = response.json()
    assert (cancelled["status"], cancelled["cancel_reason"]) == ("cancelled", "Se cambió de ciudad")
    assert cancelled["cancelled_at"] is not None
    assert cancelled["next_plan"] is None

    again = cancel(client, sur, membership["id"])
    assert again.status_code == 409
    replan = change(client, sur, membership["id"], plan(client, sur, "prepaid"))
    assert replan.status_code == 409
    assert change(client, sur, membership["id"], membership["plan_id"]).status_code == 409
    assert client.get(f"/api/memberships/{membership['id']}", headers=as_gym(sur)).json() == (
        cancelled
    )


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_cancel_needs_a_reason(client: TestClient, sur: uuid.UUID, reason: str) -> None:
    membership = started(client, sur, "signup")
    assert cancel(client, sur, membership["id"], reason).status_code == 422
    get = client.get(f"/api/memberships/{membership['id']}", headers=as_gym(sur))
    assert get.json()["status"] == "active"


def test_a_trial_cannot_be_cancelled(client: TestClient, sur: uuid.UUID) -> None:
    # Per the state machine a trial converts or lapses; it is never cancelled.
    membership = started(client, sur, "trial")
    assert cancel(client, sur, membership["id"]).status_code == 409


# --- trial conversion (#27) ---------------------------------------------------------


def on_trial(client: TestClient, gym: uuid.UUID, **body: Any) -> dict[str, Any]:
    """Someone new on a new trial plan, from `started_on` or today."""
    response = start(client, gym, plan(client, gym, "trial"), **body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def paid(client: TestClient, gym: uuid.UUID, trial: dict[str, Any], key: str = "signup") -> Any:
    """`trial`'s person on a new `key` plan."""
    response = start(client, gym, plan(client, gym, key), trial["person_id"])
    assert response.status_code == 201, response.text
    return response.json()


def start_quote(client: TestClient, gym: uuid.UUID, person_id: str, plan_id: str) -> Any:
    response = client.get(
        "/api/memberships/start",
        params={"person_id": person_id, "plan_id": plan_id},
        headers=as_gym(gym),
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("key", ["signup", "prepaid", "credits"])
def test_a_paid_plan_converts_a_trial_running_and_ends_it(
    client: TestClient, db: Database, sur: uuid.UUID, key: str
) -> None:
    trial = on_trial(client, sur)

    converted = paid(client, sur, trial, key)

    assert converted["converted_from"] == {
        "id": trial["id"],
        "plan_name": "Prueba",
        "started_on": trial["started_on"],
        "running": False,
    }
    ended = client.get(f"/api/memberships/{trial['id']}", headers=as_gym(sur)).json()
    assert ended["status"] == "cancelled"
    assert ended["cancel_reason"] == "pasó a un plan"
    assert ended["cancelled_at"] is not None
    assert ended["converted_from"] is None
    assert stored(db, converted["id"])["converted_from"] == uuid.UUID(trial["id"])


def test_a_lapsed_trial_is_converted_and_stays_lapsed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    trial = on_trial(client, sur)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(trial["id"])
        ),
    )

    converted = paid(client, sur, trial)

    assert converted["converted_from"]["id"] == trial["id"]
    assert stored(db, trial["id"])["status"] == "lapsed"


def test_a_trial_converts_once(client: TestClient, sur: uuid.UUID) -> None:
    trial = on_trial(client, sur)
    paid(client, sur, trial)

    # A course beside the plan, months later: the trial was converted already.
    assert paid(client, sur, trial, "credits")["converted_from"] is None


@pytest.mark.parametrize("key", ["trial", "dropin"])
def test_a_trial_or_a_drop_in_converts_nothing(
    client: TestClient, db: Database, sur: uuid.UUID, key: str
) -> None:
    trial = on_trial(client, sur)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(trial["id"])
        ),
    )
    plan_id = plan(client, sur, key)

    assert start_quote(client, sur, trial["person_id"], plan_id)["converts"] is None
    if key == "trial":
        again = start(client, sur, plan_id, trial["person_id"])
        assert again.status_code == 201, again.text
        assert again.json()["converted_from"] is None
    # The paid plan after it converts the latest trial.
    assert paid(client, sur, trial)["converted_from"] is not None


def test_a_paid_plan_without_a_trial_converts_nothing(client: TestClient, sur: uuid.UUID) -> None:
    assert started(client, sur, "signup")["converted_from"] is None


def test_the_start_quote_names_the_trial_it_converts(client: TestClient, sur: uuid.UUID) -> None:
    trial = on_trial(client, sur)
    monthly = plan(client, sur, "signup")

    assert start_quote(client, sur, trial["person_id"], monthly)["converts"] == {
        "id": trial["id"],
        "plan_name": "Prueba",
        "started_on": trial["started_on"],
        "running": True,
    }
    # Nothing saved.
    got = client.get(f"/api/memberships/{trial['id']}", headers=as_gym(sur)).json()
    assert got["status"] == "trial"


def test_a_plan_voided_gives_its_trial_back(client: TestClient, sur: uuid.UUID) -> None:
    trial = on_trial(client, sur)
    mistake = paid(client, sur, trial)
    voided = client.post(
        f"/api/memberships/{mistake['id']}/void",
        json={"reason": "plan equivocado"},
        headers=as_gym(sur),
    )
    assert voided.status_code == 200, voided.text

    assert paid(client, sur, trial)["converted_from"]["id"] == trial["id"]


def test_trial_conversions_counts_the_last_90_days(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, f"pruebas-{uuid.uuid4().hex[:8]}")
    today = seeded_today()
    old = on_trial(client, gym, started_on=(today - timedelta(days=90)).isoformat())
    paid(client, gym, old)
    converted = on_trial(client, gym, started_on=(today - timedelta(days=89)).isoformat())
    paid(client, gym, converted)
    on_trial(client, gym)
    lapsed = on_trial(client, gym)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET status = 'lapsed' WHERE id = $1", uuid.UUID(lapsed["id"])
        ),
    )

    response = client.get("/api/memberships/trials", headers=as_gym(gym))

    assert response.status_code == 200, response.text
    assert response.json() == {"days": 90, "started": 3, "converted": 1, "running": 1}


# --- roles --------------------------------------------------------------------------


def add_staff(db: Database, gym: uuid.UUID, role: str) -> uuid.UUID:
    staff = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", staff)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, staff
        )
        await make_staff(conn, gym, staff, role)

    run(db.admin_url, query)
    return staff


@pytest.mark.parametrize(("role", "writes"), [("admin", True), ("coach", False)])
def test_coaches_read_memberships_and_only_owner_or_admin_change_them(
    client: TestClient, db: Database, sur: uuid.UUID, role: str, writes: bool
) -> None:
    membership = started(client, sur, "signup")
    prepaid = plan(client, sur, "prepaid")
    headers = as_gym(sur, add_staff(db, sur, role))

    url = f"/api/memberships/{membership['id']}"
    assert client.get(url, headers=headers).status_code == 200
    listed = client.get(
        "/api/memberships", params={"person_id": membership["person_id"]}, headers=headers
    )
    assert listed.status_code == 200
    body = {"person_id": membership["person_id"], "plan_id": prepaid}
    codes = (
        client.post("/api/memberships", json=body, headers=headers).status_code,
        client.get(f"{url}/plan-change", params={"plan_id": prepaid}, headers=headers).status_code,
        client.post(f"{url}/plan-change", json={"plan_id": prepaid}, headers=headers).status_code,
        client.post(f"{url}/cancel", json={"reason": "x"}, headers=headers).status_code,
    )
    assert codes == ((201, 200, 200, 200) if writes else (403, 403, 403, 403))


# --- the table on its own (migration 0009) --------------------------------------------


def test_a_cancelled_row_is_final_for_every_role(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    cancel(client, sur, membership["id"])
    update = "UPDATE membership SET status = 'active', cancel_reason = NULL, cancelled_at = NULL"
    for url in (db.api_url, db.owner_url, db.admin_url):
        with pytest.raises(asyncpg.RestrictViolationError, match="cancelled membership"):
            run(url, in_gym(sur, f"{update} WHERE id = $1", uuid.UUID(membership["id"])))


@pytest.mark.parametrize(
    "assignments",
    [
        "status = 'cancelled'",  # no reason
        "cancel_reason = 'x', cancelled_at = now()",  # a reason on a live membership
        "next_plan_id = plan_id",  # no day it starts
        "status = 'cancelled', cancel_reason = 'x', cancelled_at = now(),"
        " next_plan_id = plan_id, next_plan_from = '2026-12-01'",  # pending on a cancelled one
    ],
)
def test_the_table_holds_cancellation_and_plan_change_together(
    client: TestClient, db: Database, sur: uuid.UUID, assignments: str
) -> None:
    membership = started(client, sur, "signup")
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.owner_url,
            in_gym(
                sur,
                f"UPDATE membership SET {assignments} WHERE id = $1",
                uuid.UUID(membership["id"]),
            ),
        )


def test_a_pending_plan_is_this_gyms(
    client: TestClient, db: Database, sur: uuid.UUID, norte: uuid.UUID
) -> None:
    membership = started(client, sur, "signup")
    other = uuid.UUID(plan(client, norte, "prepaid"))
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        run(
            db.admin_url,
            lambda c: c.execute(
                "UPDATE membership SET next_plan_id = $2, next_plan_from = '2026-12-01'"
                " WHERE id = $1",
                uuid.UUID(membership["id"]),
                other,
            ),
        )


def test_the_upgrade_gives_rows_cancelled_before_it_a_reason() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0008")
        gym = seed_gym(database, "antes")
        run(database.admin_url, lambda c: c.execute("UPDATE membership SET status = 'cancelled'"))
        migrate(database)
        row = run(database.admin_url, lambda c: c.fetchrow("SELECT * FROM membership"))
        assert (row["gym_id"], row["cancel_reason"]) == (gym, "sin motivo registrado")
        assert row["cancelled_at"] is not None

        command.downgrade(database.alembic(), "0008")
        columns = run(
            database.admin_url,
            lambda c: c.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'membership'"
            ),
        )
        assert {"cancel_reason", "next_plan_id"}.isdisjoint({r[0] for r in columns})


def test_the_upgrade_gives_periods_billed_before_it_their_memberships_discount() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0065")
        seed_gym(database, "antes")
        run(database.admin_url, lambda c: c.execute("UPDATE membership SET discount_pct = 15"))
        migrate(database)
        row = run(database.admin_url, lambda c: c.fetchrow("SELECT * FROM billing_period"))
        assert (row["discount_pct"], row["discount_reason"]) == (15, None)

        # A reason only with a discount.
        with pytest.raises(asyncpg.CheckViolationError):
            run(
                database.admin_url,
                lambda c: c.execute(
                    "UPDATE membership SET discount_pct = 0, discount_reason = 'Beca'"
                ),
            )

        command.downgrade(database.alembic(), "0065")
        columns = run(
            database.admin_url,
            lambda c: c.fetch(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name IN ('membership', 'billing_period')"
            ),
        )
        assert "discount_reason" not in {r[0] for r in columns}


# --- the welcome email ----------------------------------------------------------

BANK = {
    "bank": "Banco Estado",
    "account_type": "Cuenta RUT",
    "holder": "Academia Sur SpA",
    "rut": "76.123.456-7",
    "number": "12345678",
}


def test_starting_a_membership_welcomes_the_member(
    client: TestClient, db: Database, mailer: RecordingMailer
) -> None:
    gym = seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym SET settings = settings || jsonb_build_object('bank_account', $2::jsonb)"
            " WHERE id = $1",
            gym,
            json.dumps(BANK),
        ),
    )
    ana = add_person(client, gym, "Ana")
    mailer.sent.clear()

    response = start(client, gym, plan(client, gym, "signup"), ana)

    assert response.status_code == 201, response.text
    [email] = mailer.sent
    assert email.to == "ana@example.cl"
    assert email.subject.startswith("Te damos la bienvenida a academia-")
    assert "Hola, Ana:" in email.text
    assert f"Tu inscripción en el plan {PLANS['signup']['name']} quedó lista." in email.text
    assert "Número: 12345678" in email.text
    assert "sube el comprobante desde tu página" in email.text
    # Their first sign-in link, to the student page.
    [url] = [line for line in email.text.splitlines() if line.startswith("Tu página: ")]
    assert "/api/auth/callback?token=" in url
    assert url.endswith("&next=%2Fme")
    assert sent_notices(db, gym)[-1] == ("welcome", ana, "sent")


def test_a_dependents_welcome_goes_to_the_guardian(
    client: TestClient, db: Database, mailer: RecordingMailer
) -> None:
    gym = seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")
    marta = add_person(client, gym, "Marta")
    juan = new_kid(client, gym, marta, "Juan")
    mailer.sent.clear()

    assert start(client, gym, plan(client, gym, "signup"), juan).status_code == 201

    [email] = mailer.sent
    assert email.to == "marta@example.cl"
    assert "La inscripción de Juan en el plan" in email.text
    assert "donde están los datos de la cuenta" in email.text
    assert sent_notices(db, gym)[-1] == ("welcome", marta, "sent")


def test_a_member_with_no_email_is_not_welcomed(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()

    assert start(client, sur, plan(client, sur, "signup")).status_code == 201

    assert mailer.sent == []


def test_the_welcome_can_be_left_out(
    client: TestClient, db: Database, mailer: RecordingMailer
) -> None:
    # "Asignar plan" on the ficha, with the welcome unticked (#249).
    gym = seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")
    ana = add_person(client, gym, "Ana")
    mailer.sent.clear()

    response = start(client, gym, plan(client, gym, "signup"), ana, send_welcome=False)

    assert response.status_code == 201, response.text
    assert mailer.sent == []
    assert sent_notices(db, gym) == []
