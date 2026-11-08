"""Chilean peso amounts. CLP has no cents, so money is always an `int`."""


def format_clp(amount: int) -> str:
    """Format an integer CLP amount the Chilean way: `45000` -> `$45.000`, `-1500` -> `-$1.500`."""
    # `bool` is an `int` subclass; `format_clp(True)` is a bug, not one peso.
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise TypeError(f"CLP amounts are integers, got {type(amount).__name__}")
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,}".replace(",", ".")
