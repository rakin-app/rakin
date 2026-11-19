"""An operator creates a gym from the panel (#437): the same gym `app.gyms create` makes,
through one database function, at an address that works at once, and its owner emailed
a link that signs in there.

The app runs as in production, a base domain and gyms on their own hosts
(`test_platform_auth`'s panel), against a real database; mail lands in an outbox.
"""

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import gyms
from app.db_bootstrap import to_dsn
from app.domain.grading import PRESETS
from app.gyms import PROCESSOR_TERMS_VERSION
from tests.pg import run
from tests.test_gym_hosts import (
    BASE,
    HOSTS,
    SIGNED_TODAY,
    address,
    counts,
    person_in,
    programs,
)
from tests.test_platform_auth import Panel, as_gym_site, grant, operator_email
from tests.test_platform_auth import db as db
from tests.test_platform_auth import panel as panel

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _terms_signed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    # Chile's today, whatever the host's clock says: see `SIGNED_TODAY`.
    monkeypatch.setattr(gyms, "gym_today", lambda tz: SIGNED_TODAY)


NEW_ROUTES = (
    ("GET", "/api/platform/slug?slug=nuevo"),
    ("GET", "/api/platform/presets"),
    ("POST", "/api/platform/gyms"),
    ("POST", f"/api/platform/gyms/{uuid.uuid4()}/owner-link"),
)


def new_slug() -> str:
    return f"nuevo-{uuid.uuid4().hex[:6]}"


def body(slug: str, **changes: Any) -> dict[str, Any]:
    return {
        "slug": slug,
        "name": "Gimnasio Nuevo",
        "timezone": "America/Santiago",
        "owner_email": f"{slug}@example.cl",
        "owner_name": "Dueña Nueva",
        "processor_terms": PROCESSOR_TERMS_VERSION,
        "signed_on": PROCESSOR_TERMS_VERSION,
        **changes,
    }


def signed_in(panel: Panel) -> Any:
    email = operator_email()
    operator_id = grant(panel.db, email)
    return operator_id, panel.signed_in(email)


def gym_events(panel: Panel, gym_id: uuid.UUID) -> list[tuple[str, uuid.UUID, dict[str, Any]]]:
    rows = run(
        panel.db.owner_url,
        lambda c: c.fetch(
            "SELECT action, operator_id, detail FROM platform_event WHERE gym_id = $1"
            " ORDER BY at, action",
            gym_id,
        ),
    )
    return [(r["action"], r["operator_id"], json.loads(r["detail"])) for r in rows]


def gyms_with(panel: Panel, slug: str) -> int:
    return int(
        run(
            panel.db.admin_url,
            lambda c: c.fetchval("SELECT count(*) FROM gym WHERE slug = $1", slug),
        )
    )


# --- creating --------------------------------------------------------------------------


