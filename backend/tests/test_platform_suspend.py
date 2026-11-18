"""An operator suspends a gym from the panel and resumes it (#439); removing one is
refused until #377.

While a gym is suspended its host shows a notice, nobody gets a link into it, a live
session there stops, and its data stays. The app runs as in production, a base domain
and gyms on their own hosts (`test_platform_auth`'s panel), against a real database;
mail lands in an outbox. The nightly jobs' side is `test_catch_up`.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import gyms
from app.api.webhooks import RESEND_PATH
from app.domain.dates import gym_today
from app.magiclink import COOKIE_NAME
from app.magiclink.tokens import hash_token
from app.notices.unsubscribe import UNSUBSCRIBE_PATH, UnsubscribeSigner
from app.platform import removal
from app.platform.session import COOKIE_NAME as PLATFORM_COOKIE
from tests.pg import run, seed_gym
from tests.test_gym_hosts import BASE, SIGNED_TODAY, Site, address, person_in
from tests.test_platform_auth import Panel, as_gym_site
from tests.test_platform_auth import db as db
from tests.test_platform_auth import panel as panel
from tests.test_platform_create import gym_events, new_slug, signed_in
from tests.test_platform_edit import create, stale
from tests.test_resend_webhook import SECRET, bounced, signed

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _terms_signed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    # Chile's today, whatever the host's clock says: see `SIGNED_TODAY`.
    monkeypatch.setattr(gyms, "gym_today", lambda tz: SIGNED_TODAY)


NEW_ROUTES = (
    ("POST", f"/api/platform/gyms/{uuid.uuid4()}/suspend"),
    ("POST", f"/api/platform/gyms/{uuid.uuid4()}/resume"),
    ("DELETE", f"/api/platform/gyms/{uuid.uuid4()}"),
)


def suspend(client: TestClient, gym_id: uuid.UUID, reason: str = "Impago") -> Any:
    return client.post(f"/api/platform/gyms/{gym_id}/suspend", json={"reason": reason})


def resume(client: TestClient, gym_id: uuid.UUID) -> Any:
    return client.post(f"/api/platform/gyms/{gym_id}/resume")


def suspended(panel: Panel, gym_id: uuid.UUID) -> None:
    """The gym, suspended by an operator just signed in."""
    with signed_in(panel)[1] as client:
        response = suspend(client, gym_id)
        assert response.status_code == 200, response.text
        assert response.json() == {"changed": True}


def resumed(panel: Panel, gym_id: uuid.UUID) -> None:
    with signed_in(panel)[1] as client:
        response = resume(client, gym_id)
        assert response.status_code == 200, response.text
        assert response.json() == {"changed": True}


def two_gyms(panel: Panel) -> Site:
    """The panel's gym, and another, as a gym's site sees them."""
    slug_b = f"sur-{uuid.uuid4().hex[:6]}"
    gym_b = seed_gym(panel.db, slug_b)
    return Site(panel.db, panel.app, panel.outbox, panel.gym_a, gym_b, panel.slug_a, slug_b)


def asks_for_a_link(site: Site, client: TestClient, email: str) -> list[str]:
    """The links an ask for one on `client`'s host emails `email`."""
    site.outbox.sent.clear()
    assert client.post("/api/auth/link", json={"email": email}).status_code == 202
    return site.outbox.links_to(email)


def calling(sql: str, *args: object) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    return lambda c: c.fetch(sql, *args)


def gym_rows(panel: Panel, gym_id: uuid.UUID) -> dict[str, int]:
    """How many rows each gym-scoped table holds for the gym."""

    async def query(conn: asyncpg.Connection) -> dict[str, int]:
        tables = await conn.fetch(
            "SELECT table_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND column_name = 'gym_id'"
            " AND table_name NOT LIKE 'platform%'"
        )
        counts = {}
        for row in tables:
            name = row["table_name"]
            counts[name] = await conn.fetchval(
                f'SELECT count(*) FROM "{name}" WHERE gym_id = $1', gym_id
            )
        counts["gym"] = await conn.fetchval("SELECT count(*) FROM gym WHERE id = $1", gym_id)
        return counts

    return dict(run(panel.db.admin_url, query))


# --- while it is suspended -------------------------------------------------------------


