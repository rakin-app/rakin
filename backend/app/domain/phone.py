"""Chilean mobile numbers, normalised to E.164 (`+56912345678`).

The phone is a person's identity because it is what WhatsApp uses, so only mobiles are
accepted: since 2012 every Chilean mobile is `9` followed by eight digits.
"""

import re

_SEPARATORS = re.compile(r"[\s.\-()]")
# `[0-9]`, not `\d`: `\d` also matches non-ASCII digits.
_CHILEAN_MOBILE = re.compile(r"56(9[0-9]{8})")


class InvalidPhoneError(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Normalise a Chilean mobile to E.164.

    Accepts the usual ways people type one: `+56 9 1234 5678`, `56912345678`,
    `0056 9 1234 5678`, `(9) 1234-5678`, `912345678`. Raises `InvalidPhoneError` otherwise,
    including for landlines and other countries' numbers.
    """
    digits = _SEPARATORS.sub("", raw)
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    elif len(digits) == 9:
        digits = "56" + digits
    if _CHILEAN_MOBILE.fullmatch(digits) is None:
        raise InvalidPhoneError(f"not a Chilean mobile number: {raw!r}")
    return "+" + digits


def is_valid_phone(raw: str) -> bool:
    try:
        normalize_phone(raw)
    except InvalidPhoneError:
        return False
    return True
