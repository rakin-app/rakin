"""Staff management (#62): invite an admin or a coach, change their role, revoke it.

The owner manages everyone but themselves; an admin manages coaches only.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.integrations.mailer import Email, MailDeliveryError
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_guardians import add_person
from tests.test_people import new_phone
from tests.test_proofs import RecordingMailer, sent_notices

pytestmark = pytest.mark.postgres


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
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    """A fresh gym per test, so each one's staff list is its own."""
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def invite(
    client: TestClient,
    gym: uuid.UUID,
    role: str = "coach",
    by: uuid.UUID | None = None,
    **body: Any,
) -> Any:
    sent = {"phone": new_phone(), "name": "Pedro", "email": "pedro@example.cl", "role": role}
    return client.post("/api/staff", json={**sent, **body}, headers=as_gym(gym, by))


def invited(client: TestClient, gym: uuid.UUID, role: str = "coach", **body: Any) -> uuid.UUID:
    response = invite(client, gym, role, **body)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["person_id"])


def staff_of(client: TestClient, gym: uuid.UUID) -> list[tuple[str, str]]:
    response = client.get("/api/staff", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return [(s["name"], s["role"]) for s in response.json()]


# --- invite ---------------------------------------------------------------------------


def test_an_invite_adds_the_person_with_their_role(client: TestClient, gym: uuid.UUID) -> None:
    phone = new_phone()
    response = invite(client, gym, "admin", phone=phone, name="Carla", email="carla@example.cl")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["name"], body["phone"], body["email"], body["role"]) == (
        "Carla",
        phone,
        "carla@example.cl",
        "admin",
    )
    invited(client, gym, "coach", name="Beto")
    # The owner first, then admins, then coaches.
    [owner, *rest] = staff_of(client, gym)
    assert owner[1] == "owner"
    assert rest == [("Carla", "admin"), ("Beto", "coach")]