def test_a_suspended_gym_shuts_everyone_out_and_keeps_its_data(panel: Panel) -> None:
    site = two_gyms(panel)
    email = address()
    person_in(site, [panel.gym_a], email)
    # One client at a time: each starts the app's lifespan.
    with site.client(panel.slug_a) as member:
        assert site.open(member, site.ask_link(member, email)).status_code == 303
        assert site.gym_of_session(member) == str(panel.gym_a)
        token = member.cookies[COOKIE_NAME]
        # The host's gym, found and kept by its lookup.
        assert member.get("/api/host").json()["gym"]["suspended"] is False
    with site.client(panel.slug_a) as member:
        # The same session, on a client of its own.
        member.cookies.set(COOKIE_NAME, token)
        assert site.gym_of_session(member) == str(panel.gym_a)
    before = gym_rows(panel, panel.gym_a)

    suspended(panel, panel.gym_a)

    with site.client(panel.slug_a) as member:
        member.cookies.set(COOKIE_NAME, token)
        # The live session stops at once, and the host says so at once.
        assert member.get("/test/setting").status_code == 401
        assert member.get("/api/host").json()["gym"]["suspended"] is True
        # Nobody gets a link into it.
        assert asks_for_a_link(site, member, email) == []
    with site.client(None) as base:
        assert asks_for_a_link(site, base, email) == []
        # Its host still gets a certificate, to serve the notice.
        tls = base.get("/internal/tls-allowed", params={"domain": f"{panel.slug_a}.{BASE}"})
        assert tls.status_code == 200
    assert gym_rows(panel, panel.gym_a) == before


def test_check_in_stops_with_the_session_and_unsubscribe_stays_open(panel: Panel) -> None:
    # Check-in is the staff's, behind a session: it stops when the session does. The
    # unsubscribe link stays open, so anyone can always stop the gym's email.
    site = two_gyms(panel)
    email = address()
    person = person_in(site, [panel.gym_a], email)
    with site.client(panel.slug_a) as member:
        assert site.open(member, site.ask_link(member, email)).status_code == 303
        token = member.cookies[COOKIE_NAME]
        assert member.get("/api/check-in").status_code != 401
    link = UnsubscribeSigner(panel.app.state.settings.secret_key).sign(panel.gym_a, person)

    suspended(panel, panel.gym_a)

    with site.client(panel.slug_a) as member:
        member.cookies.set(COOKIE_NAME, token)
        assert member.get("/api/check-in").status_code == 401
        assert member.post(f"{UNSUBSCRIBE_PATH}/{link}").status_code == 200


def test_someone_in_a_suspended_gym_and_an_active_one_signs_in_to_the_active_one(
    panel: Panel,
) -> None:
    site = two_gyms(panel)
    email = address()
    person_in(site, [site.a, site.b], email)
    suspended(panel, site.a)
    with site.client(site.slug_b) as client:
        assert site.open(client, site.ask_link(client, email)).status_code == 303
        assert site.gym_of_session(client) == str(site.b)
    # On the base host, the active gym is the only one there is.
    with site.client(None) as client:
        assert site.open(client, site.ask_link(client, email)).status_code == 303
        assert site.gym_of_session(client) == str(site.b)


