"""Rakin's sign-in against real Postgres: people by email, sessions and the gym they set.

The app is the real one with `tests/test_tenancy.py`'s gym-scoped test routes mounted
and a mailer that keeps what it is given. The module itself, over in-memory fakes,
is `tests/magiclink`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import MailSender, PostgresStore
from app.db import create_engine, create_sessionmaker
from app.integrations.mailer import Email
from app.magiclink import COOKIE_NAME, Session
from app.magiclink.tokens import hash_token
from app.main import create_app
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_tenancy import router as tenant_routes

pytestmark = pytest.mark.postgres

BASE_URL = "https://testserver"


@dataclass
class Outbox:
    sent: list[Email] = field(default_factory=list)

    async def send(self, email: Email) -> None:
        self.sent.append(email)

    def link_to(self, address: str) -> str:
        [email] = [e for e in self.sent if e.to.lower() == address.lower()]
        [url] = [w for w in email.text.split() if w.startswith(BASE_URL)]
        return url


@dataclass(frozen=True)
class People:
    sur: uuid.UUID
    norte: uuid.UUID
    ana: uuid.UUID  # ana@example.cl, a member of Sur
    shared: uuid.UUID  # shared@example.cl, a member of both gyms
    orphan: uuid.UUID  # orphan@example.cl, in no gym


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def people(db: Database) -> People:
    sur, norte = seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")
    ana, shared, orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # As the superuser, which skips RLS, to write across both gyms at once.
    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "INSERT INTO person (id, name, email) VALUES"
            " ($1, 'Ana', 'Ana@Example.cl'), ($2, 'Shared', 'shared@example.cl'),"
            " ($3, 'Orphan', 'orphan@example.cl')",
            ana,
            shared,
            orphan,
        )
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $1, id, 'active' FROM plan WHERE gym_id = $2",
            ana,
            sur,
        )
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $1, id, 'active' FROM plan",
            shared,
        )

    run(db.admin_url, query)
    return People(sur, norte, ana, shared, orphan)


@dataclass
class Harness:
    client: TestClient
    outbox: Outbox

    def sign_in(self, address: str) -> str:
        """Request a link, open it and press the button; returns the session token."""
        assert self.client.post("/api/auth/link", json={"email": address}).status_code == 202
        url = self.outbox.link_to(address)
        assert self.client.get(url).status_code == 200
        token = parse_qs(urlsplit(url).query)["token"][0]
        response = self.client.post("/api/auth/callback", data={"token": token})
        assert response.status_code == 303
        return str(self.client.cookies[COOKIE_NAME])


@pytest.fixture
def harness(db: Database, people: People) -> Iterator[Harness]:
    app: FastAPI = create_app(db.settings.model_copy(update={"public_base_url": BASE_URL}))
    app.include_router(tenant_routes)
    outbox = Outbox()
    app.state.magic_links.sender = MailSender(outbox)
    with TestClient(app, base_url=BASE_URL, follow_redirects=False) as client:
        yield Harness(client, outbox)


def with_store[T](db: Database, use: Callable[[PostgresStore], Awaitable[T]]) -> T:
    """`use(store)` on a store of its own, over the API user's connection."""

    async def go() -> T:
        engine = create_engine(db.settings)
        sessionmaker = create_sessionmaker(engine)
        try:
            return await use(PostgresStore(lambda: sessionmaker))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def session_row(db: Database, token: str) -> asyncpg.Record:
    [row] = run(
        db.admin_url,
        lambda c: c.fetch("SELECT * FROM auth_session WHERE token_hash = $1", hash_token(token)),
    )
    return row


# --- end to end -------------------------------------------------------------------


def test_signing_in_scopes_requests_to_the_persons_gym(harness: Harness, people: People) -> None:
    client = harness.client
    assert client.get("/test/setting").status_code == 401

    harness.sign_in("ana@example.cl")

    assert client.get("/test/setting").json()["gym"] == str(people.sur)
    plans = client.get("/test/rows/plan").json()
    assert plans and {p["gym_id"] for p in plans} == {str(people.sur)}


def test_the_email_is_in_spanish_and_carries_the_link(harness: Harness) -> None:
    harness.client.post("/api/auth/link", json={"email": "ana@example.cl"})
    [email] = harness.outbox.sent
    assert email.to == "Ana@Example.cl"
    assert email.subject == "Tu enlace para entrar a Rakin"
    assert email.text.startswith("Hola, Ana:")
    assert f"{BASE_URL}/api/auth/callback?token=" in email.text


def test_a_person_in_several_gyms_signs_in_to_no_gym_yet(
    harness: Harness, people: People, db: Database
) -> None:
    token = harness.sign_in("shared@example.cl")

    assert session_row(db, token)["gym_id"] is None
    # Signed in, but gym routes still answer 401 until a gym is picked (#16).
    assert harness.client.get("/test/setting").status_code == 401


def test_nobody_outside_a_gym_gets_a_link(harness: Harness) -> None:
    response = harness.client.post("/api/auth/link", json={"email": "orphan@example.cl"})
    assert response.status_code == 202
    assert harness.outbox.sent == []


