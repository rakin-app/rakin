"""Resend's bounce and complaint webhook (#104): the Svix signature, the suppression it
writes, the mail that then never goes, and the ficha that says why.

The signature and the events need nothing; the suppression runs against real Postgres.
"""

import asyncio
import base64
import dataclasses
import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app.api.webhooks import RESEND_PATH, recipients, suppressions
from app.integrations.svix import SignatureError, sign, signing_key, verify
from app.main import create_app
from app.notices import MAGIC_LINK, Notice, Notices, Outcome
from tests.auth import FakeAuth, as_gym
from tests.conftest import UNREACHABLE_DB, make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_member_roll import enrolled, welcome
from tests.test_proofs import RecordingMailer, sent_notices

pg = pytest.mark.postgres

SECRET = "whsec_" + base64.b64encode(b"a test signing secret, 24+").decode()
KEY = signing_key(SECRET)


def signed(
    event: dict[str, Any] | bytes,
    *,
    key: bytes = KEY,
    at: float | None = None,
    msg_id: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    """`event` as Resend delivers it: the body and its Svix headers."""
    body = event if isinstance(event, bytes) else json.dumps(event).encode()
    msg_id = msg_id or f"msg_{uuid.uuid4().hex}"
    timestamp = str(int(time.time() if at is None else at))
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{sign(key, msg_id, timestamp, body)}",
        "content-type": "application/json",
    }
    return body, headers


def bounced(*to: str, kind: str = "Permanent") -> dict[str, Any]:
    return {
        "type": "email.bounced",
        "created_at": "2026-11-13T12:00:00.000Z",
        "data": {
            "email_id": str(uuid.uuid4()),
            "from": "Rakin <no-reply@rakin.app>",
            "to": list(to),
            "subject": "Bienvenida",
            "bounce": {
                "type": kind,
                "subType": "General",
                "message": "550 5.1.1 The email account does not exist.",
            },
        },
    }


def complained(*to: str) -> dict[str, Any]:
    return {
        "type": "email.complained",
        "created_at": "2026-11-13T12:00:00.000Z",
        "data": {"email_id": str(uuid.uuid4()), "to": list(to), "subject": "Aviso"},
    }


# --- the signature --------------------------------------------------------------