def test_the_invite_emails_a_sign_in_link_to_the_admin_screens(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()

    pedro = invited(client, gym, "coach")

    [email] = mailer.sent
    assert email.to == "pedro@example.cl"
    # The owner `seed_gym` made, "owner of <slug>", invited them to the gym of that slug.
    assert email.subject.startswith("owner of academia-")
    assert " te invitó al equipo de academia-" in email.subject
    assert "Hola, Pedro:" in email.text
    assert "como coach." in email.text
    assert "Tu página" not in email.text
    [url] = [line for line in email.text.splitlines() if line.startswith("Entrar: ")]
    assert "/api/auth/callback?token=" in url
    # No `next`: signing in lands on the app's start, the admin screens.
    assert "next=" not in url
    assert email.html is not None and "Entrar a Rakin" in email.html
    assert "Ir a mi página" not in email.html
    assert sent_notices(db, gym)[-1] == ("staff_invite", str(pedro), "sent")


def test_the_invited_person_can_ask_for_a_sign_in_link(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    address = f"{uuid.uuid4().hex[:8]}@example.cl"
    pedro = invited(client, gym, email=address)

    assert signs_in_with(db, address.upper()) == [pedro]


def test_inviting_a_member_keeps_their_record_and_gives_them_the_role(
    client: TestClient, gym: uuid.UUID
) -> None:
    phone = new_phone()
    ana = add_person(client, gym, "Ana", phone=phone)

    response = invite(client, gym, phone=phone, name="Otra", email="ana.coach@example.cl")

    assert response.status_code == 201, response.text
    assert response.json()["person_id"] == ana
    person = client.get(f"/api/people/{ana}", headers=as_gym(gym)).json()
    # Their name as the gym has it; the invite's email, which is the one they sign in with.
    assert (person["name"], person["email"]) == ("Ana", "ana.coach@example.cl")
    assert ("Ana", "coach") in staff_of(client, gym)


def gyms_reached(db: Database, person: uuid.UUID, address: str) -> set[uuid.UUID]:
    """The gyms a sign-in with `address` reaches for `person` (migration 0029)."""
    rows = run(
        db.admin_url,
        lambda c: c.fetch("SELECT gym FROM auth_gyms_of($1, $2) AS gym", person, address),
    )
    return {r["gym"] for r in rows}


def signs_in_with(db: Database, address: str) -> list[uuid.UUID]:
    """Whom a sign-in link asked for at `address` goes to (migration 0005)."""
    rows = run(
        db.admin_url,
        lambda c: c.fetch("SELECT person_id FROM auth_people_by_email($1)", address),
    )
    return [r["person_id"] for r in rows]


def test_someone_known_to_another_gym_gets_the_role_and_the_invites_email(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    phone = new_phone()
    elsewhere = add_person(client, other, "Ana", phone=phone)
    address = f"{uuid.uuid4().hex[:8]}@example.cl"
    mailer.sent.clear()

    response = invite(client, gym, phone=phone, name="Ana Pérez", email=address)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["person_id"], body["name"], body["email"]) == (elsewhere, "Ana Pérez", address)
    # Nothing in the answer says another gym has them (#146).
    assert "emailed" not in body
    [email] = mailer.sent
    assert email.to == address
    # The address signs in to this gym alone: the other's record does not hold it.
    assert signs_in_with(db, address) == [uuid.UUID(elsewhere)]
    assert gyms_reached(db, uuid.UUID(elsewhere), address) == {gym}
    assert ("Ana Pérez", "coach") in staff_of(client, gym)
    # The other gym still has no staff row for her, nor this gym's email.
    assert ("Ana", "coach") not in staff_of(client, other)
    assert client.get(f"/api/people/{elsewhere}", headers=as_gym(other)).json()["email"] != address


def test_a_member_known_elsewhere_takes_the_invites_email_and_is_invited_there(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    phone = new_phone()
    add_person(client, other, "Ana", phone=phone)
    ana = add_person(client, gym, "Ana", phone=phone)
    mailer.sent.clear()

    response = invite(client, gym, phone=phone, email="otra@example.cl")

    assert response.status_code == 201, response.text
    assert (response.json()["person_id"], response.json()["email"]) == (ana, "otra@example.cl")
    [email] = mailer.sent
    assert email.to == "otra@example.cl"


def test_the_invite_stands_when_the_mail_fails(
    client: TestClient,
    db: Database,
    gym: uuid.UUID,
    mailer: RecordingMailer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(email: Email) -> None:
        raise MailDeliveryError("smtp relay: 421 try later")

    monkeypatch.setattr(mailer, "send", refuse)

    pedro = invited(client, gym)

    assert ("Pedro", "coach") in staff_of(client, gym)
    assert sent_notices(db, gym)[-1] == ("staff_invite", str(pedro), "failed")


def test_an_invite_refuses_someone_already_on_the_staff(client: TestClient, gym: uuid.UUID) -> None:
    phone = new_phone()
    pedro = invited(client, gym, phone=phone)

    response = invite(client, gym, "admin", phone=phone)

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "already_staff", "person_id": str(pedro)}
    assert ("Pedro", "coach") in staff_of(client, gym)


@pytest.mark.parametrize(
    ("field", "value"),
    [("role", "owner"), ("role", "member"), ("email", None), ("email", "nope"), ("phone", "12")],
)
def test_an_invite_refuses_what_it_cannot_send(
    client: TestClient, gym: uuid.UUID, field: str, value: Any
) -> None:
    response = invite(client, gym, **{field: value})

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]


def test_an_invite_without_an_email_is_refused(client: TestClient, gym: uuid.UUID) -> None:
    body = {"phone": new_phone(), "name": "Pedro", "role": "coach"}
    response = client.post("/api/staff", json=body, headers=as_gym(gym))
    assert response.status_code == 422


# --- change role and revoke -----------------------------------------------------------


def test_the_owner_moves_someone_between_admin_and_coach(
    client: TestClient, gym: uuid.UUID
) -> None:
    pedro = invited(client, gym)

    up = client.patch(f"/api/staff/{pedro}", json={"role": "admin"}, headers=as_gym(gym))
    assert up.status_code == 200, up.text
    assert up.json()["role"] == "admin"
    again = client.patch(f"/api/staff/{pedro}", json={"role": "admin"}, headers=as_gym(gym))
    assert again.status_code == 200
    down = client.patch(f"/api/staff/{pedro}", json={"role": "coach"}, headers=as_gym(gym))
    assert down.json()["role"] == "coach"
    # A role takes effect on the next request (app.roles).
    assert client.get("/api/staff", headers=as_gym(gym, pedro)).status_code == 403


def test_a_revoked_person_loses_the_role_and_keeps_their_record(
    client: TestClient, gym: uuid.UUID
) -> None:
    pedro = invited(client, gym)
    assert client.get("/api/people", headers=as_gym(gym, pedro)).status_code == 200

    response = client.delete(f"/api/staff/{pedro}", headers=as_gym(gym))

    assert response.status_code == 204
    assert ("Pedro", "coach") not in staff_of(client, gym)
    assert client.get("/api/people", headers=as_gym(gym, pedro)).status_code == 403
    assert client.get(f"/api/people/{pedro}", headers=as_gym(gym)).status_code == 200
    # And can be invited again.
    assert invite(client, gym, phone=person_phone(client, gym, pedro)).status_code == 201


def person_phone(client: TestClient, gym: uuid.UUID, person: uuid.UUID) -> str:
    phone: str = client.get(f"/api/people/{person}", headers=as_gym(gym)).json()["phone"]
    return phone


def test_someone_not_on_the_staff_is_not_found(client: TestClient, gym: uuid.UUID) -> None:
    ana = add_person(client, gym, "Ana")
    for response in (
        client.patch(f"/api/staff/{ana}", json={"role": "admin"}, headers=as_gym(gym)),
        client.delete(f"/api/staff/{ana}", headers=as_gym(gym)),
        client.delete(f"/api/staff/{uuid.uuid4()}", headers=as_gym(gym)),
    ):
        assert response.status_code == 404


def test_another_gyms_staff_is_not_found(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    theirs = invited(client, other)

    assert client.delete(f"/api/staff/{theirs}", headers=as_gym(gym)).status_code == 404
    assert ("Pedro", "coach") in staff_of(client, other)


def test_the_owner_is_never_changed_or_revoked(client: TestClient, gym: uuid.UUID) -> None:
    owner = seeded_owner(gym)
    admin = invited(client, gym, "admin")
    for by in (None, admin):
        headers = as_gym(gym, by)
        changed = client.patch(f"/api/staff/{owner}", json={"role": "admin"}, headers=headers)
        revoked = client.delete(f"/api/staff/{owner}", headers=headers)
        assert (changed.status_code, revoked.status_code) == (403, 403)
    assert staff_of(client, gym)[0][1] == "owner"


# --- who may ----------------------------------------------------------------------------


def test_an_admin_manages_coaches_and_not_admins(client: TestClient, gym: uuid.UUID) -> None:
    admin = invited(client, gym, "admin", name="Carla")
    other_admin = invited(client, gym, "admin", name="Daniel")

    coach = invite(client, gym, "coach", by=admin)
    assert coach.status_code == 201, coach.text
    coach_id = coach.json()["person_id"]
    headers = as_gym(gym, admin)

    assert invite(client, gym, "admin", by=admin).status_code == 403
    promote = client.patch(f"/api/staff/{coach_id}", json={"role": "admin"}, headers=headers)
    assert promote.status_code == 403
    demote = client.patch(f"/api/staff/{other_admin}", json={"role": "coach"}, headers=headers)
    assert demote.status_code == 403
    assert client.delete(f"/api/staff/{other_admin}", headers=headers).status_code == 403
    # Not even themselves: stepping down is the owner's call too.
    assert client.delete(f"/api/staff/{admin}", headers=headers).status_code == 403

    assert client.get("/api/staff", headers=headers).status_code == 200
    assert client.delete(f"/api/staff/{coach_id}", headers=headers).status_code == 204


def test_coaches_and_members_cannot_see_or_manage_the_staff(
    client: TestClient, gym: uuid.UUID
) -> None:
    coach = invited(client, gym)
    member = uuid.UUID(add_person(client, gym, "Ana"))
    for person in (coach, member):
        headers = as_gym(gym, person)
        assert client.get("/api/staff", headers=headers).status_code == 403
        assert invite(client, gym, by=person).status_code == 403
        assert client.delete(f"/api/staff/{coach}", headers=headers).status_code == 403
