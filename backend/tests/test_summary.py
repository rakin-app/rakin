"""Resumen del mes, `GET /api/summary` (#505): what was paid after a reminder, who came
back after a nudge, and the month's plain counts, from the rows already there.

The rules' edges without a database are `tests/domain/test_value_summary.py`; these
write the rows those rules read, with the instants they hinge on, and read the page.
Every instant is Santiago's, the seeded gym's timezone, so a day-0 email at 23:30 is
23:30 on the due date there whatever the host's clock says.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.domain.dates import add_months
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    DEFAULT_TIMEZONE,
    Database,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_attendance import class_type, program
from tests.test_plans import add_staff

pg = pytest.mark.postgres

SANTIAGO = ZoneInfo(DEFAULT_TIMEZONE)

# The month most tests read, two before the current one so it is whole and closed, and
# the one after it.
MONTH = add_months(seeded_today().replace(day=1), -2)
NEXT = add_months(MONTH, 1)
# A period falling due on the 10th of it.
DUE = MONTH + timedelta(days=9)


def day(n: int) -> date:
    """`n` days after `DUE`."""
    return DUE + timedelta(days=n)


def local(on: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.combine(on, time(hour, minute), tzinfo=SANTIAGO)


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


def opened_on(db: Database, gym: uuid.UUID, on: date) -> None:
    run(
        db.admin_url,
        lambda c: c.execute("UPDATE gym SET created_at = $1 WHERE id = $2", local(on, 9), gym),
    )


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    """A gym on Rakin since well before `MONTH`."""
    made = seed_gym(db, unique_slug("academia"))
    opened_on(db, made, add_months(MONTH, -3))
    return made


def admin(db: Database, sql: str, *args: object) -> Any:
    """`sql` as the superuser, which skips RLS, returning the first column of its row."""
    return run(db.admin_url, lambda c: c.fetchval(sql, *args))


def a_member(
    db: Database, gym: uuid.UUID, status: str = "active", **membership: object
) -> tuple[uuid.UUID, uuid.UUID]:
    """A person with a Mensual membership in `status`, and `membership`'s columns: their
    id, and the membership's."""
    person = uuid.uuid4()
    admin(db, "INSERT INTO person (id, name) VALUES ($1, 'Socia Ejemplo')", person)
    admin(
        db,
        "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Socia Ejemplo')",
        gym,
        person,
    )
    columns = ", ".join(["gym_id", "person_id", "plan_id", "status", *membership])
    values = ", ".join(f"${i + 4}" for i in range(len(membership)))
    membership_id = admin(
        db,
        f"INSERT INTO membership ({columns}) SELECT $1, $2, id, $3"
        f"{', ' if membership else ''}{values} FROM plan WHERE gym_id = $1 AND name = 'Mensual'"
        " RETURNING id",
        gym,
        person,
        status,
        *membership.values(),
    )
    return person, membership_id


def a_period(
    db: Database, gym: uuid.UUID, membership: uuid.UUID, due: date = DUE, amount: int = 30000
) -> uuid.UUID:
    period: uuid.UUID = admin(
        db,
        "INSERT INTO billing_period (gym_id, membership_id, period_start, period_end,"
        " amount_due_clp, due_date) VALUES ($1, $2, $3, $4, $5, $3) RETURNING id",
        gym,
        membership,
        due,
        due + timedelta(days=29),
        amount,
    )
    return period


def paid(
    db: Database,
    gym: uuid.UUID,
    membership: uuid.UUID,
    period: uuid.UUID | None,
    *,
    made: datetime,
    validated: datetime | None = None,
    by: uuid.UUID | None = None,
    amount: int = 30000,
    status: str = "validated",
    method: str = "transfer",
) -> None:
    """A payment on `period` that staff recorded at `made`, or that `by` uploaded a
    proof of then, validated at `validated` (`made` by default).

    Written as the app writes them: staff's entry is claimed by the recording admin at
    the moment they record it (`app.api.entries.INSERT_ENTRY`), with no proof; the
    member's carries the proof's key (`app.api.proofs.CLAIM`)."""
    owner = seeded_owner(gym)
    admin(
        db,
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
        " kind, status, method, claimed_by, claimed_at, created_at, validated_by,"
        " validated_at, proof_object_key) VALUES ($1, $2, $3, $4, 'payment', $5, $6, $7,"
        " $8, $8, $9, $10, $11)",
        gym,
        membership,
        period,
        amount,
        status,
        method,
        by or owner,
        made,
        owner,
        validated or made,
        f"proofs/{gym}/{by}/{uuid.uuid4()}.jpg" if by else None,
    )


