"""Reactivar plan caducado (#284): a lapsed plan Active again, by hand.

A member whose plan lapsed months ago pays what they owed; the plan stays lapsed until
the owner reactivates it, billing from where it left off (the months since the lapse,
one per cycle, at once) or from today (the gap never billed). Hoy and Alumnos show it
Active, and the nightly lapse leaves it alone tonight: it has its grace from the day it
was reactivated. Refused while a period past grace is unpaid, which the job would lapse
again, and beside another live plan of the person for the same program: a course in its
own program leaves it be (#354).
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months, start_of_local_day
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    DEFAULT_TIMEZONE,
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_today,
    throwaway_database,
)
from tests.test_lapsed_reassign import ledger, ok, overdue, run_lapse, shown, start, status
from tests.test_member_roll import enrolled, memberships, plan
from tests.test_memberships import add_staff
from tests.test_plans import CREDITS

pytestmark = pytest.mark.postgres

PRICE = 45_000


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


def lapsed_plan(
    client: TestClient,
    db: Database,
    gym: uuid.UUID,
    *,
    months_ago: int = 3,
    paid: bool = True,
    key: str = "first",
) -> tuple[str, str, date]:
    """A monthly plan on the 1st, started and created `months_ago` months back, billed
    its first month and lapsed since; that month `paid` after the lapse, as a member
    paying an old debt does. The person, the membership and the month's last day."""
    first = add_months(seeded_today().replace(day=1), -months_ago)
    end = add_months(first, 1) - timedelta(days=1)
    plan_id = plan(client, gym, key)
    person = enrolled(client, gym, name="Rosa Vidal")["id"]
    started = start_of_local_day(first, DEFAULT_TIMEZONE)
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "WITH m AS ("
            " INSERT INTO membership (gym_id, person_id, plan_id, status, anchor_day,"
            " started_at, created_at, current_period_end)"
            " VALUES (current_setting('app.gym_id')::uuid, $1, $2, 'lapsed', 1, $3, $3, $4)"
            " RETURNING id),"
            " bp AS ("
            " INSERT INTO billing_period (gym_id, membership_id, period_start, period_end,"
            " amount_due_clp, due_date)"
            " SELECT current_setting('app.gym_id')::uuid, m.id, $5, $6, $7, $5 FROM m"
            " RETURNING id, membership_id)"
            " INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, validated_at)"
            " SELECT current_setting('app.gym_id')::uuid, bp.membership_id, bp.id, $7,"
            " 'charge', 'validated', now() FROM bp RETURNING membership_id, billing_period_id",
            uuid.UUID(person),
            uuid.UUID(plan_id),
            started,
            first - timedelta(days=1),
            first,
            end,
            PRICE,
        ),
    )
    membership, period = str(rows[0][0]), str(rows[0][1])
    if paid:
        pay(client, gym, membership, period, PRICE)
    return person, membership, end


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> Any:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "method": "cash",
    }
    return ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)


def path(membership: str) -> str:
    return f"/api/memberships/{membership}/reactivate"


def quote(client: TestClient, gym: uuid.UUID, membership: str, **headers: Any) -> Any:
    return client.get(path(membership), headers=as_gym(gym, **headers))


def reactivate(
    client: TestClient,
    gym: uuid.UUID,
    membership: str,
    bill_from: str | None = None,
    person_id: uuid.UUID | None = None,
) -> Any:
    body = {"reason": "volvió y pagó lo que debía"}
    if bill_from is not None:
        body["bill_from"] = bill_from
    return client.post(path(membership), json=body, headers=as_gym(gym, person_id))


def monthly_starts(after: date, today: date) -> list[str]:
    """The 1sts after `after` that the job bills by `today`, its 7 days ahead included."""
    starts = []
    day = after + timedelta(days=1)
    while day <= today + timedelta(days=7):
        starts.append(day.isoformat())
        day = add_months(day, 1)
    return starts


