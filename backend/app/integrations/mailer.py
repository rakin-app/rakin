"""Outgoing email: the system of record for every notice a student or guardian gets.

`ConsoleMailer` writes each message to the log and sends nothing; `SmtpMailer` hands it
to any SMTP server. Hosted Rakin sends through Resend's SMTP relay; self-hosters point it
at their own. What the messages say, and the record of each, is `app.notices`.
"""

import asyncio
import logging
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Literal, Protocol

logger = logging.getLogger(__name__)


class MailDeliveryError(Exception):
    """The message was not accepted for delivery; the caller may retry."""


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str | None = None
    # Extra headers, such as `List-Unsubscribe`; never `From`, `To` or `Subject`.
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        # A newline in a header field is header injection, never a real value.
        fields = [self.to, self.subject, *(part for header in self.headers for part in header)]
        if any(c in field for field in fields for c in "\r\n"):
            raise ValueError("header fields must be single lines")
        for name, _ in self.headers:
            # RFC 5322 field names: printable ASCII but space and colon.
            if name.lower() in ("from", "to", "subject") or not re.fullmatch(r"[!-9;-~]+", name):
                raise ValueError(f"not an extra header: {name!r}")
        if "@" not in parseaddr(self.to)[1]:
            raise ValueError(f"not an email address: {self.to!r}")


class Mailer(Protocol):
    async def send(self, email: Email) -> None:
        """Hand `email` over for delivery, or raise `MailDeliveryError`."""
        ...


class ConsoleMailer:
    """Logs every message instead of sending it: the offline default."""

    async def send(self, email: Email) -> None:
        logger.info(
            "mail (console, not sent)",
            extra={
                "mail_to": email.to,
                "mail_subject": email.subject,
                "mail_text": email.text,
                "mail_headers": dict(email.headers),
            },
        )


class SmtpMailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        security: Literal["starttls", "tls", "none"],
        username: str = "",
        password: str = "",
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.security = security
        self.username = username
        self.password = password
        self.timeout = timeout

    async def send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        for name, value in email.headers:
            message[name] = value
        message.set_content(email.text)
        if email.html is not None:
            message.add_alternative(email.html, subtype="html")
        try:
            await asyncio.to_thread(self._send, message)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailDeliveryError(f"smtp {self.host}:{self.port}: {exc}") from exc

    def _send(self, message: EmailMessage) -> None:
        smtp_class = smtplib.SMTP_SSL if self.security == "tls" else smtplib.SMTP
        with smtp_class(self.host, self.port, timeout=self.timeout) as smtp:
            if self.security == "starttls":
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)
