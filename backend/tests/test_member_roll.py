"""Members in and out by hand (#157): add one, dar de baja, reactivar, eliminar.

Adding goes through the same doors as `POST /api/people` and the import: the phone is
the identity, so one another gym has is the same person, and a phone or RUT this gym
already has is refused naming who has it. Leaving ends every membership, so nothing
more is billed and the lists stop counting them, and keeps what they owe. Deleting is
for someone with no ledger here, and reaches only this gym's rows.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.domain.rut import format_rut
from app.jobs import billing
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_memberships import PLANS, add_staff
from tests.test_people import new_phone, new_rut
from tests.test_proofs import RecordingMailer

pg = pytest.mark.postgres


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
    """A gym of its own per test, so lists hold only what the test put there."""
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def plan(client: TestClient, gym: uuid.UUID, key: str = "signup") -> str:
    response = client.post("/api/plans", json=PLANS[key], headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def enrol(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None, **body: Any) -> Any:
    return client.post("/api/people/enrol", json=body, headers=as_gym(gym, by))


def enrolled(client: TestClient, gym: uuid.UUID, **body: Any) -> dict[str, Any]:
    # Someone is their RUT or an email (0034): a made-up RUT unless the body says who.
    key = {} if body.keys() & {"rut", "email", "guardian"} else {"rut": new_rut()}
    response = enrol(client, gym, **{"phone": new_phone(), "name": "Ana Soto", **key, **body})
    assert response.status_code == 201, response.text
    return dict(response.json())


def memberships(client: TestClient, gym: uuid.UUID, person: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/memberships?person_id={person}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return list(response.json())


def listed(client: TestClient, gym: uuid.UUID, left: str | None = None) -> list[str]:
    query = "" if left is None else f"?left={left}"
    response = client.get(f"/api/people{query}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return [row["name"] for row in response.json()["items"]]


def leave(client: TestClient, gym: uuid.UUID, person: str, **body: Any) -> Any:
    return client.post(f"/api/people/{person}/leave", json=body, headers=as_gym(gym))


def count(db: Database, gym: uuid.UUID, sql: str, *args: object) -> int:
    """`sql`'s count in `gym`, as the owner, whom RLS holds to it."""
    rows = run(db.owner_url, in_gym(gym, sql, *args))
    return int(rows[0][0])


# --- adding ----------------------------------------------------------------------


@pg
def test_a_member_added_without_a_plan(client: TestClient, gym: uuid.UUID) -> None:
    rut = new_rut()
    body = enrolled(
        client, gym, name="Camila Rojas", email="camila@example.com", rut=rut, dob="1994-03-12"
    )
    assert body["rut"] == rut
    assert body["left_on"] is None
    assert client.get(f"/api/people/{body['id']}", headers=as_gym(gym)).json() == body
    assert memberships(client, gym, body["id"]) == []
    assert "Camila Rojas" in listed(client, gym)


