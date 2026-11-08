import re
from pathlib import Path

from tests.test_settings import read_env_example

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# `${NAME:-default}` interpolations; `$${NAME}` is an escaped, container-side reference.
INTERPOLATION = re.compile(r"(?<!\$)\$\{(\w+):-([^}]*)\}")


def compose_variables() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name, default in INTERPOLATION.findall(COMPOSE_FILE.read_text()):
        found.setdefault(name, set()).add(default)
    return found


def test_compose_interpolates_variables() -> None:
    assert compose_variables()


def test_every_compose_variable_is_listed_in_env_example_with_its_default() -> None:
    listed = read_env_example()
    mismatched = {
        name: (defaults, listed.get(name))
        for name, defaults in compose_variables().items()
        if defaults != {listed.get(name)}
    }
    assert mismatched == {}
