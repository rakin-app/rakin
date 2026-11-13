"""Overdue payment emails (#260): the nightly `overdue` job and "Enviar recordatorio".

A period still owed is emailed on its due date, the day after, then every 3 days while
the gym's grace lasts, and never twice in one day; nothing goes once it is paid or its
membership is cancelled, frozen or lapsed. The same email goes out by hand from the
reminders' `POST .../email`, for owner and admin.
"""

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.auth import build_notices
from app.db import create_engine, create_sessionmaker
from app.db_bootstrap import to_dsn
from app.jobs import lapse, overdue
from app.main import create_app
from app.notices import PAYMENT_OVERDUE, Notice, render
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_today, throwaway_database
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer
from tests.test_statements_job import BANK, Outbox, address, billed, pay, period_id

DUE = date(2026, 11, 15)

GYM = uuid.UUID("00000000-0000-4000-8000-000000000001")
PERSON = uuid.UUID("00000000-0000-4000-8000-000000000002")


def notice(days_overdue: int, **context: Any) -> Notice:
    return Notice(
        PAYMENT_OVERDUE,
        "ana@example.cl",
        PERSON,
        GYM,
        {
            "name": "Ana",
            "gym": "Academia Sur",
            "plan_name": "Mensual",
            "billing_period_id": uuid.uuid4(),
            "period_start": DUE,
            "period_end": DUE + timedelta(days=29),
            "due_date": DUE,
            "amount_clp": 45_000,
            "days_overdue": days_overdue,
            "bank_account": BANK,
            "dependent_name": None,
            "on": DUE + timedelta(days=days_overdue),
            **context,
        },
    )


# --- the email, no database -------------------------------------------------------


def test_the_email_says_how_much_for_which_period_and_how_late() -> None:
    email = render(notice(4), page_url="https://sur.rakin.test/ingresar")

    assert email.subject == "Tu pago de $45.000 en Academia Sur está atrasado"
    assert email.text.startswith("Hola, Ana:\n\n")
    assert (
        "El pago de $45.000 en Academia Sur venció el 15-11-2026 y lleva 4 días de atraso:"
        " plan Mensual, período del 15-11-2026 al 14-12-2026." in email.text
    )
    assert "Transfiere a esta cuenta y sube el comprobante desde tu página." in email.text
    assert "Número: 12345678" in email.text
    assert "Tu página: https://sur.rakin.test/ingresar" in email.text
    assert email.html is not None
    assert "<strong>4 días de atraso</strong>" in email.html
    # Essential: about money owed, so no unsubscribe.
    assert PAYMENT_OVERDUE.essential
    assert "List-Unsubscribe" not in dict(email.headers)


def test_on_the_due_date_it_says_today() -> None:
    email = render(notice(0))

    assert email.subject == "Hoy vence tu pago de $45.000 en Academia Sur"
    assert "Hoy vence el pago de $45.000 en Academia Sur: plan Mensual" in email.text
    assert "atraso" not in email.text


def test_one_day_late_is_singular_and_a_dependent_is_named() -> None:
    email = render(notice(1, dependent_name="Tomás", bank_account=None))

    assert "El pago de $45.000 de Tomás en Academia Sur venció el 15-11-2026" in email.text
    assert "lleva 1 día de atraso" in email.text
    assert "donde están los datos de la cuenta" in email.text


# --- the nightly job --------------------------------------------------------------

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def jobgym(db: Database) -> Gym:
    return Gym(db)


def night(db: Database, day: date, outbox: Outbox) -> None:
    """Run `lapse` then `overdue` for `day`, as the runner does, each in its own
    transaction."""

    async def go() -> None:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            notices = build_notices(db.settings, outbox, lambda: sessionmaker)
            conn = await asyncpg.connect(to_dsn(db.owner_url))
            try:
                async with conn.transaction():
                    assert await lapse.JOB.run(conn, day) is not False
                async with conn.transaction():
                    assert await overdue.job(notices).run(conn, day)
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    asyncio.run(go())


def grace(gym: Gym, days: int) -> None:
    gym.sql(
        "UPDATE gym SET settings = settings || jsonb_build_object('grace_days', $2::int)"
        " WHERE id = $1",
        gym.id,
        days,
    )


def status(gym: Gym, membership: uuid.UUID) -> str:
    [row] = gym.sql("SELECT status FROM membership WHERE id = $1", membership)
    return str(row["status"])


def emailed(gym: Gym) -> list[tuple[str, str, str]]:
    rows = gym.sql(
        "SELECT payload ->> 'on', payload ->> 'days_overdue', status FROM message_log"
        " WHERE gym_id = $1 AND channel = 'email' AND template = 'payment_overdue'"
        " ORDER BY sent_at",
        gym.id,
    )
    return [tuple(r) for r in rows]


