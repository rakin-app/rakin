import pytest

from app.backup import ReportingSettings
from app.main import create_app
from app.sentry import init_sentry
from tests.conftest import make_settings


def test_the_api_starts_sentry_from_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr("app.main.init_sentry", lambda s: started.append(s.sentry_dsn))

    create_app(make_settings(sentry_dsn="https://public@sentry.invalid/1"))

    assert started == ["https://public@sentry.invalid/1"]


def test_sentry_reports_its_own_environment_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    environments: list[str] = []
    monkeypatch.setattr(
        "app.sentry.sentry_sdk.init", lambda **kw: environments.append(kw["environment"])
    )
    dsn = "https://public@sentry.invalid/1"

    init_sentry(make_settings(sentry_dsn=dsn))
    init_sentry(make_settings(sentry_dsn=dsn, sentry_environment="staging"))
    monkeypatch.setenv("SENTRY_DSN", dsn)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    init_sentry(ReportingSettings())
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "")  # Compose's unset: ENVIRONMENT
    init_sentry(ReportingSettings())

    assert environments == ["test", "staging", "staging", "production"]
