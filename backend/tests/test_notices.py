"""The email pipeline (#52): templates, `message_log`, and one-click unsubscribe.

Rendering and the unsubscribe token need nothing; sending, recording and
unsubscribing run against real Postgres, through a mailer that keeps what it is given.
"""

import asyncio
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jinja2 import UndefinedError

from alembic import command
from app.auth import build_notices
from app.db import create_engine, create_sessionmaker
from app.integrations.mailer import Email, MailDeliveryError
from app.main import create_app
from app.notices import (
    JOIN_APPROVED,
    MAGIC_LINK,
    PROOF_RECEIVED,
    PROOF_REJECTED,
    RECEIPT,
    STAFF_INVITE,
    STATEMENT,
    TEMPLATES_DIR,
    WELCOME,
    Notice,
    Notices,
    Outcome,
    Template,
    payload,
    render,
)
from app.notices.unsubscribe import UNSUBSCRIBE_PATH, UnsubscribeSigner
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, seeded_owner, throwaway_database

BASE_URL = "https://rakin.test"
SECRET = "a-test-secret-of-some-length"

GYM = uuid.UUID("00000000-0000-4000-8000-000000000001")
PERSON = uuid.UUID("00000000-0000-4000-8000-000000000002")

PROOF = {
    "name": "Ana",
    "gym": "Academia <Sur>",
    "amount_clp": 45000,
    "period_start": date(2026, 11, 1),
    "period_end": date(2026, 11, 30),
    "dependent_name": None,
}

# The same message, as a notice someone may opt out of: plan events and
# announcements will be these.
OPTIONAL = Template("proof_received", essential=False)


def proof_notice(template: Template = PROOF_RECEIVED, **context: Any) -> Notice:
    return Notice(template, "ana@example.cl", PERSON, GYM, {**PROOF, **context})


# --- rendering ------------------------------------------------------------------


TEMPLATES = [
    MAGIC_LINK,
    WELCOME,
    STATEMENT,
    PROOF_RECEIVED,
    RECEIPT,
    PROOF_REJECTED,
    STAFF_INVITE,
    JOIN_APPROVED,
]


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_has_a_subject_a_text_and_an_html_part(template: Template) -> None:
    for suffix in ("subject.txt", "txt", "html"):
        assert (TEMPLATES_DIR / f"{template.name}.{suffix}").is_file()


def test_a_notice_renders_as_spanish_text_and_html() -> None:
    email = render(proof_notice())

    assert email.to == "ana@example.cl"
    assert email.subject == "Recibimos tu comprobante"
    assert email.text.startswith("Hola, Ana:\n\n")
    assert "$45.000" in email.text
    assert "del 01-11-2026 al 30-11-2026" in email.text
    assert email.html is not None
    assert '<html lang="es">' in email.html
    assert "<strong>$45.000</strong>" in email.html


def test_values_are_escaped_in_html_and_left_alone_in_text() -> None:
    email = render(proof_notice(PROOF_REJECTED, note="<script>alert(1)</script> & más"))

    assert email.html is not None
    assert "<script>" not in email.html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; más" in email.html
    assert "Academia &lt;Sur&gt;" in email.html
    assert "Nota: <script>alert(1)</script> & más" in email.text


@pytest.mark.parametrize("missing", ["name", "amount_clp", "period_start"])
def test_a_missing_value_is_an_error_not_a_blank(missing: str) -> None:
    # `amount_clp` and `period_start` go through a filter, which must fail the same way.
    context = {k: v for k, v in PROOF.items() if k != missing}
    with pytest.raises(UndefinedError, match=missing):
        render(Notice(PROOF_RECEIVED, "ana@example.cl", PERSON, GYM, context))


def test_an_essential_notice_has_no_unsubscribe_link() -> None:
    email = render(proof_notice())

    assert email.headers == ()
    assert "dejar de recibir" not in email.text.lower()


