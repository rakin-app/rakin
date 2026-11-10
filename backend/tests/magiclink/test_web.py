"""The module end to end over HTTP, with in-memory accounts, storage and delivery.

Rakin's Postgres store and directory have their own tests in `tests/test_auth.py`.
"""

import asyncio
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.magiclink import (
    COOKIE_NAME,
    DEV_COOKIE_NAME,
    Link,
    MagicLinks,
    MemoryRateLimiter,
    Recipient,
    Session,
    SessionMiddleware,
    build_router,
    callback_url,
    session_cookie_name,
)
from app.magiclink.tokens import hash_token

BASE_URL = "https://app.example"
PREFIX = "/auth"
IP = "x-test-ip"

ANA = Recipient("ana", "ana@example.cl", "Ana")
# Two accounts on one address, as a parent and child may share one.
CAMILA = Recipient("camila", "familia@example.cl", "Camila")
MATEO = Recipient("mateo", "familia@example.cl", "Mateo")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class DirectoryDown(Exception):
    pass


@dataclass
class Directory:
    down: bool = False  # every lookup raises, as with the database unreachable

    async def recipients(self, address: str) -> Sequence[Recipient]:
        if self.down:
            raise DirectoryDown
        return [r for r in (ANA, CAMILA, MATEO) if r.address == address.strip().lower()]

    async def scope(self, subject: str) -> str | None:
        if self.down:
            raise DirectoryDown
        return None if subject == "camila" else f"gym-of-{subject}"


@dataclass
class Store:
    links: dict[bytes, tuple[str, datetime, bool]] = field(default_factory=dict)
    sessions: dict[bytes, tuple[Session, bool]] = field(default_factory=dict)

    async def add_link(self, token_hash: bytes, subject: str, expires_at: datetime) -> None:
        self.links[token_hash] = (subject, expires_at, False)

    async def pending_link(self, token_hash: bytes, now: datetime) -> str | None:
        subject, expires_at, used = self.links.get(token_hash, ("", now, True))
        return None if used or now >= expires_at else subject

    async def redeem_link(
        self, token_hash: bytes, now: datetime, session_hash: bytes, session: Session
    ) -> bool:
        if await self.pending_link(token_hash, now) != session.subject:
            return False
        subject, expires_at, _ = self.links[token_hash]
        self.links[token_hash] = (subject, expires_at, True)
        self.sessions[session_hash] = (session, False)
        return True

    async def session(self, token_hash: bytes, now: datetime) -> Session | None:
        session, ended = self.sessions.get(token_hash, (None, True))
        return session if session and not ended and now < session.expires_at else None

    async def end_session(self, token_hash: bytes, now: datetime) -> None:
        if token_hash in self.sessions:
            self.sessions[token_hash] = (self.sessions[token_hash][0], True)


@dataclass
class Outbox:
    sent: list[Link] = field(default_factory=list)
    refuse: set[str] = field(default_factory=set)  # subjects whose send raises

    async def send(self, link: Link) -> None:
        if link.recipient.subject in self.refuse:
            raise ConnectionError("mail server said no")
        self.sent.append(link)

    def url_for(self, recipient: Recipient) -> str:
        [url] = [link.url for link in self.sent if link.recipient == recipient]
        return url


@dataclass
class Harness:
    client: TestClient
    directory: Directory
    clock: Clock
    store: Store
    outbox: Outbox
    links: MagicLinks

    def request_link(self, email: str, ip: str = "203.0.113.1") -> int:
        response = self.client.post(f"{PREFIX}/link", json={"email": email}, headers={IP: ip})
        return int(response.status_code)

    def sign_in(self, recipient: Recipient) -> Any:
        assert self.request_link(recipient.address) == 202
        token = token_of(self.outbox.url_for(recipient))
        return self.client.post(f"{PREFIX}/callback", data={"token": token})


def token_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["token"][0]


def make_app(
    links: MagicLinks, base_url: str = BASE_URL, cookie_name: str | None = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_router(
            links,
            prefix=PREFIX,
            base_url=base_url,
            landings=frozenset({"/me"}),
            cookie_name=cookie_name,
        )
    )

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, Any]:
        return {"subject": getattr(request.state, "subject", None)}

    def bind(session: Session, state: dict[str, Any]) -> None:
        state["subject"] = session.subject

    app.add_middleware(
        SessionMiddleware,
        links=links,
        bind=bind,
        cookie_name=cookie_name or session_cookie_name(base_url),
    )
    app.add_middleware(ClientAddress)
    return app


