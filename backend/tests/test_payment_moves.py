"""Mover pago (#280): a payment moved to another month, plan, or a sibling's.

A move is a pair of entries written in one transaction, both `purpose = 'move'` and
both naming the payment in `corrects`: a refund-shaped entry on the old period, and a
validated payment on the new one, settled as any payment is. Neither is income nor a
refund: "Cobrado" and "Reembolsos" do not change, and the person's balance does not
either, while each membership's follows its own entries. No email is sent.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from alembic import command
from app import ledger_export
from app.domain import billing as domain
from app.domain.billing import BillingPeriod
from app.domain.errors import InvalidTransition
from app.domain.ledger import EntryKind, EntryStatus, LedgerEntry, Purpose
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import (
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    seeded_today,
    throwaway_database,
)
from tests.test_corrections import audit_rows
from tests.test_extra_charges import create, draft, line_of
from tests.test_guardians import add_person
from tests.test_member_roll import enrolled, forget, memberships, plan
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer
from tests.test_voids import balance, book, ledger, member, ok, pending_proof, void_plan

WHY = "se registró en el mes equivocado"

# --- the domain, no database ------------------------------------------------------


def period_of(paid: int = 0) -> BillingPeriod:
    return BillingPeriod(
        period_start=seeded_today(),
        period_end=seeded_today() + timedelta(days=29),
        amount_due_clp=45_000,
        due_date=seeded_today(),
        paid_clp=paid,
        closed=paid >= 45_000,
    )


PAID = LedgerEntry(kind=EntryKind.PAYMENT, amount_clp=45_000, status=EntryStatus.VALIDATED)


def test_a_move_takes_part_or_all_of_what_is_left_off_its_period() -> None:
    out = domain.move_out(period_of(45_000), PAID, 0, 20_000, f" {WHY} ")
    assert (out.entry.kind, out.entry.amount_clp, out.entry.purpose) == (
        "refund",
        20_000,
        Purpose.MOVE,
    )
    assert out.entry.note == WHY
    assert (out.period.outstanding_clp, out.period.closed) == (20_000, False)

    # After 10.000 given back, 35.000 at most.
    assert domain.move_out(period_of(35_000), PAID, 10_000, 35_000, WHY).period.paid_clp == 0
    with pytest.raises(InvalidTransition):
        domain.move_out(period_of(35_000), PAID, 10_000, 35_001, WHY)
    pending = dataclasses.replace(PAID, status=EntryStatus.PENDING)
    with pytest.raises(InvalidTransition):
        domain.move_out(period_of(), pending, 0, 1, WHY)
    with pytest.raises(ValueError):
        domain.move_out(period_of(45_000), PAID, 0, 1, "  ")


def test_a_move_lands_as_a_payment_and_carries_what_is_not_needed() -> None:
    into = domain.move_in(period_of(), 50_000, WHY)
    assert (into.entry.kind, into.entry.purpose, into.entry.note) == ("payment", Purpose.MOVE, WHY)
    assert into.period.closed
    assert into.credit is not None and into.credit.amount_clp == 5_000
    with pytest.raises(InvalidTransition):
        domain.move_in(period_of(45_000), 1, WHY)
    with pytest.raises(ValueError):
        LedgerEntry(kind=EntryKind.ADJUSTMENT, amount_clp=1, purpose=Purpose.MOVE)


# --- against real Postgres --------------------------------------------------------

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
    app = create_app(make_settings(database_url=db.api_url, public_base_url="http://testserver"))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("sur"))


def pay(client: TestClient, gym: uuid.UUID, membership: str, period: str, amount: int) -> Any:
    body = {
        "membership_id": membership,
        "billing_period_id": period,
        "amount_clp": amount,
        "method": "transfer",
    }
    return ok(client.post("/api/ledger/payments", json=body, headers=as_gym(gym)), 201)


def move(
    client: TestClient, gym: uuid.UUID, payment: str, period: str, amount: int, **kw: Any
) -> Any:
    body = {"payment_id": payment, "billing_period_id": period, "amount_clp": amount, "reason": WHY}
    return client.post("/api/ledger/moves", json=body, headers=as_gym(gym, **kw))


def refused(response: Any) -> str:
    assert response.status_code == 409, response.text
    return str(response.json()["detail"]["code"])


def targets(client: TestClient, gym: uuid.UUID, payment: str) -> Any:
    return ok(
        client.get("/api/ledger/moves/targets", params={"payment_id": payment}, headers=as_gym(gym))
    )


def kpis(client: TestClient, gym: uuid.UUID) -> Any:
    k = book(client, gym)["kpis"]
    return {
        key: k[key] for key in ("collected_clp", "collected_payments", "refunded_clp", "refunds")
    }


def entry_of(client: TestClient, gym: uuid.UUID, membership: str, entry: str) -> Any:
    return next(e for e in ledger(client, gym, membership)["entries"] if e["id"] == entry)


def second_plan(client: TestClient, gym: uuid.UUID, person: str) -> str:
    """Another plan of `person`, started 10 days ago: one period, owing."""
    body = {
        "person_id": person,
        "plan_id": plan(client, gym),
        "started_on": (seeded_today() - timedelta(days=10)).isoformat(),
        "send_welcome": False,
    }
    return str(ok(client.post("/api/memberships", json=body, headers=as_gym(gym)), 201)["id"])


@pg
@pytest.mark.parametrize("role", ["owner", "admin"])
def test_a_payment_moved_to_another_month_is_neither_income_nor_a_refund(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer, role: str
) -> None:
    person, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]
    before = kpis(client, gym)
    owed = balance(db, membership)

    offered = targets(client, gym, payment["id"])
    assert (offered["movable_clp"], offered["whole_only"]) == (45_000, False)
    assert second["id"] in {t["billing_period_id"] for t in offered["targets"]}
    assert first["id"] not in {t["billing_period_id"] for t in offered["targets"]}

    by = None if role == "owner" else add_staff(db, gym, "admin")
    mailer.sent.clear()
    moved = ok(
        move(client, gym, payment["id"], second["id"], 45_000, **({"person_id": by} if by else {})),
        201,
    )
    out, into = moved["moved_out"], moved["moved_in"]
    assert (out["kind"], out["purpose"], out["refund_of"], out["corrects"]) == (
        "refund",
        "move",
        payment["id"],
        payment["id"],
    )
    assert (out["billing_period_id"], out["method"], out["note"]) == (first["id"], None, WHY)
    assert (into["kind"], into["purpose"], into["corrects"], into["refund_of"]) == (
        "payment",
        "move",
        payment["id"],
        None,
    )
    assert (into["billing_period_id"], into["method"], into["status"]) == (
        second["id"],
        "transfer",
        "validated",
    )
    assert (moved["reverted"], moved["credit"]) == (None, None)
    assert moved["from_period"]["outstanding_clp"] == 45_000
    assert moved["to_period"]["closed"] is True

    # Both periods settle; nothing reported, nothing owed beyond what was; no email.
    assert kpis(client, gym) == before
    assert balance(db, membership) == owed
    assert mailer.sent == []
    open_now = {p["id"] for p in ledger(client, gym, membership)["open_periods"]}
    assert first["id"] in open_now and second["id"] not in open_now

    # The Libro names the other month on each half.
    assert (
        entry_of(client, gym, membership, out["id"])["moved"]["period_start"]
        == (second["period_start"])
    )
    assert (
        entry_of(client, gym, membership, into["id"])["moved"]["period_start"]
        == (first["period_start"])
    )
    booked = {i["id"]: i for i in book(client, gym)["items"]}
    assert booked[out["id"]]["purpose"] == booked[into["id"]]["purpose"] == "move"

    # The audit row says what moved and where.
    row = audit_rows(db, gym, person)[-1]
    assert (row["action"], row["reason"]) == ("ledger_corrected", WHY)
    detail = row["detail"]
    assert (detail["purpose"], detail["moved"], detail["payment_id"]) == (
        "move",
        "out",
        payment["id"],
    )
    assert (detail["billing_period_id"], detail["other_billing_period_id"]) == (
        first["id"],
        second["id"],
    )
    assert detail["entry_ids"] == [out["id"], into["id"]]
    assert (detail["before"]["outstanding_clp"], detail["after"]["outstanding_clp"]) == (0, 45_000)
    assert detail["other_after"]["outstanding_clp"] == 0
    corrections = ok(client.get(f"/api/ledger/people/{person}/corrections", headers=as_gym(gym)))[
        "items"
    ]
    assert (corrections[0]["moved"], corrections[0]["other_period_start"]) == (
        "out",
        second["period_start"],
    )

    # "Mis pagos" shows the move, never why.
    mine = ok(client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person))))["payments"]
    shown = {p["id"]: p for p in mine}
    assert (shown[out["id"]]["purpose"], shown[out["id"]]["moved_period_start"]) == (
        "move",
        second["period_start"],
    )
    assert shown[into["id"]]["moved_period_start"] == first["period_start"]
    assert shown[out["id"]]["note"] is None and shown[into["id"]]["note"] is None

    # Nothing is left of the payment to move, refund or undo.
    elsewhere = ledger(client, gym, second_plan(client, gym, person))["open_periods"][0]
    assert refused(move(client, gym, payment["id"], elsewhere["id"], 1)) == "nothing_left"
    assert targets(client, gym, payment["id"])["movable_clp"] == 0


@pg
def test_part_of_a_payment_moves_and_no_more_than_is_left(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]
    before = kpis(client, gym)
    owed = balance(db, membership)

    moved = ok(move(client, gym, payment["id"], second["id"], 20_000), 201)
    assert moved["from_period"]["outstanding_clp"] == 20_000
    assert moved["to_period"]["outstanding_clp"] == 25_000
    assert kpis(client, gym) == before
    assert balance(db, membership) == owed
    [left] = [
        p
        for p in ledger(client, gym, membership)["refundable_payments"]
        if p["id"] == payment["id"]
    ]
    assert left["refundable_clp"] == 25_000

    assert refused(move(client, gym, payment["id"], second["id"], 25_001)) == "beyond_left"
    ok(move(client, gym, payment["id"], second["id"], 25_000), 201)
    assert balance(db, membership) == owed


@pg
def test_a_payment_moves_to_another_plan_of_the_same_person(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    other = second_plan(client, gym, person)
    first = ledger(client, gym, membership)["open_periods"][0]
    target = ledger(client, gym, other)["open_periods"][0]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]
    before = kpis(client, gym)
    total = balance(db, membership) + balance(db, other)
    one, two = balance(db, membership), balance(db, other)

    assert target["id"] in {
        t["billing_period_id"] for t in targets(client, gym, payment["id"])["targets"]
    }
    moved = ok(move(client, gym, payment["id"], target["id"], 45_000), 201)
    assert moved["moved_in"]["membership_id"] == other
    assert kpis(client, gym) == before
    # The person's balance is what it was; each plan's follows its own entries.
    assert balance(db, membership) + balance(db, other) == total
    assert (balance(db, membership), balance(db, other)) == (one + 45_000, two - 45_000)
    moved_with = entry_of(client, gym, membership, moved["moved_out"]["id"])["moved"]
    assert (moved_with["membership_id"], moved_with["person_id"]) == (other, person)

    # Merging: the duplicate plan, its payment moved off, is voided.
    ok(void_plan(client, gym, membership))


@pg
def test_a_payment_moves_to_a_sibling_and_both_ledgers_say_so(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    marta = enrolled(client, gym, name="Marta")
    started_on = (seeded_today() - timedelta(days=10)).isoformat()

    def kid(name: str) -> tuple[str, str]:
        body = enrolled(
            client,
            gym,
            name=name,
            guardian={"person_id": marta["id"]},
            membership={"plan_id": plan(client, gym), "started_on": started_on},
        )
        [m] = memberships(client, gym, body["id"])
        return body["id"], m["id"]

    tomas, tomas_plan = kid("Tomás")
    sofia, sofia_plan = kid("Sofía")
    paid_on = ledger(client, gym, tomas_plan)["open_periods"][0]
    target = ledger(client, gym, sofia_plan)["open_periods"][0]
    payment = pay(client, gym, tomas_plan, paid_on["id"], 45_000)["payment"]
    before = kpis(client, gym)
    total = balance(db, tomas_plan) + balance(db, sofia_plan)

    offered = targets(client, gym, payment["id"])["targets"]
    [sibling] = [t for t in offered if t["billing_period_id"] == target["id"]]
    assert (sibling["person_id"], sibling["person_name"]) == (sofia, "Sofía")

    mailer.sent.clear()
    moved = ok(move(client, gym, payment["id"], target["id"], 45_000), 201)
    assert kpis(client, gym) == before
    assert balance(db, tomas_plan) + balance(db, sofia_plan) == total
    assert mailer.sent == []
    came = entry_of(client, gym, sofia_plan, moved["moved_in"]["id"])["moved"]
    assert (came["person_id"], came["person_name"]) == (tomas, "Tomás")

    # Each child's "Correcciones" shows it.
    assert audit_rows(db, gym, tomas)[-1]["detail"]["moved"] == "out"
    assert audit_rows(db, gym, sofia)[-1]["detail"]["moved"] == "in"

    # Tomás has nothing left of it, but Sofía's entry names his payment: he stays.
    ok(void_plan(client, gym, tomas_plan))
    assert ok(client.get(f"/api/people/{tomas}/deletion", headers=as_gym(gym))) == {
        "refused": "moved",
        "amount_clp": None,
    }
    assert forget(client, gym, tomas, reason="era de prueba").status_code == 409


@pg
def test_an_overpaid_payment_moves_whole_with_its_credit(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    paid = pay(client, gym, membership, first["id"], 50_000)
    credit = paid["credit"]
    payment = paid["payment"]
    assert credit["amount_clp"] == 5_000
    assert targets(client, gym, payment["id"])["whole_only"] is True
    owed = balance(db, membership)

    assert refused(move(client, gym, payment["id"], second["id"], 45_000)) == "whole_only"
    moved = ok(move(client, gym, payment["id"], second["id"], 50_000), 201)
    reverted = moved["reverted"]
    assert (
        reverted["kind"],
        reverted["amount_clp"],
        reverted["purpose"],
        reverted["corrects"],
    ) == (
        "adjustment",
        -5_000,
        "revert",
        credit["id"],
    )
    # The new period needs 45.000 of it: the rest is carried afresh.
    fresh = moved["credit"]
    assert (fresh["amount_clp"], fresh["billing_period_id"], fresh["purpose"]) == (
        5_000,
        None,
        None,
    )
    assert moved["to_period"]["closed"] is True
    assert moved["from_period"]["outstanding_clp"] == 45_000
    assert balance(db, membership) == owed

    # The payment moved in carries that credit as its own: moving it back takes it.
    back = ok(move(client, gym, moved["moved_in"]["id"], first["id"], 50_000), 201)
    assert back["reverted"]["corrects"] == fresh["id"]


@pg
def test_what_may_not_move_is_refused(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    person, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]

    # Onto its own period, or a period paid in full.
    assert refused(move(client, gym, payment["id"], first["id"], 45_000)) == "same_period"
    pay(client, gym, membership, second["id"], 45_000)
    assert refused(move(client, gym, payment["id"], second["id"], 1)) == "paid"

    # To someone unrelated.
    _, stranger = member(client, gym)
    theirs = ledger(client, gym, stranger)["open_periods"][0]
    assert refused(move(client, gym, payment["id"], theirs["id"], 1)) == "unrelated"
    assert theirs["id"] not in {
        t["billing_period_id"] for t in targets(client, gym, payment["id"])["targets"]
    }

    # Onto a period with a proof waiting.
    third = second_plan(client, gym, person)
    waiting = ledger(client, gym, third)["open_periods"][0]
    pending_proof(db, gym, person, third, waiting["id"])
    assert refused(move(client, gym, payment["id"], waiting["id"], 1)) == "pending"
    [listed] = [
        t
        for t in targets(client, gym, payment["id"])["targets"]
        if t["billing_period_id"] == waiting["id"]
    ]
    assert listed["pending"] is True

    # A proof is reviewed, not moved.
    [proof] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT id FROM ledger_entry WHERE billing_period_id = $1 AND status = 'pending'",
            uuid.UUID(waiting["id"]),
        ),
    )
    assert refused(move(client, gym, str(proof["id"]), first["id"], 1)) == "not_validated"
    assert move(client, gym, str(uuid.uuid4()), first["id"], 1).status_code == 404
    assert move(client, gym, payment["id"], str(uuid.uuid4()), 1).status_code == 404

    # A reason is required, and a positive amount.
    blank = client.post(
        "/api/ledger/moves",
        json={
            "payment_id": payment["id"],
            "billing_period_id": first["id"],
            "amount_clp": 1,
            "reason": " ",
        },
        headers=as_gym(gym),
    )
    assert blank.status_code == 422
    assert move(client, gym, payment["id"], first["id"], 0).status_code == 422

    # A coach moves nothing.
    coach = add_staff(db, gym, "coach")
    assert move(client, gym, payment["id"], first["id"], 1, person_id=coach).status_code == 403


@pg
def test_a_cobro_line_payment_does_not_move(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    ana = add_person(client, gym, "Ana")
    charge = create(client, gym, draft([ana], amount_clp=25_000))
    line = line_of(charge, ana)["id"]
    paid = ok(
        client.post(
            f"/api/extra-charges/{charge['id']}/lines/{line}/payments",
            json={"amount_clp": 25_000, "method": "cash"},
            headers=as_gym(gym),
        ),
        201,
    )
    _, membership = member(client, gym)
    period = ledger(client, gym, membership)["open_periods"][0]
    assert refused(move(client, gym, paid["payment"]["id"], period["id"], 1)) == "extra_line"


@pg
def test_a_person_whose_payment_moved_between_their_plans_still_holds_it(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    person, membership = member(client, gym)
    other = second_plan(client, gym, person)
    first = ledger(client, gym, membership)["open_periods"][0]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]
    target = ledger(client, gym, other)["open_periods"][0]
    ok(move(client, gym, payment["id"], target["id"], 45_000), 201)
    # Given back from the first plan, held on the second: 45.000, not twice that.
    assert ok(client.get(f"/api/people/{person}/deletion", headers=as_gym(gym))) == {
        "refused": "payment",
        "amount_clp": 45_000,
    }


@pg
def test_the_database_holds_a_move_to_its_pair(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    _, membership = member(client, gym)
    first, second = ledger(client, gym, membership)["open_periods"][:2]
    payment = pay(client, gym, membership, first["id"], 45_000)["payment"]
    owner = seeded_owner(gym)

    def half(kind: str, period: str, refund_of: str | None, amount: int = 1000) -> str:
        ref = "NULL" if refund_of is None else f"'{refund_of}'"
        return (
            "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp,"
            " kind, status, note, refund_of, corrects, purpose, validated_by, validated_at)"
            f" VALUES (current_setting('app.gym_id')::uuid, '{membership}', '{period}', {amount},"
            f" '{kind}', 'validated', 'x', {ref}, '{payment['id']}', 'move',"
            " current_setting('app.person_id')::uuid, now())"
        )

    # Half a move does not commit.
    with pytest.raises(asyncpg.CheckViolationError):
        run(db.api_url, in_gym(gym, half("refund", first["id"], payment["id"]), person=owner))
    # Nor a pair that does not add up.
    both = (
        half("refund", first["id"], payment["id"]) + "; " + half("payment", second["id"], None, 999)
    )

    async def pair(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("SELECT set_config('app.person_id', $1, true)", str(owner))
            await conn.execute(both)

    with pytest.raises(asyncpg.CheckViolationError):
        run(db.api_url, pair)
    # A refund half naming another payment than its own, or a payment half a refund's.
    with pytest.raises(asyncpg.CheckViolationError):
        run(db.api_url, in_gym(gym, half("payment", second["id"], payment["id"]), person=owner))


def test_upgrade_and_downgrade_0089() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0088")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0088")
        migrate(scratch)


def test_the_export_lists_a_move_in_no_total() -> None:
    day = seeded_today()

    def row(kind: str, amount: int) -> ledger_export.Row:
        return ledger_export.Row(
            day=day,
            member="Ana",
            rut=None,
            concept="Mensual",
            period=None,
            kind=kind,
            method=None,
            amount_clp=amount,
            status=ledger_export.STATUSES["validated"],
            bank_ref=None,
            note=None,
        )

    out = ledger_export.kind_label("refund", False, "move")
    into = ledger_export.kind_label("payment", False, "move")
    assert (out, into) == ("Pago movido (sale)", "Pago movido (entra)")
    lines = dict(
        ledger_export.total_lines(
            ledger_export.totals([row("Pago", 45_000), row(out, 45_000), row(into, 45_000)], 0)
        )
    )
    assert (lines["Total pagado"], lines["Total devuelto"]) == (45_000, 0)