@pg
def test_a_month_unpaid_is_emailed_on_the_due_date_then_until_the_lapse(jobgym: Gym) -> None:
    to = address(jobgym)
    grace(jobgym, 15)
    membership = billed(jobgym, DUE)
    outbox = Outbox()

    statuses = {}
    for offset in range(-5, 25):
        day = DUE + timedelta(days=offset)
        night(jobgym.db, day, outbox)
        statuses[offset] = status(jobgym, membership)

    days = [int(d) for _, d, _ in emailed(jobgym)]
    assert days == [0, 1, 4, 7, 10, 13]
    assert len(outbox.to(to)) == 6
    # Active through the 15 days of grace, lapsed on the first day past it.
    assert statuses[15] == "active"
    assert statuses[16] == "lapsed"


@pg
def test_the_schedule_follows_the_gyms_grace(jobgym: Gym) -> None:
    address(jobgym)
    billed(jobgym, DUE)  # the default grace, 5 days

    for offset in range(0, 12):
        night(jobgym.db, DUE + timedelta(days=offset), Outbox())

    assert [int(d) for _, d, _ in emailed(jobgym)] == [0, 1, 4]


@pg
def test_never_twice_in_one_day(jobgym: Gym) -> None:
    to = address(jobgym)
    billed(jobgym, DUE)
    outbox = Outbox()

    for _ in range(3):
        night(jobgym.db, DUE, outbox)

    assert len(outbox.to(to)) == 1


@pg
def test_the_email_asks_for_what_is_still_owed(jobgym: Gym) -> None:
    to = address(jobgym)
    jobgym.sql(
        "UPDATE gym SET settings = settings || jsonb_build_object('bank_account', $2::jsonb)"
        " WHERE id = $1",
        jobgym.id,
        json.dumps(BANK),
    )
    membership = billed(jobgym, DUE)
    pay(jobgym, membership, DUE, 15_000, "validated")
    outbox = Outbox()

    night(jobgym.db, DUE + timedelta(days=4), outbox)

    [email] = outbox.to(to)
    assert "El pago de $30.000 en" in email.text
    assert "lleva 4 días de atraso" in email.text
    assert "Número: 12345678" in email.text
    [url] = [line for line in email.text.splitlines() if line.startswith("Tu página: ")]
    assert "/api/auth/callback?token=" in url and url.endswith("&next=%2Fme")
    [(on, _, sent)] = emailed(jobgym)
    assert (on, sent) == (str(DUE + timedelta(days=4)), "sent")
    [row] = jobgym.sql(
        "SELECT payload ->> 'billing_period_id' AS period FROM message_log WHERE gym_id = $1",
        jobgym.id,
    )
    assert row["period"] == period_id(jobgym, membership, DUE)


@pg
@pytest.mark.parametrize("why", ["paid", "cancelled", "frozen", "lapsed", "proof"])
def test_nothing_goes_once_paid_cancelled_frozen_lapsed_or_with_a_proof(
    jobgym: Gym, why: str
) -> None:
    to = address(jobgym)
    member_status = why if why in ("cancelled", "frozen", "lapsed") else "active"
    membership = billed(jobgym, DUE, status=member_status)
    if why == "paid":
        pay(jobgym, membership, DUE, 45_000, "validated")
    if why == "proof":
        pay(jobgym, membership, DUE, 45_000, "pending")
    outbox = Outbox()

    for offset in (0, 1, 4):
        night(jobgym.db, DUE + timedelta(days=offset), outbox)

    assert outbox.to(to) == []
    assert emailed(jobgym) == []


@pg
def test_paying_stops_the_emails(jobgym: Gym) -> None:
    to = address(jobgym)
    membership = billed(jobgym, DUE)
    outbox = Outbox()

    night(jobgym.db, DUE, outbox)
    pay(jobgym, membership, DUE, 45_000, "validated")
    night(jobgym.db, DUE + timedelta(days=1), outbox)

    assert len(outbox.to(to)) == 1


@pg
def test_a_minors_email_goes_to_the_guardian(jobgym: Gym) -> None:
    marta = uuid.uuid4()
    to = f"marta-{jobgym.id.hex[:8]}@example.cl"
    jobgym.sql("INSERT INTO person (id, name) VALUES ($1, 'Marta')", marta)
    jobgym.sql(
        "INSERT INTO gym_person (gym_id, person_id, name, email) VALUES ($1, $2, 'Marta', $3)",
        jobgym.id,
        marta,
        to,
    )
    jobgym.sql(
        "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
        " VALUES ($1, $2, $3)",
        jobgym.id,
        marta,
        jobgym.person,
    )
    billed(jobgym, DUE)
    outbox = Outbox()

    night(jobgym.db, DUE + timedelta(days=1), outbox)

    [email] = outbox.to(to)
    assert "Hola, Marta:" in email.text
    assert "$45.000 de Ana en" in email.text
    [row] = jobgym.sql("SELECT person_id FROM message_log WHERE gym_id = $1", jobgym.id)
    assert row["person_id"] == marta