@pg
def test_a_member_added_on_a_plan_from_a_day(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    plan_id = plan(client, gym)
    started_on = (seeded_today() - timedelta(days=3)).isoformat()
    mailer.sent.clear()
    body = enrolled(
        client,
        gym,
        email="ana@example.com",
        membership={"plan_id": plan_id, "started_on": started_on},
    )
    [membership] = memberships(client, gym, body["id"])
    assert (membership["plan_id"], membership["status"]) == (plan_id, "active")
    assert membership["started_on"] == started_on
    # Off by default, like the import.
    assert mailer.sent == []


@pg
def test_the_welcome_is_sent_only_when_asked(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mailer.sent.clear()
    enrolled(
        client,
        gym,
        email="ana@example.com",
        membership={"plan_id": plan(client, gym)},
        send_welcome=True,
    )
    [email] = mailer.sent
    assert email.to == "ana@example.com"


@pg
def test_the_welcome_needs_a_plan(client: TestClient, gym: uuid.UUID) -> None:
    response = enrol(client, gym, phone=new_phone(), rut=new_rut(), name="Ana", send_welcome=True)
    assert response.status_code == 422


@pg
def test_a_rut_or_email_already_here_is_refused_naming_who(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    phone, rut = new_phone(), new_rut()
    first = enrolled(client, gym, phone=phone, rut=rut)
    by_email = enrolled(client, gym, email="sin.rut@example.com", name="Sin RUT")

    # A phone finds nobody: someone else may share it.
    assert enrol(client, gym, phone=phone, rut=new_rut(), name="Hermana").status_code == 201

    same_rut = enrol(client, gym, phone=new_phone(), name="Otra", rut=rut)
    assert same_rut.status_code == 409
    assert same_rut.json()["detail"] == {"code": "rut_in_gym", "person_id": first["id"]}
    same_email = enrol(client, gym, phone=new_phone(), name="Otra", email="SIN.RUT@example.com")
    assert same_email.status_code == 409
    assert same_email.json()["detail"] == {"code": "email_in_gym", "person_id": by_email["id"]}
    assert count(db, gym, "SELECT count(*) FROM gym_person WHERE name = 'Otra'") == 0


@pg
def test_a_rut_already_here_is_refused_on_an_edit_too(client: TestClient, gym: uuid.UUID) -> None:
    rut = new_rut()
    first = enrolled(client, gym, rut=rut)
    other = enrolled(client, gym, name="Otra")
    response = client.patch(f"/api/people/{other['id']}", json={"rut": rut}, headers=as_gym(gym))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "rut_in_gym", "person_id": first["id"]}
    # Their own RUT, sent again, is no conflict.
    own = client.patch(f"/api/people/{first['id']}", json={"rut": rut}, headers=as_gym(gym))
    assert own.status_code == 200


@pg
def test_a_rut_another_gym_has_is_the_same_person(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    rut = new_rut()
    theirs = enrolled(client, norte, rut=rut, name="Ana N.", email="ana@norte.cl")
    ours = enrolled(client, gym, rut=rut, name="Ana Soto")
    assert ours["id"] == theirs["id"]
    # Only what this gym typed.
    assert (ours["name"], ours["email"]) == ("Ana Soto", None)


@pg
def test_a_minor_needs_a_guardian(client: TestClient, gym: uuid.UUID) -> None:
    ten = (seeded_today() - timedelta(days=365 * 10)).isoformat()
    response = enrol(client, gym, phone=new_phone(), rut=new_rut(), name="Tomás", dob=ten)
    assert response.status_code == 422


@pg
def test_a_minor_with_a_new_guardian_and_no_phone(
    client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    ten = (seeded_today() - timedelta(days=365 * 10)).isoformat()
    mailer.sent.clear()
    body = enrolled(
        client,
        gym,
        phone=None,
        name="Tomás Vera",
        dob=ten,
        guardian={"phone": new_phone(), "name": "Marta Vera", "email": "marta@example.com"},
        membership={"plan_id": plan(client, gym)},
        send_welcome=True,
    )
    assert body["phone"] is None
    family = client.get(f"/api/people/{body['id']}/family", headers=as_gym(gym)).json()
    assert family["guardian"]["name"] == "Marta Vera"
    # The welcome goes to the one who pays.
    [email] = mailer.sent
    assert email.to == "marta@example.com"


@pg
def test_a_guardian_already_here_by_pick_or_by_rut(client: TestClient, gym: uuid.UUID) -> None:
    rut = new_rut()
    marta = enrolled(client, gym, rut=rut, name="Marta Vera")

    picked = enrolled(client, gym, phone=None, name="Tomás", guardian={"person_id": marta["id"]})
    typed = enrolled(
        client,
        gym,
        phone=None,
        name="Sofía",
        guardian={"rut": format_rut(rut), "phone": new_phone(), "name": "M. Vera"},
    )
    family = client.get(f"/api/people/{marta['id']}/family", headers=as_gym(gym)).json()
    assert {d["id"] for d in family["dependents"]} == {picked["id"], typed["id"]}
    # The guardian is as this gym has them, whatever name was typed.
    assert client.get(f"/api/people/{marta['id']}", headers=as_gym(gym)).json()["name"] == (
        "Marta Vera"
    )


@pg
def test_a_guardian_who_is_a_dependent_is_refused(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    marta = enrolled(client, gym, name="Marta")
    kid = enrolled(client, gym, name="Tomás", guardian={"person_id": marta["id"]})
    response = enrol(client, gym, phone=None, name="Sofía", guardian={"person_id": kid["id"]})
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "one_level"}
    assert count(db, gym, "SELECT count(*) FROM gym_person WHERE name = 'Sofía'") == 0


@pg
def test_a_member_needs_a_rut_or_an_email_or_a_guardian(client: TestClient, gym: uuid.UUID) -> None:
    assert enrol(client, gym, name="Nadie", phone=new_phone()).status_code == 422


# --- the phone a member needs (#165) ---------------------------------------------


@pg
def test_a_member_needs_a_phone_unless_they_have_no_whatsapp(
    client: TestClient, gym: uuid.UUID
) -> None:
    refused = enrol(client, gym, rut=new_rut(), name="Sin fono")
    assert refused.status_code == 422
    body = enrolled(client, gym, phone=None, name="Sin WhatsApp", no_whatsapp=True)
    assert (body["phone"], body["no_whatsapp"], body["missing_phone"]) == (None, True, False)


@pg
def test_a_minor_needs_their_guardians_phone_not_their_own(
    client: TestClient, gym: uuid.UUID
) -> None:
    ten = (seeded_today() - timedelta(days=365 * 10)).isoformat()
    guardian = {"name": "Marta", "email": f"marta.{uuid.uuid4().hex[:6]}@example.com"}
    refused = enrol(client, gym, name="Tomás", dob=ten, guardian=guardian)
    assert refused.status_code == 422
    sin_whatsapp = enrolled(
        client, gym, phone=None, name="Tomás", dob=ten, guardian={**guardian, "no_whatsapp": True}
    )
    family = client.get(f"/api/people/{sin_whatsapp['id']}/family", headers=as_gym(gym)).json()
    marta = client.get(f"/api/people/{family['guardian']['id']}", headers=as_gym(gym)).json()
    assert (marta["phone"], marta["no_whatsapp"]) == (None, True)
    # The kid is their guardian's to reach, so is never "Falta teléfono".
    assert (sin_whatsapp["phone"], sin_whatsapp["missing_phone"]) == (None, False)


@pg
def test_a_guardian_picked_with_no_phone_is_refused_or_given_one(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rut = new_rut()
    marta = enrolled(client, gym, rut=rut, name="Marta")
    # A record with no phone, as the migration leaves some: "Falta teléfono".
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_person SET phone = NULL WHERE person_id = $1", uuid.UUID(marta["id"])
        ),
    )

    picked = enrol(client, gym, phone=None, name="Tomás", guardian={"person_id": marta["id"]})
    assert picked.status_code == 422
    assert count(db, gym, "SELECT count(*) FROM gym_person WHERE name = 'Tomás'") == 0

    # Typed again with a phone, by their RUT: the phone fills in what this gym lacked.
    phone = new_phone()
    typed = enrolled(
        client, gym, phone=None, name="Tomás", guardian={"rut": rut, "name": "M.", "phone": phone}
    )
    assert typed["missing_phone"] is False
    assert client.get(f"/api/people/{marta['id']}", headers=as_gym(gym)).json()["phone"] == phone


@pg
def test_custom_fields_are_written_with_the_member_or_nothing_is(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    field = client.post(
        "/api/custom-fields", json={"label": "Talla", "type": "text"}, headers=as_gym(gym)
    ).json()
    body = enrolled(client, gym, fields={field["key"]: "M"})
    values = client.get(f"/api/people/{body['id']}/fields", headers=as_gym(gym)).json()
    assert [(v["key"], v["value"]) for v in values] == [(field["key"], "M")]

    refused = enrol(
        client, gym, phone=new_phone(), rut=new_rut(), name="Sin campo", fields={"nope": "x"}
    )
    assert refused.status_code == 422
    assert count(db, gym, "SELECT count(*) FROM gym_person WHERE name = 'Sin campo'") == 0


# --- leaving and coming back -----------------------------------------------------


def freeze(client: TestClient, gym: uuid.UUID, membership: str, days_from_now: int) -> None:
    today = seeded_today()
    body = {
        "from_date": (today + timedelta(days=days_from_now)).isoformat(),
        "to_date": (today + timedelta(days=days_from_now + 10)).isoformat(),
        "reason": "viaje",
    }
    response = client.post(f"/api/memberships/{membership}/freeze", json=body, headers=as_gym(gym))
    assert response.status_code == 200, response.text


@pg
@pytest.mark.parametrize("kind", ["signup", "trial", "frozen", "booked"])
def test_leaving_ends_every_live_membership(client: TestClient, gym: uuid.UUID, kind: str) -> None:
    body = enrolled(
        client, gym, membership={"plan_id": plan(client, gym, kind if kind in PLANS else "signup")}
    )
    [membership] = memberships(client, gym, body["id"])
    if kind == "frozen":
        freeze(client, gym, membership["id"], 0)
    elif kind == "booked":
        freeze(client, gym, membership["id"], 5)

    response = leave(client, gym, body["id"])
    assert response.status_code == 200, response.text
    assert response.json()["left_on"] == seeded_today().isoformat()
    [ended] = memberships(client, gym, body["id"])
    assert (ended["status"], ended["cancel_reason"]) == ("cancelled", "dado de baja")
    assert ended["freeze"] is None


@pg
def test_a_member_who_left_is_on_the_dados_de_baja_list_only(
    client: TestClient, gym: uuid.UUID
) -> None:
    body = enrolled(client, gym, name="Se Fue", membership={"plan_id": plan(client, gym)})
    leave(client, gym, body["id"])
    assert "Se Fue" not in listed(client, gym)
    assert listed(client, gym, "only") == ["Se Fue"]
    assert "Se Fue" in listed(client, gym, "any")


@pg
def test_leaving_stops_billing_and_the_roster_and_keeps_what_is_owed(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    today = seeded_today()
    started_on = (today - timedelta(days=20)).isoformat()
    body = enrolled(
        client,
        gym,
        name="Se Fue",
        membership={"plan_id": plan(client, gym), "started_on": started_on},
    )
    [membership] = memberships(client, gym, body["id"])

    async def bill(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, today)

    run(db.owner_url, bill)
    periods = "SELECT count(*) FROM billing_period WHERE membership_id = $1"
    billed = count(db, gym, periods, uuid.UUID(membership["id"]))
    assert billed > 0
    inactive = client.get("/api/inactive", headers=as_gym(gym)).json()
    assert body["id"] in {m["person_id"] for m in inactive}

    leave(client, gym, body["id"])

    # The next month is never billed, and what was billed is still owed.
    async def bill_later(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await billing.generate_billing_periods(conn, today + timedelta(days=40))

    run(db.owner_url, bill_later)
    assert count(db, gym, periods, uuid.UUID(membership["id"])) == billed
    ledger = client.get(f"/api/ledger/memberships/{membership['id']}", headers=as_gym(gym))
    assert ledger.status_code == 200, ledger.text
    assert ledger.json()["open_periods"] != []

    inactive = client.get("/api/inactive", headers=as_gym(gym)).json()
    assert body["id"] not in {m["person_id"] for m in inactive}
    program = client.post("/api/programs", json={"name": "Adultos"}, headers=as_gym(gym)).json()
    class_type = client.post(
        "/api/class-types",
        json={"name": "Fundamentos", "program_id": program["id"], "credit_cost": 1},
        headers=as_gym(gym),
    ).json()
    session = client.post(
        "/api/sessions", json={"class_type_id": class_type["id"]}, headers=as_gym(gym)
    ).json()
    roster = client.get(f"/api/sessions/{session['id']}/roster", headers=as_gym(gym)).json()
    assert body["id"] not in {m["person_id"] for m in roster["members"]}


@pg
def test_leaving_takes_a_past_day_but_not_a_later_one(client: TestClient, gym: uuid.UUID) -> None:
    today = seeded_today()
    later = enrolled(client, gym)
    tomorrow = (today + timedelta(days=1)).isoformat()
    assert leave(client, gym, later["id"], left_on=tomorrow).status_code == 422

    past = (today - timedelta(days=10)).isoformat()
    response = leave(client, gym, later["id"], left_on=past)
    assert response.status_code == 200
    assert response.json()["left_on"] == past
    assert leave(client, gym, later["id"]).status_code == 409


@pg
def test_reactivating_brings_them_back_on_a_plan_if_given(
    client: TestClient, gym: uuid.UUID
) -> None:
    plan_id = plan(client, gym)
    body = enrolled(client, gym, name="Vuelve", membership={"plan_id": plan_id})
    not_left = client.post(f"/api/people/{body['id']}/return", json={}, headers=as_gym(gym))
    assert not_left.status_code == 409

    leave(client, gym, body["id"])
    response = client.post(
        f"/api/people/{body['id']}/return",
        json={"membership": {"plan_id": plan_id}},
        headers=as_gym(gym),
    )
    assert response.status_code == 200, response.text
    assert response.json()["left_on"] is None
    assert "Vuelve" in listed(client, gym)
    statuses = [m["status"] for m in memberships(client, gym, body["id"])]
    assert sorted(statuses) == ["active", "cancelled"]


# --- deleting --------------------------------------------------------------------


def forget(client: TestClient, gym: uuid.UUID, person: str, by: uuid.UUID | None = None) -> Any:
    return client.delete(f"/api/people/{person}", headers=as_gym(gym, by))


@pg
def test_deleting_someone_with_no_ledger_takes_every_record_here(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    marta = enrolled(client, gym, name="Marta")
    # A trial writes no ledger entry: a membership, an attendance and a field, no money.
    kid = enrolled(
        client,
        gym,
        phone=None,
        name="Tomás",
        guardian={"person_id": marta["id"]},
        membership={"plan_id": plan(client, gym, "trial")},
    )
    field = client.post(
        "/api/custom-fields", json={"label": "Talla", "type": "text"}, headers=as_gym(gym)
    ).json()
    client.patch(
        f"/api/people/{kid['id']}/fields", json={"values": {field["key"]: "S"}}, headers=as_gym(gym)
    )
    person = uuid.UUID(kid["id"])

    asked = client.get(f"/api/people/{kid['id']}/deletion", headers=as_gym(gym))
    assert asked.json() == {"refused": None}
    assert forget(client, gym, kid["id"]).status_code == 204
    assert client.get(f"/api/people/{kid['id']}", headers=as_gym(gym)).status_code == 404
    for table, column in [
        ("gym_person", "person_id"),
        ("membership", "person_id"),
        ("guardian_link", "dependent_person_id"),
        ("person_field_value", "person_id"),
    ]:
        assert count(db, gym, f"SELECT count(*) FROM {table} WHERE {column} = $1", person) == 0
    assert forget(client, gym, kid["id"]).status_code == 404


@pg
def test_deleting_is_refused_with_a_ledger_or_staff_or_dependents(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    paying = enrolled(client, gym, membership={"plan_id": plan(client, gym)})
    [membership] = memberships(client, gym, paying["id"])

    async def charge(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            period = await conn.fetchval(
                "INSERT INTO billing_period"
                " (gym_id, membership_id, period_start, period_end, amount_due_clp, due_date)"
                " VALUES ($1, $2, $3, $3, 45000, $3) RETURNING id",
                gym,
                uuid.UUID(membership["id"]),
                seeded_today(),
            )
            await conn.execute(
                "INSERT INTO ledger_entry"
                " (gym_id, membership_id, billing_period_id, amount_clp, kind)"
                " VALUES ($1, $2, $3, 45000, 'charge')",
                gym,
                uuid.UUID(membership["id"]),
                period,
            )

    run(db.owner_url, charge)
    response = forget(client, gym, paying["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "ledger"}
    asked = client.get(f"/api/people/{paying['id']}/deletion", headers=as_gym(gym))
    assert asked.json() == {"refused": "ledger"}
    assert client.get(f"/api/people/{paying['id']}", headers=as_gym(gym)).status_code == 200

    coach = add_staff(db, gym, "coach")
    assert forget(client, gym, str(coach)).json()["detail"] == {"code": "staff"}

    marta = enrolled(client, gym, name="Marta")
    enrolled(client, gym, phone=None, name="Tomás", guardian={"person_id": marta["id"]})
    assert forget(client, gym, marta["id"]).json()["detail"] == {"code": "guardian"}


@pg
def test_deleting_reaches_only_this_gyms_records(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:8]}")
    rut = new_rut()
    theirs = enrolled(client, norte, rut=rut, name="Ana N.")
    enrolled(client, gym, rut=rut, name="Ana Soto")

    # Another gym's owner cannot reach this gym's record of someone it does not know.
    stranger = enrolled(client, gym, name="Solo Sur")
    assert forget(client, norte, stranger["id"]).status_code == 404

    assert forget(client, gym, theirs["id"]).status_code == 204
    assert client.get(f"/api/people/{theirs['id']}", headers=as_gym(norte)).json() == theirs
    # The identity stays: the other gym still has them.
    rows = run(db.admin_url, lambda c: c.fetch("SELECT id FROM person WHERE rut = $1", rut))
    assert [str(r["id"]) for r in rows] == [theirs["id"]]


@pg
def test_the_app_role_cannot_delete_records_itself(db: Database, gym: uuid.UUID) -> None:
    async def delete(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("DELETE FROM gym_person")

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(db.api_url, delete)


# --- who may --------------------------------------------------------------------


@pg
def test_coaches_may_do_none_of_it_and_admins_may_not_delete(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    body = enrolled(client, gym)
    coach = add_staff(db, gym, "coach")
    admin = add_staff(db, gym, "admin")
    headers = as_gym(gym, coach)
    assert enrol(client, gym, coach, rut=new_rut(), phone=new_phone(), name="X").status_code == 403
    assert (
        client.post(f"/api/people/{body['id']}/leave", json={}, headers=headers).status_code == 403
    )
    assert (
        client.post(f"/api/people/{body['id']}/return", json={}, headers=headers).status_code == 403
    )
    assert forget(client, gym, body["id"], coach).status_code == 403
    assert forget(client, gym, body["id"], admin).status_code == 403
    deletion = f"/api/people/{body['id']}/deletion"
    assert client.get(deletion, headers=as_gym(gym, admin)).status_code == 403

    assert enrol(client, gym, admin, rut=new_rut(), phone=new_phone(), name="Y").status_code == 201
    left = client.post(f"/api/people/{body['id']}/leave", json={}, headers=as_gym(gym, admin))
    assert left.status_code == 200


# --- no new membership while they are away -------------------------------------


@pg
def test_no_path_starts_a_membership_for_someone_who_left(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rut = new_rut()
    body = enrolled(client, gym, rut=rut, name="Se Fue")
    leave(client, gym, body["id"])

    # Starting one by hand.
    started = client.post(
        "/api/memberships",
        json={"person_id": body["id"], "plan_id": plan(client, gym)},
        headers=as_gym(gym),
    )
    assert started.status_code == 409
    assert started.json()["detail"] == {"code": "has_left"}

    # A trial at a class: the coach is pointed at Reactivar.
    program = client.post("/api/programs", json={"name": "Adultos"}, headers=as_gym(gym)).json()
    class_type = client.post(
        "/api/class-types",
        json={"name": "Fundamentos", "program_id": program["id"], "credit_cost": 1},
        headers=as_gym(gym),
    ).json()
    session = client.post(
        "/api/sessions", json={"class_type_id": class_type["id"]}, headers=as_gym(gym)
    ).json()
    trial = client.post(
        f"/api/sessions/{session['id']}/trials",
        json={"person_id": body["id"], "plan_id": plan(client, gym, "trial")},
        headers=as_gym(gym),
    )
    assert trial.status_code == 409
    assert trial.json()["detail"] == {"code": "has_left"}

    # A sheet that still lists them: that row is refused, the others import.
    due = (seeded_today() + timedelta(days=10)).isoformat()
    rows = [
        {"number": 2, "cells": ["Se Fue", rut, "Mensual", due]},
        {"number": 3, "cells": ["Llega", new_rut(), "Mensual", due]},
    ]
    report = client.post(
        "/api/import/members",
        json={
            "rows": rows,
            "mapping": {"name": 0, "rut": 1, "plan": 2, "due_on": 3},
            "dry_run": False,
        },
        headers=as_gym(gym),
    )
    assert report.status_code == 200, report.text
    first, second = report.json()["rows"]
    assert first["errors"] == [{"field": "plan", "code": "has_left"}]
    assert second["errors"] == [] and second["membership"] == "created"

    assert [m["status"] for m in memberships(client, gym, body["id"])] == []
    # Reactivated, they start one again.
    back = client.post(
        f"/api/people/{body['id']}/return",
        json={"membership": {"plan_id": plan(client, gym)}},
        headers=as_gym(gym),
    )
    assert back.status_code == 200, back.text
