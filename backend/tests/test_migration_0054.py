"""Migration 0054: a grade belongs to the person (#296).

Every gym's grades get their membership's person, so every current rank reads the same
through `person_id` as it did through `membership`; a downgrade puts them back, and
refuses once a grade has no membership.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pg = pytest.mark.postgres

# 0053's read of everyone's current rank, through the membership.
RANKS_BEFORE = """
    SELECT DISTINCT ON (m.person_id) m.person_id, ge.rank_key, ge.awarded_on
    FROM grade_event ge JOIN membership m ON m.id = ge.membership_id
    ORDER BY m.person_id, ge.awarded_on DESC, ge.created_at DESC, ge.id
"""
RANKS_AFTER = """
    SELECT DISTINCT ON (person_id) person_id, rank_key, awarded_on
    FROM grade_event
    ORDER BY person_id, awarded_on DESC, created_at DESC, id
"""


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0053")
        yield database


def grade(db: Database, gym: uuid.UUID, rank: str, on: date) -> None:
    """A grade on each of the gym's memberships, as 0018 stored them."""
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO grade_event (gym_id, membership_id, rank_key, awarded_on)"
            " SELECT gym_id, id, $1, $2 FROM membership",
            rank,
            on,
        ),
    )


def second_membership(db: Database, gym: uuid.UUID) -> None:
    """Another membership for the gym's person, as after a plan change."""
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, person_id, plan_id, 'active' FROM membership",
        ),
    )


def ranks(db: Database, sql: str) -> set[tuple[Any, ...]]:
    """Every gym's current ranks, as the superuser, whom RLS does not hold."""
    return {tuple(r) for r in run(db.admin_url, lambda c: c.fetch(sql))}


@pg
def test_grades_move_to_the_person_and_back(db: Database) -> None:
    sur, norte = seed_gym(db, "sur"), seed_gym(db, "norte")
    grade(db, sur, "white", date(2024, 3, 1))
    second_membership(db, sur)
    # On both memberships now: the latest is current, over either.
    run(
        db.owner_url,
        in_gym(
            sur,
            "INSERT INTO grade_event (gym_id, membership_id, rank_key, awarded_on)"
            " SELECT gym_id, id, 'blue', '2025-06-01' FROM membership"
            " ORDER BY created_at DESC LIMIT 1",
        ),
    )
    grade(db, norte, "purple", date(2023, 1, 10))
    before = ranks(db, RANKS_BEFORE)
    assert {r[1] for r in before} == {"blue", "purple"}

    command.upgrade(db.alembic(), "0054")
    assert ranks(db, RANKS_AFTER) == before
    sources = run(db.admin_url, lambda c: c.fetch("SELECT DISTINCT source FROM grade_event"))
    assert [r["source"] for r in sources] == ["app"]

    command.downgrade(db.alembic(), "0053")
    assert ranks(db, RANKS_BEFORE) == before


@pg
def test_a_grade_is_its_memberships_persons(db: Database) -> None:
    sur = seed_gym(db, "sur")
    command.upgrade(db.alembic(), "0054")
    stranger = uuid.uuid4()
    run(
        db.admin_url,
        lambda c: c.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", stranger),
    )
    with pytest.raises(Exception, match="grade_event_persons_membership"):
        run(
            db.owner_url,
            in_gym(
                sur,
                "INSERT INTO grade_event (gym_id, person_id, membership_id, rank_key, awarded_on)"
                " SELECT gym_id, $1, id, 'blue', current_date FROM membership",
                stranger,
            ),
        )


@pg
def test_a_downgrade_refuses_a_grade_with_no_membership(db: Database) -> None:
    sur = seed_gym(db, "sur")
    command.upgrade(db.alembic(), "0054")
    run(
        db.owner_url,
        in_gym(
            sur,
            "INSERT INTO grade_event (gym_id, person_id, rank_key, awarded_on, source)"
            " SELECT gym_id, person_id, 'blue', '2021-06-12', 'manual' FROM gym_person",
        ),
    )
    with pytest.raises(Exception, match="no place for"):
        command.downgrade(db.alembic(), "0053")
