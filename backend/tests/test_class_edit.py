"""Changing a class once it exists (#163, migration 0033): move it, change its type or
coach, cancel it, delete it, and correct what its timer recorded.

An owner or admin may change everything; a class's own coach its topic and notes and
its timer record. A cancelled class stays on its day and counts for nothing; one with
attendance is deleted instead, and deleting gives back the credits it took.
"""

import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alembic import command
from app.domain.dates import gym_today
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_attendance import (
    SANTIAGO,
    at,
    change,
    changed,
    class_type,
    counts,
    credits_left,
    guest,
    join,
    plan,
    program,
    roster,
)
from tests.test_class_timer import kinds, ok, open_mat, put_plan, record, technique_and_sparring
from tests.test_guardians import add_person
from tests.test_plans import CREDITS, MONTHLY, TRIAL, add_staff

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
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def start(
    client: TestClient, gym: uuid.UUID, body: dict[str, Any], by: uuid.UUID | None = None
) -> Any:
    response = client.post("/api/sessions", json=body, headers=as_gym(gym, by))
    assert response.status_code == 201, response.text
    return response.json()


def edit(
    client: TestClient,
    gym: uuid.UUID,
    session: str,
    body: dict[str, Any],
    by: uuid.UUID | None = None,
) -> Any:
    return client.patch(f"/api/sessions/{session}", json=body, headers=as_gym(gym, by))


def act(
    client: TestClient, gym: uuid.UUID, session: str, what: str, by: uuid.UUID | None = None
) -> Any:
    return client.post(f"/api/sessions/{session}/{what}", headers=as_gym(gym, by))


def delete(client: TestClient, gym: uuid.UUID, session: str, by: uuid.UUID | None = None) -> Any:
    return client.delete(f"/api/sessions/{session}", headers=as_gym(gym, by))


def day_ids(client: TestClient, gym: uuid.UUID, day: str) -> list[str]:
    listed = ok(client.get("/api/sessions", params={"date": day}, headers=as_gym(gym)))
    return [s["id"] for s in listed["sessions"]]


def unmarked_ids(client: TestClient, gym: uuid.UUID) -> list[str]:
    listed = ok(client.get("/api/sessions/unmarked", headers=as_gym(gym)))
    return [s["id"] for s in listed["sessions"]]


def owner_membership(client: TestClient, gym: uuid.UUID, session: str) -> str:
    """The seeded owner's membership, on every roster."""
    return str(roster(client, gym, session)["members"][0]["membership_id"])


def yesterday() -> date:
    return gym_today(SANTIAGO) - timedelta(days=1)


# --- edit ---------------------------------------------------------------------------


