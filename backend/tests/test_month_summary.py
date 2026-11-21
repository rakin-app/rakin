"""Resumen del mes keeps each closed month (#506): the `month_summary` job writes the
month's figures to `gym_month_figure` on the 1st, as numbers only, and the page reads a
closed month from there, so it outlives the log purges #378 plans.

The rows the figures are counted from are written with `tests.test_summary`'s helpers,
in its `MONTH`, two before the current one: the job runs as if it were `NEXT`'s 1st.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.domain.value_summary import RULES_VERSION, Figure
from app.jobs import month_summary
from app.main import create_app
from tests.auth import FakeAuth
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_plans import add_staff
from tests.test_summary import (
    MONTH,
    NEXT,
    a_member,
    a_period,
    admin,
    attended,
    day,
    emailed,
    local,
    nudged,
    opened_on,
    paid,
    summary,
    whatsapped,
)

pytestmark = pytest.mark.postgres

# The 1st the closed month is kept on, and the day after.
FIRST = NEXT
SECOND = NEXT + timedelta(days=1)


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
    """A gym on Rakin since well before `MONTH`."""
    made = seed_gym(db, unique_slug("academia"))
    opened_on(db, made, add_months(MONTH, -3))
    return made


def keep(db: Database, on: date) -> bool:
    """Run the job as the runner does, as the owner in a transaction, on `on`."""

    async def go(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await month_summary.keep_months(conn, on)

    complete: bool = run(db.owner_url, go)
    return complete


def kept(db: Database, gym: uuid.UUID, month: date = MONTH) -> dict[str, Any]:
    """What was kept of `gym`'s `month`: each figure, with its version and time."""
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT figure, value, rules_version, computed_at FROM gym_month_figure"
            " WHERE gym_id = $1 AND month = $2",
            gym,
            month,
        ),
    )
    return {r["figure"]: (r["value"], r["rules_version"], r["computed_at"]) for r in rows}


def a_busy_month(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    """A late payment after an email, one after a WhatsApp, and a nudge that brought
    someone back: figures every one of which reads `message_log.payload`."""
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    emailed(db, gym, person, period, local(day(1), 3))
    paid(db, gym, membership, period, made=local(day(2)))
    other, other_m = a_member(db, gym)
    other_p = a_period(db, gym, other_m)
    whatsapped(db, gym, other, other_p, local(day(2)))
    paid(db, gym, other_m, other_p, made=local(day(3)), by=other, validated=local(day(3), 15))
    on = MONTH + timedelta(days=2)
    nudged(db, gym, person, local(on))
    attended(client, db, gym, membership, local(on + timedelta(days=3)))


def owing(db: Database, gym: uuid.UUID, status: str, amount: int) -> None:
    """A membership in `status` with a period of `amount` charged in `MONTH` and unpaid."""
    _, membership = a_member(db, gym, status=status)
    period = a_period(db, gym, membership)
    admin(
        db,
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
        " kind, status, validated_at) VALUES ($1, $2, $3, $4, 'charge', 'validated', now())",
        gym,
        membership,
        period,
        amount,
    )
    admin(db, "UPDATE billing_period SET amount_due_clp = $2 WHERE id = $1", period, amount)


def without(page: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in page.items() if k not in keys}


# --- the job -----------------------------------------------------------------------


def test_run_twice_on_the_1st_it_writes_one_set_and_on_the_2nd_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)

    assert keep(db, FIRST)
    first = kept(db, gym)
    assert keep(db, FIRST)
    assert keep(db, SECOND)

    assert set(first) == set(Figure)
    assert kept(db, gym) == first
    assert {version for _, version, _ in first.values()} == {RULES_VERSION}
    assert first[Figure.EMAILS_ONLY_PAYMENTS][0] == 1
    assert first[Figure.AFTER_WHATSAPP_PAYMENTS][0] == 1
    assert (first[Figure.NUDGED][0], first[Figure.NUDGED_BACK][0]) == (1, 1)
    # Nothing kept of the month before, nor of the one being lived.
    assert kept(db, gym, NEXT) == {}


def test_a_month_with_no_proof_reviewed_keeps_no_median(db: Database, gym: uuid.UUID) -> None:
    assert keep(db, FIRST)

    figures = kept(db, gym)
    assert Figure.PROOF_REVIEW_MEDIAN_MINUTES not in figures
    assert figures[Figure.INCOME_PAYMENTS][0] == 0


