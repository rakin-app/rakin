"""The contract every `Mailer` passes: what it was given is what goes out.

Each implementation runs behind a harness that reads back what it sent: the log for
`ConsoleMailer`, a throwaway SMTP server for `SmtpMailer`.
"""

import asyncio
import email
import email.policy
import logging
import socketserver
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from email.message import EmailMessage

import pytest

from app.integrations import build_mailer
from app.integrations.mailer import ConsoleMailer, Email, MailDeliveryError, Mailer, SmtpMailer
from tests.conftest import make_settings


@dataclass(frozen=True)
class Sent:
    to: str
    subject: str
    text: str


@dataclass
class Harness:
    mailer: Mailer
    sent: Callable[[], list[Sent]]


class SmtpStub(socketserver.ThreadingTCPServer):
    """Just enough SMTP for `smtplib` to deliver a message, without TLS or auth."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), SmtpHandler)
        self.messages: list[EmailMessage] = []

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class SmtpHandler(socketserver.StreamRequestHandler):
    server: SmtpStub

    def reply(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")

    def handle(self) -> None:
        self.reply("220 stub")
        while line := self.rfile.readline():
            verb = line.decode().strip().split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                self.reply("250 stub")
            elif verb in ("MAIL", "RCPT", "RSET", "NOOP"):
                self.reply("250 ok")
            elif verb == "DATA":
                self.reply("354 go ahead")
                data = b""
                while (chunk := self.rfile.readline()) not in (b".\r\n", b""):
                    data += chunk[1:] if chunk.startswith(b"..") else chunk
                # Wire format is CRLF; the parser wants native line endings.
                wire = data.replace(b"\r\n", b"\n")
                parsed = email.message_from_bytes(wire, policy=email.policy.default)
                assert isinstance(parsed, EmailMessage)
                self.server.messages.append(parsed)
                self.reply("250 queued")
            elif verb == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("502 not implemented")


@pytest.fixture
def smtp_stub() -> Iterator[SmtpStub]:
    server = SmtpStub()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def smtp_mailer(port: int) -> SmtpMailer:
    return SmtpMailer(
        host="127.0.0.1", port=port, sender="Rakin <no-reply@rakin.test>", security="none"
    )


def plain_text(message: EmailMessage) -> str:
    body = message.get_body(("plain",))
    assert isinstance(body, EmailMessage)
    return str(body.get_content())


@pytest.fixture(params=["console", "smtp"])
def harness(request: pytest.FixtureRequest, caplog: pytest.LogCaptureFixture) -> Iterator[Harness]:
    if request.param == "console":
        caplog.set_level(logging.INFO, logger="app.integrations.mailer")

        def logged() -> list[Sent]:
            return [
                Sent(r.__dict__["mail_to"], r.__dict__["mail_subject"], r.__dict__["mail_text"])
                for r in caplog.records
                if r.name == "app.integrations.mailer"
            ]

        yield Harness(ConsoleMailer(), logged)
    else:
        stub = request.getfixturevalue("smtp_stub")

        def received() -> list[Sent]:
            return [Sent(m["To"], m["Subject"], plain_text(m).rstrip("\n")) for m in stub.messages]

        yield Harness(smtp_mailer(stub.port), received)


def test_a_message_goes_out_as_given(harness: Harness) -> None:
    message = Email(
        to="ana@example.cl",
        subject="Tu cuota de noviembre: $45.000",
        text="Hola Ana,\nvence el 5 de noviembre.\n¡Gracias!",
    )

    asyncio.run(harness.mailer.send(message))

    assert harness.sent() == [Sent(message.to, message.subject, message.text)]


def test_each_message_goes_out_once(harness: Harness) -> None:
    for to in ("a@example.cl", "b@example.cl"):
        asyncio.run(harness.mailer.send(Email(to=to, subject="Hola", text="...")))

    assert [s.to for s in harness.sent()] == ["a@example.cl", "b@example.cl"]


@pytest.mark.parametrize(
    "fields",
    [
        {"to": "ana@example.cl", "subject": "Hola\r\nBcc: everyone@example.cl"},
        {"to": "ana@example.cl\nBcc: everyone@example.cl", "subject": "Hola"},
        {"to": "not an address", "subject": "Hola"},
    ],
)
def test_header_injection_and_bad_addresses_never_reach_a_mailer(fields: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Email(to=fields["to"], subject=fields["subject"], text="...")


@pytest.mark.parametrize(
    "header",
    [
        ("List-Unsubscribe", "<https://x>\r\nBcc: everyone@example.cl"),
        ("X-Evil\nBcc", "everyone@example.cl"),
        ("Bad Name", "x"),
        ("Bad:Name", "x"),
        ("To", "everyone@example.cl"),
        ("subject", "Otra cosa"),
    ],
)
def test_extra_headers_cannot_inject_or_override(header: tuple[str, str]) -> None:
    with pytest.raises(ValueError):
        Email(to="ana@example.cl", subject="Hola", text="...", headers=(header,))


def test_smtp_sends_the_extra_headers(smtp_stub: SmtpStub) -> None:
    headers = (
        ("List-Unsubscribe", "<https://rakin.test/api/mail/unsubscribe/t>"),
        ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
    )
    message = Email(to="ana@example.cl", subject="Aviso", text="...", headers=headers)

    asyncio.run(smtp_mailer(smtp_stub.port).send(message))

    [received] = smtp_stub.messages
    assert received["List-Unsubscribe"] == "<https://rakin.test/api/mail/unsubscribe/t>"
    assert received["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_smtp_sends_the_html_alternative_and_the_sender(smtp_stub: SmtpStub) -> None:
    message = Email(to="ana@example.cl", subject="Recibo", text="Pagado.", html="<p>Pagado.</p>")

    asyncio.run(smtp_mailer(smtp_stub.port).send(message))

    [received] = smtp_stub.messages
    assert received["From"] == "Rakin <no-reply@rakin.test>"
    html = received.get_body(("html",))
    assert isinstance(html, EmailMessage)
    assert html.get_content().strip() == "<p>Pagado.</p>"


def test_smtp_failure_is_a_delivery_error() -> None:
    with SmtpStub() as server:
        port = server.port  # bound, then closed: nothing listens there now

    with pytest.raises(MailDeliveryError, match=f"127.0.0.1:{port}"):
        asyncio.run(smtp_mailer(port).send(Email(to="a@example.cl", subject="x", text="x")))


def test_mailer_is_selected_by_settings() -> None:
    assert isinstance(build_mailer(make_settings()), ConsoleMailer)
    smtp = build_mailer(make_settings(mailer="smtp", smtp_host="mail.example.cl", smtp_port=465))
    assert isinstance(smtp, SmtpMailer)
    assert (smtp.host, smtp.port) == ("mail.example.cl", 465)