def test_the_link_is_stored_hashed_and_spent_once(
    harness: Harness, db: Database, people: People
) -> None:
    harness.client.post("/api/auth/link", json={"email": "ana@example.cl"})
    token = parse_qs(urlsplit(harness.outbox.link_to("ana@example.cl")).query)["token"][0]
    select = "SELECT person_id, used_at FROM auth_link WHERE token_hash = $1"

    [row] = run(db.admin_url, lambda c: c.fetch(select, hash_token(token)))
    assert (row["person_id"], row["used_at"]) == (people.ana, None)

    form = {"token": token}
    assert harness.client.post("/api/auth/callback", data=form).status_code == 303
    assert harness.client.post("/api/auth/callback", data=form).status_code == 400
    [row] = run(db.admin_url, lambda c: c.fetch(select, hash_token(token)))
    assert row["used_at"] is not None


def test_logging_out_ends_the_session(harness: Harness, db: Database) -> None:
    token = harness.sign_in("ana@example.cl")

    assert harness.client.post("/api/auth/logout").status_code == 204

    assert session_row(db, token)["ended_at"] is not None
    harness.client.cookies.set(COOKIE_NAME, token)
    assert harness.client.get("/test/setting").status_code == 401


# --- the store --------------------------------------------------------------------


def test_of_concurrent_redemptions_exactly_one_wins(db: Database, people: People) -> None:
    token_hash, now = hash_token(uuid.uuid4().hex), datetime.now(UTC)

    async def race(store: PostgresStore) -> list[str | None]:
        await store.add_link(token_hash, str(people.ana), now + timedelta(minutes=15))
        return list(await asyncio.gather(*(store.redeem_link(token_hash, now) for _ in range(5))))

    results = with_store(db, race)
    assert [r for r in results if r is not None] == [str(people.ana)]
    assert results.count(None) == 4


def test_an_expired_link_or_session_is_not_found(db: Database, people: People) -> None:
    now, day = datetime.now(UTC), timedelta(days=1)
    link, session = hash_token(uuid.uuid4().hex), hash_token(uuid.uuid4().hex)

    async def check(store: PostgresStore) -> None:
        await store.add_link(link, str(people.ana), now + timedelta(minutes=15))
        await store.add_session(session, Session(str(people.ana), str(people.sur), now + day))

        assert await store.session(session, now) is not None
        assert await store.session(session, now + day) is None
        assert await store.redeem_link(link, now + timedelta(minutes=15)) is None

    with_store(db, check)


# --- privileges -------------------------------------------------------------------


def test_sessions_are_gym_scoped_for_the_api(
    harness: Harness, db: Database, people: People
) -> None:
    token = harness.sign_in("ana@example.cl")
    by_hash = "SELECT person_id FROM auth_session WHERE token_hash = $1"

    assert run(db.api_url, in_gym(None, by_hash, hash_token(token))) == []
    assert run(db.api_url, in_gym(people.norte, by_hash, hash_token(token))) == []
    assert [r[0] for r in run(db.api_url, in_gym(people.sur, by_hash, hash_token(token)))] == [
        people.ana
    ]
    # Before any gym is set, only the lookup by hash finds it.
    lookup = "SELECT person_id FROM auth_live_session($1, now())"
    assert [r[0] for r in run(db.api_url, in_gym(None, lookup, hash_token(token)))] == [people.ana]


def test_the_email_lookup_reads_across_gyms_but_not_beyond_people_in_one(
    db: Database, people: People
) -> None:
    lookup = "SELECT * FROM auth_people_by_email($1)"
    assert run(db.api_url, in_gym(None, "SELECT * FROM person")) == []
    [ana] = run(db.api_url, in_gym(None, lookup, " ANA@example.CL"))
    assert dict(ana) == {"person_id": people.ana, "name": "Ana", "email": "Ana@Example.cl"}
    assert run(db.api_url, in_gym(None, lookup, "orphan@example.cl")) == []
    gyms = run(db.api_url, in_gym(None, "SELECT auth_gyms_of($1)", people.shared))
    assert {r[0] for r in gyms} == {people.sur, people.norte}


def test_the_lookups_belong_to_rakin_auth_and_only_the_api_may_call_them(db: Database) -> None:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT p.proname, pg_get_userbyid(p.proowner) AS owner, p.prosecdef,"
            " has_function_privilege('public', p.oid, 'EXECUTE') AS public_may,"
            " has_function_privilege('rakin_app', p.oid, 'EXECUTE') AS app_may"
            " FROM pg_proc p WHERE p.proname LIKE 'auth\\_%'"
        ),
    )
    assert {r["proname"] for r in rows} == {
        "auth_people_by_email",
        "auth_gyms_of",
        "auth_live_session",
        "auth_end_session",
    }
    for r in rows:
        assert (r["owner"], r["prosecdef"], r["public_may"], r["app_may"]) == (
            "rakin_auth",
            True,
            False,
            True,
        ), r["proname"]


def test_rakin_auth_cannot_log_in_and_holds_only_what_the_lookups_read(db: Database) -> None:
    role = run(
        db.admin_url,
        lambda c: c.fetchrow(
            "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'rakin_auth'"
        ),
    )
    assert tuple(role) == (False, False, True)
    grants = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = 'rakin_auth'"
        ),
    )
    assert {(g["table_name"], g["privilege_type"]) for g in grants} == {
        ("person", "SELECT"),
        ("membership", "SELECT"),
        ("staff", "SELECT"),
        ("auth_session", "SELECT"),
        ("auth_session", "UPDATE"),
    }
    may_create = "SELECT has_schema_privilege('rakin_auth', 'public', 'CREATE')"
    assert run(db.admin_url, lambda c: c.fetchval(may_create)) is False