def test_the_list_and_the_gym_say_it_is_suspended_since_when_and_why(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        listed = next(g for g in client.get("/api/platform/gyms").json() if g["id"] == str(gym_id))
        assert (listed["status"], listed["suspended_at"]) == ("active", None)
        detail = client.get(f"/api/platform/gyms/{gym_id}").json()
        assert (detail["suspended_at"], detail["suspended_reason"], detail["removal"]) == (
            None,
            None,
            None,
        )

        assert suspend(client, gym_id, "  Pidió una pausa  ").json() == {"changed": True}

        listed = next(g for g in client.get("/api/platform/gyms").json() if g["id"] == str(gym_id))
        assert listed["status"] == "suspended"
        assert listed["suspended_at"] is not None
        detail = client.get(f"/api/platform/gyms/{gym_id}").json()
        assert detail["suspended_reason"] == "Pidió una pausa"
        assert detail["suspended_at"] == listed["suspended_at"]
        # The dates a removal started today would keep, by the terms' numbers.
        assert detail["removal"]["export_days"] == removal.EXPORT_DAYS
        assert detail["removal"]["deletion_days"] == removal.DELETION_DAYS
        assert detail["removal"]["backup_days"] == removal.BACKUP_DAYS
        dates = removal.schedule(gym_today(panel.app.state.settings.jobs_timezone))
        assert detail["removal"]["export_until"] == dates.export_until.isoformat()
        assert detail["removal"]["deleted_by"] == dates.deleted_by.isoformat()
        assert detail["removal"]["backups_gone_by"] == dates.backups_gone_by.isoformat()


def test_a_payment_webhook_is_still_taken_for_a_suspended_gym(
    panel: Panel, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Rakin takes no payment webhook yet: Resend's is the only one, and it belongs to no
    # gym. A bounce for a suspended gym's member is still recorded.
    settings = panel.app.state.settings.model_copy(update={"resend_webhook_secret": SECRET})
    monkeypatch.setattr(panel.app.state, "settings", settings)
    site = two_gyms(panel)
    email = address()
    person_in(site, [panel.gym_a], email)
    suspended(panel, panel.gym_a)
    body, headers = signed(bounced(email))
    with panel.client() as client:
        assert client.post(RESEND_PATH, content=body, headers=headers).status_code == 204
    kept = run(
        panel.db.admin_url,
        lambda c: c.fetchval("SELECT count(*) FROM mail_suppression WHERE address = $1", email),
    )
    assert kept == 1


# --- resuming --------------------------------------------------------------------------


def test_after_a_resume_the_titular_signs_in_again(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        gym_id = create(client, slug)
        assert suspend(client, gym_id).status_code == 200
    site = as_gym_site(panel)
    titular = f"{slug}@example.cl"
    with panel.client(slug) as host:
        assert asks_for_a_link(site, host, titular) == []
    resumed(panel, gym_id)
    with panel.client(slug) as host:
        assert host.get("/api/host").json()["gym"]["suspended"] is False
        [link] = asks_for_a_link(site, host, titular)
        assert site.open(host, link).status_code == 303
        assert site.gym_of_session(host) == str(gym_id)

    # The jobs owe it the days since it was suspended (`app.jobs.catch_up`).
    owed = run(
        panel.db.admin_url,
        lambda c: c.fetchrow(
            "SELECT jobs_owed_since, suspended_at, suspended_reason FROM gym WHERE id = $1",
            gym_id,
        ),
    )
    assert owed["jobs_owed_since"] is not None
    assert (owed["suspended_at"], owed["suspended_reason"]) == (None, None)


def test_suspending_or_resuming_twice_writes_one_event(panel: Panel) -> None:
    operator_id, signing_in = signed_in(panel)
    slug = new_slug()
    with signing_in as client:
        gym_id = create(client, slug)
        assert suspend(client, gym_id, "Impago").json() == {"changed": True}
        assert suspend(client, gym_id, "Otra razón").json() == {"changed": False}
        assert client.get(f"/api/platform/gyms/{gym_id}").json()["suspended_reason"] == "Impago"
        assert resume(client, gym_id).json() == {"changed": True}
        assert resume(client, gym_id).json() == {"changed": False}
    events = [e for e in gym_events(panel, gym_id) if e[0] in ("gym_suspended", "gym_resumed")]
    assert events == [
        ("gym_suspended", operator_id, {"slug": slug, "reason": "Impago"}),
        ("gym_resumed", operator_id, {"slug": slug}),
    ]


def test_a_stale_session_gets_reauth_on_suspend_and_resume(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        stale(panel, client)
        for response in (suspend(client, gym_id), resume(client, gym_id)):
            assert response.status_code == 401
            assert response.json() == {"detail": {"code": "reauth"}}
    assert [e for e in gym_events(panel, gym_id) if e[0] == "gym_suspended"] == []


def test_the_database_refuses_a_suspension_on_a_stale_session(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        stale(panel, client)
        session = hash_token(client.cookies[PLATFORM_COOKIE])
    for sql in (
        "SELECT * FROM platform_suspend_gym($1, $2, 'x')",
        "SELECT * FROM platform_resume_gym($1, $2)",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="not fresh"):
            run(panel.db.api_url, calling(sql, session, gym_id))


def test_a_reason_is_required_and_an_unknown_gym_is_a_404(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        for body in ({}, {"reason": "   "}, {"reason": "x" * 501}):
            response = client.post(f"/api/platform/gyms/{gym_id}/suspend", json=body)
            assert response.status_code == 422, body
        assert suspend(client, uuid.uuid4()).status_code == 404
        assert resume(client, uuid.uuid4()).status_code == 404
        assert client.delete(f"/api/platform/gyms/{uuid.uuid4()}").status_code == 404


# --- removing --------------------------------------------------------------------------


def test_removing_is_refused_and_deletes_nothing(panel: Panel) -> None:
    _, signing_in = signed_in(panel)
    with signing_in as client:
        gym_id = create(client, new_slug())
        before = gym_rows(panel, gym_id)
        refused = client.delete(f"/api/platform/gyms/{gym_id}")
        assert refused.status_code == 409
        assert refused.json() == {"detail": {"code": "not_suspended"}}

        assert suspend(client, gym_id).status_code == 200
        refused = client.delete(f"/api/platform/gyms/{gym_id}")
        assert refused.status_code == 409
        assert refused.json() == {"detail": {"code": "removal_unavailable", "issue": 377}}
    assert gym_rows(panel, gym_id) == before


# --- nobody else -----------------------------------------------------------------------


def call(client: TestClient, method: str, path: str) -> int:
    return int(client.request(method, path, json={"reason": "x"}).status_code)


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


def test_suspending_needs_a_live_operator_session(panel: Panel) -> None:
    nobody = b"\x00" * 32
    gym = uuid.uuid4()
    for sql in (
        "SELECT * FROM platform_suspend_gym($1, $2, 'x')",
        "SELECT * FROM platform_resume_gym($1, $2)",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="no live operator session"):
            run(panel.db.api_url, calling(sql, nobody, gym))
