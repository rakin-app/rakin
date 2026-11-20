"""The titular accepts the terms in the app before any data goes in (#499).

The texts render for the gym, every blank filled and every value escaped
(`app.legal.terms`). The gate holds a gym that never accepted to reads, whoever writes,
and the titular of one that accepted an earlier version, while the rest of its team
keeps working (`app.tenancy`, `app.permissions`). The acceptance keeps what #500 lists,
and its copy is emailed, attached, and downloads from Ajustes (`app.api.terms`).
"""

import dataclasses
import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from email import message_from_bytes
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import tenancy
from app.api import terms as terms_api
from app.legal import PROCESSOR_TERMS_VERSION, SERVICE_TERMS_VERSION
from app.legal import terms as legal
from app.main import create_app
from tests.auth import SIGNED_IN, FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import random_rut, unique_slug
from tests.pg import (
    Database,
    in_gym,
    make_staff,
    migrate,
    run,
    seed_gym,
    seeded_owner,
    throwaway_database,
)
from tests.test_join import adult
from tests.test_proofs import RecordingMailer, sent_notices

TEXTS = legal.load(make_settings())

FILLED: dict[str, Any] = {
    "legal_name": "Academia Norte SpA",
    "rut": "76.123.456-0",
    "address": "Av. Siempre Viva 123, Puerto Montt",
    "representative": "Dueña Norte",
    "breach_contacts": [
        {"name_and_role": "Ana Pérez, gerente", "email": "ana@norte.cl", "phone": "+56 9 1234 5678"}
    ],
}


def body(**changes: Any) -> dict[str, Any]:
    return {
        "service_version": SERVICE_TERMS_VERSION,
        "processor_version": PROCESSOR_TERMS_VERSION,
        "filled": FILLED,
        "accept_service": True,
        "accept_processor": True,
        **changes,
    }


# --- the texts, no database --------------------------------------------------------------


def values(**filled: str) -> dict[str, str]:
    return {"gym_name": "Norte", "slug": "norte", "legal_name": "X", "rut": "1-9", **filled}


@pytest.mark.parametrize("key", legal.KEYS)
def test_each_text_renders_with_every_blank_filled(key: str) -> None:
    text = TEXTS[key]
    every = dict.fromkeys(legal.BLANKS.values(), "valor")
    rendered = legal.render(text, every)
    # A quotation's cut stays; nothing else in brackets does.
    assert [b for b in re.findall(r"\[[^\]]*\]", rendered) if b != "[...]"] == []
    for left in ("ABOGADO", "PENDIENTE", "BORRADOR", "Firmas", "Cambios de versión"):
        assert left not in rendered, left
    assert f"Versión: {text.version}." in rendered


def test_a_blank_with_no_value_shows_its_label_where_the_page_fills_it() -> None:
    rendered = legal.render(TEXTS[legal.PROCESSOR], {"gym_name": "Norte", "slug": "norte"})
    assert (
        '<span class="legal-blank" data-blank="legal_name">[Razón social del gimnasio]</span>'
        in rendered
    )
    assert '<span class="legal-blank" data-blank="gym_name">Norte</span>' in rendered


