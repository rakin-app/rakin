"""A student uploads a transfer proof and claims the payment (#35).

The proof goes to the BlobStore through a presigned PUT, never through the API; the
claim records a pending transfer pointing at it, emails "proof received" to whoever
gets the student's notices, and shows up in the admin's pending count.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.integrations.blobstore import MAX_UPLOAD_BYTES
from app.integrations.mailer import Email
from app.main import create_app
from app.schemas.plans import MAX_PRICE_CLP
from app.schemas.proofs import ProofClaim, ProofUploadRequest
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_guardians import add_person, bill, new_kid
from tests.test_plans import add_staff

PDF = b"%PDF-1.7\n" + b"0" * 100

# --- input rules, no database -----------------------------------------------------


@pytest.mark.parametrize(
    "content_type", ["image/jpeg", "image/png", "image/heic", "application/pdf"]
)
def test_an_upload_takes_an_image_or_a_pdf(content_type: str) -> None:
    body = ProofUploadRequest.model_validate({"content_type": content_type, "size_bytes": 1})
    assert body.content_type == content_type


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "text/html", "size_bytes": 10},
        {"content_type": "image/svg+xml", "size_bytes": 10},
        {"content_type": "image/png", "size_bytes": 0},
        {"content_type": "image/png", "size_bytes": MAX_UPLOAD_BYTES + 1},
        {"content_type": "image/png", "size_bytes": "10"},
        {"content_type": "image/png"},
        {"size_bytes": 10},
        {"content_type": "image/png", "size_bytes": 10, "key": "proofs/x"},
    ],
    ids=str,
)
def test_an_upload_refuses(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProofUploadRequest.model_validate(body)


@pytest.mark.parametrize(
    "extra",
    [
        {"amount_clp": 0},
        {"amount_clp": -1},
        {"amount_clp": MAX_PRICE_CLP + 1},
        {"status": "validated"},
        {"method": "cash"},
    ],
    ids=str,
)
def test_a_claim_refuses(extra: dict[str, Any]) -> None:
    body = {"billing_period_id": str(uuid.uuid4()), "amount_clp": 1, "proof_key": "k", **extra}
    with pytest.raises(ValidationError):
        ProofClaim.model_validate(body)


def test_a_claim_may_exceed_what_is_owed_up_to_the_price_ceiling() -> None:
    body = {"billing_period_id": str(uuid.uuid4()), "proof_key": "k", "amount_clp": MAX_PRICE_CLP}
    assert ProofClaim.model_validate(body).amount_clp == MAX_PRICE_CLP


# --- against real Postgres --------------------------------------------------------

pg = pytest.mark.postgres


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


def sent_notices(db: Database, gym: uuid.UUID) -> list[tuple[str, str, str]]:
    """`gym`'s `message_log`, oldest first: template, addressee and outcome."""
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT template, person_id, status FROM message_log"
            " WHERE gym_id = $1 ORDER BY sent_at",
            gym,
        ),
    )
    return [(r["template"], str(r["person_id"]), r["status"]) for r in rows]


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


def me(person: str) -> uuid.UUID:
    return uuid.UUID(person)


def upload(
    client: TestClient, gym: uuid.UUID, person: str, body: bytes = PDF, ct: str = "application/pdf"
) -> str:
    """Ask for an upload URL and PUT `body` there, as the browser does; returns the key."""
    ticket = client.post(
        "/api/me/proofs",
        json={"content_type": ct, "size_bytes": len(body)},
        headers=as_gym(gym, me(person)),
    )
    assert ticket.status_code == 201, ticket.text
    put = client.put(ticket.json()["url"], content=body, headers=ticket.json()["headers"])
    assert put.status_code == 200, put.text
    key: str = ticket.json()["key"]
    return key


def periods(client: TestClient, gym: uuid.UUID, person: str) -> list[dict[str, Any]]:
    response = client.get("/api/me/periods", headers=as_gym(gym, me(person)))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def claim(
    client: TestClient, gym: uuid.UUID, person: str, period: str, key: str, amount: int = 30000
) -> Any:
    return client.post(
        "/api/me/payments",
        json={"billing_period_id": period, "amount_clp": amount, "proof_key": key},
        headers=as_gym(gym, me(person)),
    )


def pending(client: TestClient, gym: uuid.UUID) -> int:
    response = client.get("/api/ledger/pending", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    count: int = response.json()["count"]
    return count


def stored_entry(db: Database, entry_id: str) -> dict[str, Any]:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow("SELECT * FROM ledger_entry WHERE id = $1", uuid.UUID(entry_id)),
    )
    return dict(row)


