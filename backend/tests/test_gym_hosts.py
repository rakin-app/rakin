"""Each gym on its own host (#155): slugs, host resolution, sign-in there, and the
certificate `ask`."""

import asyncio
import dataclasses
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import MailSender, bind_session
from app.blob_cors import cors_rule
from app.db_bootstrap import to_dsn
from app.gyms import NewGym, create_gym, parse
from app.hosts import GymLookup, HostGym, Hosts, host_name, slug_problem
from app.integrations.mailer import Email
from app.magiclink import COOKIE_NAME, Session
from app.main import create_app
from app.notices import Notices
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut
from tests.pg import Database, migrate, run, seed_gym, throwaway_database
from tests.test_email_identity import member_of
from tests.test_people import new_phone
from tests.test_tenancy import router as tenant_routes

BASE = "staging.rakin.app"
BASE_URL = f"https://{BASE}"
HOSTS = Hosts(BASE_URL, BASE)


# --- slugs and hosts -------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["meta", "academia-sur", "a", "9", "a" * 63, "dojo-2"])
def test_a_slug_is_a_host_label(slug: str) -> None:
    assert slug_problem(slug) is None


@pytest.mark.parametrize(
    "slug", ["", "Meta", "meta_bjj", "-meta", "meta-", "a" * 64, "me.ta", "méta", "meta "]
)
def test_a_slug_that_is_no_host_label_is_refused(slug: str) -> None:
    assert slug_problem(slug) is not None


@pytest.mark.parametrize("slug", ["www", "app", "api", "staging", "admin", "mail"])
def test_reserved_names_are_refused(slug: str) -> None:
    assert slug_problem(slug) == f"{slug!r} is reserved"


@pytest.mark.parametrize(
    ("host", "slug"),
    [
        ("meta.staging.rakin.app", "meta"),
        ("META.Staging.Rakin.App", "meta"),
        ("meta.staging.rakin.app:443", "meta"),
        ("meta.staging.rakin.app.", "meta"),
        ("staging.rakin.app", None),  # the base host
        ("www.staging.rakin.app", None),  # reserved
        ("a.meta.staging.rakin.app", None),  # not one label
        ("meta.rakin.app", None),  # outside the base domain
        ("meta.evilstaging.rakin.app", None),
        ("metastaging.rakin.app", None),
        ("meta_x.staging.rakin.app", None),
        ("", None),
        ("[::1]:8000", None),
    ],
)
def test_the_slug_a_host_names(host: str, slug: str | None) -> None:
    assert HOSTS.slug_of(host) == slug


def test_without_a_base_domain_no_host_is_a_gyms() -> None:
    assert Hosts(BASE_URL).slug_of("meta.staging.rakin.app") is None
    assert Hosts(BASE_URL).base_url("meta") == BASE_URL


def test_host_name_drops_the_port() -> None:
    assert host_name("Meta.Localhost:8080") == "meta.localhost"


def test_a_gyms_base_url_keeps_the_scheme_and_port() -> None:
    assert HOSTS.base_url("meta") == "https://meta.staging.rakin.app"
    assert HOSTS.base_url(None) == BASE_URL
    local = Hosts("http://localhost:8080/", "localhost")
    assert local.base_url("meta") == "http://meta.localhost:8080"
    assert local.slug_of("meta.localhost:8080") == "meta"


def test_the_base_domain_setting_is_a_host_name() -> None:
    assert make_settings(base_domain=" Staging.Rakin.App. ").base_domain == BASE
    assert make_settings().base_domain == ""
    for bad in ("https://staging.rakin.app", "staging.rakin.app:443", "staging.rakin.app/x"):
        with pytest.raises(ValidationError):
            make_settings(base_domain=bad)


def test_the_bucket_allows_every_gyms_host() -> None:
    settings = make_settings(public_base_url=BASE_URL, base_domain=BASE)
    assert cors_rule(settings)["AllowedOrigins"] == [BASE_URL, "https://*.staging.rakin.app"]
    assert cors_rule(make_settings(public_base_url=BASE_URL))["AllowedOrigins"] == [BASE_URL]


