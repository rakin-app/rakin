import re
from pathlib import Path

from sqlalchemy.engine import make_url

from tests.test_settings import read_env_example

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# `${NAME:-default}` and bare `${NAME}`; `$${NAME}` is an escaped, container-side reference.
INTERPOLATION = re.compile(r"(?<!\$)\$\{(\w+)(?::-([^}]*))?\}")
SERVICE = re.compile(r"^  ([\w-]+):\n", re.MULTILINE)
SUPERUSER = ("POSTGRES_USER", "POSTGRES_PASSWORD")


def compose_text(path: Path = COMPOSE_FILE) -> str:
    return path.read_text()


def compose_variables() -> dict[str, set[str | None]]:
    found: dict[str, set[str | None]] = {}
    for match in INTERPOLATION.finditer(compose_text()):
        name, default = match.group(1), match.group(2)
        found.setdefault(name, set()).add(default)
    return found


def services(path: Path = COMPOSE_FILE) -> dict[str, str]:
    """Each service's block of a Compose file, by name."""
    text = compose_text(path)
    body = text[text.index("\nservices:\n") : text.index("\nvolumes:\n")]
    names = list(SERVICE.finditer(body))
    return {
        m.group(1): body[m.end() : names[i + 1].start() if i + 1 < len(names) else len(body)]
        for i, m in enumerate(names)
    }


def test_compose_interpolates_variables() -> None:
    assert compose_variables()


def test_every_compose_variable_is_listed_in_env_example_with_its_default() -> None:
    listed = read_env_example()
    mismatched = {
        name: (defaults, listed.get(name))
        for name, defaults in compose_variables().items()
        if name not in listed or defaults - {None} - {listed[name]}
    }
    assert mismatched == {}


def test_env_example_urls_use_the_users_compose_bootstraps() -> None:
    listed = read_env_example()
    for url, prefix in (
        ("DATABASE_URL", "POSTGRES_API"),
        ("MIGRATION_DATABASE_URL", "POSTGRES_OWNER"),
    ):
        parsed = make_url(listed[url])
        assert (parsed.username, parsed.password) == (
            listed[f"{prefix}_USER"],
            listed[f"{prefix}_PASSWORD"],
        )


def test_no_container_loads_the_whole_env_file() -> None:
    assert "env_file" not in compose_text()


def test_only_postgres_and_migrate_see_the_superuser() -> None:
    blocks = services()
    assert {"postgres", "migrate", "api", "jobs"} <= blocks.keys()
    seen = {name for name, block in blocks.items() if any(f"${{{v}" in block for v in SUPERUSER)}
    assert seen == {"postgres", "migrate"}
