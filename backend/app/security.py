"""Small security primitives shared across the app."""

import hmac


def constant_time_equals(a: str, b: str) -> bool:
    """Whether `a` and `b` are equal, in time that does not depend on where they differ.

    For comparing a signature from a request with the expected one. `hmac.compare_digest`
    raises on a `str` with non-ASCII characters, so this compares UTF-8 bytes, and a
    value that has no UTF-8 encoding (a lone surrogate) is simply not equal.
    """
    try:
        return hmac.compare_digest(a.encode(), b.encode())
    except UnicodeEncodeError:
        return False
