"""Chilean RUT (Rol Único Tributario): validation, normalisation and display formatting.

A RUT is a body of digits plus a mod-11 check digit (`0`-`9` or `K`). It is written
`76.123.456-0` for display and stored normalised as `76123456-0`.
"""

import re

# Input may carry dots, a dash and spaces; whatever is left must be digits then a check digit.
_SEPARATORS = re.compile(r"[\s.\-]")
# `[0-9]`, not `\d`: `\d` also matches non-ASCII digits.
_SHAPE = re.compile(r"([0-9]{1,9})([0-9K])")


class InvalidRutError(ValueError):
    pass


def check_digit(body: int) -> str:
    """The mod-11 check digit for a RUT body: weights 2..7, cycling, from the rightmost digit."""
    if body < 1:
        raise InvalidRutError("RUT body must be a positive number")
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(str(body))))
    digit = 11 - total % 11
    return {10: "K", 11: "0"}.get(digit, str(digit))


def _split(raw: str) -> tuple[int, str]:
    match = _SHAPE.fullmatch(_SEPARATORS.sub("", raw).upper())
    if match is None or int(match[1]) == 0:
        raise InvalidRutError(f"not a RUT: {raw!r}")
    body, digit = int(match[1]), match[2]
    if check_digit(body) != digit:
        raise InvalidRutError(f"RUT check digit does not match: {raw!r}")
    return body, digit


def normalize_rut(raw: str) -> str:
    """Canonical storage form, `76123456-0`. Raises `InvalidRutError` if malformed or wrong."""
    body, digit = _split(raw)
    return f"{body}-{digit}"


def format_rut(raw: str) -> str:
    """Display form, `76.123.456-0`. Raises `InvalidRutError` on a malformed or wrong RUT."""
    body, digit = _split(raw)
    return f"{body:,}".replace(",", ".") + f"-{digit}"


def is_valid_rut(raw: str) -> bool:
    try:
        _split(raw)
    except InvalidRutError:
        return False
    return True
