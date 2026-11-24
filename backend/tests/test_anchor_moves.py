"""A monthly plan's anchor changed, applied to the members already on it (#547): quoted
first, then moved from each one's next period not billed, the transition prorated, and
each move in the ficha's "Correcciones".

The members start in a November billing has not reached yet (`NOV_1`), not in this
year's: the API bills a member as they start through today plus the job's lead time, so
a start on Nov 12, 2026 came billed December too from Nov 24 on, and every month since
after it (#586). Each one's first period is billed here instead, by the job on the day
they start. November, then a 31-day December and January, keeps the prorations' days
as they are written.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.billing import GENERATE_AHEAD_DAYS
from app.domain.dates import add_months
from app.jobs import billing
from app.main import create_app
from app.seed.build import seed_id
from app.seed.data import COACH
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_today,
    throwaway_database,
)
from tests.test_memberships import plan, start

pytestmark = pytest.mark.postgres


def first_november_ahead() -> date:
    """The 1st of the first November past the days billed ahead of today."""
    horizon = seeded_today() + timedelta(days=GENERATE_AHEAD_DAYS)
    november = date(horizon.year, 11, 1)
    return november if november > horizon else date(horizon.year + 1, 11, 1)


NOV_1 = first_november_ahead()
NOV_12 = NOV_1.replace(day=12)
NOV_30 = NOV_1.replace(day=30)
DEC_1 = add_months(NOV_1, 1)
JAN_1 = add_months(NOV_1, 2)
COACH_ID = seed_id("person", COACH)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, "academia-sur")


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def generate(db: Database, day: date) -> None:
    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, day)

    assert run(db.owner_url, go)


def member(
    client: TestClient, db: Database, gym: uuid.UUID, plan_id: str, started_on: date
) -> dict[str, Any]:
    """A member on `plan_id` from `started_on`, their first period billed."""
    response = start(client, gym, plan_id, started_on=started_on.isoformat())
    assert response.status_code == 201, response.text
    generate(db, started_on)
    return dict(response.json())


def periods(db: Database, gym: uuid.UUID, membership_id: str) -> list[tuple[date, date, int]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT period_start, period_end, amount_due_clp FROM billing_period"
            " WHERE membership_id = $1 ORDER BY period_start",
            uuid.UUID(membership_id),
        ),
    )
    return [(r["period_start"], r["period_end"], r["amount_due_clp"]) for r in rows]


def membership(client: TestClient, gym: uuid.UUID, membership_id: str) -> Any:
    response = client.get(f"/api/memberships/{membership_id}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


def quote(client: TestClient, gym: uuid.UUID, plan_id: str, anchor: str) -> Any:
    return client.get(
        f"/api/plans/{plan_id}/anchor-moves", params={"anchor": anchor}, headers=as_gym(gym)
    )


def edit(client: TestClient, gym: uuid.UUID, plan_id: str, **body: Any) -> Any:
    return client.patch(f"/api/plans/{plan_id}", json=body, headers=as_gym(gym))


def anchor_corrections(client: TestClient, gym: uuid.UUID, person_id: str) -> list[Any]:
    response = client.get(f"/api/ledger/people/{person_id}/corrections", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return [c for c in response.json()["items"] if c["action"] == "anchor_changed"]


def test_a_mid_month_member_moves_from_the_1st_to_the_day_they_started(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    ana = member(client, db, sur, plan_id, NOV_12)
    assert periods(db, sur, ana["id"]) == [(NOV_12, NOV_30, 45_000)]

    quoted = quote(client, sur, plan_id, "signup")

    assert quoted.status_code == 200, quoted.text
    assert [
        {k: v for k, v in m.items() if k not in ("person_id", "name", "status")}
        for m in quoted.json()["moves"]
    ] == [
        {
            "membership_id": ana["id"],
            "from_day": 1,
            "to_day": 12,
            "starts_on": DEC_1.isoformat(),
            "ends_on": DEC_1.replace(day=11).isoformat(),
            # 11 of the 31 days Dec 1 would have billed.
            "amount_due_clp": 45_000 * 11 // 31,
            "next_starts_on": DEC_1.replace(day=12).isoformat(),
            "next_amount_clp": 45_000,
        }
    ]

    response = edit(client, sur, plan_id, anchor="signup", move_members=True)
    assert response.status_code == 200, response.text
    assert response.json()["anchor"] == "signup"
    assert membership(client, sur, ana["id"])["next_anchor_day"] == 12
    # The period billed already stays as it was.
    assert periods(db, sur, ana["id"]) == [(NOV_12, NOV_30, 45_000)]

    generate(db, DEC_1.replace(day=5))

    assert periods(db, sur, ana["id"]) == [
        (NOV_12, NOV_30, 45_000),
        (DEC_1, DEC_1.replace(day=11), 15_967),
        (DEC_1.replace(day=12), JAN_1.replace(day=11), 45_000),
    ]
    moved = membership(client, sur, ana["id"])
    assert (moved["anchor_day"], moved["next_anchor_day"]) == (12, None)
    (row,) = anchor_corrections(client, sur, ana["person_id"])
    assert row["anchor"] == {"before": 1, "after": 12, "starts_on": DEC_1.isoformat()}
    assert row["actor_name"] is not None


def test_a_member_moves_from_the_day_they_started_to_the_1st(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "signup")
    ana = member(client, db, sur, plan_id, NOV_12)
    assert periods(db, sur, ana["id"]) == [(NOV_12, DEC_1.replace(day=11), 45_000)]

    (quoted,) = quote(client, sur, plan_id, "first").json()["moves"]
    assert (quoted["starts_on"], quoted["ends_on"], quoted["amount_due_clp"]) == (
        DEC_1.replace(day=12).isoformat(),
        DEC_1.replace(day=31).isoformat(),
        45_000 * 20 // 31,
    )

    assert edit(client, sur, plan_id, anchor="first", move_members=True).status_code == 200
    generate(db, DEC_1.replace(day=26))

    assert periods(db, sur, ana["id"])[1:] == [
        (DEC_1.replace(day=12), DEC_1.replace(day=31), 29_032),
        (JAN_1, JAN_1.replace(day=31), 45_000),
    ]
    assert membership(client, sur, ana["id"])["anchor_day"] == 1
    (row,) = anchor_corrections(client, sur, ana["person_id"])
    assert row["anchor"] == {
        "before": 12,
        "after": 1,
        "starts_on": DEC_1.replace(day=12).isoformat(),
    }


def test_declining_keeps_the_members_on_their_day_and_new_ones_take_the_new_one(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    ana = member(client, db, sur, plan_id, NOV_12)

    assert edit(client, sur, plan_id, anchor="signup").status_code == 200

    assert membership(client, sur, ana["id"])["next_anchor_day"] is None
    assert anchor_corrections(client, sur, ana["person_id"]) == []
    newcomer = member(client, db, sur, plan_id, NOV_12)
    assert newcomer["anchor_day"] == 12


def test_only_members_who_would_move_are_quoted_and_moved(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    on_the_1st = member(client, db, sur, plan_id, NOV_1)
    leaving = member(client, db, sur, plan_id, NOV_12)
    other = plan(client, sur, "signup")
    response = client.post(
        f"/api/memberships/{leaving['id']}/plan-change",
        json={"plan_id": other},
        headers=as_gym(sur),
    )
    assert response.status_code == 200, response.text

    assert quote(client, sur, plan_id, "signup").json() == {"moves": [], "withdrawn": []}
    assert edit(client, sur, plan_id, anchor="signup", move_members=True).status_code == 200

    for m in (on_the_1st, leaving):
        assert membership(client, sur, m["id"])["next_anchor_day"] is None
        assert anchor_corrections(client, sur, m["person_id"]) == []


def test_changing_back_before_the_move_is_billed_withdraws_it(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    ana = member(client, db, sur, plan_id, NOV_12)
    assert edit(client, sur, plan_id, anchor="signup", move_members=True).status_code == 200

    assert edit(client, sur, plan_id, anchor="first", move_members=True).status_code == 200

    assert membership(client, sur, ana["id"])["next_anchor_day"] is None
    withdrawn, moved = anchor_corrections(client, sur, ana["person_id"])
    assert withdrawn["anchor"] == {"before": 12, "after": 1, "starts_on": DEC_1.isoformat()}
    assert moved["anchor"]["after"] == 12


def test_changing_back_unticked_withdraws_the_move_pending(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    ana = member(client, db, sur, plan_id, NOV_12)
    assert edit(client, sur, plan_id, anchor="signup", move_members=True).status_code == 200

    quoted = quote(client, sur, plan_id, "first").json()
    assert quoted["moves"] == []
    assert [(w["membership_id"], w["pending_day"], w["stays_on"]) for w in quoted["withdrawn"]] == [
        (ana["id"], 12, 1)
    ]
    assert edit(client, sur, plan_id, anchor="first").status_code == 200

    assert membership(client, sur, ana["id"])["next_anchor_day"] is None
    withdrawn, _ = anchor_corrections(client, sur, ana["person_id"])
    assert withdrawn["anchor"] == {"before": 12, "after": 1, "starts_on": DEC_1.isoformat()}
    generate(db, DEC_1.replace(day=5))
    assert periods(db, sur, ana["id"])[1] == (DEC_1, DEC_1.replace(day=31), 45_000)


def test_moving_with_the_anchor_the_plan_has_moves_those_still_on_another_day(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    straggler = member(client, db, sur, plan_id, NOV_12)
    # The plan changed earlier, its members left on the 1st.
    assert edit(client, sur, plan_id, anchor="signup").status_code == 200
    newcomer = member(client, db, sur, plan_id, NOV_12)

    (quoted,) = quote(client, sur, plan_id, "signup").json()["moves"]
    assert quoted["membership_id"] == straggler["id"]
    assert edit(client, sur, plan_id, anchor="signup", move_members=True).status_code == 200

    assert membership(client, sur, straggler["id"])["next_anchor_day"] == 12
    assert membership(client, sur, newcomer["id"])["next_anchor_day"] is None
    (row,) = anchor_corrections(client, sur, straggler["person_id"])
    assert row["anchor"] == {"before": 1, "after": 12, "starts_on": DEC_1.isoformat()}


def test_refusals(client: TestClient, sur: uuid.UUID) -> None:
    prepaid = plan(client, sur, "prepaid")
    monthly = plan(client, sur, "first")

    assert quote(client, sur, prepaid, "first").status_code == 409
    assert edit(client, sur, prepaid, anchor="first", move_members=True).status_code in (409, 422)
    assert edit(client, sur, monthly, move_members=True).status_code == 422
    assert quote(client, sur, monthly, "someday").status_code == 422


def test_a_coach_neither_quotes_nor_moves(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    plan_id = plan(client, sur, "first")
    headers = as_gym(sur, COACH_ID)

    quoted = client.get(
        f"/api/plans/{plan_id}/anchor-moves", params={"anchor": "signup"}, headers=headers
    )
    moved = client.patch(
        f"/api/plans/{plan_id}", json={"anchor": "signup", "move_members": True}, headers=headers
    )

    assert (quoted.status_code, moved.status_code) == (403, 403)


def test_a_frozen_member_on_the_plan_is_moved_too(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    plan_id = plan(client, sur, "first")
    ana = member(client, db, sur, plan_id, NOV_12)
    run(
        db.owner_url,
        in_gym(
            sur,
            "UPDATE membership SET status = 'frozen' WHERE id = $1",
            uuid.UUID(ana["id"]),
        ),
    )

    (quoted,) = quote(client, sur, plan_id, "signup").json()["moves"]

    assert (quoted["membership_id"], quoted["status"]) == (ana["id"], "frozen")
    assert edit(client, sur, plan_id, anchor="signup", move_members=True).status_code == 200
    assert membership(client, sur, ana["id"])["next_anchor_day"] == 12
