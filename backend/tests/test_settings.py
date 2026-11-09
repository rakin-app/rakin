from pathlib import Path

import pytest

from app.settings import Settings
from tests.conftest import make_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def read_env_example(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_every_setting_is_listed_in_env_example() -> None:
    listed = read_env_example()
    missing = [name.upper() for name in Settings.model_fields if name.upper() not in listed]
    assert missing == []


def test_env_example_values_are_valid_and_match_the_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)

    from_example = Settings(_env_file=ENV_EXAMPLE)

    assert from_example == Settings(_env_file=None)


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/x")

    settings = make_settings()

    assert settings.log_level == "DEBUG"
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/x"


def test_invalid_values_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError, match="log_level"):
        make_settings()


def test_production_refuses_the_local_secret_key() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        make_settings(environment="production")

    production = make_settings(
        environment="production", secret_key="x" * 32, field_encryption_key="y" * 32
    )
    assert production.secret_key == "x" * 32


def test_production_refuses_the_local_field_encryption_key() -> None:
    with pytest.raises(ValueError, match="FIELD_ENCRYPTION_KEY"):
        make_settings(environment="production", secret_key="x" * 32)

    production = make_settings(
        environment="production", secret_key="x" * 32, field_encryption_key="y" * 32
    )
    assert production.field_encryption_key == "y" * 32


def test_the_defaults_need_no_network() -> None:
    settings = make_settings()

    assert (settings.mailer, settings.messenger, settings.blob_store) == (
        "console",
        "wame",
        "local",
    )
    assert (settings.payment_rail, settings.bank_feed) == ("none", "none")


def test_jobs_timezone_must_be_a_known_zone() -> None:
    with pytest.raises(ValueError, match="unknown timezone 'Mars/Base'"):
        make_settings(jobs_timezone="Mars/Base")

    assert make_settings(jobs_timezone="UTC").jobs_timezone == "UTC"