def logged(
    db: Database,
    gym: uuid.UUID,
    person: uuid.UUID,
    channel: str,
    template: str,
    sent_at: datetime,
    status: str = "sent",
    **payload: object,
) -> None:
    admin(
        db,
        "INSERT INTO message_log (gym_id, person_id, channel, template, to_address, status,"
        " error, payload, sent_at) VALUES ($1, $2, $3, $4, 'x', $5, $6, CAST($7 AS jsonb), $8)",
        gym,
        person,
        channel,
        template,
        status,
        None if status == "sent" else "SMTPException: refused",
        json.dumps({k: str(v) for k, v in payload.items()}),
        sent_at,
    )


def emailed(
    db: Database, gym: uuid.UUID, person: uuid.UUID, period: uuid.UUID, at: datetime
) -> None:
    logged(db, gym, person, "email", "payment_overdue", at, billing_period_id=period)


def whatsapped(
    db: Database, gym: uuid.UUID, person: uuid.UUID, period: uuid.UUID, at: datetime
) -> None:
    logged(db, gym, person, "whatsapp", "payment_overdue", at, billing_period_id=period)


def nudged(db: Database, gym: uuid.UUID, about: uuid.UUID, at: datetime) -> None:
    logged(db, gym, about, "whatsapp", "inactive_nudge", at, about=about)


def attended(
    client: TestClient, db: Database, gym: uuid.UUID, membership: uuid.UUID, at: datetime
) -> None:
    kind = class_type(client, gym, program(client, gym, f"P {uuid.uuid4().hex[:6]}"), cost=0)
    session = admin(
        db,
        "INSERT INTO session (gym_id, class_type_id, starts_at, coach_id)"
        " VALUES ($1, $2, $3, $4) RETURNING id",
        gym,
        uuid.UUID(kind),
        at,
        seeded_owner(gym),
    )
    admin(
        db,
        "INSERT INTO attendance (gym_id, session_id, membership_id) VALUES ($1, $2, $3)",
        gym,
        session,
        membership,
    )


def summary(client: TestClient, gym: uuid.UUID, month: date | None = MONTH, **kw: Any) -> Any:
    query = "" if month is None else f"?month={month:%Y-%m}"
    response = client.get(f"/api/summary{query}", headers=as_gym(gym, **kw))
    assert response.status_code == 200, response.text
    return response.json()


def after(client: TestClient, gym: uuid.UUID, month: date = MONTH) -> tuple[int, int, int]:
    """How many payments came after a reminder: in all, by email only, after a WhatsApp."""
    figures = summary(client, gym, month)["after_reminders"]
    return (
        figures["total"]["payments"],
        figures["emails_only"]["payments"],
        figures["after_whatsapp"]["payments"],
    )


# --- payments after a reminder ----------------------------------------------------


@pg
def test_a_payment_on_the_due_date_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    emailed(db, gym, person, period, local(day(-1)))
    paid(db, gym, membership, period, made=local(DUE, 20))

    assert after(client, gym) == (0, 0, 0)


@pg
def test_a_reminder_after_the_payment_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    paid(db, gym, membership, period, made=local(day(3), 10))
    emailed(db, gym, person, period, local(day(3), 22))

    assert after(client, gym) == (0, 0, 0)


@pg
def test_a_day_0_email_late_at_night_then_a_payment_before_days_1_email_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    # 23:30 on the due date in Santiago is already the next day in UTC.
    emailed(db, gym, person, period, local(DUE, 23, 30))
    paid(db, gym, membership, period, made=local(day(1), 9))
    emailed(db, gym, person, period, local(day(1), 23, 30))

    assert after(client, gym) == (0, 0, 0)


