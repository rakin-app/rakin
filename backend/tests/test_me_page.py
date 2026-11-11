"""The student page, "Mi página" (#65): the next payment, where to transfer it, and the
payments already sent with how each was reviewed.

It answers only about the person acting and the dependents they pay for, so a
student never sees another's payments.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.me import PAYMENTS_SHOWN
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, seed_gym, seeded_today, throwaway_database
from tests.test_guardians import add_person, bill, new_kid
from tests.test_gym_settings import BANK, BANK_STORED
from tests.test_plans import add_staff
from tests.test_proof_review import claimed, reject
from tests.test_proofs import RecordingMailer

pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=RecordingMailer())
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def page(client: TestClient, gym: uuid.UUID, person: str) -> Any:
    response = client.get("/api/me/page", headers=as_gym(gym, uuid.UUID(person)))
    assert response.status_code == 200, response.text
    return response.json()


@pg
def test_a_student_with_nothing_owed(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana Rojas")

    mine = page(client, sur, ana)

    assert mine["gym_name"].startswith("academia-sur-")
    assert mine["timezone"] == "America/Santiago"
    assert (mine["person_id"], mine["name"]) == (ana, "Ana Rojas")
    assert mine["next_payment"] is None
    assert mine["bank_account"] is None
    assert mine["payments"] == []


@pg
def test_the_bank_details_are_the_gyms(client: TestClient, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    response = client.patch("/api/gym/settings", json={"bank_account": BANK}, headers=as_gym(sur))
    assert response.status_code == 200, response.text

    assert page(client, sur, ana)["bank_account"] == BANK_STORED


@pg
@pytest.mark.parametrize(("due_in", "status"), [(-3, "overdue"), (0, "due"), (5, "due")])
def test_the_next_payment_is_the_earliest_open_period(
    client: TestClient, db: Database, sur: uuid.UUID, due_in: int, status: str
) -> None:
    ana = add_person(client, sur, "Ana")
    # Paid, then open, then a later one not yet due.
    bill(
        db,
        sur,
        ana,
        [(due_in - 30, 45000, 45000, 0), (due_in, 45000, 0, 0), (due_in + 30, 45000, 0, 0)],
    )

    nxt = page(client, sur, ana)["next_payment"]

    assert nxt["status"] == status
    assert (nxt["period"]["person_id"], nxt["period"]["outstanding_clp"]) == (ana, 45000)


@pg
def test_a_claimed_period_is_in_review_and_listed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(-3, 45000, 0, 0)])
    entry = claimed(client, sur, ana, 45000)

    mine = page(client, sur, ana)

    assert mine["next_payment"]["status"] == "in_review"
    assert mine["next_payment"]["period"]["pending_clp"] == 45000
    [payment] = mine["payments"]
    assert (payment["id"], payment["status"], payment["amount_clp"]) == (
        entry["id"],
        "pending",
        45000,
    )
    assert payment["claimed_at"] is not None
    assert payment["validated_at"] is None
    assert payment["period_start"] == mine["next_payment"]["period"]["period_start"]


@pg
def test_a_rejection_shows_its_note_and_the_period_is_owed_again(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(-3, 45000, 0, 0)])
    entry = claimed(client, sur, ana, 40000)
    admin = add_staff(db, sur, "admin")
    assert reject(client, sur, entry["id"], "falta $5.000", person_id=admin).status_code == 200

    mine = page(client, sur, ana)

    assert mine["next_payment"]["status"] == "overdue"
    [payment] = mine["payments"]
    assert (payment["status"], payment["note"]) == ("rejected", "falta $5.000")
    assert payment["validated_at"] is not None


@pg
def test_an_admins_note_on_a_recorded_payment_is_not_shown(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-3, 45000, 0, 0)])
    period = page(client, sur, ana)["next_payment"]["period"]
    response = client.post(
        "/api/ledger/payments",
        json={
            "membership_id": membership,
            "billing_period_id": period["id"],
            "amount_clp": 45000,
            "method": "cash",
            "note": "pagó en recepción, dijo que vuelve mañana",
        },
        headers=as_gym(sur),
    )
    assert response.status_code == 201, response.text

    mine = page(client, sur, ana)

    assert mine["next_payment"] is None
    [payment] = mine["payments"]
    assert (payment["status"], payment["note"]) == ("validated", None)


@pg
def test_a_guardian_sees_their_dependents_payments(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    bill(db, sur, juan, [(-35, 30000, 30000, 0), (2, 30000, 0, 0)])

    mine = page(client, sur, marta)

    assert mine["next_payment"]["period"]["person_name"] == "Juan"
    assert [(p["person_id"], p["person_name"]) for p in mine["payments"]] == [(juan, "Juan")]


@pg
def test_a_student_sees_only_their_own_payments(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    bill(db, sur, bea, [(-3, 45000, 45000, 0), (27, 45000, 0, 0)])

    mine = page(client, sur, ana)

    assert mine["next_payment"] is None
    assert mine["payments"] == []


@pg
def test_the_history_is_newest_first_and_bounded(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    months = PAYMENTS_SHOWN + 2
    bill(db, sur, ana, [(-30 * i, 45000, 45000, 0) for i in range(months, 0, -1)])

    payments = page(client, sur, ana)["payments"]

    # Recorded together, so the latest periods first; the two oldest are left out.
    starts = [p["period_start"] for p in payments]
    assert len(starts) == PAYMENTS_SHOWN
    assert starts == sorted(starts, reverse=True)
    assert starts[0] == str(seeded_today() - timedelta(days=30))
    assert str(seeded_today() - timedelta(days=30 * PAYMENTS_SHOWN)) in starts


@pg
def test_refunds_and_adjustments_are_listed_so_the_history_adds_up(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # Two payments of 20.000 against 45.000, one given back, and a 5.000 discount
    # (#210): the student reads every movement, and 45.000 - 40.000 + 20.000 - 5.000 is
    # the 20.000 still owed.
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(-3, 45000, 0, 0)])
    period = page(client, sur, ana)["next_payment"]["period"]["id"]
    staff = as_gym(sur)

    def post(path: str, body: dict[str, Any]) -> Any:
        response = client.post(path, json=body, headers=staff)
        assert response.status_code == 201, response.text
        return response.json()

    ids = {"membership_id": membership, "billing_period_id": period}
    first = post("/api/ledger/payments", {**ids, "amount_clp": 20000, "method": "transfer"})
    post("/api/ledger/payments", {**ids, "amount_clp": 20000, "method": "transfer"})
    post(
        "/api/ledger/refunds",
        {
            "payment_id": first["payment"]["id"],
            "amount_clp": 20000,
            "method": "transfer",
            "note": "pagó dos veces",
        },
    )
    post("/api/ledger/adjustments", {**ids, "amount_clp": 5000, "note": "descuento hermano"})

    mine = page(client, sur, ana)

    assert [(p["kind"], p["amount_clp"]) for p in mine["payments"]] == [
        ("adjustment", 5000),
        ("refund", 20000),
        ("payment", 20000),
        ("payment", 20000),
    ]
    # An admin's note is theirs, as on a recorded payment.
    assert {p["note"] for p in mine["payments"]} == {None}
    assert mine["next_payment"]["period"]["outstanding_clp"] == 20000


@pg
def test_refunds_and_adjustments_never_push_a_payment_off_the_list(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    # A year of payments, then two discounts on the latest period: still a year of
    # payments, and both discounts on top.
    ana = add_person(client, sur, "Ana")
    months = PAYMENTS_SHOWN + 2
    membership = bill(
        db, sur, ana, [(-30 * i, 45000, 45000 if i > 1 else 0, 0) for i in range(months, 0, -1)]
    )
    period = page(client, sur, ana)["next_payment"]["period"]["id"]
    for amount in (1000, 2000):
        response = client.post(
            "/api/ledger/adjustments",
            json={
                "membership_id": membership,
                "billing_period_id": period,
                "amount_clp": amount,
                "note": "beca",
            },
            headers=as_gym(sur),
        )
        assert response.status_code == 201, response.text

    payments = page(client, sur, ana)["payments"]

    kinds = [p["kind"] for p in payments]
    assert kinds == ["adjustment", "adjustment", *["payment"] * PAYMENTS_SHOWN]


# --- who has a student page (#214) -------------------------------------------------


def student_page(client: TestClient, gym: uuid.UUID, person: uuid.UUID) -> Any:
    response = client.get("/api/me/role", headers=as_gym(gym, person))
    assert response.status_code == 200, response.text
    return response.json()["student_page"]


@pg
def test_staff_who_also_train_have_a_student_page(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    coach = add_staff(db, sur, "coach")
    assert student_page(client, sur, coach) is False
    bill(db, sur, str(coach), [])
    assert student_page(client, sur, coach) is True


@pg
def test_members_and_guardians_have_a_student_page(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    member = add_person(client, sur, "Ana")
    bill(db, sur, member, [])
    assert student_page(client, sur, uuid.UUID(member)) is True
    guardian = add_person(client, sur, "Carla")
    new_kid(client, sur, guardian, "Simón")
    assert student_page(client, sur, uuid.UUID(guardian)) is True