def test_a_found_gym_is_kept_a_while_and_a_missing_one_is_asked_again() -> None:
    gym = HostGym(uuid.uuid4(), "meta", "Meta")
    answers: dict[str, HostGym | None] = {"meta": gym, "nada": None}
    asked: list[str] = []
    now = [0.0]

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_: object) -> None:
            pass

        async def execute(self, _sql: Any, params: dict[str, str]) -> Any:
            asked.append(params["slug"])
            found = answers[params["slug"]]
            row = (
                None
                if found is None
                else type("Row", (), {"id": found.id, "name": found.name, "theme": found.theme})
            )
            return type("Result", (), {"one_or_none": lambda self: row})()

    lookup = GymLookup(lambda: Session, ttl=60, clock=lambda: now[0])  # type: ignore[arg-type, return-value]

    async def go() -> None:
        assert await lookup("meta") == gym
        assert await lookup("meta") == gym
        assert await lookup("nada") is None
        assert await lookup("nada") is None
        now[0] = 61
        assert await lookup("meta") == gym

    asyncio.run(go())
    assert asked == ["meta", "nada", "nada", "meta"]

    # Forgotten, it is asked again at once, however long it had left.
    lookup.forget("meta")
    lookup.forget("nunca")
    asyncio.run(lookup("meta"))
    assert asked == ["meta", "nada", "nada", "meta", "meta"]


def session_in(scope: uuid.UUID | None) -> Session:
    expires = datetime.now(UTC) + timedelta(days=1)
    return Session(
        str(uuid.uuid4()), "a@example.cl", None if scope is None else str(scope), expires
    )


def test_a_session_works_on_its_own_gyms_host_and_the_base_host() -> None:
    gym = HostGym(uuid.uuid4(), "meta", "Meta")
    for host in (gym, None):
        state: dict[str, Any] = {"host_gym": host}
        bind_session(session_in(gym.id), state)
        assert state["tenant"].gym_id == gym.id


def test_a_session_in_another_gym_acts_in_none_on_a_gyms_host() -> None:
    state: dict[str, Any] = {"host_gym": HostGym(uuid.uuid4(), "meta", "Meta")}
    session = session_in(uuid.uuid4())
    bind_session(session, state)
    assert "tenant" not in state
    assert str(state["person_id"]) == session.subject


# --- the command ------------------------------------------------------------------------


ARGS = [
    "create",
    "--slug",
    "meta",
    "--name",
    "Meta",
    "--owner-email",
    "dueno@meta.cl",
    "--owner-name",
    "Dueño Meta",
    "--owner-phone",
    "+56 9 1234 5678",
]


def test_the_command_reads_its_arguments() -> None:
    gym = parse(ARGS)
    assert (gym.slug, gym.name, gym.timezone) == ("meta", "Meta", "America/Santiago")
    assert gym.owner_phone == "+56912345678"
    assert gym.owner_rut is None


def test_the_owner_phone_is_optional_and_the_rut_normalised() -> None:
    args = [a for a in ARGS if a not in ("--owner-phone", "+56 9 1234 5678")]
    gym = parse([*args, "--owner-rut", "7.654.321-6"])
    assert (gym.owner_phone, gym.owner_rut) == (None, "7654321-6")


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--slug", "www"),
        ("--slug", "Meta"),
        ("--owner-phone", "123"),
        ("--owner-rut", "7.654.321-0"),
        ("--timezone", "Mars/Base"),
    ],
)
def test_the_command_refuses_bad_arguments(
    flag: str, value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = list(ARGS)
    if flag in args:
        args[args.index(flag) + 1] = value
    else:
        args += [flag, value]
    with pytest.raises(SystemExit) as exit_:
        parse(args)
    assert exit_.value.code == 2
    assert flag in capsys.readouterr().err


# --- with Postgres ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


def new_gym(slug: str) -> NewGym:
    return NewGym(
        slug=slug,
        name=f"Gimnasio {slug}",
        timezone="America/Santiago",
        owner_email=f"{slug}@example.cl",
        owner_name="Dueña",
        owner_phone=new_phone(),
    )


def create(db: Database, gym: NewGym) -> Any:
    async def go() -> Any:
        conn = await asyncpg.connect(to_dsn(db.owner_url))
        try:
            return await create_gym(conn, gym)
        finally:
            await conn.close()

    return asyncio.run(go())


def counts(db: Database, gym_id: uuid.UUID) -> dict[str, int]:
    async def query(conn: asyncpg.Connection) -> dict[str, int]:
        return {
            table: await conn.fetchval(f"SELECT count(*) FROM {table} WHERE gym_id = $1", gym_id)
            for table in ("program", "block_kind", "staff", "gym_person", "membership", "plan")
        }

    return dict(run(db.admin_url, query))


@pytest.mark.postgres
def test_create_makes_an_empty_gym_with_its_owner(db: Database) -> None:
    gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}")

    created = create(db, gym)

    assert created.created
    made = counts(db, created.gym_id)
    assert made.pop("block_kind") > 0
    assert made == {"program": 3, "staff": 1, "gym_person": 1, "membership": 0, "plan": 0}

    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetchrow(
            "SELECT g.name, g.timezone, g.settings, s.role, gp.name AS owner, gp.email"
            " FROM gym g JOIN staff s ON s.gym_id = g.id"
            " JOIN gym_person gp ON gp.gym_id = g.id AND gp.person_id = s.person_id"
            " WHERE g.id = $1",
            gym_id,
        )

    gym_id = created.gym_id
    row = run(db.admin_url, query)
    assert (row["name"], row["timezone"], row["role"]) == (gym.name, gym.timezone, "owner")
    assert (row["owner"], row["email"]) == (gym.owner_name, gym.owner_email)
    assert json.loads(row["settings"])["grading"]["ranks"]


