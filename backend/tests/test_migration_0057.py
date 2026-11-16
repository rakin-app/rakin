"""Migration 0057: a freeze request's reason says nothing about health (#384).

Requests stored as `lesion` or `salud` become `personal`, with what the member wrote
kept; neither is accepted after. A downgrade makes them `otro`, which needs a note.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database

pg = pytest.mark.postgres

# A request on the gym's membership, by its person, as 0045 stored them.
ASK = """
    INSERT INTO freeze_request (gym_id, membership_id, requested_by, from_date, to_date,
                                reason, note)
    SELECT gym_id, id, person_id, current_date, current_date + 14, $1, $2 FROM membership
"""


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0056")
        yield database


def ask(db: Database, gym: uuid.UUID, reason: str, note: str | None) -> None:
    run(db.owner_url, in_gym(gym, ASK, reason, note))


def requests(db: Database) -> set[tuple[Any, ...]]:
    """Every request's reason and note, as the superuser, whom RLS does not hold."""
    rows = run(db.admin_url, lambda c: c.fetch("SELECT reason, note FROM freeze_request"))
    return {tuple(r) for r in rows}


@pg
def test_health_reasons_become_personal_and_back(db: Database) -> None:
    gyms = [seed_gym(db, slug) for slug in ("sur", "norte", "este", "oeste")]
    for gym, (reason, note) in zip(
        gyms,
        [("lesion", "Esguince"), ("salud", None), ("viaje", None), ("otro", "Trabajo")],
        strict=True,
    ):
        ask(db, gym, reason, note)

    command.upgrade(db.alembic(), "0057")
    assert requests(db) == {
        ("personal", "Esguince"),
        ("personal", None),
        ("viaje", None),
        ("otro", "Trabajo"),
    }
    with pytest.raises(asyncpg.CheckViolationError, match="freeze_request_reason_check"):
        run(db.owner_url, in_gym(gyms[0], "UPDATE freeze_request SET reason = 'lesion'"))

    command.downgrade(db.alembic(), "0056")
    assert requests(db) == {
        ("otro", "Esguince"),
        ("otro", "Motivo personal"),
        ("viaje", None),
        ("otro", "Trabajo"),
    }
