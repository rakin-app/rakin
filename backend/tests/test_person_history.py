"""Alumno desde and classes before Rakin, on the person and never on a plan (#293).

`PUT /api/people/{id}/history` writes `member_since` and `prior_classes` (0051), owner
and admin only, each write recorded as one `history_set` row. Billing never reads
either: a plan's start and what the nightly job bills are the same with and without
them. The class total adds the classes before Rakin; the last 30 days and the classes
since a promotion do not.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import add_months
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_member_roll import count, enrolled, forget, memberships, plan
from tests.test_plans import add_staff

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
    return seed_gym(db, unique_slug("gym"))


def set_history(
    client: TestClient,
    gym: uuid.UUID,
    person: str,
    by: uuid.UUID | None = None,
    *,
    member_since: str | None = None,
    prior_classes: int = 0,
) -> Any:
    return client.put(
        f"/api/people/{person}/history",
        json={"member_since": member_since, "prior_classes": prior_classes},
        headers=as_gym(gym, by),
    )


def history_rows(db: Database, gym: uuid.UUID, person: str) -> list[dict[str, Any]]:
    rows = run(
        db.owner_url,
        in_gym(
            gym,
            "SELECT * FROM audit_event WHERE person_id = $1 AND action = 'history_set'"
            " ORDER BY at, id",
            uuid.UUID(person),
        ),
    )
    return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]


@pg
def test_history_is_written_and_read_on_the_person(client: TestClient, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    assert (ana["member_since"], ana["prior_classes"]) == (None, 0)

    response = set_history(client, gym, ana["id"], member_since="2019-03-05", prior_classes=320)
    assert response.status_code == 200, response.text
    assert (response.json()["member_since"], response.json()["prior_classes"]) == (
        "2019-03-05",
        320,
    )
    read = client.get(f"/api/people/{ana['id']}", headers=as_gym(gym)).json()
    assert (read["member_since"], read["prior_classes"]) == ("2019-03-05", 320)


@pg
def test_each_write_records_one_row_with_before_and_after(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    owner = uuid.uuid5(gym, "owner")
    set_history(client, gym, ana["id"], member_since="2019-03-05", prior_classes=320)
    # The same again records nothing; one field changed records that field alone.
    set_history(client, gym, ana["id"], member_since="2019-03-05", prior_classes=320)
    set_history(client, gym, ana["id"], member_since="2019-03-05", prior_classes=300)

    first, second = history_rows(db, gym, ana["id"])
    assert first["actor_id"] == owner
    assert first["detail"] == {
        "member_since": {"before": None, "after": "2019-03-05"},
        "prior_classes": {"before": 0, "after": 320},
    }
    assert second["detail"] == {"prior_classes": {"before": 320, "after": 300}}
    # Not a correction of their billing: the ficha's "Correcciones" leaves it out.
    corrections = client.get(f"/api/ledger/people/{ana['id']}/corrections", headers=as_gym(gym))
    assert corrections.json() == {"total": 0, "items": []}


@pg
def test_a_health_reason_cleared_is_no_correction(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """0057's log rows (#384) are about the person, and not about their billing."""
    ana = enrolled(client, gym)
    detail = {"table": "gym_person", "id": ana["id"], "column": "left_reason", "now": "x"}
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO audit_event (gym_id, person_id, action, detail)"
            " VALUES ($1, $2, 'health_reason_cleared', $3)",
            gym,
            uuid.UUID(ana["id"]),
            json.dumps(detail),
        ),
    )
    corrections = client.get(f"/api/ledger/people/{ana['id']}/corrections", headers=as_gym(gym))
    assert corrections.json() == {"total": 0, "items": []}


@pg
def test_the_date_is_not_after_today_nor_over_60_years_back(
    client: TestClient, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    today = seeded_today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    assert set_history(client, gym, ana["id"], member_since=tomorrow).status_code == 422
    too_old = (add_months(today, -12 * 60) - timedelta(days=1)).isoformat()
    assert set_history(client, gym, ana["id"], member_since=too_old).status_code == 422
    oldest = add_months(today, -12 * 60).isoformat()
    assert set_history(client, gym, ana["id"], member_since=oldest).status_code == 200
    assert set_history(client, gym, ana["id"], member_since=today.isoformat()).status_code == 200
    assert set_history(client, gym, ana["id"], prior_classes=-1).status_code == 422
    unknown = str(uuid.uuid4())
    assert set_history(client, gym, unknown, prior_classes=1).status_code == 404


@pg
def test_a_coach_writes_neither_field(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    ana = enrolled(client, gym)
    coach = add_staff(db, gym, "coach")
    response = set_history(client, gym, ana["id"], coach, member_since="2019-03-05")
    assert response.status_code == 403
    assert set_history(client, gym, ana["id"], coach, prior_classes=10).status_code == 403
    read = client.get(f"/api/people/{ana['id']}", headers=as_gym(gym, coach)).json()
    assert (read["member_since"], read["prior_classes"]) == (None, 0)
    # Nor past the API: the policy holds the app role to owners and admins (0051).
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                gym,
                "INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)"
                " VALUES ($1, $2, $3, 'history_set', '{}')",
                gym,
                coach,
                uuid.UUID(ana["id"]),
                person=coach,
            ),
        )
    admin = add_staff(db, gym, "admin")
    assert set_history(client, gym, ana["id"], admin, prior_classes=10).status_code == 200
    assert history_rows(db, gym, ana["id"])[0]["actor_id"] == admin


