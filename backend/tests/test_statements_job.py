"""The nightly `statements` job: each period's statement, 7 days before it is due (#53).

The job works on every gym in the module's database, so each test's member has an
address of their own and reads back only the mail sent to it.
"""

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta

import asyncpg
import pytest

from app.auth import build_notices
from app.db import create_engine, create_sessionmaker
from app.db_bootstrap import to_dsn
from app.integrations.mailer import Email, MailDeliveryError
from app.jobs import billing, daily, freezes, join_requests, lapse, overdue, schedule, statements
from app.notices import Notices
from tests.conftest import require_test_database_url
from tests.jobgym import Gym
from tests.pg import Database, migrate, throwaway_database

pytestmark = pytest.mark.postgres

NOV_8 = date(2026, 11, 8)
NOV_15 = NOV_8 + timedelta(days=7)

BANK = {
    "bank": "Banco Estado",
    "account_type": "Cuenta RUT",
    "holder": "Academia Sur SpA",
    "rut": "76.123.456-7",
    "number": "12345678",
}


class Outbox:
    def __init__(self) -> None:
        self.sent: list[Email] = []
        self.fail = False

    async def send(self, email: Email) -> None:
        if self.fail:
            raise MailDeliveryError("smtp relay: 421 try later")
        self.sent.append(email)

    def to(self, address: str) -> list[Email]:
        return [e for e in self.sent if e.to == address]


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def gym(db: Database) -> Gym:
    return Gym(db)


def address(gym: Gym) -> str:
    """Gives the gym's member Ana an address of her own, and returns it."""
    email = f"ana-{gym.id.hex[:8]}@example.cl"
    gym.sql("UPDATE gym_person SET email = $1 WHERE person_id = $2", email, gym.person)
    return email


def state(db: Database, day: date, outbox: Outbox) -> bool:
    """Run the job for `day` as the runner would, inside its day's transaction."""

    async def go() -> bool:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            notices = build_notices(db.settings, outbox, lambda: sessionmaker)
            conn = await asyncpg.connect(to_dsn(db.owner_url))
            try:
                async with conn.transaction():
                    return bool(await statements.job(notices).run(conn, day))
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    return asyncio.run(go())


def logged(gym: Gym) -> list[tuple[str, str, str]]:
    rows = gym.sql(
        "SELECT template, status, payload ->> 'billing_period_id' FROM message_log"
        " WHERE gym_id = $1 ORDER BY sent_at",
        gym.id,
    )
    return [tuple(r) for r in rows]


def period_id(gym: Gym, membership: uuid.UUID, start: date) -> str:
    [row] = gym.sql(
        "SELECT id FROM billing_period WHERE membership_id = $1 AND period_start = $2",
        membership,
        start,
    )
    return str(row["id"])


def billed(gym: Gym, start: date, amount: int = 45_000, **member: object) -> uuid.UUID:
    """A membership with one period starting and due on `start`, and its charge."""
    membership = gym.member("signup", start - timedelta(days=30), **member)  # type: ignore[arg-type]
    gym.bill(membership, start, start + timedelta(days=29), amount)
    gym.sql(
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
        " status) VALUES ($1, $2, $3, $4, 'charge', 'validated')",
        gym.id,
        membership,
        uuid.UUID(period_id(gym, membership, start)),
        amount,
    )
    return membership


def pay(gym: Gym, membership: uuid.UUID, start: date, amount: int, status: str) -> None:
    gym.sql(
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
        " status) VALUES ($1, $2, $3, $4, 'payment', $5)",
        gym.id,
        membership,
        uuid.UUID(period_id(gym, membership, start)),
        amount,
        status,
    )


def test_a_period_due_in_7_days_is_stated(gym: Gym) -> None:
    to = address(gym)
    gym.sql(
        "UPDATE gym SET settings = settings || jsonb_build_object('bank_account', $2::jsonb)"
        " WHERE id = $1",
        gym.id,
        json.dumps(BANK),
    )
    membership = billed(gym, NOV_15)
    outbox = Outbox()

    assert state(gym.db, NOV_8, outbox)

    [email] = outbox.to(to)
    assert email.subject == f"Tu pago de $45.000 en {gym.id} vence el 15-11-2026"
    assert "Hola, Ana:" in email.text
    assert "El 15-11-2026 vence el pago de $45.000" in email.text
    assert "plan signup, período del 15-11-2026 al 14-12-2026" in email.text
    assert "Número: 12345678" in email.text
    [url] = [line for line in email.text.splitlines() if line.startswith("Tu página: ")]
    assert "/api/auth/callback?token=" in url and url.endswith("&next=%2Fme")
    assert logged(gym) == [("statement", "sent", period_id(gym, membership, NOV_15))]


