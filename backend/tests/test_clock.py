"""Today is the gym's date, never the host's (#122).

The API reckons "today" in `gym.timezone` (`app.domain.dates.gym_today`, and
`now() AT TIME ZONE g.timezone` in SQL). On a UTC machine the host's date runs a day
ahead of Chile's from 00:00 UTC until Chile's own midnight, so a test that built its
periods on the host's date disagreed with the API, and CI failed every night for
those hours.

This scan refuses the host-date idioms in `app`, `tests` and `alembic` (outside this
file, whose cases are made of them). A line that does mean the host's or UTC's date
says so with a `# system date: <why>` comment on it or on the line above.
"""

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROOTS = ("app", "tests", "alembic")
MARKER = "# system date:"

HOST_DATE = re.compile(
    r"\bdate\.today\("
    r"|\bdatetime\.today\("
    r"|\bdatetime\.now\(\s*\)"
    r"|\butcnow\("
    r"|\.now\(UTC\)\.date\(\)"
)


def host_dates(source: str) -> list[tuple[int, str]]:
    """The lines of `source` that take the host's date without a `system date` marker."""
    lines = source.splitlines()
    return [
        (n, line.strip())
        for n, line in enumerate(lines, start=1)
        if HOST_DATE.search(line)
        and MARKER not in line
        and not (n > 1 and lines[n - 2].strip().startswith(MARKER))
    ]


def test_no_code_takes_the_hosts_date() -> None:
    found = [
        f"{path.relative_to(BACKEND)}:{n}: {line}"
        for root in ROOTS
        for path in sorted((BACKEND / root).rglob("*.py"))
        if path != Path(__file__).resolve()
        for n, line in host_dates(path.read_text())
    ]
    assert not found, "use gym_today(tz), or mark the line '# system date: <why>':\n" + "\n".join(
        found
    )


@pytest.mark.parametrize(
    "line",
    [
        "start = date.today()",
        "now = datetime.today()",
        "now = datetime.now()",
        "now = datetime.utcnow()",
        "day = datetime.now(UTC).date()",
    ],
)
def test_the_scan_catches_each_idiom(line: str) -> None:
    assert host_dates(line) == [(1, line)]


def test_the_scan_takes_a_marker_on_the_line_or_the_one_above() -> None:
    assert host_dates("x = date.today()  # system date: pydantic's") == []
    assert host_dates("# system date: pydantic's\nx = date.today()") == []
    assert host_dates("# system date: one line only\ny = 1\nx = date.today()") == [
        (3, "x = date.today()")
    ]


def test_the_scan_leaves_aware_instants_alone() -> None:
    assert host_dates("now = datetime.now(UTC)\nday = gym_today(tz)") == []