@pg
def test_an_unsubscribe_does_not_stop_it(jobgym: Gym) -> None:
    to = address(jobgym)
    jobgym.sql(
        "INSERT INTO mail_unsubscribe (gym_id, person_id) VALUES ($1, $2)",
        jobgym.id,
        jobgym.person,
    )
    billed(jobgym, DUE)
    outbox = Outbox()

    night(jobgym.db, DUE, outbox)

    assert len(outbox.to(to)) == 1


# --- "Enviar recordatorio" --------------------------------------------------------


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
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def reminder_of(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    response = client.get(f"/api/reminders?person_id={person}", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    [row] = response.json()
    return row


def send(client: TestClient, gym: uuid.UUID, period: str, **headers: Any) -> Any:
    return client.post(f"/api/reminders/{period}/email", headers={**as_gym(gym), **headers})


def to_of(mailer: RecordingMailer, address: str) -> list[Any]:
    return [e for e in mailer.sent if e.to == address]


def email_rows(db: Database, gym: uuid.UUID) -> list[Any]:
    return list(
        run(
            db.api_url,
            in_gym(
                gym,
                "SELECT person_id, channel, payload FROM message_log"
                " WHERE template = 'payment_overdue' ORDER BY sent_at",
            ),
        )
    )


@pg
def test_the_button_sends_the_email_now_and_says_when(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    ignacio = add_person(client, gym, "Ignacio Vera")
    bill(db, gym, ignacio, [(-2, 30000, 0, 0)])
    row = reminder_of(client, gym, ignacio)
    assert (row["can_email"], row["emailed_at"], row["emailed_today"]) == (True, None, False)

    response = send(client, gym, row["billing_period_id"])

    assert response.status_code == 201, response.text
    assert response.json()["contact_name"] == "Ignacio Vera"
    [email] = to_of(mailer, "ignacio.vera@example.cl")
    assert "lleva 2 días de atraso" in email.text
    after = reminder_of(client, gym, ignacio)
    assert after["emailed_at"] is not None and after["emailed_today"]
    # The email is not a WhatsApp reminder: it moves neither its count nor its cadence.
    assert (after["reminders_sent"], after["reminder_due"]) == (0, True)
    [log] = email_rows(db, gym)
    assert log["channel"] == "email"
    assert json.loads(log["payload"])["on"] == str(seeded_today())


@pg
def test_once_a_day_and_a_double_tap_sends_once(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, gym, "Ana Tap")
    bill(db, gym, ana, [(-4, 30000, 0, 0)])
    period = reminder_of(client, gym, ana)["billing_period_id"]
    key = str(uuid.uuid4())

    first = send(client, gym, period, **{"Idempotency-Key": key})
    again = send(client, gym, period, **{"Idempotency-Key": key})
    other = send(client, gym, period, **{"Idempotency-Key": str(uuid.uuid4())})

    assert (first.status_code, again.status_code) == (201, 201)
    assert again.headers.get("idempotent-replayed") == "true"
    assert other.status_code == 409
    assert other.json()["detail"]["code"] == "emailed_today"
    assert len(to_of(mailer, "ana.tap@example.cl")) == 1


@pg
def test_a_dependents_email_goes_to_the_guardian(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, gym, "Ana Rojas")
    tomas = new_kid(client, gym, ana, "Tomás Rojas")
    bill(db, gym, tomas, [(-1, 30000, 0, 0)])
    row = reminder_of(client, gym, tomas)

    assert send(client, gym, row["billing_period_id"]).status_code == 201

    [email] = to_of(mailer, "ana.rojas@example.cl")
    assert "Hola, Ana Rojas:" in email.text
    assert "de Tomás Rojas en" in email.text
    [log] = email_rows(db, gym)
    assert str(log["person_id"]) == ana


@pg
def test_nothing_to_send_before_the_due_date_or_without_an_email(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = add_person(client, gym, "Ana Sin Correo")
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_person SET email = NULL WHERE person_id = $1", uuid.UUID(ana)
        ),
    )
    bill(db, gym, ana, [(-3, 30000, 0, 0)])
    row = reminder_of(client, gym, ana)

    assert row["can_email"] is False
    response = send(client, gym, row["billing_period_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_email"
    assert send(client, gym, str(uuid.uuid4())).status_code == 404


@pg
def test_a_coach_cannot_send_it(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    ana = add_person(client, gym, "Ana Coach")
    bill(db, gym, ana, [(-3, 30000, 0, 0)])
    period = reminder_of(client, gym, ana)["billing_period_id"]
    coach = add_staff(db, gym, "coach")

    response = client.post(f"/api/reminders/{period}/email", headers=as_gym(gym, person_id=coach))

    assert response.status_code == 403
    assert email_rows(db, gym) == []