def refusal(response: Any) -> dict[str, Any]:
    assert response.status_code == 409, response.text
    return dict(response.json()["detail"])


def test_reactivated_from_where_it_left_off_bills_the_months_since(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    person, membership, end = lapsed_plan(client, db, gym)
    expected = monthly_starts(end, today)
    assert len(expected) >= 3

    quoted = ok(quote(client, gym, membership))
    assert quoted["last"]["bills_from"] == expected[0]
    assert [p["period_start"] for p in quoted["last"]["periods"]] == expected
    assert quoted["last"]["total_clp"] == PRICE * len(expected)
    assert status(client, gym, membership) == "lapsed"  # the quote saves nothing

    reactivated = ok(reactivate(client, gym, membership))
    assert reactivated["status"] == "active"
    periods = ledger(client, gym, membership)["periods"]
    assert sorted(p["period_start"] for p in periods)[1:] == expected
    assert ledger(client, gym, membership)["owed_clp"] == PRICE * sum(
        1 for s in expected if s <= today.isoformat()
    )

    # Hoy lists what it owes under an Active plan; Alumnos shows it Active.
    rows = [p for p in overdue(client, gym) if p["person_id"] == person]
    assert rows and {r["membership_status"] for r in rows} == {"active"}
    assert shown(client, gym, person) == membership
    people = ok(client.get("/api/people", headers=as_gym(gym)))["items"]
    [row] = [r for r in people if r["id"] == person]
    assert row["membership"]["status"] == "active"

    # Its catch-up fell due while it was lapsed: the job gives it its grace from today.
    run_lapse(db, today)
    run_lapse(db, today + timedelta(days=1))
    run_lapse(db, today + timedelta(days=5))
    assert status(client, gym, membership) == "active"
    run_lapse(db, today + timedelta(days=6))
    assert status(client, gym, membership) == "lapsed"


def test_reactivated_from_today_bills_no_day_of_the_gap(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    _, membership, end = lapsed_plan(client, db, gym, key="signup")
    month_end = add_months(today, 1) - timedelta(days=1)

    quoted = ok(quote(client, gym, membership))["today"]
    assert quoted == {
        "bills_from": today.isoformat(),
        "periods": [
            {
                "period_start": today.isoformat(),
                "period_end": month_end.isoformat(),
                "due_date": today.isoformat(),
                "amount_due_clp": PRICE,
            }
        ],
        "total_clp": PRICE,
    }

    reactivated = ok(reactivate(client, gym, membership, "today"))
    assert reactivated["status"] == "active"
    # Paid through yesterday, and billing on today's day of the month from now on.
    assert reactivated["current_period_end"] == (today - timedelta(days=1)).isoformat()
    assert reactivated["anchor_day"] == today.day
    periods = sorted(ledger(client, gym, membership)["periods"], key=lambda p: p["period_start"])
    assert [(p["period_start"], p["period_end"]) for p in periods[1:]] == [
        (today.isoformat(), month_end.isoformat())
    ]
    assert periods[0]["period_end"] == end.isoformat()
    assert ledger(client, gym, membership)["owed_clp"] == PRICE

    run_lapse(db, today + timedelta(days=1))
    assert status(client, gym, membership) == "active"


def test_a_reactivation_is_recorded_with_its_status_and_from_when(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership, _ = lapsed_plan(client, db, gym, key="signup")
    ok(reactivate(client, gym, membership, "today"))
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT action, reason, person_id, detail FROM audit_event WHERE person_id = $1",
            uuid.UUID(person),
        ),
    )
    [row] = rows
    assert (row["action"], row["reason"], str(row["person_id"])) == (
        "membership_reactivated",
        "volvió y pagó lo que debía",
        person,
    )
    detail = json.loads(row["detail"])
    assert detail["membership_id"] == membership
    assert detail["status"] == {"before": "lapsed", "after": "active"}
    assert (detail["bill_from"], detail["bills_from"]) == ("today", seeded_today().isoformat())
    assert len(detail["billing_period_ids"]) == 1

    # The ficha's "Correcciones" lists it.
    [listed] = ok(client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym)))[
        "items"
    ]
    assert (listed["action"], listed["reason"]) == (
        "membership_reactivated",
        "volvió y pagó lo que debía",
    )


