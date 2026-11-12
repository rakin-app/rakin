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
from sqlalchemy.exc import IntegrityError

from app.auth import MailSender, PostgresStore
from app.db import create_engine, create_sessionmaker
from app.integrations.mailer import Email
from app.magiclink import COOKIE_NAME, Pending, Session
from app.magiclink.tokens import hash_token
from app.main import create_app
from app.notices import Notices
from tests.conftest import require_test_database_url
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_tenancy import router as tenant_routes

pytestmark = pytest.mark.postgres

BASE_URL = "https://testserver"

# The address Sur's record of Ana holds, as a link to her records it.
ANA = "Ana@Example.cl"


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
    ana: uuid.UUID  # Sur's record: Ana, Ana@Example.cl, a member
    shared: uuid.UUID  # a member of both; Sur has shared@example.cl, Norte another address
    both: uuid.UUID  # a member of both, and both have both@example.cl for them
    planless: uuid.UUID  # on Sur's roster, planless@example.cl, with no plan or staff row (#246)
    left: uuid.UUID  # Sur's record, left@example.cl, dado de baja with no plan
    legacy: uuid.UUID  # legacy@example.cl only on `person`, which sign-in does not read


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


async def add_person(
    conn: asyncpg.Connection,
    person: uuid.UUID,
    records: dict[uuid.UUID, tuple[str, str | None]],
    *,
    member: bool = True,
) -> None:
    """A person and each gym's (name, email) record of them, as members of those gyms."""
    await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
    for gym, (name, email) in records.items():
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name, email) VALUES ($1, $2, $3, $4)",
            gym,
            person,
            name,
            email,
        )
        if member:
            await conn.execute(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " SELECT gym_id, $1, id, 'active' FROM plan WHERE gym_id = $2",
                person,
                gym,
            )


@pytest.fixture(scope="module")
def people(db: Database) -> People:
    sur, norte = seed_gym(db, "academia-sur"), seed_gym(db, "dojo-norte")
    ana, shared, both, planless, left, legacy = (uuid.uuid4() for _ in range(6))

    # As the superuser, which skips RLS, to write across both gyms at once.
    async def query(conn: asyncpg.Connection) -> None:
        await add_person(conn, ana, {sur: ("Ana", "Ana@Example.cl")})
        await add_person(
            conn,
            shared,
            {sur: ("Shared", "shared@example.cl"), norte: ("Shared", "s.norte@example.cl")},
        )
        await add_person(
            conn, both, {sur: ("Both", "both@example.cl"), norte: ("Both", "Both@Example.cl")}
        )
        await add_person(conn, planless, {sur: ("Planless", "planless@example.cl")}, member=False)
        await add_person(conn, left, {sur: ("Left", "left@example.cl")}, member=False)
        await conn.execute(
            "UPDATE gym_person SET left_on = current_date WHERE person_id = $1", left
        )
        await add_person(conn, legacy, {sur: ("Legacy", None)})
        await conn.execute("UPDATE person SET email = 'legacy@example.cl' WHERE id = $1", legacy)

    run(db.admin_url, query)
    return People(sur, norte, ana, shared, both, planless, left, legacy)


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
    app.state.magic_links.sender = MailSender(
        Notices(
            outbox,
            lambda: app.state.sessionmaker,
            base_url=BASE_URL,
            secret_key=db.settings.secret_key,
        )
    )
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
    assert email.html is not None and "Entrar a Rakin" in email.html


def test_each_link_is_logged_in_no_gym_without_its_url(
    harness: Harness, people: People, db: Database
) -> None:
    harness.client.post("/api/auth/link", json={"email": "ana@example.cl"})

    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT * FROM message_log WHERE person_id = $1 ORDER BY sent_at DESC LIMIT 1",
            people.ana,
        ),
    )
    [row] = [dict(r) for r in rows]
    assert (row["gym_id"], row["template"], row["status"]) == (None, "magic_link", "sent")
    assert row["to_address"] == "Ana@Example.cl"
    assert "token" not in row["payload"] and "url" not in row["payload"]
    # No gym reads it, Ana's own included.
    assert run(db.api_url, in_gym(people.sur, "SELECT 1 FROM message_log")) == []


def test_an_email_several_gyms_hold_signs_in_to_no_gym_yet(
    harness: Harness, people: People, db: Database
) -> None:
    token = harness.sign_in("both@example.cl")

    assert session_row(db, token)["gym_id"] is None
    # Signed in, but gym routes still answer 401 until a gym is picked (#16).
    assert harness.client.get("/test/setting").status_code == 401


