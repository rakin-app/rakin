"""The panel's list of gyms (#436): one row per gym, counts and dates only.

Two seeded gyms (`tests.pg.seed_gym`): one with a coach, three more people with plans,
two signatures of the Términos de encargo and a class taken, and one left as seeded.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.gyms import PROCESSOR_TERMS_VERSION
from tests.ids import unique_slug
from tests.pg import Database, in_gym, make_staff, run, seed_gym, seeded_owner
from tests.test_gym_hosts import HOSTS
from tests.test_platform_auth import Panel, grant, operator_email
from tests.test_platform_auth import db as db
from tests.test_platform_auth import panel as panel

pytestmark = pytest.mark.postgres

MARKED_AT = datetime(2030, 1, 2, 12, tzinfo=UTC)


def add_people(db: Database, gym: uuid.UUID, slug: str) -> None:
    """A coach, and members active, frozen and lapsed; the owner's record gets an
    email and an old and the current signature; a class is taken, later than all else."""

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "UPDATE gym_person SET email = $3 WHERE gym_id = $1 AND person_id = $2",
                gym,
                seeded_owner(gym),
                f"titular@{slug}.cl",
            )
            plan = await conn.fetchval("SELECT id FROM plan WHERE gym_id = $1", gym)
            memberships = {}
            for status in ("active", "frozen", "lapsed", "coach"):
                person = uuid.uuid4()
                await conn.execute(
                    "INSERT INTO person (id, name) VALUES ($1, 'Alumna Secreta')", person
                )
                await conn.execute(
                    "INSERT INTO gym_person (gym_id, person_id, name)"
                    " VALUES ($1, $2, 'Alumna Secreta')",
                    gym,
                    person,
                )
                if status == "coach":
                    await make_staff(conn, gym, person, "coach")
                    continue
                memberships[status] = await conn.fetchval(
                    "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                    " VALUES ($1, $2, $3, $4) RETURNING id",
                    gym,
                    person,
                    plan,
                    status,
                )
            await conn.executemany(
                "INSERT INTO processor_terms (gym_id, version, signed_on) VALUES ($1, $2, $3)",
                [
                    (gym, "2026-01-01", datetime(2026, 1, 5).date()),
                    (gym, PROCESSOR_TERMS_VERSION, datetime(2026, 11, 19).date()),
                ],
            )
            program = await conn.fetchval(
                "INSERT INTO program (gym_id, name) VALUES ($1, 'p') RETURNING id", gym
            )
            class_type = await conn.fetchval(
                "INSERT INTO class_type (gym_id, program_id, name) VALUES ($1, $2, 'Clase')"
                " RETURNING id",
                gym,
                program,
            )
            session = await conn.fetchval(
                "INSERT INTO session (gym_id, class_type_id, starts_at, coach_id)"
                " VALUES ($1, $2, $3, $4) RETURNING id",
                gym,
                class_type,
                MARKED_AT - timedelta(hours=1),
                seeded_owner(gym),
            )
            await conn.execute(
                "INSERT INTO attendance (gym_id, session_id, membership_id, marked_at)"
                " VALUES ($1, $2, $3, $4)",
                gym,
                session,
                memberships["active"],
                MARKED_AT,
            )

    run(db.owner_url, query)


@pytest.fixture
def listed(panel: Panel) -> Iterator[tuple[Panel, dict[str, Any], dict[str, Any]]]:
    add_people(panel.db, panel.gym_a, panel.slug_a)
    slug_b = unique_slug("sur")
    gym_b = seed_gym(panel.db, slug_b)
    email = operator_email()
    grant(panel.db, email)
    with panel.signed_in(email) as client:
        response = client.get("/api/platform/gyms")
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()}
    yield panel, rows[str(panel.gym_a)], rows[str(gym_b)]


def test_each_gym_has_its_titular_counts_terms_and_activity(
    listed: tuple[Panel, dict[str, Any], dict[str, Any]],
) -> None:
    panel, a, _ = listed
    assert a["slug"] == panel.slug_a
    assert a["name"] == panel.slug_a
    assert a["address"] == HOSTS.base_url(panel.slug_a)
    assert a["timezone"] == "America/Santiago"
    assert (a["titular_name"], a["titular_email"]) == (
        f"owner of {panel.slug_a}",
        f"titular@{panel.slug_a}.cl",
    )
    # The owner's plan, the active one and the frozen one; not the lapsed.
    assert (a["members"], a["staff"]) == (3, 2)
    assert (a["terms_version"], a["terms_signed_on"], a["terms_current"]) == (
        PROCESSOR_TERMS_VERSION,
        "2026-11-19",
        True,
    )
    assert datetime.fromisoformat(a["last_activity"]) == MARKED_AT
    assert a["status"] == "active"
    # Seeded, not created from the panel: no link to its owner was tried.
    assert a["owner_link_failed"] is False


def test_a_gym_as_seeded_has_no_terms_and_its_ledger_for_activity(
    listed: tuple[Panel, dict[str, Any], dict[str, Any]],
) -> None:
    _, _, b = listed
    assert (b["titular_name"], b["titular_email"]) == (f"owner of {b['slug']}", None)
    assert (b["members"], b["staff"]) == (1, 1)
    assert (b["terms_version"], b["terms_signed_on"], b["terms_current"]) == (None, None, False)
    created = datetime.fromisoformat(b["created_at"])
    assert datetime.fromisoformat(b["last_activity"]) >= created


def test_an_old_signature_is_not_current(panel: Panel) -> None:
    run(
        panel.db.owner_url,
        in_gym(
            panel.gym_a,
            "INSERT INTO processor_terms (gym_id, version, signed_on)"
            " VALUES ($1, '2026-01-01', '2026-01-05')",
            panel.gym_a,
        ),
    )
    email = operator_email()
    grant(panel.db, email)
    with panel.signed_in(email) as client:
        [a] = [g for g in client.get("/api/platform/gyms").json() if g["slug"] == panel.slug_a]
    assert (a["terms_version"], a["terms_current"]) == ("2026-01-01", False)


def test_the_list_carries_no_members_data(
    listed: tuple[Panel, dict[str, Any], dict[str, Any]],
) -> None:
    _, a, b = listed
    assert "Alumna Secreta" not in repr((a, b))