@pg
def test_billing_is_the_same_with_and_without_member_since(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = (today - timedelta(days=20)).isoformat()
    monthly = plan(client, gym)
    people = [
        enrolled(client, gym, membership={"plan_id": monthly, "started_on": started_on})
        for _ in range(2)
    ]
    with_history, without = (p["id"] for p in people)
    set_history(client, gym, with_history, member_since="2019-03-05", prior_classes=320)

    async def bill(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, today + timedelta(days=40))

    run(db.owner_url, bill)

    def billed(person: str) -> list[tuple[Any, ...]]:
        [membership] = memberships(client, gym, person)
        assert membership["started_on"] == started_on
        rows = run(
            db.owner_url,
            in_gym(
                gym,
                "SELECT period_start, period_end, due_date, amount_due_clp FROM billing_period"
                " WHERE membership_id = $1 ORDER BY period_start",
                uuid.UUID(membership["id"]),
            ),
        )
        return [tuple(r) for r in rows]

    assert billed(with_history) == billed(without) != []


@pg
def test_the_total_adds_the_classes_before_rakin_and_nothing_else_does(
    client: TestClient, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    set_history(client, gym, ana["id"], prior_classes=320)
    response = client.get(f"/api/people/{ana['id']}/attendance", headers=as_gym(gym))
    assert response.json() == {
        "last_30_days": 0,
        "total": 320,
        "before_rakin": 320,
        "since_promotion": None,
    }


@pg
def test_alumno_desde_on_the_students_page(client: TestClient, gym: uuid.UUID) -> None:
    today = seeded_today()
    started_on = (today - timedelta(days=20)).isoformat()
    ana = enrolled(client, gym, membership={"plan_id": plan(client, gym), "started_on": started_on})
    bea = enrolled(client, gym)

    def since(person: str) -> Any:
        response = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person)))
        assert response.status_code == 200, response.text
        return response.json()["member_since"]

    # Their first plan's start, else the day the gym added them.
    assert since(ana["id"]) == started_on
    assert since(bea["id"]) == today.isoformat()
    # The earlier of the two.
    set_history(client, gym, ana["id"], member_since="2019-03-05")
    assert since(ana["id"]) == "2019-03-05"
    later = (today - timedelta(days=5)).isoformat()
    set_history(client, gym, ana["id"], member_since=later)
    assert since(ana["id"]) == started_on


@pg
def test_deleting_a_person_removes_their_history_rows_and_counts_them(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = enrolled(client, gym)
    set_history(client, gym, ana["id"], member_since="2019-03-05")
    set_history(client, gym, ana["id"], member_since="2019-03-05", prior_classes=12)

    assert forget(client, gym, ana["id"]).status_code == 204
    theirs = "SELECT count(*) FROM audit_event WHERE person_id = $1"
    assert count(db, gym, theirs, uuid.UUID(ana["id"])) == 0
    [deleted] = run(
        db.owner_url,
        in_gym(gym, "SELECT detail FROM audit_event WHERE action = 'person_deleted'"),
    )
    detail = json.loads(deleted["detail"])
    assert (detail["history_set"], detail["corrections"]) == (2, 0)


@pg
def test_upgrade_and_downgrade_0051() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        gym = seed_gym(scratch, "sur")
        owner = uuid.uuid5(gym, "owner")

        async def log(conn: asyncpg.Connection) -> None:
            await conn.execute(
                "UPDATE gym_person SET member_since = '2019-03-05', prior_classes = 3"
                " WHERE person_id = $1",
                owner,
            )
            await conn.execute(
                "INSERT INTO audit_event (gym_id, actor_id, person_id, action)"
                " VALUES ($1, $2, $2, 'history_set'), ($1, $2, $2, 'ledger_corrected')",
                gym,
                owner,
            )

        run(scratch.admin_url, log)
        # The history rows go with their action; a correction's row stays.
        command.downgrade(scratch.alembic(), "0050")
        kept = run(scratch.admin_url, lambda c: c.fetch("SELECT action FROM audit_event"))
        assert [r["action"] for r in kept] == ["ledger_corrected"]
        migrate(scratch)
