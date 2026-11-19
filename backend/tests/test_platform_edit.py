"""An operator edits a gym from the panel (#438): its name, its titular's contact, a
new signature of the Términos de encargo, and its slug, the old address redirecting
for 90 days and no other gym's meanwhile.

The app runs as in production, a base domain and gyms on their own hosts
(`test_platform_auth`'s panel), against a real database; mail lands in an outbox. Each
gym is created through the panel, as an operator would, so its titular is a real one.
"""

import json
import re
import uuid
from datetime import date, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import gyms
from app.gyms import PROCESSOR_TERMS_VERSION
from app.magiclink.tokens import hash_token
from app.platform.session import COOKIE_NAME as PLATFORM_COOKIE
from tests.pg import run
from tests.test_gym_hosts import BASE, SIGNED_TODAY, address, person_in
from tests.test_platform_auth import Panel, as_gym_site
from tests.test_platform_auth import db as db
from tests.test_platform_auth import panel as panel
from tests.test_platform_create import body, gym_events, new_slug, signed_in

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _terms_signed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    # Chile's today, whatever the host's clock says: see `SIGNED_TODAY`.
    monkeypatch.setattr(gyms, "gym_today", lambda tz: SIGNED_TODAY)


NEW_ROUTES = (
    ("GET", f"/api/platform/gyms/{uuid.uuid4()}"),
    ("PATCH", f"/api/platform/gyms/{uuid.uuid4()}"),
    ("POST", f"/api/platform/gyms/{uuid.uuid4()}/terms"),
    ("POST", f"/api/platform/gyms/{uuid.uuid4()}/slug"),
    ("POST", "/api/platform/reauth/send"),
    ("POST", "/api/platform/reauth"),
)


def create(client: TestClient, slug: str, **changes: Any) -> uuid.UUID:
    response = client.post("/api/platform/gyms", json=body(slug, **changes))
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def rename(client: TestClient, gym_id: uuid.UUID, slug: str) -> Any:
    return client.post(f"/api/platform/gyms/{gym_id}/slug", json={"slug": slug})


def titular_signs_in(panel: Panel, slug: str, gym_id: uuid.UUID) -> None:
    """The titular opens the link the panel emailed them, on the gym's host."""
    [link] = panel.outbox.links_to(f"{slug}@example.cl")
    site = as_gym_site(panel)
    with panel.client(slug) as client:
        assert site.open(client, link).status_code == 303
        assert site.gym_of_session(client) == str(gym_id)


def titular_records(panel: Panel, *gym_ids: uuid.UUID) -> list[tuple[str, str | None, str | None]]:
    """The titular's name, phone and email in each gym's own record of them."""

    async def query(conn: asyncpg.Connection) -> list[tuple[str, str | None, str | None]]:
        rows = []
        for gym_id in gym_ids:
            row = await conn.fetchrow(
                "SELECT gp.name, gp.phone, gp.email FROM staff s"
                " JOIN gym_person gp USING (gym_id, person_id)"
                " WHERE s.gym_id = $1 AND s.account_holder",
                gym_id,
            )
            rows.append((row["name"], row["phone"], row["email"]))
        return rows

    return list(run(panel.db.admin_url, query))


def stale(panel: Panel, client: TestClient) -> None:
    """The client's session last proved 11 minutes ago."""
    run(
        panel.db.admin_url,
        lambda c: c.execute(
            "UPDATE operator_session SET fresh_at = now() - interval '11 minutes'"
            " WHERE token_hash = $1",
            hash_token(client.cookies[PLATFORM_COOKIE]),
        ),
    )


def set_alias_until(panel: Panel, slug: str, until: str) -> None:
    run(
        panel.db.admin_url,
        lambda c: c.execute(
            f"UPDATE gym_slug_alias SET until = now() + interval '{until}' WHERE slug = $1", slug
        ),
    )


def aliases(panel: Panel, gym_id: uuid.UUID) -> list[str]:
    rows = run(
        panel.db.admin_url,
        lambda c: c.fetch(
            "SELECT slug FROM gym_slug_alias WHERE gym_id = $1 ORDER BY slug", gym_id
        ),
    )
    return [r["slug"] for r in rows]


# --- name and contact ------------------------------------------------------------------