def test_svixs_own_example_verifies() -> None:
    # The example in Svix's "verifying manually" docs.
    key = signing_key("whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
    headers = {
        "svix-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "svix-timestamp": "1614265330",
        "svix-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }
    verify(key, headers, b'{"test": 2432232314}', now=1614265330)


def test_any_one_matching_signature_will_do() -> None:
    body, headers = signed(complained("a@example.com"))
    headers["svix-signature"] = f"v1,bm90IGl0 v2,whatever {headers['svix-signature']}"
    verify(KEY, headers, body)


@pytest.mark.parametrize("missing", ["svix-id", "svix-timestamp", "svix-signature"])
def test_an_unsigned_delivery_is_refused(missing: str) -> None:
    body, headers = signed(complained("a@example.com"))
    del headers[missing]
    with pytest.raises(SignatureError, match="missing"):
        verify(KEY, headers, body)


def test_another_secret_or_a_changed_body_is_refused() -> None:
    body, headers = signed(complained("a@example.com"), key=b"someone else's key")
    with pytest.raises(SignatureError, match="no matching"):
        verify(KEY, headers, body)
    body, headers = signed(complained("a@example.com"))
    with pytest.raises(SignatureError, match="no matching"):
        verify(KEY, headers, body.replace(b"a@example.com", b"b@example.com"))


@pytest.mark.parametrize("off_by", [-301, 301])
def test_a_delivery_stamped_too_far_from_now_is_a_replay(off_by: int) -> None:
    body, headers = signed(complained("a@example.com"), at=time.time() + off_by)
    with pytest.raises(SignatureError, match="too far"):
        verify(KEY, headers, body)


def test_a_signature_of_another_version_is_not_v1s() -> None:
    body, headers = signed(complained("a@example.com"))
    headers["svix-signature"] = headers["svix-signature"].replace("v1,", "v1a,")
    with pytest.raises(SignatureError):
        verify(KEY, headers, body)


def test_a_secret_that_is_not_svixs_is_a_settings_error() -> None:
    with pytest.raises(ValidationError, match="Svix"):
        make_settings(resend_webhook_secret="whsec_not base64!")
    assert make_settings(resend_webhook_secret=f" {SECRET} ").resend_webhook_secret == SECRET


# --- the events -----------------------------------------------------------------


def test_a_hard_bounce_and_a_complaint_suppress() -> None:
    assert suppressions(bounced("a@example.com")) == (
        "bounce",
        "550 5.1.1 The email account does not exist.",
    )
    assert suppressions(complained("a@example.com")) == ("complaint", None)


def test_the_recipients_are_keyed_as_the_table_holds_them() -> None:
    event = bounced("Ana <ANA@Example.com>", " ana@example.com ", "@nadie", "", "b@example.com")
    assert recipients(event) == ["ana@example.com", "b@example.com"]
    assert recipients({"data": {"to": "c@example.com"}}) == ["c@example.com"]
    assert recipients({"data": {"to": None}}) == []


@pytest.mark.parametrize(
    "event",
    [
        bounced("a@example.com", kind="Transient"),
        bounced("a@example.com", kind="Undetermined"),
        {"type": "email.delivered", "data": {"to": ["a@example.com"]}},
        {"type": "email.bounced"},
        [],
    ],
)
def test_nothing_else_does(event: Any) -> None:
    assert suppressions(event) is None


# --- the mailer, with no database -----------------------------------------------


def test_a_suppression_that_cannot_be_checked_does_not_stop_the_notice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`send` never raises: with the database down the sign-in link still goes."""

    def no_database() -> Any:
        raise OSError("connection refused")

    mailer = RecordingMailer()
    notices = Notices(mailer, no_database, base_url="https://rakin.test", secret_key="x" * 16)
    notice = Notice(MAGIC_LINK, "ana@example.com", uuid.uuid4(), None, {"url": "u", "name": "Ana"})

    assert asyncio.run(notices.send(notice)) is Outcome.SENT
    assert [email.to for email in mailer.sent] == ["ana@example.com"]
    assert "notice suppression not checked" in caplog.messages


# --- the endpoint, with no database ---------------------------------------------


def no_db_client(**settings: Any) -> TestClient:
    return TestClient(create_app(make_settings(database_url=UNREACHABLE_DB, **settings)))


def test_with_no_secret_there_is_no_webhook() -> None:
    body, headers = signed(complained("a@example.com"))
    with no_db_client() as client:
        assert client.post(RESEND_PATH, content=body, headers=headers).status_code == 404


def test_an_unsigned_post_is_a_400_before_any_database_work() -> None:
    # No tenant either: the signature, not a session, is what it checks.
    body, headers = signed(complained("a@example.com"), key=b"forged")
    with no_db_client(resend_webhook_secret=SECRET) as client:
        assert client.post(RESEND_PATH, content=body).status_code == 400
        assert client.post(RESEND_PATH, content=body, headers=headers).status_code == 400


# --- against real Postgres -------------------------------------------------------


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
    app = create_app(make_settings(database_url=db.api_url, resend_webhook_secret=SECRET))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"gym-{uuid.uuid4().hex[:8]}")


def deliver(client: TestClient, event: dict[str, Any]) -> int:
    """POST `event` as Resend does: signed, and with no session or tenant."""
    body, headers = signed(event)
    return int(client.post(RESEND_PATH, content=body, headers=headers).status_code)


def suppressed(db: Database, address: str) -> tuple[str, str | None] | None:
    row = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT reason, detail FROM mail_suppression WHERE address = $1", address
        ),
    )
    return None if row is None else (row["reason"], row["detail"])


def new_address(name: str = "rebote") -> str:
    return f"{name}-{uuid.uuid4().hex[:8]}@example.com"


@pg
def test_a_hard_bounce_suppresses_the_address_as_sign_in_compares_it(
    db: Database, client: TestClient
) -> None:
    address = new_address()
    # Resend may hand back the address as it was written, case and name and all.
    assert deliver(client, bounced(f"Ana <{address.upper()}>")) == 204
    assert suppressed(db, address) == ("bounce", "550 5.1.1 The email account does not exist.")
    # A retried delivery, or a later complaint, changes nothing.
    assert deliver(client, bounced(address)) == 204
    assert deliver(client, complained(address)) == 204
    assert suppressed(db, address) == ("bounce", "550 5.1.1 The email account does not exist.")


@pg
def test_a_complaint_suppresses_and_a_transient_bounce_does_not(
    db: Database, client: TestClient
) -> None:
    complainer, full_inbox = new_address("spam"), new_address("lleno")
    assert deliver(client, complained(complainer)) == 204
    assert deliver(client, bounced(full_inbox, kind="Transient")) == 204
    assert suppressed(db, complainer) == ("complaint", None)
    assert suppressed(db, full_inbox) is None


@pg
def test_a_forged_delivery_suppresses_nothing(db: Database, client: TestClient) -> None:
    address = new_address()
    body, headers = signed(complained(address), key=b"forged")
    assert client.post(RESEND_PATH, content=body, headers=headers).status_code == 400
    body, headers = signed(complained(address), at=time.time() - 3600)
    assert client.post(RESEND_PATH, content=body, headers=headers).status_code == 400
    assert suppressed(db, address) is None


@pg
def test_no_mail_goes_to_a_suppressed_address_and_the_ficha_says_why(
    db: Database, client: TestClient, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    address = new_address()
    person = enrolled(client, gym, email=address)
    state = client.get(f"/api/people/{person['id']}/welcome", headers=as_gym(gym))
    assert state.json()["suppressed"] is None

    assert deliver(client, bounced(address)) == 204
    mailer.sent.clear()
    answer = welcome(client, gym, person["id"])

    assert answer.status_code == 200, answer.text
    assert mailer.sent == []
    assert answer.json()["last"]["status"] == "suppressed"
    found = answer.json()["suppressed"]
    assert (found["reason"], found["detail"]) == (
        "bounce",
        "550 5.1.1 The email account does not exist.",
    )
    assert found["since"]
    [(template, _, status)] = sent_notices(db, gym)
    assert (template, status) == ("welcome", "suppressed")


@pg
def test_the_app_role_only_reads_and_adds_suppressions(db: Database, client: TestClient) -> None:
    address = new_address()
    assert deliver(client, complained(address)) == 204
    for sql in (
        "UPDATE mail_suppression SET reason = 'bounce'",
        "DELETE FROM mail_suppression",
    ):

        async def change(conn: asyncpg.Connection, sql: str = sql) -> None:
            await conn.execute(sql)

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            run(db.api_url, change)
    with pytest.raises(asyncpg.CheckViolationError):
        run(
            db.api_url,
            lambda c: c.execute(
                "INSERT INTO mail_suppression (address, reason)"
                " VALUES ('Ana@Example.com', 'bounce')"
            ),
        )


@pg
def test_downgrade_drops_the_table() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        command.downgrade(database.alembic(), "0045")
        found = run(
            database.admin_url,
            lambda c: c.fetchval("SELECT to_regclass('mail_suppression') IS NOT NULL"),
        )
        assert found is False
        migrate(database)
