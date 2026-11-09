"""Per-gym custom fields: who sees a field, what a value may be, and how a sensitive
one is sealed. Pure functions, no I/O.

A gym keeps its definitions as a list in `gym.settings.custom_fields`, in the order
the member detail shows them: `{key, label, type, options?, sensitive, visible_to,
archived}` (docs/technical.md#sport-agnostic-design). A definition stored before
`visible_to` existed reads as its default: `owner` when sensitive, else `staff`.

`visible_to` is the narrowest role that sees the field. The owner sees every field; an
admin sees `admin` and `staff` fields; a coach only `staff` ones. A field someone may
not see is, to them, a field that does not exist.

A sensitive field's value is encrypted with AES-GCM under a key derived from
`FIELD_ENCRYPTION_KEY`, bound to the gym, person and field it belongs to, so a sealed value
copied to another row does not open. Changing that key makes those values
unreadable.
"""

import hashlib
import json
import math
import os
import re
import secrets
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from enum import StrEnum
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    ENUM = "enum"


class VisibleTo(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    STAFF = "staff"


# The staff roles (`app.roles.Role`) that see a field at each `visible_to`.
_SEEN_BY: dict[VisibleTo, frozenset[str]] = {
    VisibleTo.OWNER: frozenset({"owner"}),
    VisibleTo.ADMIN: frozenset({"owner", "admin"}),
    VisibleTo.STAFF: frozenset({"owner", "admin", "coach"}),
}

TEXT_MAX_LENGTH = 1000
KEY_MAX_LENGTH = 40
# `fromisoformat` alone also takes `20261109` and `2026-W45-1`.
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class InvalidValue(ValueError):
    """A value the field's type does not take."""


def default_visible_to(sensitive: bool) -> VisibleTo:
    return VisibleTo.OWNER if sensitive else VisibleTo.STAFF


def normalize(definition: Mapping[str, Any]) -> dict[str, Any]:
    """A stored definition with every key present, defaults filled in."""
    sensitive = bool(definition.get("sensitive", False))
    out: dict[str, Any] = {
        "key": definition["key"],
        "label": definition["label"],
        "type": FieldType(definition["type"]),
        "sensitive": sensitive,
        "visible_to": VisibleTo(definition.get("visible_to") or default_visible_to(sensitive)),
        "archived": bool(definition.get("archived", False)),
    }
    if out["type"] is FieldType.ENUM:
        out["options"] = list(definition.get("options") or [])
    return out


def definitions(settings: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The gym's definitions, in order, normalised."""
    return [normalize(d) for d in settings.get("custom_fields") or []]


def sees(role: str | None, definition: Mapping[str, Any]) -> bool:
    return role is not None and role in _SEEN_BY[VisibleTo(definition["visible_to"])]


def visible(role: str | None, defs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(d) for d in defs if sees(role, d)]


def key_for(
    label: str, taken: Iterable[str], suffix: Callable[[], str] = lambda: secrets.token_hex(2)
) -> str:
    """A key made from `label` and a random suffix (`Contacto de emergencia` →
    `contacto_de_emergencia_3f9a`), drawn again until it is not one of `taken`.

    Every key gets a suffix, not only one that clashes: a `_2` would tell an admin
    that a field they may not see already holds the plain key.
    """
    ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_") or "campo"
    if base[0].isdigit():
        base = f"campo_{base}"
    used = set(taken)
    while True:
        end = f"_{suffix()}"
        key = base[: KEY_MAX_LENGTH - len(end)].rstrip("_") + end
        if key not in used:
            return key


def reorder(defs: list[dict[str, Any]], keys: list[str], role: str) -> list[dict[str, Any]]:
    """`defs` with the fields `role` sees put in the order of `keys`, which must name
    each of them once. Fields `role` does not see keep their places."""
    shown = [d["key"] for d in defs if sees(role, d)]
    if sorted(keys) != sorted(shown):
        raise ValueError("keys must list every field once")
    by_key = {d["key"]: d for d in defs}
    order = iter(keys)
    return [by_key[next(order)] if sees(role, d) else d for d in defs]


def validate_value(definition: Mapping[str, Any], raw: Any) -> Any:
    """`raw` as stored for the field, or `None` to clear it. Raises `InvalidValue`."""
    if raw is None:
        return None
    kind = FieldType(definition["type"])
    if kind is FieldType.TEXT:
        if not isinstance(raw, str):
            raise InvalidValue("must be text")
        value = raw.strip()
        if len(value) > TEXT_MAX_LENGTH:
            raise InvalidValue(f"at most {TEXT_MAX_LENGTH} characters")
        return value or None
    if kind is FieldType.NUMBER:
        if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
            raise InvalidValue("must be a number")
        return raw
    if kind is FieldType.DATE:
        try:
            if not isinstance(raw, str) or _ISO_DATE.fullmatch(raw) is None:
                raise ValueError
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            raise InvalidValue("must be a date, YYYY-MM-DD") from None
    if not isinstance(raw, str) or raw not in definition.get("options", []):
        raise InvalidValue("must be one of the field's options")
    return raw


class FieldCipher:
    """Seals and opens sensitive values, keyed by `FIELD_ENCRYPTION_KEY`."""

    def __init__(self, field_encryption_key: str) -> None:
        key = hashlib.sha256(b"custom-field-value\0" + field_encryption_key.encode()).digest()
        self._aead = AESGCM(key)

    @staticmethod
    def _bound_to(gym_id: uuid.UUID, person_id: uuid.UUID, field_key: str) -> bytes:
        return f"{gym_id}\0{person_id}\0{field_key}".encode()

    def seal(self, gym_id: uuid.UUID, person_id: uuid.UUID, field_key: str, value: Any) -> bytes:
        nonce = os.urandom(12)
        plain = json.dumps(value).encode()
        return nonce + self._aead.encrypt(
            nonce, plain, self._bound_to(gym_id, person_id, field_key)
        )

    def open(self, gym_id: uuid.UUID, person_id: uuid.UUID, field_key: str, sealed: bytes) -> Any:
        nonce, body = sealed[:12], sealed[12:]
        plain = self._aead.decrypt(nonce, body, self._bound_to(gym_id, person_id, field_key))
        return json.loads(plain)
