import pytest

from app.security import constant_time_equals


@pytest.mark.parametrize(
    ("a", "b", "equal"),
    [
        ("abc", "abc", True),
        ("", "", True),
        ("abc", "abd", False),
        ("abc", "abcd", False),
        ("ñandú", "ñandú", True),
        ("abc", "é", False),
        ("é", "abc", False),
        ("abc", "\udcff", False),  # a lone surrogate has no UTF-8: not equal, no error
        ("\udcff", "\udcff", False),
    ],
)
def test_it_compares_any_two_strings_without_raising(a: str, b: str, equal: bool) -> None:
    assert constant_time_equals(a, b) is equal
