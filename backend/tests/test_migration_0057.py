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


# A `history_set` row for the gym's owner, as 0051 writes them.
HISTORY_SET = """
    INSERT INTO audit_event (gym_id, actor_id, person_id, action, detail)
    VALUES ($1, $2, $2, 'history_set', $3::jsonb)
"""


def history_set(db: Database, gym: uuid.UUID, detail: dict[str, Any]) -> None:
    body = json.dumps(detail)
    run(db.admin_url, lambda c: c.execute(HISTORY_SET, gym, seeded_owner(gym), body))


def by_json(detail: dict[str, Any]) -> str:
    return json.dumps(detail, sort_keys=True)


def history(db: Database) -> list[dict[str, Any]]:
    rows = admin(db, "SELECT detail FROM audit_event WHERE action = 'history_set'")
    return sorted((json.loads(r["detail"]) for r in rows), key=by_json)


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
    on = {"before": None, "after": "2024-03-01"}
    history_set(db, sur, {"left_on": on, "left_reason": {"before": None, "after": "Lesión"}})
    history_set(db, sur, {"left_reason": {"before": " lesion", "after": "Precio"}})
    history_set(db, sur, {"left_reason": {"before": None, "after": "Lesión de rodilla"}})
    history_set(db, sur, {"prior_classes": {"before": 0, "after": 12}})

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
    # The log's own copies of the chip, the one exception to append-only; the rest of
    # each row, and every other row, as it was.
    redacted: list[dict[str, Any]] = [
        {"left_on": on, "left_reason": {"before": None, "after": "Motivo personal"}},
        {"left_reason": {"before": "Motivo personal", "after": "Precio"}},
        {"left_reason": {"before": None, "after": "Lesión de rodilla"}},
        {"prior_classes": {"before": 0, "after": 12}},
    ]
    assert history(db) == sorted(redacted, key=by_json)
    # Append-only again once the migration is done.
    with pytest.raises(asyncpg.RestrictViolationError, match="cannot change"):
        run(db.admin_url, lambda c: c.execute("UPDATE audit_event SET reason = 'x'"))

    # One row per change: 2 requests, 2 freezes, 2 left reasons, 2 emails and 2 history
    # rows, each about the gym's person, by nobody, naming the row and never what it held.
    rows = logged(db)
    tables = sorted(json.loads(r["detail"])["table"] for r in rows)
    assert tables == [
        *["audit_event"] * 2,
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
    assert logged(db) == []
    # The history stays redacted.
    assert history(db) == sorted(redacted, key=by_json)
    run(db.owner_url, in_gym(sur, "UPDATE freeze_request SET reason = 'salud'"))
