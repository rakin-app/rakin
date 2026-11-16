"""Migration 0057: no health data among the reasons Rakin stored (#384).

Requests stored as `lesion` or `salud` become `personal`; freezes an approval wrote
from those labels, and the "Lesión" chip for why someone left, become "Motivo
personal". What a person wrote stays. Each change writes a log row that names the row
and never the value it held. A downgrade makes `personal` requests `otro` and drops
the log rows.
"""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest

from alembic import command
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database

pg = pytest.mark.postgres

# A request on the gym's membership, by its person, as 0045 stored them.
ASK = """
    INSERT INTO freeze_request (gym_id, membership_id, requested_by, from_date, to_date,
                                reason, note)
    SELECT gym_id, id, person_id, current_date, current_date + 14, $1, $2 FROM membership
"""
# A freeze on the gym's membership, a year apart from the others.
FREEZE = """
    INSERT INTO membership_freeze (gym_id, membership_id, from_date, to_date, reason)
    SELECT gym_id, id, current_date + 400 * $1::int, current_date + 400 * $1::int + 7, $2
    FROM membership
"""
HEALTH = ("lesion", "salud", "Lesión", "Salud", "lesión")
# A `freeze_requested` email to the gym's owner, about `member`, as `message_log` kept it.
EMAIL = """
    INSERT INTO message_log (gym_id, person_id, channel, template, to_address, status,
                             payload)
    VALUES ($1, $2, 'email', 'freeze_requested', 'duena@example.cl', 'sent', $3::jsonb)
"""


def email(db: Database, gym: uuid.UUID, member: uuid.UUID, reason: str) -> None:
    body = json.dumps({"member_id": str(member), "reason": reason, "note": "Esguince"})
    run(db.admin_url, lambda c: c.execute(EMAIL, gym, seeded_owner(gym), body))


def emails(db: Database) -> list[tuple[str, str]]:
    rows = admin(db, "SELECT payload FROM message_log ORDER BY sent_at, id")
    return sorted(
        (json.loads(r["payload"])["reason"], json.loads(r["payload"])["note"]) for r in rows
    )


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0056")
        yield database


def admin(db: Database, sql: str) -> list[Any]:
    """As the superuser, whom RLS does not hold."""
    return list(run(db.admin_url, lambda c: c.fetch(sql)))


def requests(db: Database) -> set[tuple[Any, ...]]:
    return {tuple(r) for r in admin(db, "SELECT reason, note FROM freeze_request")}


def freezes(db: Database) -> set[str]:
    return {r["reason"] for r in admin(db, "SELECT reason FROM membership_freeze")}


def left(db: Database, gyms: list[uuid.UUID]) -> list[str | None]:
    rows = {r["gym_id"]: r["left_reason"] for r in admin(db, "SELECT * FROM gym_person")}
    return [rows[gym] for gym in gyms]


def logged(db: Database) -> list[Any]:
    return admin(
        db,
        "SELECT gym_id, person_id, actor_id, detail FROM audit_event"
        " WHERE action = 'health_reason_cleared'",
    )


@pg
def test_health_reasons_are_cleared_logged_and_put_back(db: Database) -> None:
    gyms = [seed_gym(db, slug) for slug in ("sur", "norte", "este", "oeste")]
    asked = [("lesion", "Esguince"), ("salud", None), ("viaje", None), ("otro", "Trabajo")]
    for gym, (reason, note) in zip(gyms, asked, strict=True):
        run(db.owner_url, in_gym(gym, ASK, reason, note))
    sur = gyms[0]
    for n, reason in enumerate(["Lesión", "Salud: Gripe", "Lesión de rodilla", "Viaje"]):
        run(db.owner_url, in_gym(sur, FREEZE, n, reason))
    for gym, reason in zip(
        gyms, ["Lesión", "  lesion ", "Lesión de rodilla", "Precio"], strict=True
    ):
        run(db.owner_url, in_gym(gym, "UPDATE gym_person SET left_reason = $1", reason))
    email(db, sur, seeded_owner(sur), "Lesión")
    email(db, sur, seeded_owner(sur), "Viaje")
    # About someone forgotten since: the log row is the recipient's.
    email(db, gyms[1], uuid.uuid4(), "Salud")

    command.upgrade(db.alembic(), "0057")

    assert requests(db) == {
        ("personal", "Esguince"),
        ("personal", None),
        ("viaje", None),
        ("otro", "Trabajo"),
    }
    # The labels go; what someone wrote stays, health words or not.
    assert freezes(db) == {
        "Motivo personal",
        "Motivo personal: Gripe",
        "Lesión de rodilla",
        "Viaje",
    }
    assert left(db, gyms) == ["Motivo personal", "Motivo personal", "Lesión de rodilla", "Precio"]
    assert emails(db) == [
        ("Motivo personal", "Esguince"),
        ("Motivo personal", "Esguince"),
        ("Viaje", "Esguince"),
    ]

    # One row per change: 2 requests, 2 freezes, 2 left reasons and 2 emails, each about
    # the gym's person, by nobody, naming the row and never what it held.
    rows = logged(db)
    tables = sorted(json.loads(r["detail"])["table"] for r in rows)
    assert tables == [
        *["freeze_request"] * 2,
        *["gym_person"] * 2,
        *["membership_freeze"] * 2,
        *["message_log"] * 2,
    ]
    for row in rows:
        assert (row["person_id"], row["actor_id"]) == (seeded_owner(row["gym_id"]), None)
        detail = json.loads(row["detail"])
        assert set(detail) == {"table", "id", "column", "now"}
        assert not any(word in row["detail"] for word in HEALTH)

    with pytest.raises(asyncpg.CheckViolationError, match="freeze_request_reason_check"):
        run(db.owner_url, in_gym(sur, "UPDATE freeze_request SET reason = 'lesion'"))

    command.downgrade(db.alembic(), "0056")

    assert requests(db) == {
        ("otro", "Esguince"),
        ("otro", "Motivo personal"),
        ("viaje", None),
        ("otro", "Trabajo"),
    }
    # What was cleared stays cleared; only its log goes.
    assert freezes(db) == {
        "Motivo personal",
        "Motivo personal: Gripe",
        "Lesión de rodilla",
        "Viaje",
    }
    assert left(db, gyms)[0] == "Motivo personal"
    assert admin(db, "SELECT count(*) FROM audit_event")[0][0] == 0
    run(db.owner_url, in_gym(sur, "UPDATE freeze_request SET reason = 'salud'"))
