"""Payment reminders by WhatsApp from the admin's lists (#55).

Which periods are listed, which of the three messages each gets (due today, overdue,
the follow-up to a rejected proof), the count of reminders so far and the cadence
between them, the `wa.me` link to them or their guardian, and the reminder recorded in
`message_log` as it is opened.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.notices.whatsapp import payment_due_today, payment_overdue, proof_rejected_followup
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import add_staff

# --- the messages, no database ----------------------------------------------------


def test_the_due_today_reminder_says_what_and_how_much() -> None:
    text = payment_due_today(
        to_name="Ignacio Vera",
        about_name=None,
        gym_name="Academia Sur",
        plan_name="Mensual",
        outstanding_clp=45000,
    )
    assert text == (
        "Hola Ignacio, te recordamos que hoy vence tu pago de Mensual en Academia Sur:"
        " $45.000. Si ya pagaste, envíanos el comprobante. ¡Gracias!"
    )


def test_the_overdue_reminder_says_since_when() -> None:
    text = payment_overdue(
        to_name="Ana Rojas",
        about_name="Tomás Rojas",
        gym_name="Academia Sur",
        plan_name="Kids",
        outstanding_clp=30000,
        due_date=date(2026, 11, 5),
    )
    assert text == (
        "Hola Ana, el pago de Tomás de Kids en Academia Sur venció el 05-11-2026 y quedan"
        " $30.000 por pagar. ¿Nos ayudas a ponerte al día? Si ya pagaste, envíanos el"
        " comprobante. ¡Gracias!"
    )


def test_the_rejection_follow_up_carries_the_note() -> None:
    text = proof_rejected_followup(
        to_name="Ignacio Vera",
        about_name=None,
        gym_name="Academia Sur",
        plan_name="Mensual",
        amount_clp=40000,
        note=" falta $5.000 ",
    )
    assert text == (
        "Hola Ignacio, en Academia Sur revisamos el comprobante de $40.000 por Mensual y"
        " no pudimos validarlo: falta $5.000. ¿Nos envías uno nuevo? ¡Gracias!"
    )


# --- against real Postgres --------------------------------------------------------

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
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def listed(client: TestClient, gym: uuid.UUID, person: str | None = None) -> Any:
    query = "" if person is None else f"?person_id={person}"
    response = client.get(f"/api/reminders{query}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    # The seed bills its owner a period already overdue; these tests are about others.
    owner = str(seeded_owner(gym))
    return [r for r in response.json() if r["person_id"] != owner]


def remind(client: TestClient, gym: uuid.UUID, period: str, **kw: Any) -> Any:
    return client.post(f"/api/reminders/{period}", headers=as_gym(gym, **kw))


def text_of(row: Any) -> str:
    return str(parse_qs(urlsplit(row["whatsapp_url"]).query)["text"][0])


def phone_of(db: Database, person: str) -> str:
    rows = run(
        db.admin_url,
        lambda c: c.fetch("SELECT phone FROM gym_person WHERE person_id = $1", uuid.UUID(person)),
    )
    return str(rows[0]["phone"])


def logged(db: Database, gym: uuid.UUID) -> list[Any]:
    return list(
        run(
            db.api_url,
            in_gym(
                gym,
                "SELECT person_id, template, to_address, status, payload"
                " FROM message_log WHERE channel = 'whatsapp' ORDER BY sent_at",
            ),
        )
    )


def backdate_reminders(db: Database, gym: uuid.UUID, days: int) -> None:
    """Every reminder logged so far, `days` earlier."""
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE message_log SET sent_at = sent_at - make_interval(days => $1)"
            " WHERE gym_id = $2",
            days,
            gym,
        ),
    )


def proof_sent(db: Database, gym: uuid.UUID, membership: str, amount: int) -> str:
    """A pending transfer with a proof against the membership's period."""

    async def query(conn: Any) -> Any:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            return await conn.fetchval(
                "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id,"
                " amount_clp, kind, status, method, proof_object_key)"
                " SELECT gym_id, membership_id, id, $2, 'payment', 'pending', 'transfer', $3"
                " FROM billing_period WHERE membership_id = $1 RETURNING id",
                uuid.UUID(membership),
                amount,
                f"proofs/{uuid.uuid4()}.png",
            )

    return str(run(db.owner_url, query))


def rejected_entry(db: Database, membership: str) -> str:
    return str(
        run(
            db.admin_url,
            lambda c: c.fetchval(
                "SELECT id FROM ledger_entry WHERE membership_id = $1 AND status = 'rejected'",
                uuid.UUID(membership),
            ),
        )
    )