@pytest.mark.parametrize(
    ("address", "gym"), [("shared@example.cl", "sur"), ("s.norte@example.cl", "norte")]
)
def test_an_email_one_gym_holds_signs_in_to_that_gym_alone(
    harness: Harness, people: People, address: str, gym: str
) -> None:
    """The person is in both gyms, but each gym's own record has its own address (#146)."""
    harness.sign_in(address)

    assert harness.client.get("/test/setting").json()["gym"] == str(getattr(people, gym))


def test_a_student_on_the_roster_with_no_plan_signs_in(harness: Harness, people: People) -> None:
    """No membership, staff row or dependent: on the roster is enough (#246)."""
    harness.sign_in("planless@example.cl")

    assert harness.client.get("/test/setting").json()["gym"] == str(people.sur)
    assert harness.client.get("/api/me/page").status_code == 200


@pytest.mark.parametrize("address", ["left@example.cl", "legacy@example.cl"])
def test_only_someone_in_a_gym_gets_a_link(harness: Harness, address: str) -> None:
    """Dado de baja with nothing left here, or an email only `person` holds: the same 202
    as anyone, and no link."""
    response = harness.client.post("/api/auth/link", json={"email": address})
    assert response.status_code == 202
    assert harness.outbox.sent == []


def test_either_gyms_record_of_a_shared_person_reaches_them(harness: Harness) -> None:
    for address in ("shared@example.cl", "s.norte@example.cl"):
        harness.client.post("/api/auth/link", json={"email": address})
    assert [e.to for e in harness.outbox.sent] == ["shared@example.cl", "s.norte@example.cl"]


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
    link, now = hash_token(uuid.uuid4().hex), datetime.now(UTC)
    session = Session(str(people.ana), ANA, str(people.sur), now + timedelta(days=30))

    async def race(store: PostgresStore) -> list[bool]:
        await store.add_link(link, str(people.ana), ANA, now + timedelta(minutes=15))
        attempts = (store.redeem_link(link, now, hash_token(f"s{n}"), session) for n in range(5))
        return list(await asyncio.gather(*attempts))

    assert sorted(with_store(db, race)) == [False] * 4 + [True]


def test_a_session_that_cannot_be_stored_leaves_the_link_unspent(
    db: Database, people: People
) -> None:
    link, now = hash_token(uuid.uuid4().hex), datetime.now(UTC)
    # A gym that does not exist: the session insert fails on its foreign key.
    broken = Session(str(people.ana), ANA, str(uuid.uuid4()), now + timedelta(days=30))

    async def check(store: PostgresStore) -> None:
        await store.add_link(link, str(people.ana), ANA, now + timedelta(minutes=15))
        with pytest.raises(IntegrityError):
            await store.redeem_link(link, now, hash_token("broken"), broken)
        assert await store.pending_link(link, now) == Pending(str(people.ana), ANA)

    with_store(db, check)


def test_a_link_redeems_only_for_its_own_person_and_address(db: Database, people: People) -> None:
    link, now = hash_token(uuid.uuid4().hex), datetime.now(UTC)
    later = now + timedelta(days=30)
    someone_else = Session(str(people.shared), ANA, None, later)
    another_address = Session(str(people.ana), "shared@example.cl", None, later)

    async def check(store: PostgresStore) -> None:
        await store.add_link(link, str(people.ana), ANA, now + timedelta(minutes=15))
        assert not await store.redeem_link(link, now, hash_token("x"), someone_else)
        assert not await store.redeem_link(link, now, hash_token("y"), another_address)
        assert await store.pending_link(link, now) == Pending(str(people.ana), ANA)

    with_store(db, check)


def test_an_expired_link_or_session_is_not_found(db: Database, people: People) -> None:
    now, day = datetime.now(UTC), timedelta(days=1)
    link, session = hash_token(uuid.uuid4().hex), hash_token(uuid.uuid4().hex)

    async def check(store: PostgresStore) -> None:
        await store.add_link(link, str(people.ana), ANA, now + timedelta(minutes=15))
        later = now + timedelta(minutes=15)
        assert await store.pending_link(link, later) is None
        assert not await store.redeem_link(
            link, later, session, Session(str(people.ana), ANA, None, later + day)
        )
        assert await store.redeem_link(
            link, now, session, Session(str(people.ana), ANA, str(people.sur), now + day)
        )

        assert await store.session(session, now) is not None
        assert await store.session(session, now + day) is None

    with_store(db, check)


