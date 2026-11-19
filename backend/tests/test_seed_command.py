"""`python -m app.seed` refuses on production unless the host is seed-only (#464)."""

import sys

import pytest

from app.seed import __main__ as seed_command
from tests.conftest import make_settings

PRODUCTION = {"environment": "production", "secret_key": "x" * 32, "field_encryption_key": "y" * 32}


def seed(monkeypatch: pytest.MonkeyPatch, **settings: object) -> list[object]:
    ran: list[object] = []

    async def run(today: object) -> tuple[object, int]:
        ran.append(today)
        raise SystemExit(0)

    monkeypatch.setattr(seed_command, "get_settings", lambda: make_settings(**settings))
    monkeypatch.setattr(seed_command, "run", run)
    monkeypatch.setattr(sys, "argv", ["app.seed"])
    with pytest.raises(SystemExit):
        seed_command.main()
    return ran


def test_seed_refuses_on_production_naming_seed_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed(monkeypatch, **PRODUCTION) == []
    assert "SEED_ONLY" in capsys.readouterr().err


@pytest.mark.parametrize(
    "settings",
    [{**PRODUCTION, "seed_only": True}, {"environment": "local"}, {"environment": "test"}],
)
def test_seed_runs_on_a_seed_only_host_and_off_production(
    monkeypatch: pytest.MonkeyPatch, settings: dict[str, object]
) -> None:
    assert seed(monkeypatch, **settings) == [None]