class ClientAddress:
    """The `IP` header as the client address, which TestClient fixes per client."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        ip = Headers(scope=scope).get(IP) if scope["type"] == "http" else None
        if ip:
            scope["client"] = (ip, 1234)
        await self.app(scope, receive, send)


def make_harness(base_url: str = BASE_URL, cookie_name: str | None = None) -> Iterator[Harness]:
    clock, directory, store, outbox = Clock(), Directory(), Store(), Outbox()
    links = MagicLinks(
        secret_key="s" * 32,
        callback_url=callback_url(base_url, PREFIX),
        directory=directory,
        store=store,
        sender=outbox,
        per_address=MemoryRateLimiter(limit=3, window_seconds=900),
        per_ip=MemoryRateLimiter(limit=5, window_seconds=900),
        clock=clock,
    )
    app = make_app(links, base_url, cookie_name)
    # Errors come back as 500s, as a browser would see them.
    with TestClient(
        app, base_url=base_url, follow_redirects=False, raise_server_exceptions=False
    ) as client:
        yield Harness(client, directory, clock, store, outbox, links)


@pytest.fixture
def harness() -> Iterator[Harness]:
    yield from make_harness()


# --- requesting a link ------------------------------------------------------------


def test_a_link_goes_to_the_account_at_the_address(harness: Harness) -> None:
    assert harness.request_link("Ana@Example.cl ") == 202

    [link] = harness.outbox.sent
    assert link.recipient == ANA
    assert link.url.startswith(f"{BASE_URL}{PREFIX}/callback?token=")
    assert link.expires_at == harness.clock.now + timedelta(minutes=15)


def test_each_account_at_a_shared_address_gets_its_own_link(harness: Harness) -> None:
    harness.request_link("familia@example.cl")
    assert [link.recipient for link in harness.outbox.sent] == [CAMILA, MATEO]
    assert harness.outbox.url_for(CAMILA) != harness.outbox.url_for(MATEO)


def test_a_failed_send_does_not_stop_the_others(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    harness.outbox.refuse = {CAMILA.subject}

    assert harness.request_link(CAMILA.address) == 202

    assert [link.recipient for link in harness.outbox.sent] == [MATEO]
    [failure] = [r for r in caplog.records if r.message == "magic link not sent"]
    assert failure.__dict__["subject"] == CAMILA.subject
    # Both links were stored; the log carries neither.
    assert len(harness.store.links) == 2
    logged = caplog.text + repr(failure.__dict__)
    assert "token=" not in logged and "callback" not in logged


def test_an_unknown_address_gets_the_same_answer_and_nothing_is_sent(harness: Harness) -> None:
    assert harness.request_link("nadie@example.cl") == 202
    assert harness.outbox.sent == []


@pytest.mark.parametrize("email", ["", "ana", "ana@", "@example.cl", "a na@example.cl"])
def test_something_that_is_not_an_address_is_a_422(harness: Harness, email: str) -> None:
    assert harness.request_link(email) == 422


def test_the_lookup_happens_after_the_answer(harness: Harness) -> None:
    # The directory fails, and the request has already been answered: nothing that
    # depends on the address ran before the 202.
    harness.directory.down = True
    assert harness.request_link(ANA.address) == 202
    assert harness.outbox.sent == []


def test_only_the_hash_of_a_link_is_stored(harness: Harness) -> None:
    harness.request_link(ANA.address)
    token = token_of(harness.outbox.url_for(ANA))
    assert list(harness.store.links) == [hash_token(token)]


# --- rate limits ------------------------------------------------------------------


def test_an_address_is_limited_however_it_is_spelled(harness: Harness) -> None:
    for spelling in ("ana@example.cl", "ANA@example.cl", " ana@example.cl"):
        assert harness.request_link(spelling) == 202

    response = harness.client.post(f"{PREFIX}/link", json={"email": "Ana@Example.CL"})

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) == 900
    assert len(harness.outbox.sent) == 3


def test_an_unknown_address_is_limited_too(harness: Harness) -> None:
    statuses = [harness.request_link("nadie@example.cl") for _ in range(4)]
    assert statuses == [202, 202, 202, 429]


def test_an_ip_is_limited_across_addresses(harness: Harness) -> None:
    statuses = [harness.request_link(f"n{i}@example.cl") for i in range(6)]
    assert statuses == [202] * 5 + [429]
    assert harness.request_link("n9@example.cl", ip="198.51.100.7") == 202


# --- opening a link ---------------------------------------------------------------


def test_opening_a_link_shows_a_button_and_spends_nothing(harness: Harness) -> None:
    harness.request_link(ANA.address)
    url = harness.outbox.url_for(ANA)

    response = harness.client.get(url)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "same-origin"
    page = response.text
    assert f'<form method="post" action="{PREFIX}/callback">' in page
    assert f'value="{token_of(url)}"' in page
    # A plain HTML form: it works in any browser tab, with no script to run.
    assert "<script" not in page
    assert harness.client.get(url).status_code == 200


def test_the_button_signs_in_with_a_30_day_session_cookie(harness: Harness) -> None:
    response = harness.sign_in(ANA)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    attributes = {a.strip().split("=")[0].lower() for a in cookie.split(";")}
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert {"httponly", "secure", "path", "max-age"} <= attributes
    assert "Max-Age=2592000" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "domain" not in attributes
    [(session, _)] = harness.store.sessions.values()
    assert session == Session("ana", "gym-of-ana", harness.clock.now + timedelta(days=30))


def test_an_http_base_url_signs_in_with_a_plain_cookie_that_is_not_secure() -> None:
    # Local dev, on `http://localhost`: Safari drops a Secure cookie there.
    for harness in make_harness("http://localhost:8080"):
        response = harness.sign_in(ANA)

        cookie = response.headers["set-cookie"]
        attributes = {a.strip().split("=")[0].lower() for a in cookie.split(";")}
        assert cookie.startswith(f"{DEV_COOKIE_NAME}=")
        assert "secure" not in attributes
        assert {"httponly", "path", "max-age"} <= attributes
        assert "SameSite=lax" in cookie
        assert harness.client.get("/whoami").json() == {"subject": "ana"}

        logout = harness.client.post(f"{PREFIX}/logout")
        assert f'{DEV_COOKIE_NAME}=""' in logout.headers["set-cookie"]
        assert "secure" not in logout.headers["set-cookie"].lower()
        assert harness.client.get("/whoami").json() == {"subject": None}


def test_an_https_base_url_keeps_the_cookie_secure_whatever_it_is_named() -> None:
    for harness in make_harness(BASE_URL, cookie_name=DEV_COOKIE_NAME):
        cookie = harness.sign_in(ANA).headers["set-cookie"]
        attributes = {a.strip().split("=")[0].lower() for a in cookie.split(";")}
        assert cookie.startswith(f"{DEV_COOKIE_NAME}=")
        assert "secure" in attributes
        assert "secure" in harness.client.post(f"{PREFIX}/logout").headers["set-cookie"].lower()


def test_the_router_refuses_a_host_cookie_it_cannot_make_secure() -> None:
    links = MagicLinks(
        secret_key="s" * 32,
        callback_url=callback_url("http://localhost:8080", PREFIX),
        directory=Directory(),
        store=Store(),
        sender=Outbox(),
        per_address=MemoryRateLimiter(limit=1, window_seconds=1),
        per_ip=MemoryRateLimiter(limit=1, window_seconds=1),
    )
    with pytest.raises(ValueError, match="not Secure"):
        build_router(
            links, prefix=PREFIX, base_url="http://localhost:8080", cookie_name=COOKIE_NAME
        )


def test_the_session_cookie_identifies_later_requests(harness: Harness) -> None:
    assert harness.client.get("/whoami").json() == {"subject": None}
    harness.sign_in(ANA)
    assert harness.client.get("/whoami").json() == {"subject": "ana"}


def test_a_session_can_start_with_no_scope(harness: Harness) -> None:
    harness.request_link(CAMILA.address)
    token = token_of(harness.outbox.url_for(CAMILA))
    harness.client.post(f"{PREFIX}/callback", data={"token": token})
    [(session, _)] = harness.store.sessions.values()
    assert (session.subject, session.scope) == ("camila", None)


def test_a_link_works_once(harness: Harness) -> None:
    harness.request_link(ANA.address)
    url = harness.outbox.url_for(ANA)
    form = {"token": token_of(url)}

    assert harness.client.post(f"{PREFIX}/callback", data=form).status_code == 303
    again = harness.client.post(f"{PREFIX}/callback", data=form)

    assert again.status_code == 400
    assert "set-cookie" not in again.headers
    assert len(harness.store.sessions) == 1


def test_a_failed_sign_in_leaves_the_link_usable(harness: Harness) -> None:
    harness.request_link(ANA.address)
    form = {"token": token_of(harness.outbox.url_for(ANA))}

    harness.directory.down = True
    assert harness.client.post(f"{PREFIX}/callback", data=form).status_code == 500
    harness.directory.down = False

    assert harness.client.post(f"{PREFIX}/callback", data=form).status_code == 303


def test_a_link_expires_after_15_minutes(harness: Harness) -> None:
    harness.request_link(ANA.address)
    url = harness.outbox.url_for(ANA)
    harness.clock.now += timedelta(minutes=15)

    assert harness.client.get(url).status_code == 400
    assert harness.client.post(f"{PREFIX}/callback", data={"token": token_of(url)}).status_code == (
        400
    )
    assert harness.store.sessions == {}


def test_a_link_issued_for_longer_lasts_that_long(harness: Harness) -> None:
    link = asyncio.run(harness.links.issue(ANA, ttl=timedelta(days=7)))
    assert link.expires_at == harness.clock.now + timedelta(days=7)

    harness.clock.now += timedelta(days=7) - timedelta(seconds=1)
    assert harness.client.get(link.url).status_code == 200
    harness.clock.now += timedelta(seconds=1)
    assert harness.client.get(link.url).status_code == 400


def test_a_link_lands_on_the_page_it_names(harness: Harness) -> None:
    link = asyncio.run(harness.links.issue(ANA, landing="/me"))
    assert parse_qs(urlsplit(link.url).query)["next"] == ["/me"]

    page = harness.client.get(link.url).text
    assert '<input type="hidden" name="next" value="/me">' in page
    signed_in = harness.client.post(
        f"{PREFIX}/callback", data={"token": token_of(link.url), "next": "/me"}
    )

    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/me"


@pytest.mark.parametrize("landing", ["https://evil.example/", "//evil.example", "/admin", ""])
def test_a_page_the_router_does_not_list_lands_on_the_start(harness: Harness, landing: str) -> None:
    link = asyncio.run(harness.links.issue(ANA, landing=landing))

    page = harness.client.get(link.url).text
    assert '<input type="hidden" name="next" value="/">' in page
    # A form posted by hand, past the page.
    signed_in = harness.client.post(
        f"{PREFIX}/callback", data={"token": token_of(link.url), "next": landing}
    )
    assert signed_in.headers["location"] == "/"


@pytest.mark.parametrize("token", ["", "nonsense", "a.1.b"])
def test_a_bad_token_gets_the_expired_page(harness: Harness, token: str) -> None:
    opened = harness.client.get(f"{PREFIX}/callback", params={"token": token})
    spent = harness.client.post(f"{PREFIX}/callback", data={"token": token})
    assert (opened.status_code, spent.status_code) == (400, 400)
    assert 'href="/"' in opened.text


def test_a_form_posted_from_another_site_is_refused(harness: Harness) -> None:
    harness.request_link(ANA.address)
    form = {"token": token_of(harness.outbox.url_for(ANA))}

    foreign = harness.client.post(
        f"{PREFIX}/callback", data=form, headers={"Origin": "https://evil.example"}
    )
    own = harness.client.post(f"{PREFIX}/callback", data=form, headers={"Origin": BASE_URL})

    assert foreign.status_code == 403
    assert own.status_code == 303  # the refused attempt did not spend the link


# --- sessions ---------------------------------------------------------------------


def test_a_session_lasts_30_days(harness: Harness) -> None:
    harness.sign_in(ANA)
    harness.clock.now += timedelta(days=30) - timedelta(seconds=1)
    assert harness.client.get("/whoami").json() == {"subject": "ana"}
    harness.clock.now += timedelta(seconds=1)
    assert harness.client.get("/whoami").json() == {"subject": None}


def test_logging_out_ends_the_session_and_clears_the_cookie(harness: Harness) -> None:
    harness.sign_in(ANA)
    token = harness.client.cookies[COOKIE_NAME]

    response = harness.client.post(f"{PREFIX}/logout")

    assert response.status_code == 204
    assert f'{COOKIE_NAME}=""' in response.headers["set-cookie"]
    assert "secure" in response.headers["set-cookie"].lower()
    assert harness.client.get("/whoami").json() == {"subject": None}
    # The old cookie, replayed, opens nothing either.
    harness.client.cookies.set(COOKIE_NAME, token)
    assert harness.client.get("/whoami").json() == {"subject": None}


def test_logging_out_without_a_session_is_harmless(harness: Harness) -> None:
    assert harness.client.post(f"{PREFIX}/logout").status_code == 204


def test_an_unknown_cookie_is_ignored(harness: Harness) -> None:
    harness.client.cookies.set(COOKIE_NAME, "forged")
    assert harness.client.get("/whoami").json() == {"subject": None}


def test_the_router_refuses_links_that_point_elsewhere() -> None:
    links = MagicLinks(
        secret_key="s" * 32,
        callback_url="https://other.example/auth/callback",
        directory=Directory(),
        store=Store(),
        sender=Outbox(),
        per_address=MemoryRateLimiter(limit=1, window_seconds=1),
        per_ip=MemoryRateLimiter(limit=1, window_seconds=1),
    )
    with pytest.raises(ValueError, match="not this router's callback"):
        build_router(links, prefix=PREFIX, base_url=BASE_URL)
