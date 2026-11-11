"""A double tap runs once (#201, #203, #204, #208).

The web app sends one `Idempotency-Key` per submission (`app.idempotency`), so a
second request with it waits for the first and gets its answer back instead of
running again. Two submissions with different keys, from two tabs, are two requests;
where that would duplicate someone, the endpoint itself serialises them: an invite
of one email (#204) and an import (#203) take a lock per gym.
"""

import asyncio
import dataclasses
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db_bootstrap import to_dsn
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_guardians import add_person
from tests.test_join import adult, roomy_limits, with_privacy
from tests.test_ledger_payments import new_period
from tests.test_member_import import PILOT, PLANS
from tests.test_plans import add_staff
from tests.test_proofs import PDF, RecordingMailer
from tests.test_sessions import class_type

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
def app(db: Database, mailer: RecordingMailer, tmp_path_factory: pytest.TempPathFactory) -> FastAPI:
    app = create_app(
        make_settings(
            database_url=db.api_url,
            blob_store="local",
            blob_local_dir=tmp_path_factory.mktemp("blobs"),
            public_base_url="http://testserver",
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.state.join_limits = roomy_limits()
    app.add_middleware(FakeAuth)
    return app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def keyed(key: str, headers: dict[str, str] | None = None) -> dict[str, str]:
    return {**(headers or {}), "Idempotency-Key": key}


def at_once(*calls: Callable[[], Any]) -> list[Any]:
    """Run `calls` together, each in a thread of its own, released at the same moment."""
    barrier = threading.Barrier(len(calls))

    def go(call: Callable[[], Any]) -> Any:
        barrier.wait()
        return call()

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(go, calls))


def count(db: Database, gym: uuid.UUID, sql: str, *args: object) -> int:
    rows = run(db.owner_url, in_gym(gym, sql, *args))
    n: int = rows[0][0]
    return n


def payments(db: Database, gym: uuid.UUID, period: dict[str, str]) -> int:
    return count(
        db,
        gym,
        "SELECT count(*) FROM ledger_entry WHERE kind = 'payment' AND billing_period_id = $1",
        uuid.UUID(period["billing_period_id"]),
    )


def pay(client: TestClient, gym: uuid.UUID, period: dict[str, str], key: str | None) -> Any:
    body = {**period, "amount_clp": 20_000, "method": "cash", "note": "abono parcial"}
    headers = as_gym(gym) if key is None else keyed(key, as_gym(gym))
    return client.post("/api/ledger/payments", json=body, headers=headers)


# --- Registrar pago (#201) ------------------------------------------------------------


def test_a_double_tap_records_the_payment_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    period = new_period(db, gym)
    key = str(uuid.uuid4())
    first, second = at_once(
        lambda: pay(client, gym, period, key), lambda: pay(client, gym, period, key)
    )

    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    assert first.json() == second.json()
    replayed = [r.headers.get("idempotent-replayed") for r in (first, second)]
    assert replayed.count("true") == 1
    assert payments(db, gym, period) == 1
    assert first.json()["period"]["paid_clp"] == 20_000


def test_the_same_key_later_gets_the_same_answer_and_records_nothing(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    period = new_period(db, gym)
    key = str(uuid.uuid4())
    first = pay(client, gym, period, key)
    again = pay(client, gym, period, key)

    assert first.status_code == again.status_code == 201
    assert again.headers["idempotent-replayed"] == "true"
    assert again.json() == first.json()
    assert payments(db, gym, period) == 1


def test_a_new_key_is_a_new_payment(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    period = new_period(db, gym)
    assert pay(client, gym, period, str(uuid.uuid4())).status_code == 201
    assert pay(client, gym, period, str(uuid.uuid4())).status_code == 201
    assert payments(db, gym, period) == 2


def test_a_repeat_waits_for_the_first_to_finish(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """The first holds the key while it runs: here, while a lock it needs is held."""
    period = new_period(db, gym)
    key = str(uuid.uuid4())

    async def go() -> None:
        holder = await asyncpg.connect(to_dsn(db.admin_url))
        try:
            await holder.execute("BEGIN")
            await holder.execute(
                "SELECT FROM membership WHERE id = $1 FOR UPDATE",
                uuid.UUID(period["membership_id"]),
            )
            with ThreadPoolExecutor(2) as pool:
                first = asyncio.wrap_future(pool.submit(pay, client, gym, period, key))
                await asyncio.sleep(0.5)
                second = asyncio.wrap_future(pool.submit(pay, client, gym, period, key))
                await asyncio.sleep(0.5)
                assert not first.done() and not second.done()
                await holder.execute("COMMIT")
                one, two = await first, await second
            assert (one.status_code, two.status_code) == (201, 201), (one.text, two.text)
            assert two.headers["idempotent-replayed"] == "true"
            assert two.json() == one.json()
        finally:
            await holder.close()

    asyncio.run(go())
    assert payments(db, gym, period) == 1


def test_a_refused_request_releases_its_key(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """A refusal wrote nothing, so the same submission, fixed, runs."""
    period = new_period(db, gym)
    key = str(uuid.uuid4())
    unknown = {**period, "billing_period_id": str(uuid.uuid4())}
    refused = pay(client, gym, unknown, key)
    assert refused.status_code == 404, refused.text

    assert pay(client, gym, period, key).status_code == 201
    assert payments(db, gym, period) == 1


def test_a_key_is_not_reused_for_another_request(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    period = new_period(db, gym)
    key = str(uuid.uuid4())
    assert pay(client, gym, period, key).status_code == 201

    other = client.post("/api/programs", json={"name": "Kids"}, headers=keyed(key, as_gym(gym)))
    assert other.status_code == 422, other.text
    assert other.json()["detail"]["code"] == "idempotency_key_reused"


def test_a_key_is_the_gyms_and_the_persons(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """The same key from another gym, or another person, is another submission."""
    key = str(uuid.uuid4())
    other_gym = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    admin = add_staff(db, gym, "admin")
    for where in (gym, other_gym):
        assert pay(client, where, new_period(db, where), key).status_code == 201
    period = new_period(db, gym)
    body = {**period, "amount_clp": 20_000, "method": "cash"}
    by_admin = client.post(
        "/api/ledger/payments", json=body, headers=keyed(key, as_gym(gym, admin))
    )
    assert by_admin.status_code == 201, by_admin.text
    assert "idempotent-replayed" not in by_admin.headers
    assert payments(db, gym, period) == 1


def test_keys_older_than_a_day_are_forgotten(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    period = new_period(db, gym)
    key = str(uuid.uuid4())
    assert pay(client, gym, period, key).status_code == 201
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE idempotency_key SET created_at = now() - interval '25 hours' WHERE key = $1",
            key,
        ),
    )
    again = pay(client, gym, period, key)
    assert again.status_code == 201
    assert "idempotent-replayed" not in again.headers
    assert payments(db, gym, period) == 2


def test_a_scope_sees_only_its_own_keys(db: Database, gym: uuid.UUID) -> None:
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO idempotency_key (gym_id, person_id, key, fingerprint)"
            " VALUES ($1, $2, 'k', 'POST /x'), (NULL, NULL, 'k', 'POST /y')",
            gym,
            uuid.uuid4(),
        ),
    )
    rows = run(db.api_url, in_gym(gym, "SELECT key FROM idempotency_key", person=uuid.uuid4()))
    assert rows == []
    anonymous = run(db.api_url, in_gym(None, "SELECT fingerprint FROM idempotency_key"))
    assert [r["fingerprint"] for r in anonymous] == ["POST /y"]


# --- Importar (#203) --------------------------------------------------------------------


@pytest.fixture
def importing(client: TestClient, db: Database) -> uuid.UUID:
    gym_id = seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")
    for plan in PLANS:
        response = client.post("/api/plans", json=plan, headers=as_gym(gym_id))
        assert response.status_code == 201, response.text
    return gym_id


def import_pilot(client: TestClient, gym: uuid.UUID, key: str | None) -> Any:
    sheet = client.post(
        "/api/import/sheet", content=PILOT, headers={"Content-Type": "text/csv", **as_gym(gym)}
    ).json()
    body = {"rows": sheet["rows"], "mapping": sheet["mapping"], "plans": {}, "dry_run": False}
    headers = as_gym(gym) if key is None else keyed(key, as_gym(gym))
    return client.post("/api/import/members", json=body, headers=headers)


def people(db: Database, gym: uuid.UUID) -> tuple[int, int, int]:
    return (
        count(db, gym, "SELECT count(*) FROM gym_person"),
        count(db, gym, "SELECT count(*) FROM membership"),
        count(db, gym, "SELECT count(*) FROM guardian_link"),
    )


def test_a_double_tap_on_importar_imports_once(
    client: TestClient, db: Database, importing: uuid.UUID
) -> None:
    key = str(uuid.uuid4())
    first, second = at_once(
        lambda: import_pilot(client, importing, key), lambda: import_pilot(client, importing, key)
    )
    assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
    assert first.json() == second.json()

    once = people(db, importing)
    assert import_pilot(client, importing, None).status_code == 200
    assert people(db, importing) == once


def test_two_imports_at_once_create_nobody_twice(
    client: TestClient, db: Database, importing: uuid.UUID
) -> None:
    """Two tabs, two keys: the second waits for the first and matches its people."""
    first, second = at_once(
        lambda: import_pilot(client, importing, None), lambda: import_pilot(client, importing, None)
    )
    assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)

    both = people(db, importing)
    assert import_pilot(client, importing, None).status_code == 200
    assert people(db, importing) == both
    assert (
        count(
            db,
            importing,
            "SELECT count(*) FROM"
            " (SELECT name FROM gym_person GROUP BY name HAVING count(*) > 1) twice",
        )
        == 0
    )


# --- Enviar invitación (#204) ---------------------------------------------------------


def invite(client: TestClient, gym: uuid.UUID, key: str | None, email: str) -> Any:
    body = {"name": "Coach Nuevo", "email": email, "role": "coach"}
    headers = as_gym(gym) if key is None else keyed(key, as_gym(gym))
    return client.post("/api/staff", json=body, headers=headers)


def with_email(db: Database, gym: uuid.UUID, email: str) -> int:
    return count(db, gym, "SELECT count(*) FROM gym_person WHERE lower(email) = $1", email)


def test_a_double_tap_on_enviar_invitacion_invites_once(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    key, email = str(uuid.uuid4()), f"coach.{uuid.uuid4().hex[:6]}@example.cl"
    first, second = at_once(
        lambda: invite(client, gym, key, email), lambda: invite(client, gym, key, email)
    )
    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    assert first.json() == second.json()
    assert with_email(db, gym, email) == 1
    assert sum(sent.to == email for sent in mailer.sent) == 1


def test_two_invites_of_one_email_at_once_make_one_person(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    email = f"coach.{uuid.uuid4().hex[:6]}@example.cl"
    answers = at_once(
        lambda: invite(client, gym, None, email), lambda: invite(client, gym, None, email.upper())
    )
    assert sorted(r.status_code for r in answers) == [201, 409], [r.text for r in answers]
    assert with_email(db, gym, email) == 1


# --- Enviar comprobante, Crear clase, Enviar inscripción (#208) -----------------------


def test_a_double_tap_on_enviar_comprobante_claims_once(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """The form sends `<key>:upload` for the upload URL and `<key>:claim` for the claim."""
    ana = add_person(client, gym, "Ana")
    headers = as_gym(gym, uuid.UUID(ana))
    period = new_period(db, gym)
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE membership SET person_id = $1 WHERE id = $2",
            uuid.UUID(ana),
            uuid.UUID(period["membership_id"]),
        ),
    )
    key = str(uuid.uuid4())

    def send() -> Any:
        ticket = client.post(
            "/api/me/proofs",
            json={"content_type": "application/pdf", "size_bytes": len(PDF)},
            headers=keyed(f"{key}:upload", headers),
        )
        assert ticket.status_code == 201, ticket.text
        put = client.put(ticket.json()["url"], content=PDF, headers=ticket.json()["headers"])
        assert put.status_code == 200, put.text
        return client.post(
            "/api/me/payments",
            json={
                "billing_period_id": period["billing_period_id"],
                "amount_clp": 20_000,
                "proof_key": ticket.json()["key"],
            },
            headers=keyed(f"{key}:claim", headers),
        )

    first, second = at_once(send, send)
    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    assert first.json() == second.json()
    pending = count(
        db,
        gym,
        "SELECT count(*) FROM ledger_entry WHERE status = 'pending' AND billing_period_id = $1",
        uuid.UUID(period["billing_period_id"]),
    )
    assert pending == 1


def test_a_double_tap_on_crear_clase_creates_one_class(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    fundamentals = class_type(client, gym)
    coach = add_staff(db, gym, "coach")
    key = str(uuid.uuid4())

    def start() -> Any:
        return client.post(
            "/api/sessions",
            json={"class_type_id": fundamentals["id"]},
            headers=keyed(key, as_gym(gym, coach)),
        )

    first, second = at_once(start, start)
    assert (first.status_code, second.status_code) == (201, 201), (first.text, second.text)
    assert first.json()["id"] == second.json()["id"]
    assert count(db, gym, "SELECT count(*) FROM session") == 1


def test_a_double_tap_on_enviar_inscripcion_leaves_one_request(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """Anonymous: the key is nobody's, and the token in the path tells the gym."""
    with_privacy(client, gym)
    link = client.post("/api/join-link", json={}, headers=as_gym(gym))
    assert link.status_code == 201, link.text
    token, body, key = link.json()["token"], adult(), str(uuid.uuid4())

    def submit() -> Any:
        return client.post(f"/api/join/{token}", json=body, headers=keyed(key))

    first, second = at_once(submit, submit)
    assert (first.status_code, second.status_code) == (202, 202), (first.text, second.text)
    assert count(db, gym, "SELECT count(*) FROM join_request") == 1
