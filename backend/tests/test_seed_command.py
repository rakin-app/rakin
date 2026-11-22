"""`python -m app.seed` refuses on production unless the host is seed-only (#464), and
takes the addresses staging signs in with (#503)."""

import sys
from datetime import date

import pytest

from app.seed import Loaded
from app.seed import __main__ as seed_command
from app.seed.build import build
from tests.conftest import make_settings

PRODUCTION = {"environment": "production", "secret_key": "x" * 32, "field_encryption_key": "y" * 32}


def seed(
    monkeypatch: pytest.MonkeyPatch, *args: str, **settings: object
) -> list[tuple[object, object]]:
    ran: list[tuple[object, object]] = []

    async def run(today: object, sign_in: object) -> tuple[object, int]:
        ran.append((today, sign_in))
        raise SystemExit(0)

    monkeypatch.setattr(seed_command, "get_settings", lambda: make_settings(**settings))
    monkeypatch.setattr(seed_command, "run", run)
    monkeypatch.setattr(sys, "argv", ["app.seed", *args])
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
    assert seed(monkeypatch, **settings) == [(None, [])]


def test_sign_in_takes_staging_operators_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    assert seed(monkeypatch, "--sign-in", "pm@rakin.app,owner@team.example") == [
        (None, ["pm@rakin.app", "owner@team.example"])
    ]


def test_it_says_who_each_address_became() -> None:
    seed_rows = build(date(2026, 11, 8), ["pm@rakin.app", "owner@team.example"])
    fresh = Loaded(seed_rows, {"person": len(seed_rows.people)})
    assert seed_command.sign_in_lines(fresh, ["pm@rakin.app", "owner@team.example"]) == [
        "sign in as Felipe Díaz (student, Vencido): pm@rakin.app",
        "sign in as Martín Fuentes (owner): owner@team.example",
    ]
    assert seed_command.sign_in_lines(fresh, []) == []
    # A reload writes no person, so the addresses are not there.
    reloaded = Loaded(seed_rows, {"person": 0})
    assert "ignored" in seed_command.sign_in_lines(reloaded, ["pm@rakin.app"])[0]
