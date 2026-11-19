"""The consent register (#370): approving a join request keeps who accepted which notice
when, a minor's guardian consents apart from the membership, on the form or on their
page, and withdraws it there; a notice older than the gym's is refused.
"""

import dataclasses
import re
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.member_import import Writer
from app.main import create_app
from app.schemas.privacy import TEMPLATE_UPDATED_ON
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_guardians import add_dependent, add_person
from tests.test_join import (
    adult,
    approve,
    approved,
    minor,
    notice,
    one_request,
    queue,
    roomy_limits,
    submit,
    token_of,
    with_privacy,
)
from tests.test_member_roll import forget
from tests.test_memberships import PLANS
from tests.test_proofs import RecordingMailer

pytestmark = pytest.mark.postgres

FRONTEND_PRIVACY = Path(__file__).parents[2] / "frontend" / "src" / "api" / "privacy.ts"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def app(db: Database, mailer: RecordingMailer) -> FastAPI:
    app = create_app(
        make_settings(
            database_url=db.api_url, public_base_url="https://rakin.cl", base_domain="rakin.cl"
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.state.join_limits = roomy_limits()
    app.add_middleware(FakeAuth)
    return app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database, client: TestClient) -> uuid.UUID:
    return with_privacy(client, seed_gym(db, unique_slug("academia")))


def consent(client: TestClient, gym: uuid.UUID, person: str) -> dict[str, Any]:
    response = client.get(f"/api/people/{person}/consent", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def events(client: TestClient, gym: uuid.UUID, person: str) -> list[tuple[str, str | None, str]]:
    """The ficha's acts, newest first: what, by whom, from where."""
    return [
        (e["action"], e["by"] and e["by"]["name"], e["source"])
        for e in consent(client, gym, person)["events"]
    ]


def guardian_of(client: TestClient, gym: uuid.UUID, person: str) -> uuid.UUID:
    response = client.get(f"/api/people/{person}/family", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return uuid.UUID(response.json()["guardian"]["id"])


def kid_dob() -> str:
    return (seeded_today() - timedelta(days=365 * 9)).isoformat()


def new_kid(client: TestClient, gym: uuid.UUID, guardian: str, **body: Any) -> str:
    response = add_dependent(client, gym, guardian, name="Mateo", dob=kid_dob(), **body)
    assert response.status_code == 201, response.text
    kid: str = next(d["id"] for d in response.json()["dependents"] if d["name"] == "Mateo")
    return kid


def mine(client: TestClient, gym: uuid.UUID, guardian: uuid.UUID) -> list[dict[str, Any]]:
    response = client.get("/api/me/consents", headers=as_gym(gym, guardian))
    assert response.status_code == 200, response.text
    answer: list[dict[str, Any]] = response.json()
    return answer


def give(client: TestClient, gym: uuid.UUID, guardian: uuid.UUID, kid: str, **version: Any) -> Any:
    return client.post(
        f"/api/me/consents/{kid}", json={**notice(), **version}, headers=as_gym(gym, guardian)
    )


def withdraw(client: TestClient, gym: uuid.UUID, guardian: uuid.UUID, kid: str) -> Any:
    return client.delete(f"/api/me/consents/{kid}", headers=as_gym(gym, guardian))


# --- the join form --------------------------------------------------------------------


def test_approving_an_adult_keeps_the_notice_they_accepted(
    client: TestClient, gym: uuid.UUID
) -> None:
    request = one_request(client, gym, token_of(client, gym), adult())
    [sent] = queue(client, gym)

    person = approved(client, gym, request)["person_id"]

    record = consent(client, gym, person)
    assert record["basis"] == "contract"
    assert record["consent"] is None
    [event] = record["events"]
    assert event == {
        "action": "notice_accepted",
        "at": event["at"],
        "by": {"id": person, "name": "Ana Pérez"},
        "source": "join",
        "template_on": TEMPLATE_UPDATED_ON.isoformat(),
        "details_on": seeded_today().isoformat(),
    }
    # When they sent it, not when it was approved.
    assert event["at"] == sent["created_at"]


def test_a_minors_record_names_the_guardian_who_consented(
    client: TestClient, gym: uuid.UUID
) -> None:
    request = one_request(client, gym, token_of(client, gym), minor(guardian_consent=True))

    kid = approved(client, gym, request)["person_id"]

    record = consent(client, gym, kid)
    assert (record["basis"], record["consent"]) == ("guardian_consent", "given")
    by = {"id": str(guardian_of(client, gym, kid)), "name": "Marta Pérez"}
    # Both at the time the form was sent.
    assert sorted((e["action"], e["by"]["id"], e["at"]) for e in record["events"]) == [
        ("consent_given", by["id"], record["events"][0]["at"]),
        ("notice_accepted", by["id"], record["events"][0]["at"]),
    ]
    assert all(e["by"] == by for e in record["events"])
    assert all(e["template_on"] == TEMPLATE_UPDATED_ON.isoformat() for e in record["events"])


def test_the_record_names_the_guardian_the_request_gave(client: TestClient, gym: uuid.UUID) -> None:
    """A kid here already, with their guardian: approving a request that names that
    guardian, by email, records them, whoever else the gym knows."""
    token = token_of(client, gym)
    kid = approved(client, gym, one_request(client, gym, token, minor()))["person_id"]
    guardian = guardian_of(client, gym, kid)
    add_person(client, gym, "Otra Apoderada")
    [kid_rut] = [
        r["rut"]
        for r in client.get("/api/people", headers=as_gym(gym)).json()["items"]
        if r["id"] == kid
    ]

    again = one_request(client, gym, token, minor(rut=kid_rut, guardian_consent=True))
    assert approved(client, gym, again)["person_id"] == kid

    given = [e for e in consent(client, gym, kid)["events"] if e["action"] == "consent_given"]
    assert [e["by"]["id"] for e in given] == [str(guardian)]


def test_a_request_naming_another_guardian_is_refused_and_records_nothing(
    client: TestClient, gym: uuid.UUID
) -> None:
    """A minor has one guardian in a gym (0010): a request naming someone else for a kid
    who has one is a 409, and the register keeps nothing of it."""
    token = token_of(client, gym)
    kid = approved(client, gym, one_request(client, gym, token, minor()))["person_id"]
    [kid_rut] = [
        r["rut"]
        for r in client.get("/api/people", headers=as_gym(gym)).json()["items"]
        if r["id"] == kid
    ]
    other = minor(
        rut=kid_rut,
        guardian_name="Otro Apoderado",
        guardian_email=f"{uuid.uuid4().hex[:8]}@x.cl",
        guardian_consent=True,
    )

    response = approve(client, gym, one_request(client, gym, token, other))

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "has_guardian"
    assert events(client, gym, kid) == [("notice_accepted", "Marta Pérez", "join")]


def test_a_minors_request_that_finds_no_guardian_is_a_409_not_a_500(
    client: TestClient, gym: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = Writer.write

    async def without_guardian(self: Writer, member: Any) -> Any:
        written = await write(self, member)
        self.guardian_id = None
        return written

    monkeypatch.setattr(Writer, "write", without_guardian)
    request = one_request(client, gym, token_of(client, gym), minor(guardian_consent=True))

    response = approve(client, gym, request)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {"code": "minor", "field": "guardian_name"}
    # Rolled back: the request waits in the queue still.
    assert [r["id"] for r in queue(client, gym)] == [request]


def test_a_guardian_may_send_the_form_without_consenting(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    request = one_request(
        client, gym, token_of(client, gym), minor(guardian_email=f"{uuid.uuid4().hex[:8]}@x.cl")
    )
    mailer.sent.clear()

    kid = approved(client, gym, request)["person_id"]

    assert consent(client, gym, kid)["consent"] == "missing"
    assert events(client, gym, kid) == [("notice_accepted", "Marta Pérez", "join")]
    # `join_approved` asks the guardian for it, on their page.
    [email] = mailer.sent
    assert "Falta tu autorización" in email.text
    assert email.html is not None and "Falta tu autorización" in email.html


def test_a_guardian_who_consented_is_not_asked_again(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    request = one_request(
        client,
        gym,
        token_of(client, gym),
        minor(guardian_consent=True, guardian_email=f"{uuid.uuid4().hex[:8]}@x.cl"),
    )
    mailer.sent.clear()

    approved(client, gym, request)

    [email] = mailer.sent
    assert "Falta tu autorización" not in email.text


def test_an_adults_guardian_consent_is_ignored(client: TestClient, gym: uuid.UUID) -> None:
    request = one_request(client, gym, token_of(client, gym), adult(guardian_consent=True))

    person = approved(client, gym, request)["person_id"]

    assert events(client, gym, person) == [("notice_accepted", "Ana Pérez", "join")]


@pytest.mark.parametrize(
    "version",
    [
        {"template_on": (TEMPLATE_UPDATED_ON - timedelta(days=1)).isoformat()},
        {"details_on": (seeded_today() - timedelta(days=1)).isoformat()},
    ],
)
def test_a_stale_notice_version_is_refused(
    client: TestClient, gym: uuid.UUID, version: dict[str, str]
) -> None:
    token = token_of(client, gym)

    response = submit(client, token, adult(notice={**notice(), **version}))

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "stale_notice"
    assert queue(client, gym) == []


def test_the_form_names_the_notices_details_date(client: TestClient, gym: uuid.UUID) -> None:
    form = client.get(f"/api/join/{token_of(client, gym)}").json()

    assert form["privacy_updated_on"] == seeded_today().isoformat()


# --- the guardian's page --------------------------------------------------------------


def test_a_guardian_consents_for_a_kid_added_by_hand_and_withdraws_it(
    client: TestClient, gym: uuid.UUID
) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)
    guardian = uuid.UUID(mother)
    assert consent(client, gym, kid) == {
        "basis": "guardian_consent",
        "consent": "missing",
        "events": [],
    }
    assert [(d["id"], d["consent"]) for d in mine(client, gym, guardian)] == [(kid, "missing")]

    given = give(client, gym, guardian, kid)
    assert given.status_code == 200, given.text
    assert given.json()["consent"] == "given"
    assert give(client, gym, guardian, kid).json()["detail"] == "already_given"

    withdrawn = withdraw(client, gym, guardian, kid)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["consent"] == "withdrawn"
    assert withdraw(client, gym, guardian, kid).json()["detail"] == "not_given"

    assert events(client, gym, kid) == [
        ("consent_withdrawn", "Camila Rojas", "page"),
        ("consent_given", "Camila Rojas", "page"),
    ]
    [withdrawal, giving] = consent(client, gym, kid)["events"]
    assert (withdrawal["template_on"], withdrawal["details_on"]) == (None, None)
    assert giving["details_on"] == seeded_today().isoformat()
    # Given again after a withdrawal.
    assert give(client, gym, guardian, kid).json()["consent"] == "given"


def test_withdrawing_leaves_the_membership_as_it_is(client: TestClient, gym: uuid.UUID) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)
    plan = client.post("/api/plans", json=PLANS["signup"], headers=as_gym(gym)).json()["id"]
    started = client.post(
        "/api/memberships", json={"person_id": kid, "plan_id": plan}, headers=as_gym(gym)
    )
    assert started.status_code == 201, started.text
    guardian = uuid.UUID(mother)
    give(client, gym, guardian, kid)

    withdraw(client, gym, guardian, kid)

    membership = client.get(f"/api/memberships/{started.json()['id']}", headers=as_gym(gym))
    assert membership.json()["status"] == started.json()["status"]


def test_the_page_refuses_a_stale_notice(client: TestClient, gym: uuid.UUID) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)

    response = give(
        client, gym, uuid.UUID(mother), kid, details_on=(seeded_today() - timedelta(1)).isoformat()
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "stale_notice"
    assert consent(client, gym, kid)["events"] == []


def test_only_the_guardian_consents_and_only_for_a_minor(
    client: TestClient, gym: uuid.UUID
) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)
    stranger = uuid.UUID(add_person(client, gym, "Otra Persona"))
    grown = add_dependent(client, gym, mother, name="Hija Mayor", dob="1995-01-01")
    assert grown.status_code == 201, grown.text
    adult_child = next(d["id"] for d in grown.json()["dependents"] if d["name"] == "Hija Mayor")

    assert give(client, gym, stranger, kid).status_code == 404
    assert withdraw(client, gym, stranger, kid).status_code == 404
    assert mine(client, gym, stranger) == []
    # An adult dependent's data rest on the contract: nothing to consent to.
    assert give(client, gym, uuid.UUID(mother), adult_child).status_code == 404
    assert [d["id"] for d in mine(client, gym, uuid.UUID(mother))] == [kid]
    assert consent(client, gym, adult_child)["basis"] == "contract"


def test_a_kid_with_no_birth_date_needs_their_guardians_consent(
    client: TestClient, gym: uuid.UUID
) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    response = add_dependent(client, gym, mother, name="Sin Fecha")
    assert response.status_code == 201, response.text
    kid = next(d["id"] for d in response.json()["dependents"] if d["name"] == "Sin Fecha")

    assert consent(client, gym, kid)["basis"] == "guardian_consent"


def test_the_welcome_asks_a_guardian_for_a_missing_consent(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)
    plan = client.post("/api/plans", json=PLANS["signup"], headers=as_gym(gym)).json()["id"]
    mailer.sent.clear()

    started = client.post(
        "/api/memberships",
        json={"person_id": kid, "plan_id": plan, "send_welcome": True},
        headers=as_gym(gym),
    )

    assert started.status_code == 201, started.text
    [email] = mailer.sent
    assert re.search(r"autorizar que .+ trate los datos de Mateo", email.text)


# --- the database ---------------------------------------------------------------------


def test_the_database_refuses_consent_by_someone_not_the_guardian(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    mother = add_person(client, gym, "Camila Rojas")
    kid = new_kid(client, gym, mother)
    stranger = uuid.UUID(add_person(client, gym, "Otra Persona"))
    insert = (
        "INSERT INTO consent_event (gym_id, person_id, action, by_person_id, source,"
        " template_on, details_on) VALUES ($1, $2, 'consent_given', $3, 'page', $4, $4)"
    )

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, in_gym(gym, insert, gym, uuid.UUID(kid), stranger, seeded_today()))
    # Nor changes or deletes one.
    run(db.api_url, in_gym(gym, insert, gym, uuid.UUID(kid), uuid.UUID(mother), seeded_today()))
    for statement in ("UPDATE consent_event SET source = 'join'", "DELETE FROM consent_event"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, in_gym(gym, statement))


def test_deleting_a_person_deletes_their_consent_record(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person = approved(client, gym, one_request(client, gym, token_of(client, gym), adult()))[
        "person_id"
    ]

    response = forget(client, gym, person)

    assert response.status_code == 204, response.text
    left = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT count(*) FROM consent_event WHERE person_id = $1", uuid.UUID(person)
        ),
    )
    assert left == 0


def test_the_api_and_the_spa_name_the_same_notice_template() -> None:
    found = re.search(r"TEMPLATE_UPDATED_ON = '(\d{4}-\d\d-\d\d)'", FRONTEND_PRIVACY.read_text())

    assert found is not None
    assert found.group(1) == TEMPLATE_UPDATED_ON.isoformat()


def test_another_gym_sees_none_of_it(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person = approved(client, gym, one_request(client, gym, token_of(client, gym), adult()))[
        "person_id"
    ]
    other = seed_gym(db, unique_slug("academia"))

    assert client.get(f"/api/people/{person}/consent", headers=as_gym(other)).status_code == 404
    seen = run(db.api_url, in_gym(other, "SELECT count(*) FROM consent_event"))
    assert seen[0]["count"] == 0