@pg
def test_a_day_1_email_then_a_payment_counts_with_no_message_from_the_team(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    emailed(db, gym, person, period, local(DUE, 3))
    emailed(db, gym, person, period, local(day(1), 3))
    paid(db, gym, membership, period, made=local(day(2)), amount=30000)

    figures = summary(client, gym)["after_reminders"]
    assert figures["total"] == {"payments": 1, "amount_clp": 30000}
    assert figures["emails_only"] == {"payments": 1, "amount_clp": 30000}
    assert figures["after_whatsapp"] == {"payments": 0, "amount_clp": 0}


@pg
def test_a_whatsapp_then_an_email_then_a_payment_counts_as_after_whatsapp(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    whatsapped(db, gym, person, period, local(day(2)))
    emailed(db, gym, person, period, local(day(4), 3))
    paid(db, gym, membership, period, made=local(day(5)))

    assert after(client, gym) == (1, 0, 1)


@pg
def test_a_proof_uploaded_in_the_grace_but_validated_next_month_counts_next_month(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    due = add_months(MONTH, 1) - timedelta(days=5)
    period = a_period(db, gym, membership, due)
    emailed(db, gym, person, period, local(due + timedelta(days=1), 3))
    uploaded = local(due + timedelta(days=3))
    paid(
        db, gym, membership, period, made=uploaded, by=person, validated=local(NEXT + timedelta(1))
    )

    assert after(client, gym, MONTH) == (0, 0, 0)
    assert after(client, gym, NEXT) == (1, 1, 0)


@pg
def test_a_reminder_about_another_period_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    other = a_period(db, gym, membership, DUE - timedelta(days=30))
    emailed(db, gym, person, other, local(day(1), 3))
    paid(db, gym, membership, period, made=local(day(2)))

    assert after(client, gym) == (0, 0, 0)


@pg
def test_an_email_that_did_not_go_out_does_not_count(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    logged(
        db, gym, person, "email", "payment_overdue", local(day(1), 3), "failed",
        billing_period_id=period,
    )  # fmt: skip
    paid(db, gym, membership, period, made=local(day(2)))

    assert after(client, gym) == (0, 0, 0)


@pg
def test_the_money_after_reminders_is_part_of_the_months_income(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Many reminders about each period, and a period paid in two parts: each payment
    # counts once, and the whole never passes "Cobrado".
    for _ in range(3):
        person, membership = a_member(db, gym)
        period = a_period(db, gym, membership)
        for n in (1, 4, 7):
            emailed(db, gym, person, period, local(day(n), 3))
        whatsapped(db, gym, person, period, local(day(5)))
        paid(db, gym, membership, period, made=local(day(8)), amount=10000)
        paid(db, gym, membership, period, made=local(day(9)), amount=20000)
    _, on_time = a_member(db, gym)
    paid(db, gym, on_time, a_period(db, gym, on_time), made=local(DUE), amount=45000)

    page = summary(client, gym)

    figures = page["after_reminders"]
    assert figures["total"] == {"payments": 6, "amount_clp": 90000}
    assert figures["after_whatsapp"] == {"payments": 6, "amount_clp": 90000}
    income = admin(
        db,
        "SELECT income_clp FROM v_monthly_income WHERE gym_id = $1 AND month = $2",
        gym,
        MONTH,
    )
    assert (page["income_clp"], page["income_payments"]) == (income, 7) == (135000, 7)
    assert figures["total"]["amount_clp"] <= page["income_clp"]
    assert figures["income_percent"] == 67
    assert (page["reminder_emails"], page["reminder_whatsapps"]) == (9, 3)


# --- back after a WhatsApp --------------------------------------------------------


@pg
def test_people_nudged_and_back_within_14_days(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    on = MONTH + timedelta(days=2)
    # Back on day 14, nudged twice: counted once.
    back, back_m = a_member(db, gym)
    nudged(db, gym, back, local(on, 10))
    nudged(db, gym, back, local(on + timedelta(days=5), 10))
    attended(client, db, gym, back_m, local(on + timedelta(days=14), 19))
    # Back on day 15: not back.
    late, late_m = a_member(db, gym)
    nudged(db, gym, late, local(on, 10))
    attended(client, db, gym, late_m, local(on + timedelta(days=15), 19))
    # Came that morning, before the nudge: not back.
    before, before_m = a_member(db, gym)
    attended(client, db, gym, before_m, local(on, 8))
    nudged(db, gym, before, local(on, 10))

    assert summary(client, gym)["nudges"] == {"nudged": 3, "back": 1, "percent": None}


@pg
def test_a_nudge_last_month_is_not_this_months(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = a_member(db, gym)
    nudged(db, gym, person, local(MONTH - timedelta(days=2)))
    attended(client, db, gym, membership, local(MONTH + timedelta(days=1)))

    assert summary(client, gym)["nudges"] == {"nudged": 0, "back": 0, "percent": None}


@pg
def test_the_share_back_is_shown_from_5_people_nudged(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    on = MONTH + timedelta(days=2)
    for came in (True, True, False, False, False):
        person, membership = a_member(db, gym)
        nudged(db, gym, person, local(on))
        if came:
            attended(client, db, gym, membership, local(on + timedelta(days=3)))

    assert summary(client, gym)["nudges"] == {"nudged": 5, "back": 2, "percent": 40}


# --- the plain counts ------------------------------------------------------------


@pg
def test_the_plain_counts(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    on = MONTH + timedelta(days=3)
    for template in ("statement", "payment_overdue", "receipt", "welcome"):
        logged(db, gym, person, "email", template, local(on), billing_period_id=period)
    # Two proofs reviewed, one after an hour and one after three, and a payment staff
    # recorded.
    paid(db, gym, membership, period, made=local(on, 9), by=person, validated=local(on, 10))
    paid(
        db, gym, membership, period, made=local(on, 9), by=person, validated=local(on, 12),
        status="rejected",
    )  # fmt: skip
    paid(db, gym, membership, period, made=local(on, 11))
    a_member(db, gym, reactivated_at=local(on))
    _, trial_m = a_member(db, gym, status="trial")
    a_member(db, gym, converted_from=trial_m, created_at=local(on))

    page = summary(client, gym)

    assert page["emails_sent"] == 3
    assert page["own_payments"] == {"by_members": 1, "payments": 2, "percent": None}
    assert page["proofs"] == {"reviewed": 2, "median_minutes": 120}
    assert (page["reactivated"], page["trials_converted"]) == (1, 1)


@pg
def test_a_payment_staff_recorded_is_cobrado_but_not_the_members_own_nor_a_proof_reviewed(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Staff's entries carry a claim too, the admin's at the moment they record it
    # (#511), so only the proof's key tells the member's own payment apart.
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    on = MONTH + timedelta(days=3)
    paid(db, gym, membership, period, made=local(on, 9), by=person, validated=local(on, 10))
    before = summary(client, gym)
    paid(db, gym, membership, period, made=local(on, 11), method="cash")
    paid(db, gym, membership, period, made=local(on, 12), method="transfer")

    page = summary(client, gym)

    assert before["own_payments"] == {"by_members": 1, "payments": 1, "percent": None}
    assert page["income_payments"] == 3
    assert page["income_clp"] == before["income_clp"] + 60000
    assert page["own_payments"] == {"by_members": 1, "payments": 3, "percent": None}
    assert page["proofs"] == before["proofs"] == {"reviewed": 1, "median_minutes": 60}


@pg
def test_a_late_payment_staff_recorded_after_a_reminder_counts_on_the_day_they_recorded_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # Staff's claim is the moment they record it, so "when it was paid" is that moment
    # whether it is read off `claimed_at` or `created_at`.
    person, membership = a_member(db, gym)
    period = a_period(db, gym, membership)
    emailed(db, gym, person, period, local(day(1), 9))
    paid(db, gym, membership, period, made=local(day(1), 12), method="cash")
    other_person, other_membership = a_member(db, gym)
    other = a_period(db, gym, other_membership)
    emailed(db, gym, other_person, other, local(day(1), 12))
    paid(db, gym, other_membership, other, made=local(day(1), 9), method="cash")

    assert after(client, gym) == (1, 1, 0)


@pg
def test_a_payment_staff_moved_is_not_one_of_the_months_payments(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # A move is a refund off one period and a payment onto another: staff's correction,
    # so neither "N de M" nor the 5-payment threshold counts its payment.
    person, membership = a_member(db, gym)
    first = a_period(db, gym, membership)
    second = a_period(db, gym, membership, DUE + timedelta(days=30))
    on = local(MONTH + timedelta(days=3))
    paid(db, gym, membership, first, made=on, by=person)
    moved = admin(db, "SELECT id FROM ledger_entry WHERE billing_period_id = $1", first)
    half = (
        "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
        " kind, status, method, created_at, validated_by, validated_at, purpose,"
        " corrects, refund_of, note) VALUES ($1, $2, $3, 30000, $4, 'validated',"
        " 'transfer', $5, $6, $5, 'move', $7, $8, 'otro período')"
    )

    # Both halves in one transaction: the database holds a move to its pair (0089).
    async def pair(conn: Any) -> None:
        async with conn.transaction():
            for period, kind in ((first, "refund"), (second, "payment")):
                await conn.execute(
                    half, gym, membership, period, kind, on, seeded_owner(gym), moved,
                    moved if kind == "refund" else None,
                )  # fmt: skip

    run(db.admin_url, pair)

    page = summary(client, gym)

    assert page["income_payments"] == 1
    assert page["own_payments"] == {"by_members": 1, "payments": 1, "percent": None}


@pg
def test_a_gym_with_no_reminders_has_nothing_to_show(client: TestClient, gym: uuid.UUID) -> None:
    page = summary(client, gym)

    assert (page["reminder_emails"], page["reminder_whatsapps"]) == (0, 0)
    assert page["after_reminders"] == {
        "total": {"payments": 0, "amount_clp": 0},
        "emails_only": {"payments": 0, "amount_clp": 0},
        "after_whatsapp": {"payments": 0, "amount_clp": 0},
        "income_percent": None,
    }
    assert page["nudges"] == {"nudged": 0, "back": 0, "percent": None}
    assert page["proofs"] == {"reviewed": 0, "median_minutes": None}


# --- the month --------------------------------------------------------------------


@pg
def test_the_current_month_by_default_and_every_month_since_the_gym_began(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    page = summary(client, gym, None)

    current = seeded_today().replace(day=1)
    assert page["month"] == current.isoformat()
    assert page["months"] == [add_months(current, -n).isoformat() for n in range(6)]
    assert page["since"] is None
    assert page["whatsapp"] is True


@pg
def test_a_partial_first_month_says_since_when(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    opened_on(db, gym, MONTH + timedelta(days=11))

    page = summary(client, gym)

    assert page["since"] == (MONTH + timedelta(days=11)).isoformat()
    assert page["months"][-1] == MONTH.isoformat()
    assert summary(client, gym, NEXT)["since"] is None


@pg
def test_no_month_before_the_gym_or_after_today(client: TestClient, gym: uuid.UUID) -> None:
    current = seeded_today().replace(day=1)
    for month in (add_months(MONTH, -4), add_months(current, 1)):
        response = client.get(f"/api/summary?month={month:%Y-%m}", headers=as_gym(gym))
        assert response.status_code == 404, month
    for bad in ("2026-13", "2026-1", "noviembre"):
        response = client.get(f"/api/summary?month={bad}", headers=as_gym(gym))
        assert response.status_code == 422, bad


@pg
def test_it_says_when_whatsapp_is_off(client: TestClient, gym: uuid.UUID) -> None:
    off = {"channels": {"whatsapp": False}}
    assert client.patch("/api/gym/settings", json=off, headers=as_gym(gym)).status_code == 200

    assert summary(client, gym)["whatsapp"] is False


# --- who sees it ------------------------------------------------------------------


@pg
def test_an_admin_reads_it_and_a_coach_gets_403(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    admin_id = add_staff(db, gym, "admin")
    coach = add_staff(db, gym, "coach")

    assert summary(client, gym, person_id=admin_id)["month"] == MONTH.isoformat()
    response = client.get("/api/summary", headers=as_gym(gym, person_id=coach))
    assert response.status_code == 403


@pg
def test_another_gyms_rows_are_not_counted(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    norte = seed_gym(db, unique_slug("norte"))
    opened_on(db, norte, add_months(MONTH, -3))
    person, membership = a_member(db, norte)
    period = a_period(db, norte, membership)
    emailed(db, norte, person, period, local(day(1), 3))
    paid(db, norte, membership, period, made=local(day(2)))
    nudged(db, norte, person, local(day(1)))

    assert after(client, norte) == (1, 1, 0)
    page = summary(client, gym)
    assert after(client, gym) == (0, 0, 0)
    assert (page["reminder_emails"], page["income_clp"], page["nudges"]["nudged"]) == (0, 0, 0)
