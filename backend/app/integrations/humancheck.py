"""Telling a person from a script on a public form: the join link's (#154).

`NoHumanCheck`, the default, asks nothing and lets every submission through, so a
self-hosted instance needs no account; the join form still has its honeypot and its
rate limits. `TurnstileCheck` is Cloudflare Turnstile: the form shows its widget with
`site_key`, and the token the widget gives the browser is checked with Cloudflare's
`siteverify` before anything is stored.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class HumanCheck(Protocol):
    # What the browser's widget needs; `None` when there is no widget to show.
    site_key: str | None

    async def verify(self, token: str | None, ip: str | None) -> bool:
        """Whether `token`, the widget's answer, says a person filled in the form."""
        ...


class NoHumanCheck:
    site_key: str | None = None

    async def verify(self, token: str | None, ip: str | None) -> bool:
        return True


# The form fields in, Cloudflare's JSON answer out.
Post = Callable[[str, dict[str, str], float], dict[str, object]]


def _post(url: str, fields: dict[str, str], timeout: float) -> dict[str, object]:
    data = urllib.parse.urlencode(fields).encode()
    with urllib.request.urlopen(url, data=data, timeout=timeout) as response:
        answer: dict[str, object] = json.load(response)
    return answer


class TurnstileCheck:
    def __init__(
        self,
        *,
        site_key: str,
        secret_key: str,
        timeout: float = 5.0,
        post: Post = _post,
    ) -> None:
        self.site_key: str | None = site_key
        self._secret_key = secret_key
        self._timeout = timeout
        self._post = post

    async def verify(self, token: str | None, ip: str | None) -> bool:
        if not token:
            return False
        fields = {"secret": self._secret_key, "response": token}
        if ip:
            fields["remoteip"] = ip
        try:
            answer = await asyncio.to_thread(self._post, SITEVERIFY_URL, fields, self._timeout)
        except (OSError, urllib.error.URLError, ValueError):
            # Cloudflare unreachable: refuse, and say so; the person can try again.
            logger.exception("turnstile: siteverify failed")
            return False
        return answer.get("success") is True