def test_the_closing_debt_is_what_active_memberships_owe_on_the_1st(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    owing(db, gym, "active", 30000)
    owing(db, gym, "active", 12000)
    owing(db, gym, "lapsed", 45000)

    assert keep(db, FIRST)

    assert kept(db, gym)[Figure.OVERDUE_CLP][0] == 42000
    assert summary(client, gym)["overdue_clp"] == 42000
    # The month being lived has none: `v_overdue` is today's, not its close.
    assert summary(client, gym, None)["overdue_clp"] is None


def test_a_gym_the_1st_did_not_reach_is_kept_on_its_next_run_without_the_debt(
    db: Database, gym: uuid.UUID
) -> None:
    # Suspended over the 1st, say: the month is kept on its first run back, but the
    # debt read then would be another day's, not the month's close.
    owing(db, gym, "active", 30000)

    assert keep(db, SECOND)

    figures = kept(db, gym)
    assert Figure.INCOME_CLP in figures
    assert Figure.OVERDUE_CLP not in figures


def test_a_gym_newer_than_the_month_keeps_nothing_of_it(db: Database, gym: uuid.UUID) -> None:
    opened_on(db, gym, NEXT + timedelta(days=3))

    assert keep(db, FIRST)

    assert kept(db, gym) == {}


def test_a_kept_figure_is_never_changed(db: Database, gym: uuid.UUID) -> None:
    assert keep(db, FIRST)

    with pytest.raises(asyncpg.RestrictViolationError, match="written once"):
        run(
            db.owner_url,
            in_gym(gym, "UPDATE gym_month_figure SET value = value + 1 RETURNING 1"),
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(
            db.api_url,
            in_gym(
                gym,
                "UPDATE gym_month_figure SET value = value + 1 RETURNING 1",
                person=seeded_owner(gym),
            ),
        )


# --- the page ----------------------------------------------------------------------


def test_a_kept_month_reads_as_it_was_counted(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    counted = summary(client, gym)
    assert counted["kept"] is None and counted["overdue_clp"] is None

    assert keep(db, FIRST)
    page = summary(client, gym)

    assert without(page, "kept", "overdue_clp") == without(counted, "kept", "overdue_clp")
    assert page["kept"]["rules_version"] == RULES_VERSION
    assert page["kept"]["older_rules"] is False
    assert page["overdue_clp"] == 0


def test_a_kept_month_reads_the_same_once_its_log_payloads_are_purged(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    a_busy_month(client, db, gym)
    assert keep(db, FIRST)
    before = summary(client, gym)

    # #378's purge: the payload goes, and with it `billing_period_id` and `about`.
    admin(db, "UPDATE message_log SET payload = '{}' WHERE gym_id = $1", gym)

    assert summary(client, gym) == before
    # Counted again, the month would have lost them.
    admin(db, "DELETE FROM gym_month_figure WHERE gym_id = $1", gym)
    recounted = summary(client, gym)
    assert recounted["kept"] is None
    assert recounted["after_reminders"]["total"]["payments"] == 0
    assert recounted["nudges"]["nudged"] == 0
    assert before["after_reminders"]["total"]["payments"] == 2
    assert before["nudges"]["nudged"] == 1


def test_a_month_kept_under_older_rules_says_so(
    client: TestClient, db: Database, gym: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert keep(db, FIRST)
    monkeypatch.setattr("app.api.summary.RULES_VERSION", RULES_VERSION + 1)

    page = summary(client, gym)

    assert page["kept"]["rules_version"] == RULES_VERSION
    assert page["kept"]["older_rules"] is True


# --- who sees it -------------------------------------------------------------------


def figures_seen(db: Database, gym: uuid.UUID, person: uuid.UUID) -> int:
    rows = run(db.api_url, in_gym(gym, "SELECT count(*) FROM gym_month_figure", person=person))
    count: int = rows[0][0]
    return count


def test_another_gyms_figures_are_invisible_and_a_coach_reads_none(
    db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, unique_slug("norte"))
    opened_on(db, norte, MONTH - timedelta(days=40))
    assert keep(db, FIRST)
    owner, coach = seeded_owner(gym), add_staff(db, gym, "coach")
    admin_id = add_staff(db, gym, "admin")

    assert figures_seen(db, gym, owner) == len(kept(db, gym)) > 0
    assert figures_seen(db, gym, admin_id) == len(kept(db, gym))
    assert figures_seen(db, gym, coach) == 0
    # The owner of one gym, in another's: nothing, and nothing of the other's in theirs.
    assert figures_seen(db, norte, owner) == 0
    assert figures_seen(db, gym, seeded_owner(norte)) == 0


def test_the_api_adds_rows_only_to_its_own_gym_and_only_with_money_read(
    db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, unique_slug("norte"))
    insert = (
        "INSERT INTO gym_month_figure (gym_id, month, figure, value, rules_version)"
        " VALUES ($1, $2, 'income_clp', 1, 1) RETURNING 1"
    )
    owner, coach = seeded_owner(gym), add_staff(db, gym, "coach")

    for other_gym, person in ((norte, owner), (gym, coach)):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            run(db.api_url, in_gym(gym, insert, other_gym, MONTH, person=person))
    assert run(db.api_url, in_gym(gym, insert, gym, MONTH, person=owner)) == [(1,)]