@pytest.mark.postgres
def test_create_again_with_the_slug_changes_nothing(db: Database) -> None:
    gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}")
    first = create(db, gym)
    before = counts(db, first.gym_id)

    again = create(db, gym.model_copy(update={"name": "Otro", "owner_phone": new_phone()}))

    assert (again.gym_id, again.name, again.created) == (first.gym_id, gym.name, False)
    assert counts(db, first.gym_id) == before


@pytest.mark.postgres
def test_a_person_known_elsewhere_becomes_the_owner(db: Database) -> None:
    other = seed_gym(db, f"otro-{uuid.uuid4().hex[:6]}")
    rut = random_rut()

    async def known(conn: asyncpg.Connection) -> uuid.UUID:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(other))
            return uuid.UUID(
                str(
                    await conn.fetchval(
                        "SELECT person_id FROM join_gym($1, NULL, 'Ya', NULL, NULL)",
                        rut,
                    )
                )
            )

    person = run(db.owner_url, known)
    created = create(
        db, new_gym(f"meta-{uuid.uuid4().hex[:6]}").model_copy(update={"owner_rut": rut})
    )

    async def owner(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval("SELECT person_id FROM staff WHERE gym_id = $1", created.gym_id)

    assert run(db.admin_url, owner) == person


@pytest.mark.postgres
def test_an_owner_needs_no_phone_and_no_rut(db: Database) -> None:
    gym = new_gym(f"meta-{uuid.uuid4().hex[:6]}").model_copy(update={"owner_phone": None})
    created = create(db, gym)

    async def owner(conn: asyncpg.Connection) -> Any:
        return await conn.fetchrow(
            "SELECT gp.email, gp.phone, gp.rut FROM staff s JOIN gym_person gp"
            " USING (gym_id, person_id) WHERE s.gym_id = $1",
            created.gym_id,
        )

    assert tuple(run(db.admin_url, owner)) == (gym.owner_email, None, None)


@pytest.mark.postgres
def test_the_database_refuses_a_slug_that_is_no_host_label(db: Database) -> None:
    async def query(conn: asyncpg.Connection) -> None:
        gym = uuid.uuid4()
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute(
                "INSERT INTO gym (id, name, slug) VALUES ($1, 'x', 'Not_A_Host')", gym
            )

    with pytest.raises(asyncpg.CheckViolationError):
        run(db.owner_url, query)


# --- requests on a gym's host ----------------------------------------------------------


@dataclass
class Outbox:
    sent: list[Email] = field(default_factory=list)

    async def send(self, email: Email) -> None:
        self.sent.append(email)

    def links_to(self, address: str, path: str = "/api/auth/callback") -> list[str]:
        return [
            word
            for email in self.sent
            if email.to.lower() == address.lower()
            for word in email.text.split()
            if path in word and word.startswith("https://")
        ]


@dataclass
class Site:
    db: Database
    app: FastAPI
    outbox: Outbox
    a: uuid.UUID
    b: uuid.UUID
    slug_a: str
    slug_b: str

    def client(self, slug: str | None) -> TestClient:
        return TestClient(self.app, base_url=HOSTS.base_url(slug), follow_redirects=False)

    def ask_link(self, client: TestClient, address: str) -> str:
        self.outbox.sent.clear()
        assert client.post("/api/auth/link", json={"email": address}).status_code == 202
        [link] = self.outbox.links_to(address)
        return link

    def open(self, client: TestClient, link: str) -> Any:
        token = parse_qs(urlsplit(link).query)["token"][0]
        return client.post("/api/auth/callback", data={"token": token})

    def gym_of_session(self, client: TestClient) -> str | None:
        response = client.get("/test/setting")
        return None if response.status_code == 401 else str(response.json()["gym"])


@pytest.fixture
def site(db: Database) -> Iterator[Site]:
    settings = db.settings.model_copy(update={"public_base_url": BASE_URL, "base_domain": BASE})
    app = create_app(settings)
    app.include_router(tenant_routes)
    app.add_middleware(FakeAuth)
    outbox = Outbox()
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=outbox)
    app.state.magic_links.sender = MailSender(
        Notices(
            outbox,
            lambda: app.state.sessionmaker,
            base_url=BASE_URL,
            secret_key=settings.secret_key,
        )
    )
    slug_a, slug_b = (f"{n}-{uuid.uuid4().hex[:6]}" for n in ("norte", "sur"))
    # Started here, so every client below shares the app's one lifespan.
    with TestClient(app):
        yield Site(db, app, outbox, seed_gym(db, slug_a), seed_gym(db, slug_b), slug_a, slug_b)