def rejected(
    client: TestClient, db: Database, gym: uuid.UUID, membership: str, amount: int, note: str
) -> None:
    entry = proof_sent(db, gym, membership, amount)
    response = client.post(
        f"/api/ledger/proofs/{entry}/reject", json={"note": note}, headers=as_gym(gym)
    )
    assert response.status_code == 200, response.text


@pg
def test_periods_due_today_or_overdue_longest_first(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    bill(db, gym, add_person(client, gym, "Hoy Vence"), [(0, 30000, 0, 0)])
    bill(db, gym, add_person(client, gym, "Muy Atrasado"), [(-20, 45000, 5000, 0)])
    bill(db, gym, add_person(client, gym, "Poco Atrasado"), [(-2, 30000, 0, 0)])
    bill(db, gym, add_person(client, gym, "Aún No"), [(3, 30000, 0, 0)])
    bill(db, gym, add_person(client, gym, "Al Día"), [(-5, 30000, 30000, 0)])
    # A proof waiting for review: the admin reviews it, rather than reminding them.
    bill(db, gym, add_person(client, gym, "Ya Envió"), [(-5, 30000, 0, 30000)])

    rows = listed(client, gym)

    assert [
        (r["person_name"], r["kind"], r["days_overdue"], r["outstanding_clp"]) for r in rows
    ] == [
        ("Muy Atrasado", "payment_overdue", 20, 40000),
        ("Poco Atrasado", "payment_overdue", 2, 30000),
        ("Hoy Vence", "payment_due_today", 0, 30000),
    ]
    assert all(r["reminders_sent"] == 0 and r["reminder_due"] for r in rows)


@pg
def test_the_link_opens_whatsapp_on_them_with_the_reminder(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    bill(db, gym, ignacio, [(0, 30000, 0, 0)])

    [row] = listed(client, gym)

    url = urlsplit(row["whatsapp_url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "wa.me", f"/{phone_of(db, ignacio)[1:]}")
    gym_name = run(db.admin_url, lambda c: c.fetchval("SELECT name FROM gym WHERE id = $1", gym))
    assert text_of(row) == payment_due_today(
        to_name="Ignacio Vera",
        about_name=None,
        gym_name=gym_name,
        plan_name="Mensual",
        outstanding_clp=30000,
    )
    assert row["contact_name"] == "Ignacio Vera"


@pg
def test_a_dependent_is_reminded_through_their_guardian(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = add_person(client, gym, "Ana Rojas")
    tomas = new_kid(client, gym, ana, "Tomás Rojas")
    bill(db, gym, tomas, [(-4, 30000, 0, 0)])

    [row] = listed(client, gym)

    assert (row["person_name"], row["contact_name"]) == ("Tomás Rojas", "Ana Rojas")
    assert urlsplit(row["whatsapp_url"]).path == f"/{phone_of(db, ana)[1:]}"
    assert "el pago de Tomás de Mensual" in text_of(row)

    assert remind(client, gym, row["billing_period_id"]).status_code == 201
    [log] = logged(db, gym)
    assert (str(log["person_id"]), log["to_address"]) == (ana, phone_of(db, ana))
    assert json.loads(log["payload"])["about"] == tomas


@pg
def test_opening_a_reminder_records_it_and_counts_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    bill(db, gym, ignacio, [(-6, 30000, 0, 0)])
    [row] = listed(client, gym)

    response = remind(client, gym, row["billing_period_id"])

    assert response.status_code == 201, response.text
    assert (response.json()["kind"], response.json()["ordinal"]) == ("payment_overdue", 1)
    [log] = logged(db, gym)
    assert (str(log["person_id"]), log["template"], log["status"]) == (
        ignacio,
        "payment_overdue",
        "sent",
    )
    assert log["to_address"] == phone_of(db, ignacio)
    assert json.loads(log["payload"]) == {
        "about": ignacio,
        "billing_period_id": row["billing_period_id"],
        "ordinal": 1,
        "outstanding_clp": 30000,
        "days_overdue": 6,
    }
    [after] = listed(client, gym)
    assert (after["reminders_sent"], after["reminded_at"]) == (1, response.json()["sent_at"])
    assert after["reminder_due"] is False

    assert remind(client, gym, row["billing_period_id"]).json()["ordinal"] == 2


@pg
def test_the_next_reminder_is_due_every_few_days_as_the_gym_says(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    bill(db, gym, add_person(client, gym, "Ignacio Vera"), [(-6, 30000, 0, 0)])
    period = listed(client, gym)[0]["billing_period_id"]
    remind(client, gym, period)

    backdate_reminders(db, gym, 2)
    assert listed(client, gym)[0]["reminder_due"] is False
    backdate_reminders(db, gym, 1)
    assert listed(client, gym)[0]["reminder_due"] is True

    every = {"reminder_every_days": 5}
    assert client.patch("/api/gym/settings", json=every, headers=as_gym(gym)).status_code == 200
    assert listed(client, gym)[0]["reminder_due"] is False


@pg
def test_a_rejected_proof_is_followed_up_with_the_note_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    # Not due for another ten days, but the proof sent early was rejected.
    membership = bill(db, gym, ignacio, [(10, 30000, 0, 0)])
    assert listed(client, gym) == []
    rejected(client, db, gym, membership, 25000, "falta $5.000")

    [row] = listed(client, gym, ignacio)

    assert (row["kind"], row["rejection_note"], row["reminder_due"]) == (
        "proof_rejected_followup",
        "falta $5.000",
        True,
    )
    assert "comprobante de $25.000 por Mensual y no pudimos validarlo: falta $5.000." in text_of(
        row
    )
    response = remind(client, gym, row["billing_period_id"])
    assert response.json()["kind"] == "proof_rejected_followup"
    [log] = logged(db, gym)
    assert json.loads(log["payload"])["rejected_entry_id"] == rejected_entry(db, membership)
    # Followed up, and not due yet: nothing more to send.
    assert listed(client, gym) == []


@pg
def test_an_overdue_period_goes_back_to_overdue_reminders_after_the_follow_up(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    membership = bill(db, gym, add_person(client, gym, "Ignacio Vera"), [(-4, 30000, 0, 0)])
    rejected(client, db, gym, membership, 30000, "No se ve el monto")
    period = listed(client, gym)[0]["billing_period_id"]

    assert remind(client, gym, period).json()["kind"] == "proof_rejected_followup"

    [row] = listed(client, gym)
    assert (row["kind"], row["reminders_sent"], row["rejection_note"]) == (
        "payment_overdue",
        1,
        None,
    )
    assert remind(client, gym, period).json()["ordinal"] == 2


@pg
def test_the_ficha_reads_only_its_members_reminders(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    bill(db, gym, ignacio, [(-1, 30000, 0, 0)])
    bill(db, gym, add_person(client, gym, "Otra Persona"), [(-1, 30000, 0, 0)])

    assert [r["person_name"] for r in listed(client, gym, ignacio)] == ["Ignacio Vera"]


@pg
def test_with_whatsapp_off_there_is_no_link_and_no_reminder(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    bill(db, gym, add_person(client, gym, "Ignacio Vera"), [(-1, 30000, 0, 0)])
    off = {"channels": {"whatsapp": False}}
    assert client.patch("/api/gym/settings", json=off, headers=as_gym(gym)).status_code == 200

    [row] = listed(client, gym)
    assert row["whatsapp_url"] is None
    assert remind(client, gym, row["billing_period_id"]).status_code == 409


@pg
def test_someone_marked_sin_whatsapp_has_no_link(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    bill(db, gym, ignacio, [(-1, 30000, 0, 0)])
    marked = client.patch(f"/api/people/{ignacio}", json={"no_whatsapp": True}, headers=as_gym(gym))
    assert marked.status_code == 200, marked.text

    [row] = listed(client, gym)
    assert row["whatsapp_url"] is None
    assert remind(client, gym, row["billing_period_id"]).status_code == 409


@pg
def test_only_a_period_on_the_list_is_reminded(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    membership = bill(db, gym, add_person(client, gym, "Aún No"), [(3, 30000, 0, 0)])
    period = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT id FROM billing_period WHERE membership_id = $1", uuid.UUID(membership)
        ),
    )

    assert remind(client, gym, str(period)).status_code == 404
    assert remind(client, gym, str(uuid.uuid4())).status_code == 404


@pg
def test_another_gyms_periods_are_not_listed_or_reminded(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, f"norte-{uuid.uuid4().hex[:6]}")
    bill(db, norte, add_person(client, norte, "Bea Soto"), [(-1, 30000, 0, 0)])
    [theirs] = listed(client, norte)

    assert listed(client, gym) == []
    assert remind(client, gym, theirs["billing_period_id"]).status_code == 404


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_owner_and_admin_read_it(
    client: TestClient, db: Database, gym: uuid.UUID, role: str
) -> None:
    person = seeded_owner(gym) if role == "owner" else add_staff(db, gym, role)

    assert client.get("/api/reminders", headers=as_gym(gym, person_id=person)).status_code == 200


@pg
def test_a_coach_neither_reads_it_nor_reminds(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    bill(db, gym, add_person(client, gym, "Ignacio Vera"), [(-1, 30000, 0, 0)])
    period = listed(client, gym)[0]["billing_period_id"]
    coach = add_staff(db, gym, "coach")

    assert client.get("/api/reminders", headers=as_gym(gym, person_id=coach)).status_code == 403
    assert remind(client, gym, period, person_id=coach).status_code == 403