@pg
def test_a_student_uploads_a_proof_and_claims_the_period(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(-3, 30000, 0, 0)])
    [period] = periods(client, sur, ana)
    assert (period["person_name"], period["outstanding_clp"], period["pending_clp"]) == (
        "Ana",
        30000,
        0,
    )
    assert pending(client, sur) == 0

    key = upload(client, sur, ana)
    assert key.startswith(f"proofs/{sur}/{ana}/")
    mailer.sent.clear()
    response = claim(client, sur, ana, period["id"], key)

    assert response.status_code == 201, response.text
    entry = response.json()
    assert (entry["kind"], entry["status"], entry["method"]) == ("payment", "pending", "transfer")
    assert entry["amount_clp"] == 30000
    assert entry["billing_period_id"] == period["id"]
    assert entry["claimed_by"] == ana
    assert entry["claimed_at"] is not None
    assert entry["validated_by"] is None
    assert entry["proof_object_key"] == key
    row = stored_entry(db, entry["id"])
    assert row["proof_object_key"] == key
    assert row["gym_id"] == sur

    # Pending, not paid: the period is still open, with the claim waiting.
    [after] = periods(client, sur, ana)
    assert (after["outstanding_clp"], after["pending_clp"]) == (30000, 30000)
    assert pending(client, sur) == 1

    [email] = mailer.sent
    assert email.to == "ana@example.cl"
    assert email.subject == "Recibimos tu comprobante"
    assert "$30.000" in email.text
    assert "Hola, Ana:" in email.text
    assert sent_notices(db, sur) == [("proof_received", ana, "sent")]


@pg
def test_a_guardian_claims_for_a_dependent_and_gets_the_email(
    client: TestClient, db: Database, sur: uuid.UUID, mailer: RecordingMailer
) -> None:
    marta = add_person(client, sur, "Marta")
    juan = new_kid(client, sur, marta, "Juan")
    bill(db, sur, juan, [(-1, 25000, 0, 0)])
    [period] = periods(client, sur, marta)
    assert period["person_id"] == juan

    mailer.sent.clear()
    response = claim(client, sur, marta, period["id"], upload(client, sur, marta), 25000)

    assert response.status_code == 201, response.text
    assert response.json()["claimed_by"] == marta
    [email] = mailer.sent
    assert email.to == "marta@example.cl"
    assert "de Juan" in email.text


@pg
def test_an_image_from_the_camera_is_accepted(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    [period] = periods(client, sur, ana)
    key = upload(client, sur, ana, b"\xff\xd8\xff" + b"0" * 50, "image/jpeg")

    assert claim(client, sur, ana, period["id"], key).status_code == 201


@pg
def test_only_open_periods_are_listed(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(-35, 30000, 30000, 0), (-5, 30000, 10000, 0), (25, 30000, 0, 0)])

    listed = periods(client, sur, ana)

    assert [(p["paid_clp"], p["outstanding_clp"]) for p in listed] == [(10000, 20000), (0, 30000)]


