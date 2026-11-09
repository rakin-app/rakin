"""Link and session tokens: random, signed where it helps, and stored only as a hash.

A link token is `<nonce>.<expiry>.<signature>`: the HMAC lets a forged, mangled or
expired link be refused without touching the store, and the store keeps only its
SHA-256, so a leaked table holds no usable link. A session token is plain randomness:
it is checked against the store on every request anyway.
"""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from app.security import constant_time_equals

NONCE_BYTES = 32


def hash_token(token: str) -> bytes:
    """What the store keeps in place of a token."""
    return hashlib.sha256(token.encode()).digest()


def new_session_token() -> str:
    return secrets.token_urlsafe(NONCE_BYTES)


class LinkSigner:
    def __init__(self, secret_key: str) -> None:
        # Derived per purpose, so a signature made for anything else never verifies here.
        self._key = hashlib.sha256(b"magiclink-link\0" + secret_key.encode()).digest()

    def issue(self, expires_at: datetime) -> str:
        body = f"{secrets.token_urlsafe(NONCE_BYTES)}.{int(expires_at.timestamp())}"
        return f"{body}.{self._signature(body)}"

    def expiry(self, token: str) -> datetime | None:
        """When a token this signer issued expires, or None if it did not issue it."""
        body, _, signature = token.rpartition(".")
        _, _, expiry = body.rpartition(".")
        if not body or not constant_time_equals(self._signature(body), signature):
            return None
        try:
            return datetime.fromtimestamp(int(expiry), UTC)
        except (ValueError, OverflowError, OSError):
            return None

    def valid(self, token: str, now: datetime) -> bool:
        expires_at = self.expiry(token)
        return expires_at is not None and now < expires_at

    def _signature(self, body: str) -> str:
        digest = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
