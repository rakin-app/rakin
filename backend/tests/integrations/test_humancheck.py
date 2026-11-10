"""The human check on the join form (#154): none by default, Turnstile when configured."""

import asyncio

import pytest
from pydantic import ValidationError

from app.integrations import build_human_check
from app.integrations.humancheck import SITEVERIFY_URL, NoHumanCheck, TurnstileCheck
from tests.conftest import make_settings


def test_by_default_there_is_no_check() -> None:
    check = build_human_check(make_settings())

    assert isinstance(check, NoHumanCheck)
    assert check.site_key is None
    assert asyncio.run(check.verify(None, None)) is True


def test_turnstile_is_built_from_its_keys() -> None:
    check = build_human_check(
        make_settings(human_check="turnstile", turnstile_site_key="site", turnstile_secret_key="s")
    )

    assert isinstance(check, TurnstileCheck)
    assert check.site_key == "site"


def turnstile(answer: dict[str, object] | Exception, calls: list[object]) -> TurnstileCheck:
    def post(url: str, fields: dict[str, str], timeout: float) -> dict[str, object]:
        calls.append((url, fields))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return TurnstileCheck(site_key="site", secret_key="secret", post=post)


def test_turnstile_asks_cloudflare_about_the_token() -> None:
    calls: list[object] = []
    check = turnstile({"success": True}, calls)

    assert asyncio.run(check.verify("tok", "203.0.113.9")) is True
    assert calls == [
        (SITEVERIFY_URL, {"secret": "secret", "response": "tok", "remoteip": "203.0.113.9"})
    ]


def test_turnstile_refuses_a_failed_missing_or_unverifiable_token() -> None:
    calls: list[object] = []

    assert asyncio.run(turnstile({"success": False}, calls).verify("tok", None)) is False
    assert asyncio.run(turnstile({"success": True}, calls).verify(None, None)) is False
    assert asyncio.run(turnstile(OSError("down"), calls).verify("tok", None)) is False
    # The missing token never reached Cloudflare.
    assert len(calls) == 2


@pytest.mark.parametrize(
    "keys",
    [
        {},
        {"turnstile_site_key": "site"},
        {"turnstile_secret_key": "s"},
        {"turnstile_site_key": " ", "turnstile_secret_key": "s"},
    ],
)
def test_turnstile_without_its_keys_is_refused_at_startup(keys: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY"):
        make_settings(human_check="turnstile", **keys)