def person_in(site: Site, gyms: list[uuid.UUID], email: str) -> uuid.UUID:
    """A member of each of `gyms`, every one of which has `email` on its record. One
    person, by their RUT: an email links no one across gyms (0036)."""
    rut = random_rut()
    person = None
    with site.client(None) as client:
        for gym in gyms:
            body = {"rut": rut, "phone": new_phone(), "name": "Ana", "email": email}
            response = client.post("/api/people", json=body, headers=as_gym(gym))
            assert response.status_code == 201, response.text
            person = uuid.UUID(response.json()["id"])
            member_of(site.db, gym, person)
    assert person is not None
    return person


def address() -> str:
    return f"{uuid.uuid4().hex[:10]}@example.cl"


@pytest.mark.postgres
def test_the_ask_endpoint_allows_only_gyms_hosts(site: Site) -> None:
    with site.client(None) as client:

        def ask(domain: str) -> int:
            return int(client.get("/internal/tls-allowed", params={"domain": domain}).status_code)

        assert ask(f"{site.slug_a}.{BASE}") == 200
        assert ask(f"{site.slug_a.upper()}.{BASE}") == 200
        assert ask(f"nadie-{uuid.uuid4().hex[:6]}.{BASE}") == 404
        assert ask(BASE) == 404
        assert ask(f"www.{BASE}") == 404
        assert ask(f"{site.slug_a}.example.com") == 404
        assert ask(f"x.{site.slug_a}.{BASE}") == 404
        assert ask("") == 404

        created = create(site.db, new_gym(f"nuevo-{uuid.uuid4().hex[:6]}"))
        assert created.created
        assert ask(f"{new_gym_slug(site, created.gym_id)}.{BASE}") == 200


def new_gym_slug(site: Site, gym_id: uuid.UUID) -> str:
    async def query(conn: asyncpg.Connection) -> str:
        return str(await conn.fetchval("SELECT slug FROM gym WHERE id = $1", gym_id))

    return str(run(site.db.admin_url, query))


@pytest.mark.postgres
def test_the_host_names_its_gym_for_the_sign_in_page(site: Site) -> None:
    with site.client(site.slug_a) as client:
        assert client.get("/api/host").json() == {
            "gym": {"slug": site.slug_a, "name": site.slug_a, "theme": "bosque"}
        }
    with site.client(None) as client:
        assert client.get("/api/host").json() == {"gym": None}
    with site.client(f"nadie-{uuid.uuid4().hex[:6]}") as client:
        assert client.get("/api/host").json() == {"gym": None}


