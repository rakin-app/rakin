"""Freeze requests (#270): a student, or their guardian, asks for a freeze from /me,
and the owner or an admin approves or rejects it.

Approving freezes the membership through the admin's own freeze, so these tests hold
a request approved against a freeze made by hand on a twin membership.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_freezes import freeze, periods, today
from tests.test_guardians import add_person, new_kid
from tests.test_memberships import add_staff, cancel, plan, start
from tests.test_proofs import RecordingMailer, sent_notices

pytestmark = pytest.mark.postgres

DAY = timedelta(days=1)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(db: Database, mailer: RecordingMailer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url, public_base_url="http://testserver"))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"sur-{uuid.uuid4().hex[:8]}")


def give_email(db: Database, gym: uuid.UUID, person: uuid.UUID, email: str) -> None:
    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "UPDATE gym_person SET email = $3 WHERE gym_id = $1 AND person_id = $2",
            gym,
            person,
            email,
        )

    run(db.admin_url, query)


def membership(client: TestClient, gym: uuid.UUID, person: str, started_on: date) -> str:
    response = start(
        client, gym, plan(client, gym, "signup"), person, started_on=started_on.isoformat()
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def ask(
    client: TestClient,
    gym: uuid.UUID,
    person: str,
    membership_id: str,
    from_date: date,
    to_date: date,
    reason: str = "lesion",
    note: str | None = "Esguince de tobillo",
) -> Any:
    body = {
        "membership_id": membership_id,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "reason": reason,
        "note": note,
    }
    return client.post("/api/me/freeze-requests", json=body, headers=as_gym(gym, uuid.UUID(person)))


def asked(client: TestClient, gym: uuid.UUID, person: str, membership_id: str, **kw: Any) -> Any:
    now = kw.pop("now")
    response = ask(client, gym, person, membership_id, now, now + 14 * DAY, **kw)
    assert response.status_code == 201, response.text
    return response.json()


def waiting(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None) -> Any:
    return client.get("/api/freeze-requests", headers=as_gym(gym, person))


def approve(client: TestClient, gym: uuid.UUID, request: str, **body: Any) -> Any:
    return client.post(
        f"/api/freeze-requests/{request}/approve",
        json={k: v.isoformat() for k, v in body.items()},
        headers=as_gym(gym),
    )


def reject(client: TestClient, gym: uuid.UUID, request: str, note: str | None = None) -> Any:
    return client.post(
        f"/api/freeze-requests/{request}/reject", json={"note": note}, headers=as_gym(gym)
    )


def my_plans(client: TestClient, gym: uuid.UUID, person: str) -> list[dict[str, Any]]:
    response = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person)))
    assert response.status_code == 200, response.text
    plans: list[dict[str, Any]] = response.json()["plans"]
    return plans


def membership_now(client: TestClient, gym: uuid.UUID, membership_id: str) -> Any:
    response = client.get(f"/api/memberships/{membership_id}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return response.json()


# --- asking and approving ------------------------------------------------------------


def test_an_approved_request_freezes_exactly_as_an_admin_freeze(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    give_email(db, sur, seeded_owner(sur), "duena@sur.cl")
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    twin = add_person(client, sur, "Bea")
    asked_for = membership(client, sur, ana, now - 20 * DAY)
    by_hand = membership(client, sur, twin, now - 20 * DAY)

    request = asked(client, sur, ana, asked_for, now=now)
    assert (request["status"], request["person_name"], request["requested_by"]) == (
        "pending",
        "Ana",
        ana,
    )
    [listed] = waiting(client, sur).json()
    assert (listed["id"], listed["reason"], listed["note"]) == (
        request["id"],
        "lesion",
        "Esguince de tobillo",
    )
    # Told to the owner, with a link to Ana's ficha.
    email = mailer.sent[-1]
    assert email.to == "duena@sur.cl"
    assert email.subject == "Ana pide congelar su plan"
    assert f"http://testserver/admin/alumnos/{ana}" in email.text
    assert "Lesión · Esguince de tobillo" in email.text

    approved = approve(client, sur, request["id"])
    assert approved.status_code == 200, approved.text
    by_admin = freeze(client, sur, by_hand, now + 14 * DAY).json()

    body = approved.json()
    assert body["status"] == "frozen"
    assert body["freeze"]["reason"] == "Lesión: Esguince de tobillo"
    for field in ("current_period_end", "anchor_day", "status"):
        assert body[field] == by_admin[field]
    assert periods(db, sur, asked_for) == periods(db, sur, by_hand)
    assert waiting(client, sur).json() == []
    assert sent_notices(db, sur)[-1] == ("freeze_approved", ana, "sent")
    [mine] = my_plans(client, sur, ana)
    assert mine["status"] == "frozen"
    assert mine["pending_request"] is None
    assert mine["last_decided"]["status"] == "approved"


def test_the_admin_may_approve_other_dates(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now)

    approved = approve(client, sur, request["id"], from_date=now + 2 * DAY, to_date=now + 9 * DAY)

    assert approved.status_code == 200, approved.text
    booked = approved.json()["freeze"]
    assert (booked["from_date"], booked["to_date"], booked["started"]) == (
        (now + 2 * DAY).isoformat(),
        (now + 9 * DAY).isoformat(),
        False,
    )


def test_an_approval_is_refused_as_the_freeze_would_be(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now)
    # Frozen by hand meanwhile: the request cannot freeze it again, and still waits.
    assert freeze(client, sur, started, now + 5 * DAY).status_code == 200

    assert approve(client, sur, request["id"]).status_code == 409
    assert [r["id"] for r in waiting(client, sur).json()] == [request["id"]]


def test_a_rejection_reaches_the_student_with_its_note(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now, reason="viaje", note=None)

    rejected = reject(client, sur, request["id"], "  Este mes no se puede, conversemos  ")

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    [mine] = my_plans(client, sur, ana)
    assert mine["status"] == "active"
    assert mine["pending_request"] is None
    assert mine["last_decided"]["decision_note"] == "Este mes no se puede, conversemos"
    email = mailer.sent[-1]
    assert email.to == "ana@example.cl"
    assert "no aprobó" in email.subject
    assert "Nota: Este mes no se puede, conversemos" in email.text
    assert membership_now(client, sur, started)["status"] == "active"
    # Answered once: a second answer finds nothing waiting.
    assert reject(client, sur, request["id"]).status_code == 404
    assert approve(client, sur, request["id"]).status_code == 404


def test_a_guardian_asks_for_a_dependent_and_is_told_the_answer(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    started = membership(client, sur, juan, now - 3 * DAY)

    request = asked(client, sur, marta, started, now=now, reason="salud", note=None)
    [mine] = my_plans(client, sur, marta)
    assert (mine["person_name"], mine["pending_request"]["id"]) == ("Juan", request["id"])

    assert approve(client, sur, request["id"]).status_code == 200
    assert sent_notices(db, sur)[-1] == ("freeze_approved", marta, "sent")


def test_nobody_asks_for_someone_elses_membership(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    beas = membership(client, sur, bea, now - 3 * DAY)

    response = ask(client, sur, ana, beas, now, now + 7 * DAY)

    assert response.status_code == 404
    assert my_plans(client, sur, ana) == []


# --- refusals --------------------------------------------------------------------------


def test_a_request_needs_an_active_membership_with_no_freeze_or_request(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)

    # A freeze booked ahead, then running: neither takes a request.
    assert freeze(client, sur, started, now + 20 * DAY).status_code == 200
    refused = ask(client, sur, ana, started, now + 30 * DAY, now + 40 * DAY)
    assert (refused.status_code, refused.json()["detail"]) == (409, {"code": "has_freeze"})
    client.post(f"/api/memberships/{started}/freeze/end", headers=as_gym(sur))

    bea = add_person(client, sur, "Bea")
    other = membership(client, sur, bea, now - 3 * DAY)
    booked = client.post(
        f"/api/memberships/{other}/freeze",
        json={
            "from_date": (now + 5 * DAY).isoformat(),
            "to_date": (now + 9 * DAY).isoformat(),
            "reason": "viaje",
        },
        headers=as_gym(sur),
    )
    assert booked.status_code == 200, booked.text
    refused = ask(client, sur, bea, other, now + 20 * DAY, now + 30 * DAY)
    assert (refused.status_code, refused.json()["detail"]) == (409, {"code": "has_freeze"})

    # One waiting already.
    cleo = add_person(client, sur, "Cleo")
    cleos = membership(client, sur, cleo, now - 3 * DAY)
    asked(client, sur, cleo, cleos, now=now)
    refused = ask(client, sur, cleo, cleos, now + 20 * DAY, now + 30 * DAY)
    assert (refused.status_code, refused.json()["detail"]) == (409, {"code": "has_pending"})

    # Cancelled.
    dora = add_person(client, sur, "Dora")
    doras = membership(client, sur, dora, now - 3 * DAY)
    assert cancel(client, sur, doras).status_code == 200
    refused = ask(client, sur, dora, doras, now, now + 7 * DAY)
    assert (refused.status_code, refused.json()["detail"]) == (409, {"code": "not_active"})


@pytest.mark.parametrize(
    ("starts", "ends", "reason", "note"),
    [
        (-1, 7, "lesion", None),  # in the past
        (5, 3, "lesion", None),  # ends before it starts
        (5, 5, "lesion", None),  # no day frozen
        (0, 400, "lesion", None),  # longer than a freeze lasts
        (0, 7, "otro", None),  # `otro` says nothing
        (0, 7, "vacaciones", None),  # not one of the reasons
    ],
)
def test_a_request_with_bad_dates_or_reason_is_refused(
    client: TestClient,
    db: Database,
    sur: uuid.UUID,
    starts: int,
    ends: int,
    reason: str,
    note: str | None,
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)

    response = ask(client, sur, ana, started, now + starts * DAY, now + ends * DAY, reason, note)

    assert response.status_code == 422, response.text


# --- withdrawing -----------------------------------------------------------------------


def test_whoever_asked_withdraws_a_waiting_request(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now)
    url = f"/api/me/freeze-requests/{request['id']}"

    assert client.delete(url, headers=as_gym(sur)).status_code == 404
    assert client.delete(url, headers=as_gym(sur, uuid.UUID(ana))).status_code == 204
    assert client.delete(url, headers=as_gym(sur, uuid.UUID(ana))).status_code == 404

    assert waiting(client, sur).json() == []
    [mine] = my_plans(client, sur, ana)
    assert (mine["pending_request"], mine["last_decided"]) == (None, None)
    asked(client, sur, ana, started, now=now)


# --- who answers -----------------------------------------------------------------------


def test_only_the_owner_and_admins_answer_requests(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now)
    coach = add_staff(db, sur, "coach")
    admin = add_staff(db, sur, "admin")

    for person in (coach, uuid.UUID(ana)):
        headers = as_gym(sur, person)
        assert waiting(client, sur, person).status_code == 403
        approve_url = f"/api/freeze-requests/{request['id']}/approve"
        assert client.post(approve_url, json={}, headers=headers).status_code == 403
        reject_url = f"/api/freeze-requests/{request['id']}/reject"
        assert client.post(reject_url, json={}, headers=headers).status_code == 403
    assert [r["id"] for r in waiting(client, sur, admin).json()] == [request["id"]]


def test_each_owner_and_admin_with_an_email_is_told_once(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    now = today(db, sur)
    give_email(db, sur, seeded_owner(sur), "duena@sur.cl")
    admin = add_staff(db, sur, "admin")
    give_email(db, sur, admin, "admin@sur.cl")
    coach = add_staff(db, sur, "coach")
    give_email(db, sur, coach, "coach@sur.cl")
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)

    asked(client, sur, ana, started, now=now)

    told = sorted(p for t, p, _ in sent_notices(db, sur) if t == "freeze_requested")
    assert told == sorted([str(seeded_owner(sur)), str(admin)])


def test_another_gyms_requests_are_not_seen_or_answered(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    now = today(db, sur)
    ana = add_person(client, sur, "Ana")
    started = membership(client, sur, ana, now - 3 * DAY)
    request = asked(client, sur, ana, started, now=now)

    assert waiting(client, norte).json() == []
    assert approve(client, norte, request["id"]).status_code == 404
    assert reject(client, norte, request["id"]).status_code == 404
    assert ask(client, norte, ana, started, now, now + 7 * DAY).status_code == 404
    assert [r["id"] for r in waiting(client, sur).json()] == [request["id"]]
