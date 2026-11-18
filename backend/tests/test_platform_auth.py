"""Platform operators sign in (#436): granted by the command line, on the base host, by
link or code, for 8 hours, and never with a gym's session.

The app runs as in production, a base domain and gyms on their own hosts
(`test_gym_hosts`), against a real database; mail lands in an outbox.
"""

import asyncio
import dataclasses
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import asyncpg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import operators
from app.auth import MailSender
from app.db_bootstrap import to_dsn
from app.magiclink import COOKIE_NAME
from app.main import create_app
from app.notices import Notices
from app.operators import Grant, Revoke
from app.platform.session import COOKIE_NAME as PLATFORM_COOKIE
from app.platform.session import (
    DEV_COOKIE_NAME,
    FRESH,
    Operator,
    platform_cookie_name,
    require_fresh,
)
from tests.auth import FakeAuth
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_gym_hosts import BASE, BASE_URL, HOSTS, Outbox, address, person_in
from tests.test_gym_hosts import Site as GymSite
from tests.test_tenancy import router as tenant_routes

pytestmark = pytest.mark.postgres

LINK_PATH = "/api/platform/auth/callback"
PLATFORM_ROUTES = ("/api/platform/me", "/api/platform/gyms")


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def cli(db: Database, command: operators.Command) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            if isinstance(command, Grant):
                return await operators.grant(conn, command)
            if isinstance(command, Revoke):
                return await operators.revoke(conn, command)
            return await operators.operators(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


def grant(db: Database, email: str, name: str = "Operadora") -> uuid.UUID:
    done = cli(db, Grant(email=email, name=name))
    assert done.operator is not None
    operator_id: uuid.UUID = done.operator.id
    return operator_id


@dataclass
class Panel:
    db: Database
    app: FastAPI
    outbox: Outbox
    gym_a: uuid.UUID
    slug_a: str

    def client(self, slug: str | None = None) -> TestClient:
        return TestClient(self.app, base_url=HOSTS.base_url(slug), follow_redirects=False)

    def ask(self, client: TestClient, email: str) -> int:
        self.outbox.sent.clear()
        return int(client.post("/api/platform/auth/link", json={"email": email}).status_code)

    def link_to(self, email: str) -> str:
        [link] = self.outbox.links_to(email, LINK_PATH)
        return link

    def code_to(self, email: str) -> str:
        [sent] = [e for e in self.outbox.sent if e.to.lower() == email.lower()]
        [code] = re.findall(r"código: (\d{3} \d{3})", sent.text)
        return str(code)

    def open(self, client: TestClient, link: str) -> Any:
        token = parse_qs(urlsplit(link).query)["token"][0]
        return client.post(LINK_PATH, data={"token": token})

    @contextmanager
    def signed_in(self, email: str) -> Iterator[TestClient]:
        """A client signed in as `email`'s operator. Every client is used inside its
        `with`, one at a time: each starts the app's lifespan, its own engine."""
        with self.client() as client:
            assert self.ask(client, email) == 202
            assert self.open(client, self.link_to(email)).status_code == 303
            yield client


@pytest.fixture
def panel(db: Database) -> Iterator[Panel]:
    settings = db.settings.model_copy(update={"public_base_url": BASE_URL, "base_domain": BASE})
    app = create_app(settings)
    app.include_router(tenant_routes)
    app.add_middleware(FakeAuth)
    outbox = Outbox()
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=outbox)
    app.state.platform_links.mailer = outbox
    # A gym's links too, for its owner.
    app.state.magic_links.sender = MailSender(
        Notices(
            outbox,
            lambda: app.state.sessionmaker,
            base_url=BASE_URL,
            secret_key=settings.secret_key,
        )
    )
    slug = f"norte-{uuid.uuid4().hex[:6]}"
    with TestClient(app):
        yield Panel(db, app, outbox, seed_gym(db, slug), slug)


def operator_email() -> str:
    return f"ops-{uuid.uuid4().hex[:8]}@example.cl"


def events(db: Database, operator_id: uuid.UUID) -> list[str]:
    rows = run(
        db.owner_url,
        lambda c: c.fetch(
            "SELECT action FROM platform_event"
            " WHERE operator_id = $1 OR detail ->> 'operator_id' = $2 ORDER BY at, action",
            operator_id,
            str(operator_id),
        ),
    )
    return [r["action"] for r in rows]


# --- the cookie ------------------------------------------------------------------------