@pg
def test_a_claim_without_the_upload_is_refused(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    [period] = periods(client, sur, ana)
    ticket = client.post(
        "/api/me/proofs",
        json={"content_type": "image/png", "size_bytes": 10},
        headers=as_gym(sur, me(ana)),
    )

    response = claim(client, sur, ana, period["id"], ticket.json()["key"])

    assert response.status_code == 422
    assert pending(client, sur) == 0


@pg
def test_someone_elses_upload_cannot_be_claimed(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    [period] = periods(client, sur, ana)
    beas = upload(client, sur, bea)

    for key in (beas, "proofs/other.jpg", f"proofs/{sur}/{ana}/../{bea}/x"):
        assert claim(client, sur, ana, period["id"], key).status_code == 422


@pg
def test_a_proof_backs_one_claim(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    [period] = periods(client, sur, ana)
    key = upload(client, sur, ana, ct="application/pdf")

    assert claim(client, sur, ana, period["id"], key, 10000).status_code == 201
    again = claim(client, sur, ana, period["id"], key, 10000)

    assert again.status_code == 409
    assert pending(client, sur) == 1


@pg
def test_another_persons_period_is_not_found(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    bill(db, sur, bea, [(0, 30000, 0, 0)])
    [beas] = periods(client, sur, bea)

    assert periods(client, sur, ana) == []
    assert claim(client, sur, ana, beas["id"], upload(client, sur, ana)).status_code == 404
    assert pending(client, sur) == 0


@pg
def test_another_gyms_period_is_not_found(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    norte = seed_gym(db, f"dojo-norte-{uuid.uuid4().hex[:6]}")
    ana = add_person(client, norte, "Ana")
    bill(db, norte, ana, [(0, 30000, 0, 0)])
    [theirs] = periods(client, norte, ana)

    # Ana acting in Sur, where she has nothing.
    assert claim(client, sur, ana, theirs["id"], upload(client, sur, ana)).status_code == 404


@pg
def test_a_period_paid_in_full_is_a_conflict(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 30000, 0)])
    period = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT bp.id FROM billing_period bp JOIN membership m ON m.id = bp.membership_id"
            " WHERE m.person_id = $1",
            uuid.UUID(ana),
        ),
    )

    assert claim(client, sur, ana, str(period), upload(client, sur, ana)).status_code == 409


@pg
def test_a_claim_above_what_is_owed_is_taken_for_review(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bill(db, sur, ana, [(0, 30000, 0, 0)])
    [period] = periods(client, sur, ana)

    response = claim(client, sur, ana, period["id"], upload(client, sur, ana), 60000)

    assert response.status_code == 201, response.text
    assert claim(client, sur, ana, period["id"], "x", MAX_PRICE_CLP + 1).status_code == 422


@pg
@pytest.mark.parametrize(
    ("role", "expected"),
    [("owner", "owner"), ("admin", "admin"), ("coach", "coach"), ("member", None)],
)
def test_my_role_is_the_staff_role_or_none(
    client: TestClient, db: Database, sur: uuid.UUID, role: str, expected: str | None
) -> None:
    if role == "owner":
        person = None
    elif role == "member":
        person = uuid.UUID(add_person(client, sur, "Ana"))
    else:
        person = add_staff(db, sur, role)
    response = client.get("/api/me/role", headers=as_gym(sur, person))
    assert response.status_code == 200, response.text
    assert response.json()["role"] == expected
    if person is not None:
        assert response.json()["person_id"] == str(person)


@pg
def test_my_role_names_who_is_signed_in_and_the_gym(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    owner = client.get("/api/me/role", headers=as_gym(sur))
    assert owner.status_code == 200, owner.text
    slug = owner.json()["gym_name"]
    assert slug.startswith("academia-sur-")
    assert owner.json()["name"] == f"owner of {slug}"
    coach = client.get("/api/me/role", headers=as_gym(sur, add_staff(db, sur, "coach")))
    assert coach.json() | {"person_id": None} == {
        "role": "coach",
        "person_id": None,
        "name": "x",
        "email": None,
        "gym_name": slug,
    }


@pg
def test_an_unauthenticated_request_is_refused(client: TestClient) -> None:
    body = {"content_type": "image/png", "size_bytes": 10}
    assert client.post("/api/me/proofs", json=body).status_code == 401
    assert client.post("/api/me/payments", json={}).status_code == 401
    assert client.get("/api/me/periods").status_code == 401
    assert client.get("/api/me/role").status_code == 401


@pg
@pytest.mark.parametrize("role", ["coach", "member"])
def test_only_an_owner_or_admin_sees_the_pending_count(
    client: TestClient, db: Database, sur: uuid.UUID, role: str
) -> None:
    person = add_staff(db, sur, "coach") if role == "coach" else uuid.uuid4()
    response = client.get("/api/ledger/pending", headers=as_gym(sur, person))
    assert response.status_code == 403
    assert client.get(
        "/api/ledger/pending", headers=as_gym(sur, add_staff(db, sur, "admin"))
    ).json() == {"count": 0}


# --- the table on its own (migration 0012) ----------------------------------------


def insert_as(db: Database, gym: uuid.UUID, person: str, membership: str, **columns: Any) -> Any:
    values = {
        "kind": "payment",
        "status": "pending",
        "method": "transfer",
        "claimed_by": uuid.UUID(person),
        "proof_object_key": f"proofs/{gym}/{person}/{uuid.uuid4()}",
        "validated_by": None,
        **columns,
    }
    return run(
        db.api_url,
        in_gym(
            gym,
            "INSERT INTO ledger_entry (gym_id, membership_id, amount_clp, kind, status, method,"
            " claimed_by, claimed_at, proof_object_key, validated_by, validated_at)"
            " VALUES ($1, $2, 1000, $3, $4, $5, $6, now(), $7, $8,"
            " CASE WHEN $8::uuid IS NULL THEN NULL ELSE now() END) RETURNING id",
            gym,
            uuid.UUID(membership),
            values["kind"],
            values["status"],
            values["method"],
            values["claimed_by"],
            values["proof_object_key"],
            values["validated_by"],
            person=uuid.UUID(person),
        ),
    )


@pg
def test_the_table_lets_a_member_add_only_a_pending_transfer_with_their_proof(
    client: TestClient, db: Database, sur: uuid.UUID
) -> None:
    ana = add_person(client, sur, "Ana")
    bea = add_person(client, sur, "Bea")
    mine = bill(db, sur, ana, [])
    hers = bill(db, sur, bea, [])

    assert len(insert_as(db, sur, ana, mine)) == 1
    for refused in (
        {"status": "validated", "validated_by": uuid.UUID(ana)},
        {"kind": "adjustment"},
        {"method": "cash"},
        {"claimed_by": uuid.UUID(bea)},
        {"proof_object_key": f"proofs/{sur}/{bea}/{uuid.uuid4()}"},
        {"proof_object_key": None},
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            insert_as(db, sur, ana, mine, **refused)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        insert_as(db, sur, ana, hers)


@pg
def test_the_table_takes_a_proof_once(client: TestClient, db: Database, sur: uuid.UUID) -> None:
    ana = add_person(client, sur, "Ana")
    mine = bill(db, sur, ana, [])
    key = f"proofs/{sur}/{ana}/{uuid.uuid4()}"
    insert_as(db, sur, ana, mine, proof_object_key=key)

    with pytest.raises(asyncpg.UniqueViolationError):
        insert_as(db, sur, ana, mine, proof_object_key=key)


@pg
def test_upgrade_and_downgrade_0012() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0011")
        migrate(scratch)
        command.downgrade(scratch.alembic(), "0011")
        migrate(scratch)
