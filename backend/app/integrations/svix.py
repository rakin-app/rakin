"""Svix webhook signatures, as Resend sends them (#104).

A delivery carries `svix-id`, `svix-timestamp` and `svix-signature` headers, the last
one or more space-separated `v1,<base64>` HMAC-SHA256 signatures of
`<id>.<timestamp>.<body>`, keyed with the base64 after the secret's `whsec_` prefix.
A timestamp more than `TOLERANCE` from now is refused, so a captured delivery cannot be
replayed later.
"""

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping

SECRET_PREFIX = "whsec_"
# Svix's own tolerance: a delivery stamped further from now than this is refused.
TOLERANCE = 5 * 60


class SignatureError(Exception):
    """The delivery is not one Resend signed just now with our secret."""


def signing_key(secret: str) -> bytes:
    """The HMAC key in a `whsec_<base64>` secret."""
    try:
        return base64.b64decode(secret.removeprefix(SECRET_PREFIX), validate=True)
    except binascii.Error as exc:
        raise ValueError("not a Svix signing secret") from exc


def sign(key: bytes, msg_id: str, timestamp: str, body: bytes) -> str:
    """The `v1` signature of a delivery, base64."""
    signed = f"{msg_id}.{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def verify(key: bytes, headers: Mapping[str, str], body: bytes, now: float | None = None) -> None:
    """Raise `SignatureError` unless `body` carries a fresh signature under `key`."""
    msg_id = headers.get("svix-id")
    timestamp = headers.get("svix-timestamp")
    signatures = headers.get("svix-signature")
    if not (msg_id and timestamp and signatures):
        raise SignatureError("missing svix headers")
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise SignatureError("bad svix-timestamp") from None
    if abs((time.time() if now is None else now) - sent_at) > TOLERANCE:
        raise SignatureError("svix-timestamp too far from now")
    expected = sign(key, msg_id, timestamp, body)
    for entry in signatures.split():
        version, _, signature = entry.partition(",")
        if version == "v1" and hmac.compare_digest(signature, expected):
            return
    raise SignatureError("no matching signature")