def test_an_operator_creates_a_gym_that_works_at_once(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        panel.outbox.sent.clear()
        response = client.post(
            "/api/platform/gyms",
            json=body(slug, grading="judo-karate", owner_phone="+56 9 1234 5678"),
        )
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["slug"] == slug
        assert created["address"] == HOSTS.base_url(slug) == f"https://{slug}.{BASE}"
        gym_id = uuid.UUID(created["id"])

        # A certificate may be issued for its host at once.
        tls = client.get("/internal/tls-allowed", params={"domain": f"{slug}.{BASE}"})
        assert tls.status_code == 200

    # The gym the command line makes: its programs, its activity, its practice, its
    # owner holding the account, and the terms.
    made = counts(panel.db, gym_id)
    assert (made["program"], made["staff"], made["gym_activity"]) == (2, 1, 1)
    assert programs(panel.db, gym_id) == ["Adultos", "Niños"]

    async def gym(conn: asyncpg.Connection) -> Any:
        return await conn.fetchrow(
            "SELECT g.name, g.timezone,"
            " (SELECT name FROM gym_activity a WHERE a.gym_id = g.id) AS activity,"
            " (SELECT name FROM block_kind k"
            "  WHERE k.id = block_kind_default_id(g.id, 'sparring')) AS practice,"
            " (SELECT gp.name FROM staff s JOIN gym_person gp USING (gym_id, person_id)"
            "  WHERE s.gym_id = g.id AND s.account_holder AND s.role = 'owner') AS titular,"
            " (SELECT array_agg(p.version || ' ' || p.signed_on) FROM processor_terms p"
            "  WHERE p.gym_id = g.id) AS terms"
            " FROM gym g WHERE g.id = $1",
            gym_id,
        )

    row = run(panel.db.admin_url, gym)
    assert (row["name"], row["timezone"]) == ("Gimnasio Nuevo", "America/Santiago")
    # The old judo-karate key is judo's now (#411).
    assert (row["activity"], row["practice"]) == ("Judo", "Randori")
    assert row["titular"] == "Dueña Nueva"
    assert row["terms"] == [f"{PROCESSOR_TERMS_VERSION} {PROCESSOR_TERMS_VERSION}"]

    assert gym_events(panel, gym_id) == [
        (
            "gym_created",
            operator_id,
            {"slug": slug, "grading": "judo", "terms_version": PROCESSOR_TERMS_VERSION},
        ),
        ("owner_link_sent", operator_id, {"slug": slug}),
    ]

    # The owner's link points at the new host, and signs them in to the new gym there.
    owner = f"{slug}@example.cl"
    [link] = panel.outbox.links_to(owner)
    assert link.startswith(f"https://{slug}.{BASE}/api/auth/callback?")
    site = as_gym_site(panel)
    with panel.client(slug) as client:
        assert site.open(client, link).status_code == 303
        assert site.gym_of_session(client) == str(gym_id)


def test_with_no_preset_the_gym_has_no_activity(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        response = client.post("/api/platform/gyms", json=body(new_slug()))
    assert response.status_code == 201, response.text
    gym_id = uuid.UUID(response.json()["id"])
    assert counts(panel.db, gym_id)["gym_activity"] == 0

    async def practice(conn: asyncpg.Connection) -> Any:
        return await conn.fetchval(
            "SELECT name FROM block_kind WHERE id = block_kind_default_id($1, 'sparring')", gym_id
        )

    assert run(panel.db.admin_url, practice) == "Práctica libre"


# --- refused ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "field", "kind"),
    [
        ({"slug": "Con Espacios"}, "slug", "slug_format"),
        ({"slug": "-guion"}, "slug", "slug_format"),
        ({"slug": "admin"}, "slug", "slug_reserved"),
        ({"processor_terms": "2026-01-01"}, "processor_terms", "terms_version"),
        (
            {"signed_on": (SIGNED_TODAY + timedelta(days=1)).isoformat()},
            "signed_on",
            "signed_on_future",
        ),
        ({"signed_on": "2026-01-01"}, "signed_on", "signed_on_early"),
        ({"processor_terms": None}, "processor_terms", "string_type"),
        ({"grading": "ajedrez"}, "grading", "unknown_preset"),
    ],
)
def test_a_gym_the_panel_cannot_create_is_a_422(
    panel: Panel, changes: dict[str, Any], field: str, kind: str
) -> None:
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        response = client.post("/api/platform/gyms", json={**body(slug), **changes})
    assert response.status_code == 422, response.text
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [(["body", field], kind)]
    assert gyms_with(panel, changes.get("slug", slug)) == 0
    assert panel.outbox.links_to(f"{slug}@example.cl") == []


def test_the_terms_are_required(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    without = {
        k: v for k, v in body(new_slug()).items() if k not in ("processor_terms", "signed_on")
    }
    with signing_in as client:
        response = client.post("/api/platform/gyms", json=without)
    assert response.status_code == 422
    assert {tuple(e["loc"]) for e in response.json()["detail"]} == {
        ("body", "processor_terms"),
        ("body", "signed_on"),
    }


def test_a_taken_slug_writes_nothing(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    before = counts(panel.db, panel.gym_a)
    with signing_in as client:
        panel.outbox.sent.clear()
        response = client.post(
            "/api/platform/gyms", json=body(panel.slug_a, owner_email="otra@example.cl")
        )
    assert response.status_code == 422, response.text
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [
        (["body", "slug"], "slug_taken")
    ]
    assert counts(panel.db, panel.gym_a) == before
    assert gym_events(panel, panel.gym_a) == []
    assert panel.outbox.sent == []


def test_two_creations_of_one_slug_at_once_make_one_gym(panel: Panel) -> None:
    """Both wait on the slug's lock, held here, and both pass the look for the slug
    before it; once it is let go, the second finds the first's gym: a 422, not a 500."""
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:

        def create(owner: str) -> Any:
            return client.post("/api/platform/gyms", json=body(slug, owner_email=owner))

        async def go() -> list[int]:
            holder = await asyncpg.connect(to_dsn(panel.db.admin_url))
            try:
                await holder.execute("BEGIN")
                await holder.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"gym_slug:{slug}"
                )
                with ThreadPoolExecutor(2) as pool:
                    running = [
                        asyncio.wrap_future(pool.submit(create, owner))
                        for owner in ("una@example.cl", "otra@example.cl")
                    ]
                    await asyncio.sleep(0.5)
                    assert not any(r.done() for r in running), "a creation did not wait"
                    await holder.execute("COMMIT")
                    responses = await asyncio.gather(*running)
            finally:
                await holder.close()
            return [r.status_code for r in responses]

        statuses = asyncio.run(go())
    assert sorted(statuses) == [201, 422]
    assert gyms_with(panel, slug) == 1


def a_unique_violation(panel: Panel, constraint_slug: str) -> IntegrityError:
    """What SQLAlchemy raises when an insert trips the gym slug's UNIQUE: the real
    wrapper, `orig.__cause__` the driver's error naming the constraint."""

    async def go() -> IntegrityError:
        engine = create_async_engine(panel.db.owner_url)
        try:
            async with engine.connect() as conn, conn.begin():
                gym_id = uuid.uuid4()
                await conn.execute(
                    text("SELECT set_config('app.gym_id', :g, true)"), {"g": str(gym_id)}
                )
                await conn.execute(
                    text(
                        "INSERT INTO gym (id, name, slug, timezone)"
                        " VALUES (:g, 'x', :slug, 'America/Santiago')"
                    ),
                    {"g": gym_id, "slug": constraint_slug},
                )
        except IntegrityError as error:
            return error
        finally:
            await engine.dispose()
        raise AssertionError("the insert did not trip the slug's UNIQUE")

    return asyncio.run(go())


def test_a_unique_violation_on_the_slug_is_a_422_and_any_other_is_not(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock leaves nothing to trip the slug's UNIQUE; were something to, the route
    reads the constraint through the wrapper SQLAlchemy really raises."""
    violation = a_unique_violation(panel, panel.slug_a)
    cause = violation.orig.__cause__ if violation.orig is not None else None
    assert getattr(cause, "constraint_name", None) == "gym_slug_key"
    execute = AsyncSession.execute
    raised: list[IntegrityError] = [violation]

    async def tripping(self: AsyncSession, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if "platform_create_gym" in str(statement):
            raise raised[0]
        return await execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", tripping)
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        response = client.post("/api/platform/gyms", json=body(slug))
        assert response.status_code == 422, response.text
        assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [
            (["body", "slug"], "slug_taken")
        ]

        # Another constraint is no taken slug: it goes up as it came.
        cause.constraint_name = "gym_pkey"  # type: ignore[union-attr]
        with pytest.raises(IntegrityError):
            client.post("/api/platform/gyms", json=body(new_slug()))
    assert gyms_with(panel, slug) == 0


# --- the owner's link ------------------------------------------------------------------


def listed(client: TestClient, gym_id: uuid.UUID) -> dict[str, Any]:
    [gym] = [g for g in client.get("/api/platform/gyms").json() if g["id"] == str(gym_id)]
    return dict(gym)


def test_a_link_that_did_not_go_shows_in_the_list_and_goes_again(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    operator_id, signing_in = signed_in(panel)
    slug = new_slug()
    owner = f"{slug}@example.cl"
    links = panel.app.state.magic_links

    async def fails(address: str, *, base_url: str | None = None) -> list[Any]:
        raise ConnectionError("the mail server is down")

    with signing_in as client:
        with monkeypatch.context() as down:
            down.setattr(links, "send_links", fails)
            response = client.post("/api/platform/gyms", json=body(slug))
        assert response.status_code == 201, response.text
        gym_id = uuid.UUID(response.json()["id"])
        assert panel.outbox.links_to(owner) == []
        assert listed(client, gym_id)["owner_link_failed"] is True

        again = client.post(f"/api/platform/gyms/{gym_id}/owner-link")
        assert again.status_code == 200, again.text
        assert again.json() == {"sent": True}
        [link] = panel.outbox.links_to(owner)
        assert link.startswith(f"https://{slug}.{BASE}/api/auth/callback?")
        assert listed(client, gym_id)["owner_link_failed"] is False

        # A send that answers no link is a failure too, and shows again.
        with monkeypatch.context() as empty:

            async def none(address: str, *, base_url: str | None = None) -> list[Any]:
                return []

            empty.setattr(links, "send_links", none)
            assert client.post(f"/api/platform/gyms/{gym_id}/owner-link").json() == {"sent": False}
        assert listed(client, gym_id)["owner_link_failed"] is True

        assert client.post(f"/api/platform/gyms/{uuid.uuid4()}/owner-link").status_code == 404

    assert [action for action, _, _ in gym_events(panel, gym_id)] == [
        "gym_created",
        "owner_link_failed",
        "owner_link_sent",
        "owner_link_failed",
    ]
    assert {who for _, who, _ in gym_events(panel, gym_id)} == {operator_id}


# --- the slug, as typed ----------------------------------------------------------------


def test_the_slug_check_says_where_and_why_not(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    free = new_slug()
    with signing_in as client:

        def check(slug: str) -> Any:
            response = client.get("/api/platform/slug", params={"slug": slug})
            assert response.status_code == 200, response.text
            return response.json()

        assert check(free) == {"address": f"https://{free}.{BASE}", "problem": None}
        assert check("Mayúsculas")["problem"] == "format"
        assert check("a" * 64)["problem"] == "format"
        assert check("www")["problem"] == "reserved"
        assert check(panel.slug_a) == {
            "address": f"https://{panel.slug_a}.{BASE}",
            "problem": "taken",
        }


def test_the_form_gets_the_presets_the_terms_and_the_zones(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        choices = client.get("/api/platform/presets").json()
    assert choices["grading"] == [{"key": p["key"], "label": p["label"]} for p in PRESETS]
    assert choices["terms_version"] == PROCESSOR_TERMS_VERSION
    assert "America/Santiago" in choices["timezones"]
    assert choices["timezones"] == sorted(choices["timezones"])


# --- nobody else -----------------------------------------------------------------------


def call(client: TestClient, method: str, path: str) -> int:
    return int(client.request(method, path, json=body(new_slug())).status_code)


def test_a_gym_owner_gets_a_401_on_every_new_route(panel: Panel) -> None:
    owner = address()
    person_in(as_gym_site(panel), [panel.gym_a], owner)
    site = as_gym_site(panel)
    with panel.client() as client:
        assert site.open(client, site.ask_link(client, owner)).status_code == 303
        for method, path in NEW_ROUTES:
            assert call(client, method, path) == 401, path


def test_the_new_routes_are_a_404_on_a_gyms_host(panel: Panel) -> None:
    with panel.client(panel.slug_a) as client:
        for method, path in NEW_ROUTES:
            assert call(client, method, path) == 404, path


# --- in the database -------------------------------------------------------------------


def test_the_app_cannot_call_gym_create(panel: Panel) -> None:
    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetch(
            "SELECT * FROM gym_create($1, 'x', 'x', 'America/Santiago', '{}'::jsonb, '{}',"
            " NULL, NULL, 'x', 'x@example.cl', 'X', NULL, NULL, NULL, NULL)",
            uuid.uuid4(),
        )

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(panel.db.api_url, query)


def test_creating_needs_a_live_operator_session(panel: Panel) -> None:
    async def query(conn: asyncpg.Connection) -> Any:
        return await conn.fetch(
            "SELECT * FROM platform_create_gym($1, 'none', $2, 'x', 'x', 'America/Santiago',"
            " '{}'::jsonb, '{}', NULL, NULL, 'x', 'x@example.cl', 'X', NULL, NULL, NULL, NULL)",
            b"\x00" * 32,
            uuid.uuid4(),
        )

    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
        run(panel.db.api_url, query)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
        run(
            panel.db.api_url,
            lambda c: c.fetchval("SELECT platform_slug_taken($1, 'x')", b"\x00" * 32),
        )