def test_a_new_name_shows_on_the_host_at_once(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        gym_id = create(client, slug)
    # The host's gym, found and kept by its lookup.
    with panel.client(slug) as host:
        assert host.get("/api/host").json()["gym"]["name"] == "Gimnasio Nuevo"
    with signed_in(panel)[1] as client:
        response = client.patch(f"/api/platform/gyms/{gym_id}", json={"name": "Otro Nombre"})
        assert response.status_code == 200, response.text
        assert response.json() == {"fields": ["name"]}
        # The same name again changes nothing, and logs nothing.
        same = client.patch(f"/api/platform/gyms/{gym_id}", json={"name": "Otro Nombre"})
        assert same.json() == {"fields": []}
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["name"] == "Otro Nombre"
    with panel.client(slug) as host:
        assert host.get("/api/host").json()["gym"]["name"] == "Otro Nombre"
    [edited] = [e for e in gym_events(panel, gym_id) if e[0] == "gym_edited"]
    assert edited[2] == {"slug": slug, "fields": ["name"]}
    assert edited[1] != operator_id  # the second operator's


def test_the_titulars_name_and_phone_change_in_that_gym_only(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    rut = "11111111-1"
    one, other = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, one, owner_rut=rut, owner_phone="+56 9 1111 1111")
        # The same person, by their RUT, holds another gym.
        other_id = create(client, other, owner_rut=rut, owner_phone="+56 9 1111 1111")
        response = client.patch(
            f"/api/platform/gyms/{gym_id}",
            json={"owner_name": "Nombre Nuevo", "owner_phone": "+56 9 2222 2222"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"fields": ["owner_name", "owner_phone"]}
        detail = client.get(f"/api/platform/gyms/{gym_id}").json()
    assert (detail["titular_name"], detail["titular_phone"]) == ("Nombre Nuevo", "+56922222222")
    assert titular_records(panel, gym_id, other_id) == [
        ("Nombre Nuevo", "+56922222222", f"{one}@example.cl"),
        ("Dueña Nueva", "+56911111111", f"{other}@example.cl"),
    ]
    [edited] = [e for e in gym_events(panel, gym_id) if e[0] == "gym_edited"]
    # Field names, never the values.
    assert edited[2] == {"slug": one, "fields": ["owner_name", "owner_phone"]}


def test_the_titulars_email_changes_only_before_their_first_sign_in(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        gym_id = create(client, slug)
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["titular_signed_in"] is False
        # A typo at creation, fixed.
        fixed = client.patch(
            f"/api/platform/gyms/{gym_id}", json={"owner_email": f"{slug}@example.cl"}
        )
        assert fixed.json() == {"fields": []}
        typo = client.patch(f"/api/platform/gyms/{gym_id}", json={"owner_email": "otra@example.cl"})
        assert typo.status_code == 200, typo.text
        assert typo.json() == {"fields": ["owner_email"]}
        back = client.patch(
            f"/api/platform/gyms/{gym_id}", json={"owner_email": f"{slug}@example.cl"}
        )
        assert back.json() == {"fields": ["owner_email"]}

    titular_signs_in(panel, slug, gym_id)

    with signed_in(panel)[1] as client:
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["titular_signed_in"] is True
        refused = client.patch(
            f"/api/platform/gyms/{gym_id}",
            json={"name": "Cambiado", "owner_email": "otra@example.cl"},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json() == {"detail": {"code": "titular_handover", "issue": 321}}
        # Nothing of it was written, the name included.
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["name"] == "Gimnasio Nuevo"
        # Their name still changes.
        named = client.patch(f"/api/platform/gyms/{gym_id}", json={"owner_name": "Otra"})
        assert named.json() == {"fields": ["owner_name"]}
    assert titular_records(panel, gym_id)[0][2] == f"{slug}@example.cl"


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        ({"name": ""}, "string_too_short"),
        ({"owner_phone": "no"}, "value_error"),
        ({"owner_email": "no es un correo"}, "value_error"),
        ({"owner_rut": "11111111-1"}, "extra_forbidden"),
    ],
)
def test_an_edit_the_panel_cannot_make_is_a_422(
    panel: Panel, change: dict[str, Any], kind: str
) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        response = client.patch(f"/api/platform/gyms/{gym_id}", json=change)
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert (error["loc"][-1], error["type"]) == (next(iter(change)), kind)


def test_an_unknown_gym_is_a_404(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    missing = uuid.uuid4()
    with signing_in as client:
        assert client.get(f"/api/platform/gyms/{missing}").status_code == 404
        assert client.patch(f"/api/platform/gyms/{missing}", json={"name": "X"}).status_code == 404
        terms = client.post(
            f"/api/platform/gyms/{missing}/terms", json={"signed_on": PROCESSOR_TERMS_VERSION}
        )
        assert terms.status_code == 404
        assert rename(client, missing, new_slug()).status_code == 404


# --- the terms -------------------------------------------------------------------------


def test_the_current_terms_are_recorded_once_and_keep_their_first_date(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        # Created with the terms, as the panel always does; dropped here, to sign anew.
        gym_id = create(client, slug)

        async def unsign(conn: asyncpg.Connection) -> None:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
                await conn.execute("DELETE FROM processor_terms WHERE gym_id = $1", gym_id)

        run(panel.db.owner_url, unsign)
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["terms"] == []

        first = client.post(
            f"/api/platform/gyms/{gym_id}/terms", json={"signed_on": PROCESSOR_TERMS_VERSION}
        )
        assert first.status_code == 200, first.text
        assert first.json() == {"recorded": True}
        again = client.post(
            f"/api/platform/gyms/{gym_id}/terms", json={"signed_on": SIGNED_TODAY.isoformat()}
        )
        assert again.json() == {"recorded": False}
        detail = client.get(f"/api/platform/gyms/{gym_id}").json()
    assert detail["terms"] == [
        {"version": PROCESSOR_TERMS_VERSION, "signed_on": PROCESSOR_TERMS_VERSION}
    ]
    assert detail["terms_version"] == PROCESSOR_TERMS_VERSION
    assert [e[2] for e in gym_events(panel, gym_id) if e[0] == "terms_recorded"] == [
        {"slug": slug, "terms_version": PROCESSOR_TERMS_VERSION}
    ]


@pytest.mark.parametrize(
    ("signed_on", "kind"),
    [
        ((SIGNED_TODAY + timedelta(days=1)).isoformat(), "signed_on_future"),
        ("2026-01-01", "signed_on_early"),
        (None, "date_type"),
    ],
)
def test_a_signature_the_panel_cannot_record_is_a_422(
    panel: Panel, signed_on: str | None, kind: str
) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        response = client.post(f"/api/platform/gyms/{gym_id}/terms", json={"signed_on": signed_on})
    assert response.status_code == 422, response.text
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [
        (["body", "signed_on"], kind)
    ]


# --- the slug --------------------------------------------------------------------------


def test_a_renamed_gyms_old_address_redirects_for_90_days(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    old, new = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        renamed = rename(client, gym_id, new)
        assert renamed.status_code == 200, renamed.text
        answer = renamed.json()
        assert (answer["slug"], answer["address"], answer["old_slug"]) == (
            new,
            f"https://{new}.{BASE}",
            old,
        )
        until = date.fromisoformat(answer["until"][:10])
        # system date: the database's 90 days, against the clock it keeps them by
        assert until >= date.today() + timedelta(days=89)
        [alias] = client.get(f"/api/platform/gyms/{gym_id}").json()["aliases"]
        assert (alias["slug"], alias["address"]) == (old, f"https://{old}.{BASE}")

        # A certificate for the old host while it redirects.
        tls = client.get("/internal/tls-allowed", params={"domain": f"{old}.{BASE}"})
        assert tls.status_code == 200

    with panel.client(old) as host:
        response = host.get("/alumnos?x=1")
        assert response.status_code == 301
        assert response.headers["location"] == f"https://{new}.{BASE}/alumnos?x=1"
        head = host.head("/alumnos?x=1")
        assert (head.status_code, head.headers["location"]) == (
            301,
            f"https://{new}.{BASE}/alumnos?x=1",
        )
        # Any other method keeps itself and its body on the new host.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = host.request(method, "/api/people?y=2", json={"a": 1})
            assert (sent.status_code, sent.headers["location"]) == (
                308,
                f"https://{new}.{BASE}/api/people?y=2",
            ), method
        moved = host.get("/api/host")
        assert moved.status_code == 301
        assert moved.headers["location"] == f"https://{new}.{BASE}/api/host"
    with panel.client(new) as host:
        assert host.get("/api/host").json()["gym"]["slug"] == new

    assert [e[1:] for e in gym_events(panel, gym_id) if e[0] == "gym_renamed"] == [
        (operator_id, {"from": old, "to": new})
    ]

    # Once its 90 days are past, the old host is no gym's.
    set_alias_until(panel, old, "-1 second")
    with panel.client() as client:
        tls = client.get("/internal/tls-allowed", params={"domain": f"{old}.{BASE}"})
        assert tls.status_code == 404
    panel.app.state.gym_lookup.forget(old)
    with panel.client(old) as host:
        assert host.get("/api/host").json() == {"gym": None}


def test_caddy_asks_before_serving_a_page_on_an_old_address(panel: Panel) -> None:
    # Caddy's check before a page (deploy/Caddyfile, #472): the api's own host, and the page's
    # host, method and URI in X-Forwarded-*.
    _, signing_in = signed_in(panel)
    old, new = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        assert rename(client, gym_id, new).status_code == 200

    def page(host: str, uri: str = "/alumnos?x=1&y=2", method: str = "GET") -> tuple[int, str]:
        headers = {"X-Forwarded-Host": host, "X-Forwarded-Method": method, "X-Forwarded-Uri": uri}
        with TestClient(panel.app, base_url="http://api:8000", follow_redirects=False) as api:
            answer = api.get("/internal/host", headers=headers)
        return answer.status_code, answer.headers.get("location", "")

    assert page(f"{old}.{BASE}") == (301, f"https://{new}.{BASE}/alumnos?x=1&y=2")
    assert page(f"{old}.{BASE}:443", "/") == (301, f"https://{new}.{BASE}/")
    assert page(f"{old}.{BASE}", method="HEAD") == (301, f"https://{new}.{BASE}/alumnos?x=1&y=2")
    assert page(f"{old}.{BASE}", method="POST") == (308, f"https://{new}.{BASE}/alumnos?x=1&y=2")
    # A URI that is no path stays on the gym's host.
    assert page(f"{old}.{BASE}", "evil.example/x") == (301, f"https://{new}.{BASE}/")
    # The page is served: on the gym's own host, the base host, a slug no gym has, and
    # with no host said at all.
    for host in (f"{new}.{BASE}", BASE, f"{new_slug()}.{BASE}", ""):
        assert page(host) == (200, ""), host
    # A host or method no request has is no redirect, never a validation error.
    assert page(f"{'a' * 300}.{BASE}") == (200, "")
    assert page(f"{'a' * 300}.{old}.{BASE}") == (200, "")
    assert page(f"{old}.{BASE}", method="X" * 100) == (308, f"https://{new}.{BASE}/alumnos?x=1&y=2")

    # Once its 90 days are past, the old host's pages are served, as its API's are.
    set_alias_until(panel, old, "-1 second")
    panel.app.state.gym_lookup.forget(old)
    assert page(f"{old}.{BASE}") == (200, "")


def test_no_other_gym_takes_a_slug_that_still_redirects(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    old, new = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        other_id = create(client, new_slug())
        assert rename(client, gym_id, new).status_code == 200

        def check(slug: str, gym: uuid.UUID | None = None) -> Any:
            params: dict[str, Any] = {"slug": slug}
            if gym is not None:
                params["gym"] = str(gym)
            return client.get("/api/platform/slug", params=params).json()["problem"]

        # Taken, for a new gym and for another's rename; not for its own gym's.
        assert check(old) == "taken"
        assert check(old, other_id) == "taken"
        assert check(old, gym_id) is None

        created = client.post("/api/platform/gyms", json=body(old, owner_email="x@example.cl"))
        assert created.status_code == 422, created.text
        assert [(e["loc"], e["type"]) for e in created.json()["detail"]] == [
            (["body", "slug"], "slug_taken")
        ]
        for slug in (old, new):
            taken = rename(client, other_id, slug)
            assert taken.status_code == 422, taken.text
            assert taken.json()["detail"][0]["type"] == "slug_taken"

        # Lapsed, it is anyone's.
        set_alias_until(panel, old, "-1 second")
        assert check(old) is None
        assert rename(client, other_id, old).status_code == 200
    # The lapsed alias went with it.
    assert aliases(panel, gym_id) == []


def test_the_command_line_cannot_take_a_slug_that_still_redirects(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    old = new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        assert rename(client, gym_id, new_slug()).status_code == 200

    async def go(conn: asyncpg.Connection) -> Any:
        new_gym = gyms.NewGym(
            slug=old,
            name="Ajeno",
            timezone="America/Santiago",
            owner_email="ajeno@example.cl",
            owner_name="Ajeno",
        )
        return await gyms.create_gym(conn, new_gym)

    created = run(panel.db.owner_url, go)
    # The gym it redirects to is the answer, as for a gym's own slug.
    assert (created.created, created.gym_id) == (False, gym_id)


def test_renaming_back_takes_the_old_slug_again(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    old, new = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        assert rename(client, gym_id, new).status_code == 200
        # The old host redirects, and keeps that a minute; going back forgets it.
        assert client.get(f"https://{old}.{BASE}/").status_code == 301
        back = rename(client, gym_id, old)
        assert back.status_code == 200, back.text
    assert aliases(panel, gym_id) == [new]
    with panel.client(old) as host:
        assert host.get("/api/host").json()["gym"]["slug"] == old
    with panel.client(new) as host:
        response = host.get("/x")
        assert (response.status_code, response.headers["location"]) == (
            301,
            f"https://{old}.{BASE}/x",
        )


def test_a_slug_the_gym_has_already_changes_nothing(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        gym_id = create(client, slug)
        same = rename(client, gym_id, slug)
        assert same.status_code == 200, same.text
        assert (same.json()["old_slug"], same.json()["until"]) == (slug, None)
    assert aliases(panel, gym_id) == []
    assert [e for e in gym_events(panel, gym_id) if e[0] == "gym_renamed"] == []


@pytest.mark.parametrize(
    ("slug", "kind"), [("Con Espacios", "slug_format"), ("admin", "slug_reserved")]
)
def test_a_slug_no_gym_can_have_is_a_422(panel: Panel, slug: str, kind: str) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        response = rename(client, gym_id, slug)
    assert response.status_code == 422, response.text
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [(["body", "slug"], kind)]


def test_a_stale_session_proves_itself_by_code_then_renames(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    old, new = new_slug(), new_slug()
    with signing_in as client:
        gym_id = create(client, old)
        email = client.get("/api/platform/me").json()["email"]
        stale(panel, client)
        refused = rename(client, gym_id, new)
        assert refused.status_code == 401
        assert refused.json() == {"detail": {"code": "reauth"}}
        # Still signed in: only the rename asks for the proof.
        assert client.get("/api/platform/me").status_code == 200

        panel.outbox.sent.clear()
        assert client.post("/api/platform/reauth/send").status_code == 202
        [sent] = [e for e in panel.outbox.sent if e.to == email]
        [code] = re.findall(r"código: (\d{3} \d{3})", sent.text)
        wrong = client.post("/api/platform/reauth", json={"code": "000000"})
        assert wrong.status_code == 400
        assert client.post("/api/platform/reauth", json={"code": code}).status_code == 204
        # Spent: it proves nothing twice.
        assert client.post("/api/platform/reauth", json={"code": code}).status_code == 400

        renamed = rename(client, gym_id, new)
        assert renamed.status_code == 200, renamed.text
    [renamed_event] = [e for e in gym_events(panel, gym_id) if e[0] == "gym_renamed"]
    assert renamed_event[1] == operator_id


def test_the_database_refuses_a_rename_on_a_stale_session(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        stale(panel, client)
        session = hash_token(client.cookies[PLATFORM_COOKIE])
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="not fresh"):
        run(
            panel.db.api_url,
            lambda c: c.fetch(
                "SELECT * FROM platform_rename_gym($1, $2, $3)", session, gym_id, new_slug()
            ),
        )


# --- nobody else -----------------------------------------------------------------------


def call(client: TestClient, method: str, path: str) -> int:
    return int(client.request(method, path, json={"slug": new_slug()}).status_code)


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


def test_the_app_reads_no_alias(panel: Panel) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        run(panel.db.api_url, lambda c: c.fetch("SELECT * FROM gym_slug_alias"))


def test_the_edits_need_a_live_operator_session(panel: Panel) -> None:
    nobody = b"\x00" * 32
    gym = uuid.uuid4()

    def calling(sql: str) -> Any:
        return lambda c: c.fetch(sql, nobody, gym)

    for sql in (
        "SELECT * FROM platform_gym($1, $2)",
        "SELECT * FROM platform_edit_gym($1, $2, 'x', NULL, NULL, NULL)",
        "SELECT platform_record_terms($1, $2, 'x', '2026-11-18')",
        "SELECT * FROM platform_rename_gym($1, $2, 'x')",
        "SELECT platform_slug_taken($1, 'x', $2)",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
            run(panel.db.api_url, calling(sql))


def test_an_event_names_fields_never_values(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        client.patch(
            f"/api/platform/gyms/{gym_id}",
            json={"owner_name": "Secreta Persona", "owner_phone": "+56 9 3333 3333"},
        )
    logged = json.dumps([e[2] for e in gym_events(panel, gym_id)])
    assert "Secreta" not in logged
    assert "3333" not in logged
