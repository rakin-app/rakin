"""The token in a notice's unsubscribe link: a gym and a person, signed.

It never expires: an unsubscribe link has to work in a message read months later, and
all it can do is stop that gym's non-essential notices to that person.
"""

import base64
import hashlib
import hmac
import uuid

from app.security import constant_time_equals

UNSUBSCRIBE_PATH = "/api/mail/unsubscribe"


class UnsubscribeSigner:
    def __init__(self, secret_key: str) -> None:
        # Derived per purpose, so a signature made for anything else never verifies here.
        self._key = hashlib.sha256(b"mail-unsubscribe\0" + secret_key.encode()).digest()

    def sign(self, gym_id: uuid.UUID, person_id: uuid.UUID) -> str:
        body = _b64(gym_id.bytes + person_id.bytes)
        return f"{body}.{self._signature(body)}"

    def verify(self, token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
        """The (gym, person) `token` was signed for, or `None` if it was not."""
        body, dot, signature = token.partition(".")
        if not dot or not constant_time_equals(signature, self._signature(body)):
            return None
        try:
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        except ValueError:
            return None
        if len(raw) != 32:
            return None
        return uuid.UUID(bytes=raw[:16]), uuid.UUID(bytes=raw[16:])

    def _signature(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