def test_refused_while_a_period_past_grace_is_unpaid(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, end = lapsed_plan(client, db, gym, paid=False)
    first = add_months(end + timedelta(days=1), -1)
    for response in (quote(client, gym, membership), reactivate(client, gym, membership)):
        refused = refusal(response)
        assert (refused["code"], refused["amount_clp"], refused["period_start"]) == (
            "unpaid",
            PRICE,
            first.isoformat(),
        )
    assert status(client, gym, membership) == "lapsed"
    assert len(ledger(client, gym, membership)["periods"]) == 1

    # Paid, it goes through.
    [period] = ledger(client, gym, membership)["open_periods"]
    pay(client, gym, membership, period["id"], PRICE)
    assert ok(reactivate(client, gym, membership))["status"] == "active"


def test_refused_beside_another_live_plan(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership, _ = lapsed_plan(client, db, gym)
    other = plan(client, gym, "signup")
    ok(start(client, gym, person, other, seeded_today()), 201)
    for response in (quote(client, gym, membership), reactivate(client, gym, membership)):
        refused = refusal(response)
        assert (refused["code"], refused["plan_name"]) == ("live_plan", "Mensual")
    assert status(client, gym, membership) == "lapsed"


def test_a_course_in_another_program_does_not_refuse_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # A course of credits in its own program, beside the monthly plan open to every
    # class (#354).
    person, membership, _ = lapsed_plan(client, db, gym)
    program = ok(client.post("/api/programs", json={"name": "Curso"}, headers=as_gym(gym)), 201)
    course = ok(
        client.post(
            "/api/plans",
            json={**CREDITS, "name": "Curso 8 sesiones", "credits": 8, "program_id": program["id"]},
            headers=as_gym(gym),
        ),
        201,
    )
    ok(start(client, gym, person, course["id"], seeded_today()), 201)
    assert ok(reactivate(client, gym, membership))["status"] == "active"
    assert status(client, gym, membership) == "active"


def test_only_a_lapsed_monthly_or_prepaid_plan_is_reactivated(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    plan_id = plan(client, gym, "signup")
    person = enrolled(client, gym, membership={"plan_id": plan_id})["id"]
    [active] = memberships(client, gym, person)
    assert refusal(reactivate(client, gym, active["id"]))["code"] == "not_lapsed"

    pack = plan(client, gym, "credits")
    holder = enrolled(client, gym, name="Luis Mora", membership={"plan_id": pack})["id"]
    [membership] = memberships(client, gym, holder)
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET status = 'lapsed', credits_remaining = 0 WHERE id = $1",
            uuid.UUID(membership["id"]),
        ),
    )
    assert refusal(quote(client, gym, membership["id"]))["code"] == "not_recurring"

    # Reactivated once, it is not reactivated again.
    _, lapsed, _ = lapsed_plan(client, db, gym)
    ok(reactivate(client, gym, lapsed))
    assert refusal(reactivate(client, gym, lapsed))["code"] == "not_lapsed"


def test_a_fixed_period_plan_is_not_reactivated_once_its_period_ended(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    season = client.post(
        "/api/plans",
        json={
            "kind": "fixed_period",
            "name": "Temporada",
            "price_clp": 300_000,
            "period_start": (today - timedelta(days=30)).isoformat(),
            "period_end": (today + timedelta(days=30)).isoformat(),
        },
        headers=as_gym(gym),
    ).json()["id"]
    person = enrolled(client, gym, name="Rosa Vidal", membership={"plan_id": season})["id"]
    [membership] = memberships(client, gym, person)
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE plan SET period_end = $2 WHERE id = $1",
            uuid.UUID(season),
            today - timedelta(days=1),
        ),
    )
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET status = 'lapsed' WHERE id = $1",
            uuid.UUID(membership["id"]),
        ),
    )

    for response in (
        quote(client, gym, membership["id"]),
        reactivate(client, gym, membership["id"]),
    ):
        assert refusal(response)["code"] == "period_ended"
    assert status(client, gym, membership["id"]) == "lapsed"


