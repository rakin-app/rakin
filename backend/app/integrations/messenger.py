"""WhatsApp messages to a person's phone.

v1 sends nothing itself: `WaMeMessenger` turns a message into a `wa.me` link the admin
opens and sends from their own phone, with no Meta account involved. The WhatsApp
Business API (v2) is another `Messenger` that sends directly and returns no link.
"""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from app.domain.phone import InvalidPhoneError, normalize_phone


@dataclass(frozen=True)
class Message:
    to_phone: str  # E.164, as stored on `gym_person.phone`
    text: str

    def __post_init__(self) -> None:
        try:
            normalized = normalize_phone(self.to_phone)
        except InvalidPhoneError:
            normalized = None
        if normalized != self.to_phone:
            raise ValueError(f"to_phone must be E.164: {self.to_phone!r}")
        if not self.text.strip():
            raise ValueError("text is empty")


@dataclass(frozen=True)
class Delivery:
    # A link staff open to send the message themselves, or None when it was sent.
    link: str | None


class Messenger(Protocol):
    async def deliver(self, message: Message) -> Delivery: ...


def wa_me_link(message: Message) -> str:
    """The `wa.me` link that opens WhatsApp on `message`, ready to send."""
    digits = message.to_phone.removeprefix("+")
    return f"https://wa.me/{digits}?text={quote(message.text, safe='')}"


class WaMeMessenger:
    async def deliver(self, message: Message) -> Delivery:
        return Delivery(link=wa_me_link(message))