def test_a_period_is_stated_once(gym: Gym) -> None:
    to = address(gym)
    billed(gym, NOV_15)
    outbox = Outbox()

    for day in (NOV_8, NOV_8, NOV_8 + timedelta(days=1)):
        state(gym.db, day, outbox)

    assert len(outbox.to(to)) == 1


def test_a_period_due_later_waits(gym: Gym) -> None:
    to = address(gym)
    billed(gym, NOV_15 + timedelta(days=1))
    outbox = Outbox()

    state(gym.db, NOV_8, outbox)
    assert outbox.to(to) == []

    state(gym.db, NOV_8 + timedelta(days=1), outbox)
    assert len(outbox.to(to)) == 1


def test_a_statement_asks_only_for_what_is_still_owed(gym: Gym) -> None:
    to = address(gym)
    membership = billed(gym, NOV_15)
    pay(gym, membership, NOV_15, 15_000, "validated")
    # A proof waiting for review is not paid yet.
    pay(gym, membership, NOV_15, 30_000, "pending")
    outbox = Outbox()

    state(gym.db, NOV_8, outbox)

    [email] = outbox.to(to)
    assert "vence el pago de $30.000" in email.text


# A frozen membership's periods wait for the freeze to end, which moved them past it.
@pytest.mark.parametrize("why", ["paid", "cancelled", "frozen", "free"])
def test_no_statement_for_nothing_owed(gym: Gym, why: str) -> None:
    to = address(gym)
    if why == "free":
        gym.bill(gym.member("signup", NOV_8), NOV_15, NOV_15 + timedelta(days=29), 0)
    else:
        membership = billed(gym, NOV_15, status=why if why != "paid" else "active")
        if why == "paid":
            pay(gym, membership, NOV_15, 45_000, "validated")
    outbox = Outbox()

    state(gym.db, NOV_8, outbox)

    assert outbox.to(to) == []
    assert logged(gym) == []


def test_a_member_with_no_email_gets_none(gym: Gym) -> None:
    billed(gym, NOV_15)

    assert state(gym.db, NOV_8, Outbox())

    assert logged(gym) == []


def test_a_failed_statement_is_sent_on_a_later_run(gym: Gym) -> None:
    to = address(gym)
    billed(gym, NOV_15)
    outbox = Outbox()
    outbox.fail = True

    # A failed send is a `failed` row, not a failed day.
    assert state(gym.db, NOV_8, outbox)
    outbox.fail = False
    state(gym.db, NOV_8 + timedelta(days=1), outbox)

    assert len(outbox.to(to)) == 1
    assert [status for _, status, _ in logged(gym)] == ["failed", "sent"]


def test_a_dependents_statement_goes_to_the_guardian(gym: Gym) -> None:
    marta = uuid.uuid4()
    to = f"marta-{gym.id.hex[:8]}@example.cl"
    gym.sql("INSERT INTO person (id, name) VALUES ($1, 'Marta')", marta)
    gym.sql(
        "INSERT INTO gym_person (gym_id, person_id, name, email) VALUES ($1, $2, 'Marta', $3)",
        gym.id,
        marta,
        to,
    )
    gym.sql(
        "INSERT INTO guardian_link (gym_id, guardian_person_id, dependent_person_id)"
        " VALUES ($1, $2, $3)",
        gym.id,
        marta,
        gym.person,
    )
    billed(gym, NOV_15)
    outbox = Outbox()

    state(gym.db, NOV_8, outbox)

    [email] = outbox.to(to)
    assert "Hola, Marta:" in email.text
    assert "$45.000 de Ana en" in email.text
    [row] = gym.sql("SELECT person_id FROM message_log WHERE gym_id = $1", gym.id)
    assert row["person_id"] == marta


def test_statements_run_nightly_after_billing() -> None:
    notices = Notices(Outbox(), lambda: None, base_url="https://x", secret_key="s" * 32)  # type: ignore[arg-type, return-value]

    assert [job.name for job in daily.jobs(notices)] == [
        freezes.NAME,
        billing.NAME,
        lapse.NAME,
        join_requests.NAME,
        schedule.NAME,
        statements.NAME,
        overdue.NAME,
    ]