def test_a_reactivation_needs_a_reason_and_an_owner_or_admin(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = lapsed_plan(client, db, gym)
    blank = client.post(path(membership), json={"reason": "  "}, headers=as_gym(gym))
    assert blank.status_code == 422, blank.text
    unknown = client.post(
        path(membership), json={"reason": "volvió", "bill_from": "ayer"}, headers=as_gym(gym)
    )
    assert unknown.status_code == 422, unknown.text
    coach = add_staff(db, gym, "coach")
    assert quote(client, gym, membership, person_id=coach).status_code == 403
    assert reactivate(client, gym, membership, person_id=coach).status_code == 403
    admin = add_staff(db, gym, "admin")
    assert ok(reactivate(client, gym, membership, person_id=admin))["status"] == "active"


def test_unknown_or_another_gyms_membership_is_a_404(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership, _ = lapsed_plan(client, db, gym)
    elsewhere = seed_gym(db, unique_slug("norte"))
    assert quote(client, elsewhere, membership).status_code == 404
    assert reactivate(client, elsewhere, membership).status_code == 404
    assert reactivate(client, gym, str(uuid.uuid4())).status_code == 404


def test_from_today_with_no_gap_bills_on_from_where_it_left_off(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """A plan that billed past yesterday has no gap to skip: from today, it bills on
    after its last period, on its own anchor day, never a period cut to today's day."""
    _, membership, end = lapsed_plan(client, db, gym, months_ago=0)
    quoted = ok(quote(client, gym, membership))
    assert quoted["today"] == quoted["last"]
    assert quoted["last"]["bills_from"] == (end + timedelta(days=1)).isoformat()

    reactivated = ok(reactivate(client, gym, membership, "today"))
    assert (reactivated["anchor_day"], reactivated["current_period_end"]) == (
        1,
        (seeded_today().replace(day=1) - timedelta(days=1)).isoformat(),
    )


def test_with_no_grace_the_refusal_names_the_period_and_what_it_owes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """With `grace_days = 0` a period due today lapses the plan tonight, and one due
    tomorrow does not yet: the refusal fires only on a period due by today, which is what
    it reports."""
    run(
        db.owner_url,
        in_gym(gym, """UPDATE gym SET settings = settings || '{"grace_days": 0}'"""),
    )
    today = seeded_today()
    _, membership, _ = lapsed_plan(client, db, gym)

    def unpaid_period(on: date) -> None:
        run(
            db.owner_url,
            in_gym(
                gym,
                "WITH bp AS (INSERT INTO billing_period (gym_id, membership_id, period_start,"
                " period_end, amount_due_clp, due_date) VALUES"
                " (current_setting('app.gym_id')::uuid, $1, $2, $2, $3, $2) RETURNING id)"
                " INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
                " kind, status, validated_at) SELECT current_setting('app.gym_id')::uuid, $1,"
                " bp.id, $3, 'charge', 'validated', now() FROM bp",
                uuid.UUID(membership),
                on,
                PRICE,
            ),
        )

    unpaid_period(today + timedelta(days=1))
    ok(quote(client, gym, membership))
    unpaid_period(today)
    refused = refusal(quote(client, gym, membership))
    assert (refused["code"], refused["period_start"], refused["amount_clp"]) == (
        "unpaid",
        today.isoformat(),
        PRICE,
    )
