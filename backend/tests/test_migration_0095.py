"""Migration 0095: `gym_person.left_at`, when someone was dado de baja (#549).

Backfilled only where it is known for sure: their record untouched since the leave, its
`updated_at` the leave's `now()`, which a plan ended `dado de baja` shares as its
`cancelled_at`. Anyone else keeps it null. A downgrade drops it.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0094")
        yield database


def left(db: Database, gym: UUID, left_at: datetime, cancelled_at: datetime) -> None:
    """The gym's owner dado de baja at `left_at`, their plan cancelled at `cancelled_at`."""
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE membership SET status = 'cancelled', cancel_reason = 'dado de baja',"
            " cancelled_at = $1 WHERE person_id = $2",
            cancelled_at,
            seeded_owner(gym),
        ),
    )
    run(
        db.owner_url,
        in_gym(
            gym,
            "UPDATE gym_person SET left_on = current_date, updated_at = $1 WHERE person_id = $2",
            left_at,
            seeded_owner(gym),
        ),
    )


def left_at(db: Database, gym: UUID) -> datetime | None:
    rows = run(
        db.owner_url,
        in_gym(gym, "SELECT left_at FROM gym_person WHERE person_id = $1", seeded_owner(gym)),
    )
    value: datetime | None = rows[0]["left_at"]
    return value


def test_left_at_is_backfilled_only_where_the_leave_is_known(db: Database) -> None:
    at = datetime.fromisoformat("2026-11-20T15:00:00+00:00")
    untouched = seed_gym(db, unique_slug("norte"))
    edited = seed_gym(db, unique_slug("sur"))
    here = seed_gym(db, unique_slug("este"))
    left(db, untouched, at, at)
    # Their record edited since: the leave's moment is gone.
    left(db, edited, at + timedelta(days=1), at)

    migrate(db, "0095")
    assert left_at(db, untouched) == at
    assert left_at(db, edited) is None
    assert left_at(db, here) is None

    command.downgrade(db.alembic(), "0094")
    columns = run(
        db.owner_url,
        lambda c: c.fetch(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'gym_person' AND column_name = 'left_at'"
        ),
    )
    assert columns == []