@pg
def test_an_admin_moves_a_class_and_its_attendance_stays(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    session = start(client, gym, {"class_type_id": fundamentals, "starts_at": at(yesterday())})
    changed(client, gym, session["id"], mark=[owner_membership(client, gym, session["id"])])

    admin = add_staff(db, gym, "admin")
    later = at(yesterday() - timedelta(days=2), 7)
    moved = edit(client, gym, session["id"], {"starts_at": later}, admin)
    assert moved.status_code == 200, moved.text
    assert datetime.fromisoformat(moved.json()["starts_at"]) == datetime.fromisoformat(later)
    assert moved.json()["present"] == 1
    assert day_ids(client, gym, str(yesterday())) == []
    assert day_ids(client, gym, str(yesterday() - timedelta(days=2))) == [session["id"]]
    assert roster(client, gym, session["id"])["present"] == 1


@pg
def test_changing_the_type_changes_what_the_class_counts_as(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    mat = open_mat(client, gym, adults)
    person = add_person(client, gym, "Ana Rojas")
    membership = join(client, gym, person, plan(client, gym, {**MONTHLY, "program_id": adults}))
    session = start(client, gym, {"class_type_id": fundamentals, "starts_at": at(yesterday())})
    changed(client, gym, session["id"], mark=[membership])
    assert counts(client, gym, person)["total"] == 1

    # It was an open mat after all: it no longer counts as a class, and back again.
    turned = ok(edit(client, gym, session["id"], {"class_type_id": mat}))
    assert (turned["class_type_id"], turned["class_type_name"], turned["present"]) == (
        mat,
        "Open mat",
        1,
    )
    assert counts(client, gym, person)["total"] == 0
    time_ = ok(client.get(f"/api/people/{person}/time", headers=as_gym(gym)))
    assert (time_["all_time"]["classes"], time_["all_time"]["open_mats"]) == (0, 1)
    ok(edit(client, gym, session["id"], {"class_type_id": fundamentals}))
    assert counts(client, gym, person)["total"] == 1


@pg
def test_a_class_turned_open_mat_must_have_an_open_mats_blocks(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    mat = open_mat(client, gym, adults)
    session = start(client, gym, {"class_type_id": fundamentals})["id"]
    blocks = technique_and_sparring(kinds(client, gym))
    ok(put_plan(client, gym, session, blocks))

    refused = edit(client, gym, session, {"class_type_id": mat})
    assert refused.status_code == 422, refused.text
    assert [(e["type"], e["loc"]) for e in refused.json()["detail"]] == [
        ("open_mat_plan", ["body", "class_type_id"])
    ]
    ok(put_plan(client, gym, session, blocks[1:]))
    assert ok(edit(client, gym, session, {"class_type_id": mat}))["class_type_id"] == mat


@pg
def test_a_new_type_must_be_one_of_the_gyms_active_ones(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    old = class_type(client, gym, adults, "Viejo")
    session = start(client, gym, {"class_type_id": old})["id"]
    client.patch(f"/api/class-types/{old}", json={"active": False}, headers=as_gym(gym))
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    theirs = class_type(client, other, program(client, other, "Adultos"))

    for class_type_id, kind in (
        (theirs, "unknown_class_type"),
        (str(uuid.uuid4()), "unknown_class_type"),
    ):
        refused = edit(client, gym, session, {"class_type_id": class_type_id})
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"][0]["type"] == kind
    # Kept as it is, a deactivated type stays; moved off it, it cannot come back.
    assert ok(edit(client, gym, session, {"class_type_id": old, "topic": "t"}))["topic"] == "t"
    ok(edit(client, gym, session, {"class_type_id": fundamentals}))
    refused = edit(client, gym, session, {"class_type_id": old})
    assert refused.json()["detail"][0]["type"] == "inactive_class_type"


@pg
def test_the_classs_coach_writes_its_topic_and_notes_and_nothing_else(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals, advanced = class_type(client, gym, adults), class_type(client, gym, adults, "A")
    coach, other_coach = add_staff(db, gym, "coach"), add_staff(db, gym, "coach")
    session = start(client, gym, {"class_type_id": fundamentals}, coach)

    written = edit(client, gym, session["id"], {"topic": "Guardia", "notes": "Bien"}, coach)
    assert written.status_code == 200, written.text
    # A form may send every field: those unchanged are no change.
    unchanged = {
        "topic": "Guardia 2",
        "starts_at": session["starts_at"],
        "class_type_id": fundamentals,
        "coach_id": str(coach),
    }
    assert edit(client, gym, session["id"], unchanged, coach).status_code == 200

    for body in (
        {"starts_at": at(yesterday())},
        {"class_type_id": advanced},
        {"coach_id": str(other_coach)},
    ):
        refused = edit(client, gym, session["id"], body, coach)
        assert refused.status_code == 403, (body, refused.text)
    # Another coach changes nothing of it, not even its topic.
    assert edit(client, gym, session["id"], {"topic": "x"}, other_coach).status_code == 403
    after = ok(client.get(f"/api/sessions/{session['id']}", headers=as_gym(gym)))
    assert (after["topic"], after["coach_id"], after["class_type_id"]) == (
        "Guardia 2",
        str(coach),
        fundamentals,
    )


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_change_everything(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals, advanced = class_type(client, gym, adults), class_type(client, gym, adults, "A")
    coach = add_staff(db, gym, "coach")
    person = seeded_owner(gym) if role == "owner" else add_staff(db, gym, role)
    session = start(client, gym, {"class_type_id": fundamentals}, coach)
    body = {
        "starts_at": at(yesterday(), 7),
        "class_type_id": advanced,
        "coach_id": str(person),
        "topic": "Pasajes",
        "notes": "n",
    }
    edited = ok(edit(client, gym, session["id"], body, person))
    assert (edited["class_type_id"], edited["coach_id"], edited["topic"]) == (
        advanced,
        str(person),
        "Pasajes",
    )
    assert day_ids(client, gym, str(yesterday())) == [session["id"]]


# --- cancel ---------------------------------------------------------------------------


@pg
def test_a_cancelled_class_stays_on_its_day_and_out_of_the_unmarked(
    client: TestClient, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    session = start(client, gym, {"class_type_id": fundamentals, "starts_at": at(yesterday())})
    assert session["cancelled_at"] is None
    assert unmarked_ids(client, gym) == [session["id"]]

    cancelled = ok(act(client, gym, session["id"], "cancel"))
    assert cancelled["cancelled_at"] is not None
    # Cancelling again keeps when it was.
    assert (
        ok(act(client, gym, session["id"], "cancel"))["cancelled_at"] == (cancelled["cancelled_at"])
    )
    listed = ok(client.get("/api/sessions", params={"date": str(yesterday())}, headers=as_gym(gym)))
    assert [s["cancelled_at"] for s in listed["sessions"]] == [cancelled["cancelled_at"]]
    assert unmarked_ids(client, gym) == []

    reactivated = ok(act(client, gym, session["id"], "reactivate"))
    assert reactivated["cancelled_at"] is None
    assert unmarked_ids(client, gym) == [session["id"]]
    assert ok(act(client, gym, session["id"], "reactivate"))["cancelled_at"] is None


@pg
def test_a_cancelled_class_takes_no_attendance_and_runs_no_timer(
    client: TestClient, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    session = start(client, gym, {"class_type_id": fundamentals})["id"]
    blocks = ok(put_plan(client, gym, session, technique_and_sparring(kinds(client, gym))))
    membership = owner_membership(client, gym, session)
    ok(act(client, gym, session, "cancel"))

    assert change(client, gym, session, mark=[membership]).status_code == 409
    trial = plan(client, gym, TRIAL)
    assert guest(client, gym, session, add_person(client, gym, "G"), trial).status_code == 409
    assert put_plan(client, gym, session, []).status_code == 409
    block = blocks["blocks"][0]["id"]
    assert record(client, gym, session, block, {"actual_seconds": 60}).status_code == 409
    assert roster(client, gym, session)["present"] == 0

    # Nor is a cancelled class the plan to start the next one from.
    following = start(client, gym, {"class_type_id": fundamentals})["id"]
    suggested = ok(client.get(f"/api/sessions/{following}/blocks/suggested", headers=as_gym(gym)))
    assert suggested["from_session_id"] is None

    ok(act(client, gym, session, "reactivate"))
    assert change(client, gym, session, mark=[membership]).status_code == 200


@pg
def test_a_class_with_attendance_is_not_cancelled(client: TestClient, gym: uuid.UUID) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    session = start(client, gym, {"class_type_id": fundamentals})["id"]
    changed(client, gym, session, mark=[owner_membership(client, gym, session)])
    refused = act(client, gym, session, "cancel")
    assert refused.status_code == 409, refused.text
    assert ok(client.get(f"/api/sessions/{session}", headers=as_gym(gym)))["cancelled_at"] is None


# --- delete ---------------------------------------------------------------------------


@pg
def test_deleting_a_class_removes_its_attendance_and_blocks_and_gives_credits_back(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    competition = class_type(client, gym, adults, "Competición", cost=2)
    person = add_person(client, gym, "Paula Contreras")
    pack = join(client, gym, person, plan(client, gym, CREDITS))
    session = start(client, gym, {"class_type_id": competition, "starts_at": at(yesterday())})["id"]
    planned = ok(put_plan(client, gym, session, technique_and_sparring(kinds(client, gym))))
    ok(record(client, gym, session, planned["blocks"][0]["id"], {"actual_seconds": 1200}))
    changed(client, gym, session, mark=[pack, owner_membership(client, gym, session)])
    assert credits_left(db, gym, pack) == 10
    assert counts(client, gym, person)["total"] == 1

    deleted = delete(client, gym, session)
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/sessions/{session}", headers=as_gym(gym)).status_code == 404
    assert delete(client, gym, session).status_code == 404
    assert credits_left(db, gym, pack) == 12
    assert counts(client, gym, person)["total"] == 0
    time_ = ok(client.get(f"/api/people/{person}/time", headers=as_gym(gym)))
    assert time_["all_time"]["by_kind"] == []
    left = "SELECT (SELECT count(*) FROM attendance) + (SELECT count(*) FROM session_block)"
    assert run(db.api_url, in_gym(gym, left))[0][0] == 0


@pg
def test_a_coach_neither_cancels_nor_deletes(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    session = start(client, gym, {"class_type_id": fundamentals}, coach)["id"]
    for what in ("cancel", "reactivate"):
        assert act(client, gym, session, what, coach).status_code == 403
    assert delete(client, gym, session, coach).status_code == 403
    assert client.get(f"/api/sessions/{session}", headers=as_gym(gym, coach)).status_code == 200


@pg
def test_another_gyms_class_is_not_found(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    session = start(client, gym, {"class_type_id": fundamentals})["id"]
    other = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    assert edit(client, other, session, {"starts_at": at(yesterday())}).status_code == 404
    for what in ("cancel", "reactivate"):
        assert act(client, other, session, what).status_code == 404
    assert delete(client, other, session).status_code == 404
    assert ok(client.get(f"/api/sessions/{session}", headers=as_gym(gym)))["cancelled_at"] is None


@pg
def test_only_an_owner_or_admin_deletes_a_session_at_the_database(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """RLS holds the delete to the roles even for a request that skipped the check."""
    coach, admin = add_staff(db, gym, "coach"), add_staff(db, gym, "admin")
    fundamentals = class_type(client, gym, program(client, gym, "Adultos"))
    ids = [uuid.UUID(start(client, gym, {"class_type_id": fundamentals})["id"]) for _ in range(3)]
    delete_sql = "DELETE FROM session WHERE id = $1 RETURNING id"

    for person in (coach, None, uuid.uuid4()):
        assert run(db.api_url, in_gym(gym, delete_sql, ids[0], person=person)) == []
    # An admin of another gym is no admin here.
    elsewhere = add_staff(db, seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}"), "admin")
    assert run(db.api_url, in_gym(gym, delete_sql, ids[0], person=elsewhere)) == []
    # Reads and other writes are the gym's alone, as before.
    assert len(run(db.api_url, in_gym(gym, "SELECT id FROM session", person=coach))) == 3

    assert len(run(db.api_url, in_gym(gym, delete_sql, ids[1], person=admin))) == 1
    owner = seeded_owner(gym)
    assert len(run(db.api_url, in_gym(gym, delete_sql, ids[2], person=owner))) == 1
    assert len(run(db.api_url, in_gym(gym, "SELECT id FROM session", person=owner))) == 1


# --- the timer record, corrected after the class ------------------------------------


@pg
def test_a_finished_classs_blocks_are_corrected_and_time_follows(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    adults = program(client, gym, "Adultos")
    fundamentals = class_type(client, gym, adults)
    coach = add_staff(db, gym, "coach")
    person = add_person(client, gym, "Ana Rojas")
    membership = join(client, gym, person, plan(client, gym, {**MONTHLY, "program_id": adults}))
    session = start(
        client, gym, {"class_type_id": fundamentals, "starts_at": at(yesterday())}, coach
    )["id"]
    k = kinds(client, gym)
    blocks = ok(put_plan(client, gym, session, technique_and_sparring(k), coach))["blocks"]
    # The coach forgot Terminar: técnica ran its 20 minutes, sparring was never recorded.
    ok(record(client, gym, session, blocks[0]["id"], {"actual_seconds": 1200}, coach))
    changed(client, gym, session, mark=[membership])

    def seconds() -> dict[str, int]:
        time_ = ok(client.get(f"/api/people/{person}/time", headers=as_gym(gym)))
        return {t["name"]: t["seconds"] for t in time_["all_time"]["by_kind"]}

    assert seconds() == {"Técnica": 1200}

    # Afterwards: técnica was 15 minutes, a drilling block is added, sparring ran 4 rounds.
    corrected = [
        {"id": blocks[0]["id"], "block_kind_id": k["Técnica"]["id"], "planned_seconds": 1200},
        {"id": blocks[1]["id"], **technique_and_sparring(k)[1]},
        {"block_kind_id": k["Drilling"]["id"], "planned_seconds": 600},
    ]
    plan_ = ok(put_plan(client, gym, session, corrected, coach))["blocks"]
    assert plan_[0]["actual_seconds"] == 1200
    ok(record(client, gym, session, plan_[0]["id"], {"actual_seconds": 900}, coach))
    sparring = {"actual_seconds": 1200, "rounds_completed": 4}
    ok(record(client, gym, session, plan_[1]["id"], sparring, coach))
    ok(record(client, gym, session, plan_[2]["id"], {"actual_seconds": 600}, coach))
    assert seconds() == {"Técnica": 900, "Sparring": 1200, "Drilling": 600}

    # A block removed takes its time with it.
    ok(put_plan(client, gym, session, corrected[:2], coach))
    assert seconds() == {"Técnica": 900, "Sparring": 1200}


# --- the migration ----------------------------------------------------------------------


@pg
def test_upgrade_and_downgrade() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch)
        column = (
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'session' AND column_name = 'cancelled_at'"
        )
        assert run(scratch.admin_url, lambda c: c.fetchval(column)) == 1
        command.downgrade(scratch.alembic(), "0032")
        assert run(scratch.admin_url, lambda c: c.fetchval(column)) == 0
        migrate(scratch)
        assert run(scratch.admin_url, lambda c: c.fetchval(column)) == 1