@pytest.mark.parametrize("row", ["staff", "membership", None])
def test_leaving_the_gym_ends_the_session(
    harness: Harness, db: Database, people: People, row: str | None
) -> None:
    """Their staff row or membership gone, or none to begin with, and dado de baja: on
    the roster no more, nor anything else here."""
    person, address = uuid.uuid4(), f"{uuid.uuid4().hex[:8]}@example.cl"

    async def join(conn: asyncpg.Connection) -> None:
        await add_person(
            conn, person, {people.sur: ("Leaving", address)}, member=row == "membership"
        )
        if row == "staff":
            await conn.execute(
                "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')",
                people.sur,
                person,
            )

    run(db.admin_url, join)
    harness.sign_in(address)
    assert harness.client.get("/test/setting").json()["gym"] == str(people.sur)

    if row is not None:
        run(db.admin_url, lambda c: c.execute(f"DELETE FROM {row} WHERE person_id = $1", person))
    # Still on the roster, so still in: a coach no longer on staff trains here.
    assert harness.client.get("/test/setting").status_code == 200
    leave = "UPDATE gym_person SET left_on = current_date WHERE person_id = $1"
    run(db.admin_url, lambda c: c.execute(leave, person))

    assert harness.client.get("/test/setting").status_code == 401


def test_a_forgotten_person_gets_no_link(harness: Harness, db: Database, people: People) -> None:
    """`forget_gym_person` (0032) deletes the gym's record: nothing of them is left to
    sign in to, and the answer is the same 202."""
    person, address = uuid.uuid4(), f"{uuid.uuid4().hex[:8]}@example.cl"
    records: dict[uuid.UUID, tuple[str, str | None]] = {people.sur: ("Forgotten", address)}
    run(db.admin_url, lambda c: add_person(c, person, records, member=False))
    harness.sign_in(address)
    harness.outbox.sent.clear()

    forgotten = run(db.api_url, in_gym(people.sur, "SELECT forget_gym_person($1)", person))
    assert [r[0] for r in forgotten] == [None]

    response = harness.client.post("/api/auth/link", json={"email": address})
    assert response.status_code == 202
    assert harness.outbox.sent == []
    assert harness.client.get("/test/setting").status_code == 401


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
    assert run(db.api_url, in_gym(None, "SELECT id FROM person")) == []
    [ana] = run(db.api_url, in_gym(None, lookup, " ANA@example.CL"))
    assert dict(ana) == {"person_id": people.ana, "name": "Ana", "email": "Ana@Example.cl"}
    assert run(db.api_url, in_gym(None, lookup, "left@example.cl")) == []
    [planless] = run(db.api_url, in_gym(None, lookup, "planless@example.cl"))
    assert planless["person_id"] == people.planless
    gyms_of = "SELECT auth_gyms_of($1, $2)"
    assert run(db.api_url, in_gym(None, gyms_of, people.left, "left@example.cl")) == []
    gyms = run(db.api_url, in_gym(None, gyms_of, people.planless, "planless@example.cl"))
    assert [r[0] for r in gyms] == [people.sur]
    gyms = run(db.api_url, in_gym(None, gyms_of, people.shared, " SHARED@example.cl"))
    assert {r[0] for r in gyms} == {people.sur}
    gyms = run(db.api_url, in_gym(None, gyms_of, people.both, "both@example.cl"))
    assert {r[0] for r in gyms} == {people.sur, people.norte}
    # An address no gym has for them reaches nothing, though they are in both gyms.
    assert run(db.api_url, in_gym(None, gyms_of, people.shared, "ana@example.cl")) == []


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
        "auth_gym_by_slug",
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
        ("gym_person", "SELECT"),
        ("membership", "SELECT"),
        ("staff", "SELECT"),
        ("guardian_link", "SELECT"),
        ("auth_session", "SELECT"),
        ("auth_session", "UPDATE"),
    }
    may_create = "SELECT has_schema_privilege('rakin_auth', 'public', 'CREATE')"
    assert run(db.admin_url, lambda c: c.fetchval(may_create)) is False


def test_rakin_auth_reads_of_a_gym_only_what_the_host_lookup_returns(db: Database) -> None:
    # The theme (0039) and the logo's version (0040) beside the id, name and slug; never
    # `settings`, which holds the gym's bank details.
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT column_name FROM information_schema.column_privileges"
            " WHERE table_name = 'gym' AND grantee = 'rakin_auth'"
            " AND privilege_type = 'SELECT'"
        ),
    )
    assert sorted(r["column_name"] for r in rows) == ["id", "logo_version", "name", "slug", "theme"]
