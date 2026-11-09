"""An admin validates or rejects a student's transfer proof ("Validar comprobante", #36).

The queue shows each pending proof beside the period it pays; validating closes the
period and turns an overpayment into a credit, rejecting needs a note, emails it to
the student and leaves the period open.
"""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.schemas.proofs import ProofRejection
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, seeded_owner, throwaway_database
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import add_staff
from tests.test_proofs import RecordingMailer, claim, pending, periods, stored_entry, upload

# --- input rules, no database -----------------------------------------------------


def test_a_rejection_note_is_trimmed() -> None:
    assert ProofRejection.model_validate({"note": "  falta $5.000 "}).note == "falta $5.000"


@pytest.mark.parametrize(
    "body", [{}, {"note": ""}, {"note": "   "}, {"note": "x" * 501}, {"note": "x", "status": "x"}]
)
def test_a_rejection_needs_a_note(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProofRejection.model_validate(body)


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
def client(
    db: Database, mailer: RecordingMailer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sur(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-sur-{uuid.uuid4().hex[:6]}")


def claimed(
    client: TestClient, gym: uuid.UUID, person: str, amount: int, *, by: str | None = None
) -> dict[str, Any]:
    """`by` (the person, or their guardian) claims `amount` against the person's first
    open period, with a proof; returns the pending entry."""
    by = by or person
    period = next(p for p in periods(client, gym, by) if p["person_id"] == person)
    response = claim(client, gym, by, period["id"], upload(client, gym, by), amount)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def queue(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None) -> Any:
    response = client.get("/api/ledger/proofs", headers=as_gym(gym, person))
    assert response.status_code == 200, response.text
    return response.json()


def validate(client: TestClient, gym: uuid.UUID, entry: str, **kw: Any) -> Any:
    return client.post(f"/api/ledger/proofs/{entry}/validate", headers=as_gym(gym, **kw))


def reject(client: TestClient, gym: uuid.UUID, entry: str, note: str | None, **kw: Any) -> Any:
    body = {} if note is None else {"note": note}
    return client.post(f"/api/ledger/proofs/{entry}/reject", json=body, headers=as_gym(gym, **kw))


def credits(db: Database, membership: str) -> list[dict[str, Any]]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT * FROM ledger_entry WHERE membership_id = $1 AND kind = 'adjustment'",
            uuid.UUID(membership),
        ),
    )
    return [dict(r) for r in rows]


@pg
def test_the_queue_shows_the_claim_beside_the_period(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    # Two months ago paid, last month still owing 10.000, this month the one claimed.
    bill(db, sur, ana, [(-60, 30000, 30000, 0), (-30, 30000, 20000, 0), (0, 45000, 0, 0)])
    # Against the earliest open period: last month's.
    entry = claimed(client, sur, ana, 20000)

    [item] = queue(client, sur)

    assert item["id"] == entry["id"]
    assert (item["person_name"], item["claimed_by_name"]) == ("Ana", "Ana")
    assert (item["amount_clp"], item["method"]) == (20000, "transfer")
    assert item["plan_name"] == "Mensual"
    assert item["period"]["id"] == entry["billing_period_id"]
    assert (
        item["period"]["amount_due_clp"],
        item["period"]["paid_clp"],
        item["period"]["outstanding_clp"],
    ) == (30000, 20000, 10000)
    # What else is due: this month's 45.000, not the period under review.
    assert item["prior_balance_clp"] == 45000
    # Seeded in one transaction, so at one time: compared unordered.
    assert sorted(p["amount_clp"] for p in item["last_payments"]) == [20000, 30000]
    assert item["attendance_30d"] is None
    assert item["proof_content_type"] == "application/pdf"
    proof = client.get(item["proof_url"])
    assert proof.status_code == 200
    assert proof.content.startswith(b"%PDF")


@pytest.mark.parametrize("role", ["coach", "member"])
@pg
def test_only_an_owner_or_admin_reviews(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    entry = claimed(client, sur, ana, 30000)
    person = add_staff(db, sur, "coach") if role == "coach" else uuid.UUID(ana)

    assert client.get("/api/ledger/proofs", headers=as_gym(sur, person)).status_code == 403
    assert validate(client, sur, entry["id"], person_id=person).status_code == 403
    assert reject(client, sur, entry["id"], "no", person_id=person).status_code == 403
    assert stored_entry(db, entry["id"])["status"] == "pending"
    admin = add_staff(db, sur, "admin")
    assert [i["id"] for i in queue(client, sur, admin)] == [entry["id"]]


@pg
def test_the_queue_is_oldest_first_and_holds_only_pending_proofs(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    bill(db, sur, bea, [(0, 30000, 0, 0)])
    first = claimed(client, sur, ana, 10000)
    second = claimed(client, sur, bea, 30000)
    third = claimed(client, sur, ana, 5000)
    other = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")

    assert [i["id"] for i in queue(client, sur)] == [first["id"], second["id"], third["id"]]
    assert validate(client, sur, second["id"]).status_code == 200
    assert reject(client, sur, third["id"], "ilegible").status_code == 200
    assert [i["id"] for i in queue(client, sur)] == [first["id"]]
    assert queue(client, other) == []


@pg
def test_validating_closes_the_period(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(0, 45000, 0, 0)])
    entry = claimed(client, sur, ana, 45000)
    admin = add_staff(db, sur, "admin")

    response = validate(client, sur, entry["id"], person_id=admin)

    assert response.status_code == 200, response.text
    body = response.json()
    payment = body["payment"]
    assert (payment["id"], payment["status"]) == (entry["id"], "validated")
    assert payment["validated_by"] == str(admin)
    assert payment["validated_at"] is not None
    assert payment["claimed_by"] == ana
    assert body["credit"] is None
    assert body["period"] == {
        "id": entry["billing_period_id"],
        "amount_due_clp": 45000,
        "paid_clp": 45000,
        "outstanding_clp": 0,
        "closed": True,
    }
    assert periods(client, sur, ana) == []
    assert pending(client, sur) == 0
    assert credits(db, membership) == []


@pg
def test_an_overpayment_becomes_a_credit(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(0, 30000, 10000, 0)])
    entry = claimed(client, sur, ana, 30000)

    response = validate(client, sur, entry["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"]["closed"] is True
    credit = body["credit"]
    assert (credit["kind"], credit["status"], credit["amount_clp"]) == (
        "adjustment",
        "validated",
        10000,
    )
    assert credit["billing_period_id"] is None
    assert credit["validated_by"] == str(seeded_owner(sur))
    assert credit["note"] == "Pagó $30.000, quedan $10.000 a favor"
    [stored] = credits(db, membership)
    assert stored["id"] == uuid.UUID(credit["id"])


@pg
def test_a_partial_payment_leaves_the_period_open(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    entry = claimed(client, sur, ana, 20000)

    body = validate(client, sur, entry["id"]).json()

    assert (body["period"]["outstanding_clp"], body["period"]["closed"]) == (10000, False)
    [period] = periods(client, sur, ana)
    assert period["outstanding_clp"] == 10000


@pg
def test_a_period_paid_meanwhile_is_a_conflict(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    first = claimed(client, sur, ana, 30000)
    second = claimed(client, sur, ana, 30000)
    assert validate(client, sur, first["id"]).status_code == 200

    response = validate(client, sur, second["id"])

    assert response.status_code == 409
    assert stored_entry(db, second["id"])["status"] == "pending"
    # The admin rejects it instead.
    assert reject(client, sur, second["id"], "ya estaba pagado").status_code == 200


@pg
def test_rejecting_keeps_the_period_open_and_tells_the_student(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(0, 45000, 0, 0)])
    entry = claimed(client, sur, ana, 40000)
    admin = add_staff(db, sur, "admin")
    mailer.sent.clear()

    response = reject(
        client, sur, entry["id"], "  monto no coincide, falta $5.000 ", person_id=admin
    )

    assert response.status_code == 200, response.text
    rejected = response.json()
    assert (rejected["id"], rejected["status"]) == (entry["id"], "rejected")
    assert rejected["note"] == "monto no coincide, falta $5.000"
    assert rejected["validated_by"] == str(admin)
    [period] = periods(client, sur, ana)
    assert (period["outstanding_clp"], period["pending_clp"]) == (45000, 0)
    assert pending(client, sur) == 0
    assert credits(db, membership) == []
    [email] = mailer.sent
    assert email.to == "ana@example.cl"
    assert email.subject == "Revisa tu comprobante"
    assert "Hola, Ana:" in email.text
    assert "$40.000" in email.text
    assert "Nota: monto no coincide, falta $5.000" in email.text


@pg
def test_a_rejection_reaches_the_guardian(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    bill(db, sur, juan, [(0, 25000, 0, 0)])
    entry = claimed(client, sur, juan, 25000, by=marta)
    [item] = queue(client, sur)
    assert (item["person_name"], item["claimed_by_name"]) == ("Juan", "Marta")
    mailer.sent.clear()

    assert reject(client, sur, entry["id"], "ilegible").status_code == 200

    [email] = mailer.sent
    assert email.to == "marta@example.cl"
    assert "de Juan" in email.text


@pg
def test_a_rejection_without_a_note_is_refused(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    entry = claimed(client, sur, ana, 30000)

    for note in (None, "", "   "):
        assert reject(client, sur, entry["id"], note).status_code == 422
    assert stored_entry(db, entry["id"])["status"] == "pending"


@pg
@pytest.mark.parametrize("first", ["validate", "reject"])
def test_a_proof_is_reviewed_once(
    client: TestClient, db: Database, sur: uuid.UUID, first: str
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    entry = claimed(client, sur, ana, 10000)
    review = {"validate": lambda: validate(client, sur, entry["id"])}
    review["reject"] = lambda: reject(client, sur, entry["id"], "no")
    assert review[first]().status_code == 200

    assert validate(client, sur, entry["id"]).status_code == 409
    assert reject(client, sur, entry["id"], "otra vez").status_code == 409
    assert stored_entry(db, entry["id"])["status"] == (
        "validated" if first == "validate" else "rejected"
    )


@pg
def test_only_a_pending_proof_is_found(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    membership = bill(db, sur, ana, [(0, 30000, 0, 0)])
    # An admin's recorded payment has no proof to review.
    [period] = periods(client, sur, ana)
    recorded = client.post(
        "/api/ledger/payments",
        json={
            "membership_id": membership,
            "billing_period_id": period["id"],
            "amount_clp": 1000,
            "method": "cash",
        },
        headers=as_gym(sur),
    ).json()["payment"]
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    entry = claimed(client, sur, ana, 10000)

    for gym, entry_id in ((sur, recorded["id"]), (sur, str(uuid.uuid4())), (norte, entry["id"])):
        assert validate(client, gym, entry_id).status_code == 404
        assert reject(client, gym, entry_id, "no").status_code == 404
    assert stored_entry(db, entry["id"])["status"] == "pending"


@pg
def test_a_missing_proof_file_is_still_reviewable(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    entry = claimed(client, sur, ana, 30000)

    # The file is gone from storage, the entry still waits.
    store = client.app.state.integrations.blob_store  # type: ignore[attr-defined]
    asyncio.run(store.delete(entry["proof_object_key"]))

    [item] = queue(client, sur)
    assert (item["proof_url"], item["proof_content_type"]) == (None, None)
    assert validate(client, sur, entry["id"]).status_code == 200


@pg
def test_prior_balance_counts_only_periods_already_due(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    # Last month owing 30.000 (the one claimed), this month 20.000 left, next not due.
    bill(db, sur, ana, [(-30, 30000, 0, 0), (-1, 30000, 10000, 0), (20, 30000, 0, 0)])
    claimed(client, sur, ana, 30000)

    [item] = queue(client, sur)

    assert item["period"]["due_date"] == str(date.today() - timedelta(days=30))
    assert item["prior_balance_clp"] == 20000
    assert [p["amount_clp"] for p in item["last_payments"]] == [10000]


@pg
def test_an_unauthenticated_review_is_refused(client: TestClient) -> None:
    entry = str(uuid.uuid4())
    assert client.get("/api/ledger/proofs").status_code == 401
    assert client.post(f"/api/ledger/proofs/{entry}/validate").status_code == 401
    assert client.post(f"/api/ledger/proofs/{entry}/reject", json={"note": "x"}).status_code == 401