def test_an_unsubscribe_link_goes_in_the_headers_and_the_footer() -> None:
    url = f"{BASE_URL}{UNSUBSCRIBE_PATH}/tok"
    email = render(proof_notice(OPTIONAL), unsubscribe_url=url)

    assert dict(email.headers) == {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert f"Para dejar de recibir estos avisos: {url}" in email.text
    assert email.html is not None and f'href="{url}"' in email.html


def test_the_footer_names_the_gym_or_just_rakin() -> None:
    assert "Academia <Sur>, a través de Rakin" in render(proof_notice()).text
    link = render(Notice(MAGIC_LINK, "a@example.cl", PERSON, None, {"name": "A", "url": "u"}))
    assert link.text.rstrip().endswith("--\nRakin")


def test_the_footer_shows_rakins_logo_with_its_name_as_the_alt_text() -> None:
    logo = f"{BASE_URL}/email-logo.png"
    email = render(proof_notice(), logo_url=logo)

    assert email.html is not None
    assert f'Academia &lt;Sur&gt;, a través de <img src="{logo}" alt="Rakin"' in email.html
    # Text has no image: it still names Rakin.
    assert "Academia <Sur>, a través de Rakin" in email.text
    link = render(
        Notice(MAGIC_LINK, "a@example.cl", PERSON, None, {"name": "A", "url": "u"}), logo_url=logo
    )
    assert link.html is not None and f'<img src="{logo}" alt="Rakin"' in link.html


def test_the_payload_keeps_the_values_but_not_the_redacted_ones() -> None:
    link = Notice(MAGIC_LINK, "a@example.cl", PERSON, None, {"name": "Ana", "url": "secret"})
    assert json.loads(payload(link)) == {"name": "Ana"}
    assert json.loads(payload(proof_notice()))["period_start"] == "2026-11-01"


def test_a_non_essential_notice_belongs_to_a_gym() -> None:
    with pytest.raises(ValueError, match="gym"):
        Notice(OPTIONAL, "ana@example.cl", PERSON, None, PROOF)


BANK = {
    "bank": "Banco Estado",
    "account_type": "Cuenta RUT",
    "holder": "Academia Sur SpA",
    "rut": "76.123.456-7",
    "number": "12345678",
    "email": "pagos@sur.cl",
}

WELCOMED = {
    "name": "Ana",
    "gym": "Academia Sur",
    "plan_name": "Mensual",
    "bank_account": BANK,
    "dependent_name": None,
}

STATED = {
    "name": "Ana",
    "gym": "Academia Sur",
    "plan_name": "Mensual",
    "billing_period_id": "00000000-0000-4000-8000-000000000003",
    "period_start": date(2026, 12, 1),
    "period_end": date(2026, 12, 31),
    "due_date": date(2026, 12, 1),
    "amount_clp": 45000,
    "bank_account": BANK,
    "dependent_name": None,
}

RECEIVED = {
    **PROOF,
    "amount_clp": 45000,
    "period_outstanding_clp": 0,
    "balance_clp": 0,
}

PAGE_URL = f"{BASE_URL}/api/auth/callback?token=tok&next=%2Fme"


def test_every_notice_but_the_sign_in_link_carries_a_page_link() -> None:
    assert [t.name for t in TEMPLATES if t.page_link] == [
        "welcome",
        "statement",
        "proof_received",
        "receipt",
        "proof_rejected",
        "staff_invite",
    ]


def test_the_page_link_goes_under_the_message() -> None:
    email = render(proof_notice(), page_url=PAGE_URL)

    assert f"Tu página: {PAGE_URL}\n" in email.text
    assert "vence en 7 días" in email.text
    assert email.text.index(PAGE_URL) < email.text.index("--\n")
    assert email.html is not None
    assert f'href="{PAGE_URL.replace("&", "&amp;")}"' in email.html
    assert "Ir a mi página" in email.html


def test_the_staff_invite_has_its_own_sign_in_link() -> None:
    url = f"{BASE_URL}/api/auth/callback?token=tok"
    context = {"name": "Pedro", "gym": "Academia Sur", "inviter": "Carla", "role": "coach"}
    email = render(
        Notice(STAFF_INVITE, "pedro@example.cl", PERSON, GYM, {**context, "role_is_coach": True}),
        page_url=url,
    )

    assert email.subject == "Carla te invitó al equipo de Academia Sur"
    assert "Carla te invitó a Academia Sur en Rakin como coach." in email.text
    assert "tomas asistencia" in email.text
    assert f"Entrar: {url}\n" in email.text
    assert "Tu página" not in email.text
    assert email.html is not None
    assert "Entrar a Rakin" in email.html and "Ir a mi página" not in email.html
    assert STAFF_INVITE.landing is None


def test_without_a_page_link_there_is_no_button() -> None:
    email = render(proof_notice())
    assert "Tu página" not in email.text
    assert email.html is not None and "Ir a mi página" not in email.html


def test_the_welcome_says_how_to_pay_and_where_to_upload() -> None:
    email = render(Notice(WELCOME, "ana@example.cl", PERSON, GYM, WELCOMED))

    assert email.subject == "Te damos la bienvenida a Academia Sur"
    assert "Tu inscripción en el plan Mensual quedó lista." in email.text
    assert "transfiere a esta cuenta y sube el comprobante desde tu página" in email.text
    for line in ("Banco: Banco Estado", "Número: 12345678", "RUT: 76.123.456-7"):
        assert line in email.text
    assert email.html is not None and "<strong>Mensual</strong>" in email.html


def test_a_welcome_to_a_guardian_names_the_dependent() -> None:
    context = {**WELCOMED, "name": "Marta", "dependent_name": "Juan"}
    email = render(Notice(WELCOME, "marta@example.cl", PERSON, GYM, context))

    assert "La inscripción de Juan en el plan Mensual quedó lista." in email.text


@pytest.mark.parametrize("template, context", [(WELCOME, WELCOMED), (STATEMENT, STATED)])
def test_with_no_bank_details_the_page_has_them(template: Template, context: Any) -> None:
    email = render(
        Notice(template, "ana@example.cl", PERSON, GYM, {**context, "bank_account": None})
    )

    assert "donde están los datos de la cuenta" in email.text
    assert "Banco:" not in email.text
    assert "\n\n\n" not in email.text


def test_a_bank_account_without_an_email_leaves_that_line_out() -> None:
    bank = {k: v for k, v in BANK.items() if k != "email"}
    email = render(
        Notice(STATEMENT, "ana@example.cl", PERSON, GYM, {**STATED, "bank_account": bank})
    )
    assert "Correo:" not in email.text


def test_the_statement_has_the_amount_due_date_and_bank_details() -> None:
    email = render(Notice(STATEMENT, "ana@example.cl", PERSON, GYM, STATED))

    assert email.subject == "Tu pago de $45.000 en Academia Sur vence el 01-12-2026"
    assert "El 01-12-2026 vence el pago de $45.000 en Academia Sur" in email.text
    assert "período del 01-12-2026 al 31-12-2026" in email.text
    assert "Titular: Academia Sur SpA" in email.text
    assert email.html is not None and "<strong>$45.000</strong>" in email.html


def test_a_statement_to_a_guardian_names_the_dependent() -> None:
    context = {**STATED, "name": "Marta", "dependent_name": "Juan"}
    email = render(Notice(STATEMENT, "marta@example.cl", PERSON, GYM, context))
    assert "$45.000 de Juan en Academia Sur" in email.text


@pytest.mark.parametrize(
    "left, balance, says",
    [
        (0, 0, ["Este período quedó pagado.", "Estás al día"]),
        (5000, 5000, ["quedan $5.000 por pagar", "Saldo pendiente: $5.000."]),
        (0, -3000, ["Este período quedó pagado.", "Saldo a favor: $3.000"]),
    ],
)
def test_the_receipt_has_the_period_and_the_balance(
    left: int, balance: int, says: list[str]
) -> None:
    context = {**RECEIVED, "period_outstanding_clp": left, "balance_clp": balance}
    email = render(Notice(RECEIPT, "ana@example.cl", PERSON, GYM, context))

    assert email.subject == "Pago validado"
    assert "validó tu pago de $45.000, por el período del 01-11-2026 al 30-11-2026" in email.text
    assert email.html is not None
    html_text = re.sub(r"</?strong>", "", email.html)
    for said in says:
        assert said in email.text
        assert said in html_text


# --- the unsubscribe token ------------------------------------------------------


def test_a_token_names_its_gym_and_person() -> None:
    signer = UnsubscribeSigner(SECRET)
    assert signer.verify(signer.sign(GYM, PERSON)) == (GYM, PERSON)


@pytest.mark.parametrize(
    "mangle", ["swap", "other-secret", "no-signature", "garbage", "short", "non-ascii"]
)
def test_a_token_that_was_not_signed_here_is_refused(mangle: str) -> None:
    signer = UnsubscribeSigner(SECRET)
    token = signer.sign(GYM, PERSON)
    body, _, signature = token.partition(".")
    forged = {
        "swap": f"{UnsubscribeSigner(SECRET).sign(PERSON, GYM).partition('.')[0]}.{signature}",
        "other-secret": UnsubscribeSigner("another-secret-entirely").sign(GYM, PERSON),
        "no-signature": body,
        "garbage": "!!!.???",
        "short": f"AAAA.{signer._signature('AAAA')}",
        "non-ascii": f"{body}.é{signature[1:]}",
    }[mangle]
    assert signer.verify(forged) is None


# --- against real Postgres ------------------------------------------------------

pg = pytest.mark.postgres


class Outbox:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Email] = []
        self.fail = fail

    async def send(self, email: Email) -> None:
        if self.fail:
            raise MailDeliveryError("smtp relay: 421 try later")
        self.sent.append(email)


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture
def gym(db: Database) -> uuid.UUID:
    return seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")


