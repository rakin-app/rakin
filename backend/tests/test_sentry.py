import pytest

from app.main import create_app
from tests.conftest import make_settings


def test_the_api_starts_sentry_from_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr("app.main.init_sentry", lambda s: started.append(s.sentry_dsn))

    create_app(make_settings(sentry_dsn="https://public@sentry.invalid/1"))

    assert started == ["https://public@sentry.invalid/1"]
