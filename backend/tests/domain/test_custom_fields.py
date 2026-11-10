"""Custom fields' rules: visibility by role, keys, ordering, typed values, sealing."""

import uuid
from typing import Any

import pytest
from cryptography.exceptions import InvalidTag

from app.domain.custom_fields import (
    FieldCipher,
    InvalidValue,
    definitions,
    key_for,
    normalize,
    reorder,
    sees,
    validate_value,
)


def field(key: str, visible_to: str | None = None, **extra: Any) -> dict[str, Any]:
    stored: dict[str, Any] = {"key": key, "label": key, "type": "text", **extra}
    if visible_to:
        stored["visible_to"] = visible_to
    return normalize(stored)


def test_a_stored_definition_reads_with_its_defaults() -> None:
    stored = {"custom_fields": [{"key": "a", "label": "A", "type": "text"}]}
    assert definitions(stored) == [
        {
            "key": "a",
            "label": "A",
            "type": "text",
            "sensitive": False,
            "visible_to": "staff",
            "archived": False,
        }
    ]
    assert definitions({}) == []


def test_a_sensitive_field_defaults_to_the_owner_alone() -> None:
    assert field("salud", sensitive=True)["visible_to"] == "owner"
    assert field("salud", "staff", sensitive=True)["visible_to"] == "staff"


@pytest.mark.parametrize(
    ("visible_to", "seen_by"),
    [
        ("owner", {"owner"}),
        ("admin", {"owner", "admin"}),
        ("staff", {"owner", "admin", "coach"}),
    ],
)
def test_who_sees_a_field(visible_to: str, seen_by: set[str]) -> None:
    for role in ("owner", "admin", "coach", None):
        assert sees(role, field("x", visible_to)) == (role in seen_by)


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Contacto de emergencia", "contacto_de_emergencia_ab12"),
        ("Peso (kg)", "peso_kg_ab12"),
        ("Año de ingreso", "ano_de_ingreso_ab12"),
        ("1er dan", "campo_1er_dan_ab12"),
        ("¿?", "campo_ab12"),
        ("x" * 60, "x" * 35 + "_ab12"),
    ],
)
def test_a_key_is_made_from_the_label_and_a_suffix(label: str, key: str) -> None:
    assert key_for(label, [], suffix=lambda: "ab12") == key


def test_a_key_draws_its_suffix_again_until_it_is_free() -> None:
    draws = iter(["aaaa", "bbbb", "cccc"])
    taken = ["peso_aaaa", "peso_bbbb"]
    assert key_for("Peso", taken, suffix=lambda: next(draws)) == "peso_cccc"


def test_a_key_is_suffixed_even_when_the_plain_one_is_free() -> None:
    # So a suffix never says another field, perhaps hidden, holds the plain key.
    made = key_for("Peso", [])
    assert made != "peso" and made.startswith("peso_") and len(made) == len("peso_") + 4


def test_reorder_moves_what_the_role_sees_and_keeps_the_rest_in_place() -> None:
    defs = [field("a"), field("secreto", "owner"), field("b"), field("c")]
    out = reorder(defs, ["c", "a", "b"], "coach")
    assert [d["key"] for d in out] == ["c", "secreto", "a", "b"]
    with pytest.raises(ValueError):
        reorder(defs, ["c", "a"], "coach")
    with pytest.raises(ValueError):
        reorder(defs, ["c", "a", "b", "secreto"], "coach")
    with pytest.raises(ValueError):
        reorder(defs, ["a", "a", "b"], "coach")


ENUM = normalize({"key": "k", "label": "K", "type": "enum", "options": ["Gallo", "Pluma"]})


@pytest.mark.parametrize(
    ("type_", "raw", "stored"),
    [
        ("text", "  hola ", "hola"),
        ("text", "   ", None),
        ("text", None, None),
        ("number", 72, 72),
        ("number", 72.5, 72.5),
        ("date", "2026-11-09", "2026-11-09"),
    ],
)
def test_valid_values(type_: str, raw: Any, stored: Any) -> None:
    assert validate_value(normalize({"key": "k", "label": "K", "type": type_}), raw) == stored


@pytest.mark.parametrize(
    ("type_", "raw"),
    [
        ("text", 5),
        ("text", "x" * 1001),
        ("number", "72"),
        ("number", True),
        ("number", float("nan")),
        ("date", "09-11-2026"),
        ("date", "20261109"),
        ("date", "2026-02-30"),
        ("date", 20261109),
    ],
)
def test_invalid_values(type_: str, raw: Any) -> None:
    with pytest.raises(InvalidValue):
        validate_value(normalize({"key": "k", "label": "K", "type": type_}), raw)


def test_an_enum_takes_only_its_options() -> None:
    assert validate_value(ENUM, "Pluma") == "Pluma"
    for raw in ("pluma", "Pesado", 1):
        with pytest.raises(InvalidValue):
            validate_value(ENUM, raw)


def test_a_sealed_value_opens_only_where_it_was_sealed() -> None:
    cipher = FieldCipher("a-test-secret-key-0123")
    gym, person = uuid.uuid4(), uuid.uuid4()
    sealed = cipher.seal(gym, person, "salud", "asma")
    assert b"asma" not in sealed
    assert cipher.open(gym, person, "salud", sealed) == "asma"
    for elsewhere in ((gym, uuid.uuid4(), "salud"), (gym, person, "peso")):
        with pytest.raises(InvalidTag):
            cipher.open(*elsewhere, sealed)
    with pytest.raises(InvalidTag):
        FieldCipher("another-secret-key-456").open(gym, person, "salud", sealed)