def send(db: Database, notice: Notice, outbox: Outbox, *, links: bool = True) -> Outcome:
    """Send `notice` as the app does; without `links`, with nothing to issue sign-in
    links with."""

    async def go() -> Outcome:
        engine = create_engine(db.settings)
        try:
            sessionmaker = create_sessionmaker(engine)
            settings = db.settings.model_copy(update={"public_base_url": BASE_URL})
            notices = build_notices(settings, outbox, lambda: sessionmaker)
            if not links:
                notices = Notices(
                    outbox, lambda: sessionmaker, base_url=BASE_URL, secret_key=SECRET
                )
            return await notices.send(notice)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def to_owner(gym: uuid.UUID, template: Template = PROOF_RECEIVED, **context: Any) -> Notice:
    return replace(proof_notice(template, **context), person_id=seeded_owner(gym), gym_id=gym)


def logged(db: Database, gym: uuid.UUID) -> list[dict[str, Any]]:
    """`gym`'s `message_log`, as the API reads it, oldest first."""
    rows = run(db.api_url, in_gym(gym, "SELECT * FROM message_log ORDER BY sent_at"))
    return [dict(r) for r in rows]


@pg
def test_a_sent_notice_is_recorded_in_its_gym(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()

    assert send(db, to_owner(gym), outbox) is Outcome.SENT

    assert len(outbox.sent) == 1
    [row] = logged(db, gym)
    assert row["person_id"] == seeded_owner(gym)
    assert (row["channel"], row["template"], row["status"]) == ("email", "proof_received", "sent")
    assert row["to_address"] == "ana@example.cl"
    assert row["error"] is None
    assert json.loads(row["payload"])["amount_clp"] == 45000


@pg
def test_a_sent_notice_shows_the_logo_from_the_base_host(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()

    send(db, to_owner(gym), outbox)

    [email] = outbox.sent
    assert email.html is not None and f'<img src="{BASE_URL}/email-logo.png"' in email.html


@pg
def test_a_notice_carries_a_7_day_link_to_the_student_page(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()

    send(db, to_owner(gym), outbox)

    [email] = outbox.sent
    [url] = [
        line.removeprefix("Tu página: ") for line in email.text.splitlines() if "Tu página" in line
    ]
    assert url.startswith(f"{BASE_URL}/api/auth/callback?token=")
    assert url.endswith("&next=%2Fme")
    [link] = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT person_id, used_at, expires_at - created_at AS ttl FROM auth_link"
            " WHERE person_id = $1",
            seeded_owner(gym),
        ),
    )
    assert link["used_at"] is None
    assert timedelta(days=7) - timedelta(minutes=1) < link["ttl"] <= timedelta(days=7)
    # Never written down: the record has the values, not the link.
    [row] = logged(db, gym)
    assert "token" not in row["payload"]
    assert "page_url" not in json.loads(row["payload"])


class Issued:
    """Stands in for `MagicLinks`, keeping whom each link was for."""

    def __init__(self) -> None:
        self.recipients: list[Any] = []

    async def issue(self, recipient: Any, **_: Any) -> Any:
        self.recipients.append(recipient)
        return type("Link", (), {"url": PAGE_URL})()


def test_a_notice_without_a_name_is_not_issued_a_link_for_none() -> None:
    issued = Issued()
    notices = Notices(
        Outbox(),
        lambda: None,  # type: ignore[arg-type, return-value]
        base_url=BASE_URL,
        secret_key=SECRET,
        links=issued,  # type: ignore[arg-type]
    )
    notice = replace(proof_notice(), context={k: v for k, v in PROOF.items() if k != "name"})

    assert asyncio.run(notices._page_url(notice, BASE_URL)) == PAGE_URL

    [recipient] = issued.recipients
    assert recipient.name == ""


@pg
def test_a_notice_whose_link_cannot_be_issued_is_recorded_as_failed(
    db: Database, gym: uuid.UUID
) -> None:
    outbox = Outbox()

    assert send(db, to_owner(gym), outbox, links=False) is Outcome.FAILED

    assert outbox.sent == []
    [row] = logged(db, gym)
    assert row["status"] == "failed"
    assert row["error"].startswith("RuntimeError: no sign-in links")


@pg
def test_another_gym_never_reads_the_record(db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    send(db, to_owner(gym), Outbox())

    assert logged(db, other) == []


@pg
def test_a_send_the_relay_refuses_is_recorded_as_failed(db: Database, gym: uuid.UUID) -> None:
    assert send(db, to_owner(gym), Outbox(fail=True)) is Outcome.FAILED

    [row] = logged(db, gym)
    assert row["status"] == "failed"
    assert "421 try later" in row["error"]


@pg
def test_an_address_the_gym_typed_wrong_is_recorded_as_failed(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()
    notice = replace(to_owner(gym), to="ana at example")

    assert send(db, notice, outbox) is Outcome.FAILED

    assert outbox.sent == []
    [row] = logged(db, gym)
    assert (row["status"], row["to_address"]) == ("failed", "ana at example")
    # No sign-in link is issued for a message that cannot go.
    links = run(
        db.admin_url,
        lambda c: c.fetch("SELECT 1 FROM auth_link WHERE person_id = $1", seeded_owner(gym)),
    )
    assert links == []


@pg
def test_a_template_that_cannot_render_is_recorded_as_failed(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()
    notice = to_owner(gym)
    notice = replace(notice, context={k: v for k, v in notice.context.items() if k != "name"})

    assert send(db, notice, outbox) is Outcome.FAILED

    assert outbox.sent == []
    [row] = logged(db, gym)
    assert row["status"] == "failed"
    assert row["error"].startswith("UndefinedError: ")
    assert "name" in row["error"]


@pg
def test_the_record_is_append_only_for_the_api(db: Database, gym: uuid.UUID) -> None:
    send(db, to_owner(gym), Outbox())

    for sql in ("UPDATE message_log SET status = 'failed'", "DELETE FROM message_log"):
        with pytest.raises(Exception, match="permission denied"):
            run(db.api_url, in_gym(gym, sql))


@pg
def test_the_api_cannot_log_into_another_gym(db: Database, gym: uuid.UUID) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    sql = (
        "INSERT INTO message_log (gym_id, person_id, channel, template, to_address, status)"
        " VALUES ($1, $2, 'email', 'x', 'a@example.cl', 'sent')"
    )
    for gym_id in (other, None):
        with pytest.raises(Exception, match="row-level security"):
            run(db.api_url, in_gym(gym, sql, gym_id, seeded_owner(gym)))


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(db.settings.model_copy(update={"public_base_url": BASE_URL}))
    with TestClient(app, base_url=BASE_URL) as c:
        yield c


def unsubscribe_path(db: Database, gym: uuid.UUID, person: uuid.UUID) -> str:
    token = UnsubscribeSigner(db.settings.secret_key).sign(gym, person)
    return f"{UNSUBSCRIBE_PATH}/{token}"


@pg
def test_a_non_essential_notice_links_to_its_own_unsubscribe(db: Database, gym: uuid.UUID) -> None:
    outbox = Outbox()
    send(db, to_owner(gym, OPTIONAL), outbox)

    [email] = outbox.sent
    url = f"{BASE_URL}{unsubscribe_path(db, gym, seeded_owner(gym))}"
    assert dict(email.headers)["List-Unsubscribe"] == f"<{url}>"
    assert url in email.text


@pg
def test_opening_the_link_asks_and_does_not_unsubscribe(
    db: Database, gym: uuid.UUID, client: TestClient
) -> None:
    path = unsubscribe_path(db, gym, seeded_owner(gym))

    response = client.get(path)

    assert response.status_code == 200
    assert f'action="{path}"' in response.text
    assert "Dejar de recibirlos" in response.text
    outbox = Outbox()
    assert send(db, to_owner(gym, OPTIONAL), outbox) is Outcome.SENT


@pg
def test_one_click_unsubscribes_from_optional_notices_only(
    db: Database, gym: uuid.UUID, client: TestClient
) -> None:
    path = unsubscribe_path(db, gym, seeded_owner(gym))

    # What a mail client sends for RFC 8058's one click, with no cookie or Origin.
    for _ in range(2):
        response = client.post(
            path,
            content="List-Unsubscribe=One-Click",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200
        assert "no te enviará más avisos opcionales" in response.text

    outbox = Outbox()
    assert send(db, to_owner(gym, OPTIONAL), outbox) is Outcome.SUPPRESSED
    assert outbox.sent == []
    assert send(db, to_owner(gym), outbox) is Outcome.SENT
    assert len(outbox.sent) == 1
    assert [r["status"] for r in logged(db, gym)] == ["suppressed", "sent"]


@pg
def test_an_unsubscribe_holds_for_its_gym_alone(
    db: Database, gym: uuid.UUID, client: TestClient
) -> None:
    other = seed_gym(db, f"dojo-{uuid.uuid4().hex[:6]}")
    owner = seeded_owner(gym)
    # The same person in a second gym, so only the gym differs.
    run(
        db.admin_url,
        lambda c: c.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", other, owner
        ),
    )
    client.post(unsubscribe_path(db, gym, owner))

    notice = replace(to_owner(gym, OPTIONAL), gym_id=other)
    assert send(db, notice, Outbox()) is Outcome.SENT


@pg
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_bad_token_or_a_stranger_gets_nothing(
    db: Database, gym: uuid.UUID, client: TestClient, method: str
) -> None:
    signed_elsewhere = UnsubscribeSigner("another-secret-entirely").sign(gym, seeded_owner(gym))
    for path in (
        f"{UNSUBSCRIBE_PATH}/{signed_elsewhere}",
        f"{UNSUBSCRIBE_PATH}/garbage",
        f"{UNSUBSCRIBE_PATH}/abc.%C3%A9",  # non-ASCII, which `compare_digest` refuses
        unsubscribe_path(db, gym, uuid.uuid4()),  # signed, but not one of the gym's people
    ):
        response = client.request(method, path)
        assert response.status_code == 404
        assert "no es válido" in response.text
    rows = run(db.api_url, in_gym(gym, "SELECT 1 FROM mail_unsubscribe"))
    assert rows == []


@pg
def test_downgrade_drops_both_tables() -> None:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        command.downgrade(database.alembic(), "0014")
        found = run(
            database.admin_url,
            lambda c: c.fetch(
                "SELECT tablename FROM pg_tables WHERE tablename IN"
                " ('message_log', 'mail_unsubscribe')"
            ),
        )
        assert found == []
        migrate(database)
