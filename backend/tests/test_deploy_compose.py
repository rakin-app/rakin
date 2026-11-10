"""The hosted stack's Compose file (`deploy/`) against the settings it must carry."""

import re
from pathlib import Path

from app.settings import Settings
from tests.test_compose import SUPERUSER, compose_text, services
from tests.test_settings import read_env_example

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
COMPOSE_FILE = DEPLOY / "docker-compose.yml"
ENV_EXAMPLE = DEPLOY / ".env.example"

# `${NAME}`, `${NAME:-default}` and `${NAME:?message}`; `$${NAME}` is container-side.
INTERPOLATION = re.compile(r"(?<!\$)\$\{(\w+)(?:(:[-?])([^}]*))?\}")


def interpolations() -> list[tuple[str, str | None, str]]:
    """Each `(name, operator, argument)` the hosted Compose file interpolates."""
    return [(m[1], m[2], m[3]) for m in INTERPOLATION.finditer(compose_text(COMPOSE_FILE))]


def backend_environment() -> set[str]:
    text = compose_text(COMPOSE_FILE)
    block = text[text.index("\nx-backend:") : text.index("\nservices:\n")]
    env = block[block.index("  environment:") :]
    return set(re.findall(r"^    (\w+):", env, re.MULTILINE))


def test_every_setting_reaches_the_api_and_jobs() -> None:
    missing = {name.upper() for name in Settings.model_fields} - backend_environment()
    assert missing == set()


def test_env_example_lists_exactly_the_variables_compose_reads() -> None:
    listed = read_env_example(ENV_EXAMPLE)
    read = {name for name, _, _ in interpolations()}
    assert read - listed.keys() == set()
    assert listed.keys() - read == set()


def test_compose_defaults_match_env_example() -> None:
    listed = read_env_example(ENV_EXAMPLE)
    mismatched = {
        name: (default, listed[name])
        for name, op, default in interpolations()
        # A `<placeholder>` is a value to fill in, which the default need not match.
        if op == ":-" and default != listed[name] and not listed[name].startswith("<")
    }
    assert mismatched == {}


def test_secrets_have_no_default() -> None:
    secrets = {
        "SECRET_KEY",
        "FIELD_ENCRYPTION_KEY",
        "SMTP_PASSWORD",
        "S3_SECRET_ACCESS_KEY",
        "POSTGRES_PASSWORD",
        "POSTGRES_API_PASSWORD",
        "POSTGRES_OWNER_PASSWORD",
    }
    ops = {(name, op) for name, op, _ in interpolations() if name in secrets}
    assert ops == {(name, ":?") for name in secrets}


def test_hosted_runs_released_images_only() -> None:
    text = compose_text(COMPOSE_FILE)
    assert "build:" not in text
    assert "env_file" not in text
    assert "--reload" not in text
    blocks = services(COMPOSE_FILE)
    assert blocks.keys() == {"caddy", "migrate", "api", "jobs", "postgres"}
    assert "ports:" not in blocks["postgres"]


def test_migrations_run_only_when_asked() -> None:
    # `up` must not run them: a rollback's older Alembic refuses newer revisions.
    blocks = services(COMPOSE_FILE)
    assert 'profiles: ["migrate"]' in blocks["migrate"]
    assert all("migrate" not in blocks[name] for name in ("api", "jobs", "caddy"))


def test_only_postgres_and_migrate_see_the_superuser() -> None:
    seen = {
        name
        for name, block in services(COMPOSE_FILE).items()
        if any(f"${{{v}" in block for v in SUPERUSER)
    }
    assert seen == {"postgres", "migrate"}