@pytest.mark.postgres
def test_a_gyms_host_and_its_sign_in_pages_wear_its_theme(site: Site) -> None:
    run(
        site.db.admin_url,
        lambda c: c.execute("UPDATE gym SET theme = 'volcan' WHERE id = $1", site.b),
    )
    email = address()
    person_in(site, [site.a], email)

    with site.client(site.slug_b) as client:
        assert client.get("/api/host").json()["gym"]["theme"] == "volcan"
        page = site.open(client, site.ask_link(client, email))
        assert page.status_code == 403
        assert '<html lang="es" data-theme="volcan">' in page.text
    # The base host is no gym's: its pages wear the stylesheet's default.
    with site.client(None) as client:
        page = client.post("/api/auth/callback", data={"token": "x" * 43})
        assert '<html lang="es">' in page.text


@pytest.mark.postgres
def test_a_theme_saved_in_ajustes_reaches_the_host_at_once(site: Site) -> None:
    with site.client(site.slug_b) as client:
        # Kept by the lookup now, for a minute.
        assert client.get("/api/host").json()["gym"]["theme"] == "bosque"
        response = client.patch(
            "/api/gym/settings", json={"theme": "oceano"}, headers=as_gym(site.b)
        )
        assert response.status_code == 200, response.text
        assert client.get("/api/host").json()["gym"]["theme"] == "oceano"


@pytest.mark.postgres
def test_the_database_refuses_a_theme_it_does_not_know(site: Site) -> None:
    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("UPDATE gym SET theme = 'neon' WHERE id = $1", site.a)

    with pytest.raises(asyncpg.CheckViolationError):
        run(site.db.admin_url, query)


@pytest.mark.postgres
def test_signing_in_on_a_gyms_host_lands_in_that_gym(site: Site) -> None:
    email = address()
    person_in(site, [site.a, site.b], email)

    for slug, gym in ((site.slug_a, site.a), (site.slug_b, site.b)):
        with site.client(slug) as client:
            link = site.ask_link(client, email)
            assert link.startswith(f"{HOSTS.base_url(slug)}/api/auth/callback?")
            response = site.open(client, link)
            assert response.status_code == 303
            assert COOKIE_NAME in client.cookies
            assert site.gym_of_session(client) == str(gym)


@pytest.mark.postgres
def test_the_base_host_keeps_picking_from_the_persons_gyms(site: Site) -> None:
    email = address()
    person_in(site, [site.a, site.b], email)

    with site.client(None) as client:
        link = site.ask_link(client, email)
        assert link.startswith(f"{BASE_URL}/api/auth/callback?")
        assert site.open(client, link).status_code == 303
        # In two gyms: none until they pick (#16), as before.
        assert site.gym_of_session(client) is None


@pytest.mark.postgres
def test_someone_not_in_the_hosts_gym_is_told_so(site: Site) -> None:
    email = address()
    person_in(site, [site.b], email)

    with site.client(site.slug_a) as client:
        response = site.open(client, site.ask_link(client, email))
        assert response.status_code == 403
        assert f"no tiene acceso a {site.slug_a}" in response.text
        assert COOKIE_NAME not in client.cookies
        assert site.gym_of_session(client) is None


@pytest.mark.postgres
def test_a_link_opened_from_another_hosts_page_is_refused(site: Site) -> None:
    email = address()
    person_in(site, [site.a], email)

    with site.client(site.slug_a) as client:
        link = site.ask_link(client, email)
        token = parse_qs(urlsplit(link).query)["token"][0]
        response = client.post(
            "/api/auth/callback", data={"token": token}, headers={"Origin": BASE_URL}
        )
        assert response.status_code == 403
        response = client.post(
            "/api/auth/callback",
            data={"token": token},
            headers={"Origin": HOSTS.base_url(site.slug_a)},
        )
        assert response.status_code == 303


@pytest.mark.postgres
def test_a_gyms_notices_link_to_its_host(site: Site) -> None:
    email = address()
    with site.client(None) as client:
        body = {"phone": new_phone(), "name": "Coach", "email": email, "role": "coach"}
        response = client.post("/api/staff", json=body, headers=as_gym(site.a))
        assert response.status_code == 201, response.text

    [link] = site.outbox.links_to(email)
    assert link.startswith(f"{HOSTS.base_url(site.slug_a)}/api/auth/callback?")