def test_a_value_is_escaped_never_markup() -> None:
    rendered = legal.render(
        TEXTS[legal.SERVICE], values(legal_name="<script>alert(1)</script> **x**")
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt; **x**" in rendered


def test_a_blank_the_app_does_not_know_fails_the_text() -> None:
    with pytest.raises(legal.LegalTextError, match=r"\[ciudad\]"):
        legal.parse(legal.SERVICE, "**Versión: 2026-11-20.**\n\nEn [ciudad].\n")


def test_the_changes_are_split_off_each_version_its_own() -> None:
    processor = TEXTS[legal.PROCESSOR]
    assert [v for v, _ in processor.changes] == ["2026-11-20", "2026-11-19", "2026-11-18"]
    assert "## Cambios de versión" not in processor.body
    assert [v for v, _ in legal.render_changes(processor, "2026-11-18")] == [
        "2026-11-20",
        "2026-11-19",
    ]
    assert legal.render_changes(processor, PROCESSOR_TERMS_VERSION) == []
    assert len(legal.render_changes(processor, None)) == 3


def test_the_processor_checkbox_names_every_subencargado() -> None:
    names = legal.subprocessors(TEXTS[legal.PROCESSOR])
    assert names == ["Hetzner", "Cloudflare (R2)", "Resend", "Sentry", "Cloudflare (Turnstile)"]
    said = legal.declarations("Norte SpA", names)
    assert "en nombre de Norte SpA, y declaro que puedo representarla" in said[legal.SERVICE]
    for name in names:
        assert name in said[legal.PROCESSOR]


def test_the_anchors_of_both_texts_do_not_collide() -> None:
    ids = [re.findall(r' id="([^"]+)"', legal.render(TEXTS[key], values())) for key in legal.KEYS]
    assert set(ids[0]).isdisjoint(ids[1])
    assert all(i.startswith("servicio-") for i in ids[0])


# --- with Postgres ------------------------------------------------------------------------


pg = pytest.mark.postgres


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def client(db: Database, mailer: RecordingMailer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.add_middleware(FakeAuth)
    with TestClient(app, client=("203.0.113.9", 50000)) as c:
        yield c


def pending(db: Database) -> uuid.UUID:
    return seed_gym(db, unique_slug("nueva"), accepted=False)


def staff(db: Database, gym: uuid.UUID, role: str) -> uuid.UUID:
    """Someone on `gym`'s team as `role`: `admin` or `coach`."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, $2)", person, role)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name, email) VALUES ($1, $2, $3, $4)",
                gym,
                person,
                role,
                f"{role}-{person.hex[:8]}@example.cl",
            )
            await make_staff(conn, gym, person, role)

    run(db.owner_url, query)
    return person


def member(db: Database, gym: uuid.UUID) -> uuid.UUID:
    """A student of `gym`: a person with a plan there, on no team."""
    person = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym))
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'Alumna')", person)
            await conn.execute(
                "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'Alumna')",
                gym,
                person,
            )
            plan = await conn.fetchval("SELECT id FROM plan WHERE gym_id = $1", gym)
            await conn.execute(
                "INSERT INTO membership (gym_id, person_id, plan_id, status)"
                " VALUES ($1, $2, $3, 'active')",
                gym,
                person,
                plan,
            )

    run(db.owner_url, query)
    return person


def new_member() -> dict[str, Any]:
    return {"name": "Alumna Nueva", "rut": random_rut(), "no_whatsapp": True}


def role_of(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None) -> Any:
    response = client.get("/api/me/role", headers=as_gym(gym, person))
    assert response.status_code == 200, response.text
    return response.json()


def accept(client: TestClient, gym: uuid.UUID, person: uuid.UUID | None = None, **kw: Any) -> Any:
    return client.post(
        "/api/terms/accept",
        json=body(**kw),
        headers={**as_gym(gym, person), "User-Agent": "Navegador de prueba"},
    )


def accepted(client: TestClient, gym: uuid.UUID, **kw: Any) -> dict[str, Any]:
    response = accept(client, gym, **kw)
    assert response.status_code == 201, response.text
    return dict(response.json())


def code_of(response: Any) -> str:
    return str(response.json()["detail"]["code"])


# Each a write of one kind, refused before its body is read: an empty one is enough.
WRITES = (
    "/api/people",
    "/api/plans",
    "/api/staff",
    "/api/ledger/payments",
    "/api/import/members",
)


@pg
def test_a_pending_gym_takes_no_data_from_anyone(client: TestClient, db: Database) -> None:
    gym = pending(db)
    coach = staff(db, gym, "coach")
    for path in WRITES:
        response = client.post(path, json={}, headers=as_gym(gym))
        assert (response.status_code, code_of(response)) == (409, "terms_pending"), path
    refused = client.post("/api/people", json=new_member(), headers=as_gym(gym, coach))
    assert (refused.status_code, code_of(refused)) == (409, "terms_pending")
    # Reads stay open: the page loads, and a gym could still take its data.
    assert client.get("/api/people", headers=as_gym(gym)).status_code == 200
    assert client.get("/api/ledger/export", headers=as_gym(gym)).status_code != 409
    me = role_of(client, gym, coach)
    assert (me["terms"], me["titular_name"]) == ("pending", f"owner of {me['gym_name']}")


@pg
def test_a_pending_gym_refuses_sign_ups(client: TestClient, db: Database) -> None:
    gym = pending(db)
    token = "t" * 32
    run(
        db.owner_url,
        in_gym(gym, "INSERT INTO join_link (gym_id, token) VALUES ($1, $2)", gym, token),
    )
    for response in (
        client.get(f"/api/join/{token}"),
        client.post(f"/api/join/{token}", json=adult()),
    ):
        assert (response.status_code, code_of(response)) == (410, "gym_not_open")


@pg
def test_once_the_titular_accepts_the_gym_takes_data(client: TestClient, db: Database) -> None:
    gym = pending(db)
    assert role_of(client, gym)["terms"] == "pending"
    accepted(client, gym)
    assert role_of(client, gym)["terms"] == "current"
    added = client.post("/api/people", json=new_member(), headers=as_gym(gym))
    assert added.status_code == 201, added.text


@pg
def test_a_new_version_holds_back_only_the_titular(
    client: TestClient, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    gym = seed_gym(db, unique_slug("vigente"))
    admin = staff(db, gym, "admin")
    student = member(db, gym)
    monkeypatch.setattr(tenancy, "PROCESSOR_TERMS_VERSION", "2099-01-01")
    assert role_of(client, gym)["terms"] == "outdated"

    refused = client.post("/api/people", json={}, headers=as_gym(gym))
    assert (refused.status_code, code_of(refused)) == (409, "terms_outdated")
    # The titular reads, so the page loads.
    assert client.get("/api/people", headers=as_gym(gym)).status_code == 200
    # The rest of the team and the students keep working: the earlier version governs.
    added = client.post("/api/people", json=new_member(), headers=as_gym(gym, admin))
    assert added.status_code == 201, added.text
    claimed = client.post("/api/me/payments", json={}, headers=as_gym(gym, student))
    assert claimed.status_code == 422, claimed.text


@pg
def test_a_signature_from_before_is_outdated_and_an_exempt_gym_current(
    client: TestClient, db: Database
) -> None:
    meta = pending(db)
    run(
        db.owner_url,
        in_gym(
            meta,
            "INSERT INTO processor_terms (gym_id, version, signed_on)"
            " VALUES ($1, '2026-11-19', '2026-11-19')",
            meta,
        ),
    )
    assert role_of(client, meta)["terms"] == "outdated"

    hosted_elsewhere = pending(db)
    run(
        db.owner_url,
        in_gym(
            hosted_elsewhere,
            "INSERT INTO gym_terms (gym_id, exempt) VALUES ($1, true)",
            hosted_elsewhere,
        ),
    )
    assert role_of(client, hosted_elsewhere)["terms"] == "current"


@pg
def test_the_page_renders_both_texts_for_the_gym(client: TestClient, db: Database) -> None:
    gym = pending(db)
    response = client.get("/api/terms", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["state"] == "pending"
    assert [(d["key"], d["version"]) for d in page["documents"]] == [
        ("service", SERVICE_TERMS_VERSION),
        ("processor", PROCESSOR_TERMS_VERSION),
    ]
    # The app's blanks filled, the titular's left for the page; no changes for a gym
    # that accepted none.
    processor = page["documents"][1]
    assert f'data-blank="gym_name">{page["gym_name"]}<' in processor["html"]
    assert 'data-blank="legal_name">[Razón social del gimnasio]<' in processor["html"]
    assert [d["changes"] for d in page["documents"]] == [[], []]
    assert page["prefill"] == {"representative": f"owner of {page['gym_name']}"}
    assert "{legal_name}" in page["declarations"]["service"]
    assert "Hetzner" in page["declarations"]["processor"]

    accepted(client, gym)
    again = client.get("/api/terms", headers=as_gym(gym)).json()
    assert again["state"] == "current"
    assert again["prefill"]["legal_name"] == FILLED["legal_name"]


@pg
def test_an_outdated_gym_sees_what_changed_since_its_version(
    client: TestClient, db: Database
) -> None:
    gym = pending(db)
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO processor_terms (gym_id, version, signed_on)"
            " VALUES ($1, '2026-11-18', '2026-11-18')",
            gym,
        ),
    )
    page = client.get("/api/terms", headers=as_gym(gym)).json()
    assert page["state"] == "outdated"
    service, processor = page["documents"]
    assert [c["version"] for c in processor["changes"]] == ["2026-11-20", "2026-11-19"]
    # It never accepted the Términos de servicio: every version of them is new.
    assert [c["version"] for c in service["changes"]] == ["2026-11-20"]


@pg
def test_only_the_titular_reads_and_accepts(client: TestClient, db: Database) -> None:
    gym = pending(db)
    admin = staff(db, gym, "admin")
    assert client.get("/api/terms", headers=as_gym(gym, admin)).status_code == 403
    assert accept(client, gym, admin).status_code == 403
    assert client.get("/api/terms/acceptances", headers=as_gym(gym, admin)).status_code == 403
    assert role_of(client, gym)["terms"] == "pending"


@pg
def test_versions_the_page_did_not_show_are_refused(client: TestClient, db: Database) -> None:
    gym = pending(db)
    response = accept(client, gym, service_version="2026-01-01")
    assert (response.status_code, code_of(response)) == (409, "terms_changed")
    assert role_of(client, gym)["terms"] == "pending"


@pg
@pytest.mark.parametrize(
    ("filled", "loc", "kind"),
    [
        ({"rut": "76.123.456-1"}, ["body", "filled", "rut"], "value_error"),
        ({"legal_name": " "}, ["body", "filled", "legal_name"], "string_too_short"),
        ({"breach_contacts": []}, ["body", "filled", "breach_contacts"], "too_short"),
        (
            {"breach_contacts": [*FILLED["breach_contacts"], *FILLED["breach_contacts"]]},
            ["body", "filled"],
            "same_contact_email",
        ),
    ],
)
def test_what_the_texts_cannot_take_is_a_422(
    client: TestClient, db: Database, filled: dict[str, Any], loc: list[str], kind: str
) -> None:
    gym = pending(db)
    response = accept(client, gym, filled={**FILLED, **filled})
    assert response.status_code == 422, response.text
    assert [(e["loc"], e["type"]) for e in response.json()["detail"]] == [(loc, kind)]


@pg
def test_both_boxes_must_be_ticked(client: TestClient, db: Database) -> None:
    gym = pending(db)
    response = accept(client, gym, accept_processor=False)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "accept_processor"]


def acceptance_row(db: Database, gym: uuid.UUID) -> Any:
    [row] = run(
        db.admin_url,
        lambda c: c.fetch("SELECT * FROM terms_acceptance WHERE gym_id = $1", gym),
    )
    return row


@pg
def test_the_acceptance_keeps_what_proves_it(
    client: TestClient, db: Database, mailer: RecordingMailer
) -> None:
    gym = pending(db)
    run(
        db.owner_url,
        in_gym(
            gym,
            "INSERT INTO gym_terms (gym_id, invited_email) VALUES ($1, 'creada@norte.cl')",
            gym,
        ),
    )
    mailer.sent.clear()
    made = accepted(client, gym, filled={**FILLED, "legal_name": "<b>Norte</b> SpA"})
    row = acceptance_row(db, gym)

    assert (row["id"], row["channel"]) == (uuid.UUID(made["id"]), "in_app")
    assert row["person_id"] == seeded_owner(gym)
    assert (row["service_version"], row["processor_version"]) == (
        SERVICE_TERMS_VERSION,
        PROCESSOR_TERMS_VERSION,
    )
    # The hash is over exactly what is stored, and what is stored the value escaped.
    for key in ("service", "processor"):
        html = row[f"{key}_html"]
        assert bytes(row[f"{key}_sha256"]) == hashlib.sha256(html.encode()).digest()
        assert "&lt;b&gt;Norte&lt;/b&gt; SpA" in html
        assert "[" not in html.replace("[...]", "")
    assert "76.123.456-0" in row["processor_html"]
    assert "Puerto Montt" in row["processor_html"]
    # What each box said, the subencargados it named, and what was filled in, as given.
    assert row["service_declaration"].startswith("Acepto los Términos de servicio en nombre")
    assert row["subprocessors"] == legal.subprocessors(TEXTS[legal.PROCESSOR])
    assert json.loads(row["filled"])["rut"] == "76123456-0"
    # Who signed in, how, from where: on this row only.
    assert (row["session_email"], row["signed_in_at"]) == (SIGNED_IN.email, SIGNED_IN.at)
    assert (row["invited_email"], row["ip"], row["user_agent"]) == (
        "creada@norte.cl",
        "203.0.113.9",
        "Navegador de prueba",
    )
    assert row["signed_on"] is None

    # The copy went to the address that accepted, and to the contact for breaches.
    copies = [e for e in mailer.sent if "Aceptaste" in e.subject]
    assert sorted(e.to for e in copies) == sorted([SIGNED_IN.email, "ana@norte.cl"])
    [attachment] = copies[0].attachments
    assert attachment.mime_type == "text/html"
    assert attachment.filename.startswith("terminos-") and attachment.filename.endswith(".html")
    copy = attachment.content.decode()
    assert row["service_html"] in copy and row["processor_html"] in copy
    assert bytes(row["processor_sha256"]).hex() in copy
    assert "Aceptado electrónicamente" in copy
    assert dict(copies[0].headers)["Message-ID"] == row["copy_message_id"]
    assert row["copy_sent_at"] is not None
    assert sent_notices(db, gym) == [("terms_accepted", str(seeded_owner(gym)), "sent")] * 2


@pg
def test_the_copy_downloads_as_it_was_accepted(client: TestClient, db: Database) -> None:
    gym = pending(db)
    made = accepted(client, gym)
    row = acceptance_row(db, gym)
    [listed] = client.get("/api/terms/acceptances", headers=as_gym(gym)).json()
    assert (listed["id"], listed["channel"], listed["has_copy"]) == (made["id"], "in_app", True)
    assert listed["accepted_by_name"] == f"owner of {role_of(client, gym)['gym_name']}"

    response = client.get(f"/api/terms/acceptances/{made['id']}/copy", headers=as_gym(gym))
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert re.fullmatch(
        r'attachment; filename="terminos-[a-z0-9-]+-\d{4}-\d{2}-\d{2}\.html"',
        response.headers["content-disposition"],
    )
    assert row["service_html"] in response.text and row["processor_html"] in response.text

    missing = client.get(f"/api/terms/acceptances/{uuid.uuid4()}/copy", headers=as_gym(gym))
    assert missing.status_code == 404


@pg
def test_an_acceptance_outside_the_app_has_no_copy_here(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, unique_slug("papel"))
    [listed] = client.get("/api/terms/acceptances", headers=as_gym(gym)).json()
    assert (listed["channel"], listed["has_copy"]) == ("outside", False)
    response = client.get(f"/api/terms/acceptances/{listed['id']}/copy", headers=as_gym(gym))
    assert response.status_code == 404


def test_the_copy_email_carries_the_file_over_smtp() -> None:
    """The SMTP mailer attaches it as a part of its own, with its name."""
    from app.integrations.mailer import Attachment, Email, SmtpMailer

    sent: list[bytes] = []
    mailer = SmtpMailer(host="localhost", port=25, sender="no-reply@rakin.app", security="none")
    mailer._send = lambda message: sent.append(message.as_bytes())  # type: ignore[method-assign]
    email = Email(
        to="ana@norte.cl",
        subject="Copia",
        text="Va adjunta.",
        attachments=(Attachment("terminos-norte.html", b"<p>texto</p>", "text/html"),),
    )
    import asyncio

    asyncio.run(mailer.send(email))
    [raw] = sent
    parts = [p for p in message_from_bytes(raw).walk() if p.get_filename()]
    assert [(p.get_filename(), p.get_content_type()) for p in parts] == [
        ("terminos-norte.html", "text/html")
    ]
    assert parts[0].get_payload(decode=True) == b"<p>texto</p>"


def test_the_terms_endpoints_name_the_titular_as_their_gate() -> None:
    from app.permissions import GATES, TITULAR, terms_session

    assert GATES[terms_session] == TITULAR
    assert terms_api.router.prefix == "/api/terms"