def test_the_cookie_is_its_own_and_host_only() -> None:
    assert platform_cookie_name("https://rakin.app") == PLATFORM_COOKIE == "__Host-platform"
    assert platform_cookie_name("http://localhost:8080") == DEV_COOKIE_NAME == "platform"
    assert PLATFORM_COOKIE != COOKIE_NAME


def test_with_no_cookie_the_panel_is_a_401_before_any_database_work() -> None:
    # The database is unreachable: a 401 rather than a 500 means none was asked.
    app = create_app(make_settings(database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x"))
    with TestClient(app) as client:
        for path in PLATFORM_ROUTES:
            assert client.get(path).status_code == 401


# --- signing in ------------------------------------------------------------------------


def test_an_operator_signs_in_by_link_on_the_base_host(panel: Panel) -> None:
    email = operator_email()
    operator_id = grant(panel.db, email, "Martina")
    with panel.client() as client:
        assert panel.ask(client, email.upper()) == 202
        link = panel.link_to(email)
        assert link.startswith(f"{BASE_URL}{LINK_PATH}?")
        # The link's page only shows a button; the button's POST spends it.
        page = client.get(urlsplit(link).path, params=parse_qs(urlsplit(link).query))
        assert page.status_code == 200
        assert "plataforma" in page.text
        response = panel.open(client, link)
        assert response.status_code == 303
        assert response.headers["location"] == "/plataforma"
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{PLATFORM_COOKIE}=")
        for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=28800"):
            assert attribute in cookie
        assert COOKIE_NAME not in client.cookies

        me = client.get("/api/platform/me")
        assert me.status_code == 200
        assert me.json()["email"] == email
        assert me.json()["name"] == "Martina"
        # Spent: the link signs nobody in again.
        assert panel.open(client, link).status_code == 400
    assert events(panel.db, operator_id) == ["operator_granted", "operator_signed_in"]


def test_an_operator_signs_in_by_code(panel: Panel) -> None:
    email = operator_email()
    grant(panel.db, email)
    with panel.client() as client:
        assert panel.ask(client, email) == 202
        code = panel.code_to(email)
        wrong = client.post("/api/platform/auth/code", json={"email": email, "code": "000000"})
        assert wrong.status_code == 400
        response = client.post("/api/platform/auth/code", json={"email": email, "code": code})
        assert response.status_code == 200
        assert response.json() == {"next": "/plataforma"}
        assert client.get("/api/platform/me").status_code == 200
        # The code spent its link.
        assert panel.open(client, panel.link_to(email)).status_code == 400


def test_an_unknown_or_revoked_address_answers_the_same_and_gets_no_mail(panel: Panel) -> None:
    revoked = operator_email()
    grant(panel.db, revoked)
    cli(panel.db, Revoke(email=revoked))
    # A gym's owner is no operator either.
    owner = address()
    person_in(as_gym_site(panel), [panel.gym_a], owner)
    with panel.client() as client:
        for email in (operator_email(), revoked, owner):
            assert panel.ask(client, email) == 202
            assert panel.outbox.sent == []


def test_signing_out_ends_the_session(panel: Panel) -> None:
    email = operator_email()
    operator_id = grant(panel.db, email)
    with panel.signed_in(email) as client:
        assert client.post("/api/platform/auth/logout").status_code == 204
        assert client.get("/api/platform/me").status_code == 401
    assert events(panel.db, operator_id)[-1] == "operator_signed_out"


def test_a_session_older_than_eight_hours_is_a_401(panel: Panel) -> None:
    email = operator_email()
    operator_id = grant(panel.db, email)
    with panel.signed_in(email) as client:
        assert client.get("/api/platform/me").status_code == 200
        run(
            panel.db.admin_url,
            lambda c: c.execute(
                "UPDATE operator_session SET created_at = created_at - interval '8 hours 1 second',"
                " fresh_at = fresh_at - interval '8 hours 1 second',"
                " expires_at = expires_at - interval '8 hours 1 second'"
                " WHERE operator_id = $1",
                operator_id,
            ),
        )
        for path in PLATFORM_ROUTES:
            assert client.get(path).status_code == 401


def test_revoke_ends_the_live_session(panel: Panel) -> None:
    email = operator_email()
    operator_id = grant(panel.db, email)
    with panel.signed_in(email) as client:
        done = cli(panel.db, Revoke(email=email))
        assert (done.changed, done.sessions_ended) == (True, 1)
        assert client.get("/api/platform/me").status_code == 401
    assert events(panel.db, operator_id) == [
        "operator_granted",
        "operator_signed_in",
        "operator_revoked",
    ]
    # Granted again, they sign in again, from a fresh link.
    grant(panel.db, email)
    with panel.signed_in(email) as client:
        assert client.get("/api/platform/me").status_code == 200


def test_a_regrant_revives_no_link_from_before_the_revoke(panel: Panel) -> None:
    email = operator_email()
    grant(panel.db, email)
    with panel.client() as client:
        assert panel.ask(client, email) == 202
        link, code = panel.link_to(email), panel.code_to(email)
        cli(panel.db, Revoke(email=email))
        grant(panel.db, email)
        # Both within their 15 minutes, and spent by the revoke.
        assert panel.open(client, link).status_code == 400
        typed = client.post("/api/platform/auth/code", json={"email": email, "code": code})
        assert typed.status_code == 400
        assert client.get("/api/platform/me").status_code == 401


def test_the_command_line_grants_once_and_lists(panel: Panel) -> None:
    email = operator_email()
    operator_id = grant(panel.db, email, "Primera")
    again = cli(panel.db, Grant(email=email.upper(), name="Segunda"))
    assert (again.changed, again.operator.name) == (False, "Primera")
    assert email in [o.email for o in cli(panel.db, operators.Listing())]
    assert cli(panel.db, Revoke(email=operator_email())).operator is None
    assert events(panel.db, operator_id) == ["operator_granted"]
    [detail] = run(
        panel.db.owner_url,
        lambda c: c.fetch(
            "SELECT operator_id, detail FROM platform_event WHERE detail ->> 'operator_id' = $1",
            str(operator_id),
        ),
    )
    assert detail["operator_id"] is None
    assert '"by": "cli"' in detail["detail"]


def test_the_command_reads_its_arguments() -> None:
    assert operators.parse(["grant", "--email", "A@B.cl", "--name", "Ana"]) == Grant(
        email="A@B.cl", name="Ana"
    )
    assert operators.parse(["revoke", "--email", "a@b.cl"]) == Revoke(email="a@b.cl")
    with pytest.raises(SystemExit):
        operators.parse(["grant", "--email", "not an address", "--name", "Ana"])


def test_require_fresh_asks_for_a_recent_proof() -> None:
    now = datetime.now(UTC)
    operator = Operator(uuid.uuid4(), "a@example.cl", "A", now, now, b"", cast(AsyncSession, None))
    require_fresh(operator, now + FRESH)
    with pytest.raises(HTTPException) as refused:
        require_fresh(operator, now + FRESH + timedelta(seconds=1))
    assert refused.value.status_code == 401
    assert cast(object, refused.value.detail) == {"code": "reauth"}


# --- never a gym's ---------------------------------------------------------------------


def as_gym_site(panel: Panel) -> GymSite:
    return GymSite(panel.db, panel.app, panel.outbox, panel.gym_a, panel.gym_a, panel.slug_a, "")


def test_a_gym_owner_never_reaches_the_panel(panel: Panel) -> None:
    owner = address()
    person_in(as_gym_site(panel), [panel.gym_a], owner)
    site = as_gym_site(panel)
    for slug, refused in ((None, 401), (panel.slug_a, 404)):
        with panel.client(slug) as client:
            link = site.ask_link(client, owner)
            assert site.open(client, link).status_code == 303
            assert COOKIE_NAME in client.cookies
            assert site.gym_of_session(client) == str(panel.gym_a)
            for path in PLATFORM_ROUTES:
                assert client.get(path).status_code == refused, (slug, path)


def test_an_operator_session_works_in_no_gym(panel: Panel) -> None:
    email = operator_email()
    grant(panel.db, email)
    with panel.signed_in(email) as client:
        assert client.get("/test/setting").status_code == 401


def test_the_panel_is_a_404_on_a_gyms_host_even_with_an_operators_cookie(panel: Panel) -> None:
    email = operator_email()
    grant(panel.db, email)
    with panel.signed_in(email) as client:
        token = client.cookies[PLATFORM_COOKIE]
    for slug in (panel.slug_a, "nadie"):
        with panel.client(slug) as client:
            client.cookies.set(PLATFORM_COOKIE, token)
            for path in PLATFORM_ROUTES:
                assert client.get(path).status_code == 404, (slug, path)
            assert client.post("/api/platform/auth/link", json={"email": email}).status_code == 404
            assert client.post("/api/platform/auth/logout").status_code == 404
    # The session is untouched: the base host still takes it.
    with panel.client() as client:
        client.cookies.set(PLATFORM_COOKIE, token)
        assert client.get("/api/platform/me").status_code == 200
