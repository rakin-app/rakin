"""A test gym's slug carries a full UUID, never a few hex digits of one (#335).

A run seeds hundreds of gyms into one database, and `gym.slug` is UNIQUE. Slugs of a
prefix and `uuid4().hex[:6]`, 24 random bits, met there once (`gym_slug_key`), so each
is now `tests.ids.unique_slug(prefix)`. This scan refuses a line in `tests` that cuts a
hex string short where it builds a gym or a slug.
"""

import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

SHORT_HEX = re.compile(r"\.hex\[:\d+\]")
BUILDS_A_SLUG = re.compile(r"\bseed_gym\(|\bnew_gym\(|\bstaffed\(|slug")


def short_slugs(source: str) -> list[tuple[int, str]]:
    """The lines of `source` that build a gym slug from a cut-short hex string."""
    return [
        (n, line.strip())
        for n, line in enumerate(source.splitlines(), start=1)
        if SHORT_HEX.search(line) and BUILDS_A_SLUG.search(line)
    ]


def test_no_test_gym_slug_is_cut_short() -> None:
    found = [
        f"{path.relative_to(TESTS.parent)}:{n}: {line}"
        for path in sorted(TESTS.rglob("*.py"))
        if path != Path(__file__).resolve()
        for n, line in short_slugs(path.read_text())
    ]
    assert not found, "use tests.ids.unique_slug(prefix):\n" + "\n".join(found)


@pytest.mark.parametrize(
    "line",
    [
        'gym = seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}")',
        'gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}")',
        'slug_b = f"sur-{uuid.uuid4().hex[:8]}"',
    ],
)
def test_a_short_slug_is_found(line: str) -> None:
    assert short_slugs(line)


@pytest.mark.parametrize(
    "line",
    [
        'gym = seed_gym(db, unique_slug("academia"))',
        'address = f"{uuid.uuid4().hex[:8]}@example.cl"',
        'job = Job(f"billing-{uuid.uuid4().hex[:8]}", billing.generate_billing_periods)',
    ],
)
def test_other_short_hex_is_left_alone(line: str) -> None:
    assert not short_slugs(line)
