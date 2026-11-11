"""The join link (#154): the gym's link, the public form, and the queue staff approve.

Nothing the public form answers may say whether a phone, RUT or email is already
someone's, here or in another gym; the queue, which is staff's, does say so for this
gym.
"""

import dataclasses
import itertools
import random
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.join import JoinLimits
from app.domain.dates import start_of_local_day
from app.domain.rut import check_digit, format_rut
from app.jobs import join_requests
from app.magiclink.ratelimit import MemoryRateLimiter
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import (
    DEFAULT_TIMEZONE,
    Database,
    in_gym,
    migrate,
    run,
    seed_gym,
    seeded_today,
    throwaway_database,
)
from tests.test_guardians import add_person
from tests.test_gym_settings import PRIVACY
from tests.test_memberships import PLANS, add_staff
from tests.test_people import new_phone
from tests.test_proofs import RecordingMailer, sent_notices

pytestmark = pytest.mark.postgres

ROOMY = 1_000_000


def roomy_limits() -> JoinLimits:
    """Limits no test reaches unless it means to."""
    return JoinLimits(
        per_ip=MemoryRateLimiter(limit=ROOMY, window_seconds=3600),
        per_link=MemoryRateLimiter(limit=ROOMY, window_seconds=3600),
    )


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture(scope="module")
def app(db: Database, mailer: RecordingMailer) -> FastAPI:
    app = create_app(
        make_settings(
            database_url=db.api_url, public_base_url="https://rakin.cl", base_domain="rakin.cl"
        )
    )
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=mailer)
    app.state.join_limits = roomy_limits()
    app.add_middleware(FakeAuth)
    return app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def with_privacy(client: TestClient, gym: uuid.UUID) -> uuid.UUID:
    """`gym`, with the privacy details its join link needs (#168)."""
    response = client.patch("/api/gym/settings", json={"privacy": PRIVACY}, headers=as_gym(gym))
    assert response.status_code == 200, response.text
    return gym


@pytest.fixture
def gym(db: Database, client: TestClient) -> uuid.UUID:
    return with_privacy(client, seed_gym(db, f"academia-{uuid.uuid4().hex[:6]}"))


_ruts = itertools.count(random.randrange(10_000_000, 20_000_000, 10_000))


def new_rut() -> str:
    body = next(_ruts)
    return f"{body}-{check_digit(body)}"


ADULT_DOB = "1990-05-20"


def minor_dob() -> str:
    return (seeded_today() - timedelta(days=365 * 10)).isoformat()


def adult(**fields: Any) -> dict[str, Any]:
    return {
        "first_name": "Ana",
        "last_name": "Pérez",
        "rut": new_rut(),
        "phone": new_phone(),
        "email": "ana@example.cl",
        "dob": ADULT_DOB,
        "consent": True,
        **fields,
    }


def minor(**fields: Any) -> dict[str, Any]:
    return {
        "first_name": "Juan",
        "last_name": "Pérez",
        "rut": new_rut(),
        "dob": minor_dob(),
        "guardian_name": "Marta Pérez",
        "guardian_phone": new_phone(),
        "guardian_email": "marta@example.cl",
        "consent": True,
        **fields,
    }


def generate(client: TestClient, gym: uuid.UUID, **options: Any) -> dict[str, Any]:
    response = client.post("/api/join-link", json=options, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    link: dict[str, Any] = response.json()
    return link


def token_of(client: TestClient, gym: uuid.UUID, **options: Any) -> str:
    return str(generate(client, gym, **options)["token"])


def submit(client: TestClient, token: str, body: dict[str, Any]) -> Any:
    return client.post(f"/api/join/{token}", json=body)


def submitted(client: TestClient, token: str, body: dict[str, Any]) -> None:
    response = submit(client, token, body)
    assert response.status_code == 202, response.text


def queue(client: TestClient, gym: uuid.UUID, by: uuid.UUID | None = None) -> list[dict[str, Any]]:
    response = client.get("/api/join-requests", headers=as_gym(gym, by))
    assert response.status_code == 200, response.text
    requests: list[dict[str, Any]] = response.json()["items"]
    return requests


def one_request(client: TestClient, gym: uuid.UUID, token: str, body: dict[str, Any]) -> str:
    submitted(client, token, body)
    [request] = queue(client, gym)
    return str(request["id"])


def approve(
    client: TestClient, gym: uuid.UUID, request_id: str, by: uuid.UUID | None = None, **body: Any
) -> Any:
    return client.post(
        f"/api/join-requests/{request_id}/approve", json=body, headers=as_gym(gym, by)
    )


def approved(client: TestClient, gym: uuid.UUID, request_id: str, **body: Any) -> dict[str, Any]:
    response = approve(client, gym, request_id, **body)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def record(db: Database, gym: uuid.UUID, person_id: str) -> dict[str, Any]:
    rows = run(
        db.admin_url,
        lambda c: c.fetch(
            "SELECT gp.name, gp.email, gp.rut, gp.dob, gp.phone, gp.no_whatsapp FROM gym_person gp"
            " WHERE gp.gym_id = $1 AND gp.person_id = $2",
            gym,
            uuid.UUID(person_id),
        ),
    )
    [row] = rows
    return dict(row)


def guardian_of(db: Database, gym: uuid.UUID, person_id: str) -> uuid.UUID | None:
    found: uuid.UUID | None = run(
        db.admin_url,
        lambda c: c.fetchval(
            "SELECT guardian_person_id FROM guardian_link"
            " WHERE gym_id = $1 AND dependent_person_id = $2",
            gym,
            uuid.UUID(person_id),
        ),
    )
    return found


def plan(client: TestClient, gym: uuid.UUID, key: str = "signup") -> str:
    response = client.post("/api/plans", json=PLANS[key], headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def program(client: TestClient, gym: uuid.UUID, name: str = "Kids") -> str:
    response = client.post("/api/programs", json={"name": name}, headers=as_gym(gym))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# --- the link -------------------------------------------------------------------------


def test_generating_a_link_gives_a_url_to_the_form_on_the_gyms_host(
    client: TestClient, gym: uuid.UUID
) -> None:
    link = generate(client, gym)

    slug = run_gym_slug(client, gym)
    assert link["url"] == f"https://{slug}.rakin.cl/unirse/{link['token']}"
    assert len(link["token"]) >= 20
    assert (link["program_id"], link["expires_on"], link["expired"]) == (None, None, False)
    again = client.get("/api/join-link", headers=as_gym(gym))
    assert again.status_code == 200
    assert again.json()["token"] == link["token"]


def test_no_link_until_the_privacy_details_are_set(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, f"sin-datos-{uuid.uuid4().hex[:6]}")

    refused = client.post("/api/join-link", json={}, headers=as_gym(gym))

    assert (refused.status_code, refused.json()) == (409, {"detail": "privacy_incomplete"})
    assert client.get("/api/join-link", headers=as_gym(gym)).status_code == 404
    generate(client, with_privacy(client, gym))


def test_a_link_without_privacy_details_does_not_work(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    token = token_of(client, gym)

    # A link made before the details were asked for.
    async def forget(conn: asyncpg.Connection) -> None:
        await conn.execute("UPDATE gym SET settings = settings - 'privacy' WHERE id = $1", gym)

    run(db.admin_url, forget)

    gone = client.get(f"/api/join/{token}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "invalid_link"})
    assert submit(client, token, adult()).status_code == 404
    assert client.get("/api/join-link", headers=as_gym(gym)).status_code == 200


def test_a_gym_without_a_link_has_none(client: TestClient, gym: uuid.UUID) -> None:
    assert client.get("/api/join-link", headers=as_gym(gym)).status_code == 404


def test_regenerating_retires_the_old_token(client: TestClient, gym: uuid.UUID) -> None:
    old = token_of(client, gym)
    new = token_of(client, gym)

    assert new != old
    gone = client.get(f"/api/join/{old}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "invalid_link"})
    assert submit(client, old, adult()).status_code == 404
    assert client.get(f"/api/join/{new}").status_code == 200


def test_revoking_retires_the_link(client: TestClient, gym: uuid.UUID) -> None:
    token = token_of(client, gym)

    assert client.delete("/api/join-link", headers=as_gym(gym)).status_code == 204

    assert client.get("/api/join-link", headers=as_gym(gym)).status_code == 404
    assert client.get(f"/api/join/{token}").status_code == 404
    assert submit(client, token, adult()).status_code == 404


@pytest.mark.parametrize("token", ["x" * 32, "corto", "x" * 300])
def test_an_unknown_or_malformed_token_is_an_invalid_link(client: TestClient, token: str) -> None:
    gone = client.get(f"/api/join/{token}")
    assert (gone.status_code, gone.json()) == (404, {"detail": "invalid_link"})
    sent = submit(client, token, adult())
    assert (sent.status_code, sent.json()) == (404, {"detail": "invalid_link"})


def test_a_truncated_link_is_an_invalid_link(client: TestClient, gym: uuid.UUID) -> None:
    token = token_of(client, gym)

    assert client.get(f"/api/join/{token[:12]}").status_code == 404
    assert client.get(f"/api/join/{token[:-1]}").status_code == 404


def test_a_link_works_through_its_last_day(client: TestClient, gym: uuid.UUID) -> None:
    today = seeded_today()
    token = token_of(client, gym, expires_on=today.isoformat())
    assert client.get(f"/api/join/{token}").status_code == 200

    changed = client.patch(
        "/api/join-link",
        json={"expires_on": (today - timedelta(days=1)).isoformat()},
        headers=as_gym(gym),
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["token"] == token
    assert changed.json()["expired"] is True
    assert client.get(f"/api/join/{token}").status_code == 404
    assert submit(client, token, adult()).status_code == 404
    cleared = client.patch("/api/join-link", json={"expires_on": None}, headers=as_gym(gym))
    assert cleared.json()["expired"] is False
    assert client.get(f"/api/join/{token}").status_code == 200


def test_a_link_may_pre_select_a_program(client: TestClient, gym: uuid.UUID) -> None:
    kids = program(client, gym, "Kids")
    link = generate(client, gym, program_id=kids)
    assert (link["program_id"], link["program_name"]) == (kids, "Kids")

    form = client.get(f"/api/join/{link['token']}")
    assert form.json()["program"] == "Kids"
    submitted(client, link["token"], adult())
    [request] = queue(client, gym)
    assert (request["program_id"], request["program_name"]) == (kids, "Kids")


def test_a_link_refuses_another_gyms_program(
    client: TestClient, gym: uuid.UUID, db: Database
) -> None:
    other = program(client, seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}"))

    response = client.post("/api/join-link", json={"program_id": other}, headers=as_gym(gym))

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "unknown_program"


def test_only_owner_and_admin_manage_the_link(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    coach = add_staff(db, gym, "coach")
    admin = add_staff(db, gym, "admin")
    coach_gym = as_gym(gym, coach)

    assert client.post("/api/join-link", json={}, headers=coach_gym).status_code == 403
    assert client.get("/api/join-link", headers=coach_gym).status_code == 403
    assert client.delete("/api/join-link", headers=coach_gym).status_code == 403
    assert client.post("/api/join-link", json={}, headers=as_gym(gym, admin)).status_code == 201


# --- the form -------------------------------------------------------------------------


def test_the_form_shows_the_gym_and_its_today(client: TestClient, gym: uuid.UUID) -> None:
    form = client.get(f"/api/join/{token_of(client, gym)}")

    assert form.status_code == 200
    assert form.json() == {
        "gym": run_gym_name(client, gym),
        "program": None,
        "today": seeded_today().isoformat(),
        "human_check_site_key": None,
    }


def run_gym_slug(client: TestClient, gym: uuid.UUID) -> str:
    response = client.get("/api/gym/settings", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    slug: str = response.json()["slug"]
    return slug


def run_gym_name(client: TestClient, gym: uuid.UUID) -> str:
    response = client.get("/api/gym/settings", headers=as_gym(gym))
    assert response.status_code == 200, response.text
    name: str = response.json()["name"]
    return name


def test_an_adult_leaves_a_request_not_a_member(client: TestClient, gym: uuid.UUID) -> None:
    token = token_of(client, gym)
    body = adult(phone="9 8765 4321", rut="7.654.321-6", first_name=" Ana ")
    members = client.get("/api/people", headers=as_gym(gym)).json()["total"]

    response = submit(client, token, body)

    assert (response.status_code, response.content) == (202, b"")
    [request] = queue(client, gym)
    assert request["first_name"] == "Ana"
    assert (request["phone"], request["rut"]) == ("+56987654321", "7654321-6")
    assert (request["dob"], request["guardian"]) == (ADULT_DOB, None)
    assert client.get("/api/people", headers=as_gym(gym)).json()["total"] == members


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rut", "7.654.321-5"),  # the check digit is 6
        ("phone", "2 2345 6789"),  # a landline
        ("email", "ana.example.cl"),
        ("dob", "2999-01-01"),
        ("consent", False),
        ("first_name", " "),
    ],
)
def test_the_form_refuses(client: TestClient, gym: uuid.UUID, field: str, value: Any) -> None:
    response = submit(client, token_of(client, gym), adult(**{field: value}))

    assert response.status_code == 422
    assert [e["loc"] for e in response.json()["detail"]] == [["body", field]]
    assert queue(client, gym) == []


@pytest.mark.parametrize("field", ["phone", "email"])
def test_an_adult_gives_their_phone_and_email(
    client: TestClient, gym: uuid.UUID, field: str
) -> None:
    body = adult()
    del body[field]

    response = submit(client, token_of(client, gym), body)

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["body", field], "msg": "Field required"}
    ]


def test_an_adult_with_no_whatsapp_may_leave_out_the_phone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    body = adult(no_whatsapp=True, rut=None, email=f"{uuid.uuid4().hex[:8]}@example.cl")
    del body["phone"]

    request = one_request(client, gym, token_of(client, gym), body)
    [queued] = queue(client, gym)
    assert (queued["phone"], queued["rut"], queued["no_whatsapp"]) == (None, None, True)

    answer = approved(client, gym, request)
    kept = record(db, gym, answer["person_id"])
    assert (kept["phone"], kept["rut"], kept["no_whatsapp"]) == (None, None, True)


def test_a_minors_guardian_with_no_whatsapp_may_leave_out_their_phone(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    body = minor(no_whatsapp=True, guardian_email=f"{uuid.uuid4().hex[:8]}@example.cl")
    del body["guardian_phone"]

    answer = approved(client, gym, one_request(client, gym, token_of(client, gym), body))

    guardian = guardian_of(db, gym, answer["person_id"])
    assert guardian is not None
    assert (
        record(db, gym, str(guardian))["phone"],
        record(db, gym, str(guardian))["no_whatsapp"],
    ) == (None, True)
    # The box is the guardian's: the kid's own record is left as it is.
    assert record(db, gym, answer["person_id"])["no_whatsapp"] is False


def test_a_minor_needs_a_guardian(client: TestClient, gym: uuid.UUID) -> None:
    body = minor()
    for field in ("guardian_name", "guardian_phone", "guardian_email"):
        del body[field]

    response = submit(client, token_of(client, gym), body)

    assert response.status_code == 422
    assert [(e["loc"][1], e["type"]) for e in response.json()["detail"]] == [
        ("guardian_name", "missing"),
        ("guardian_phone", "missing"),
        ("guardian_email", "missing"),
    ]


def test_a_minor_is_under_eighteen_on_the_gyms_today(client: TestClient, gym: uuid.UUID) -> None:
    today = seeded_today()
    turning = date(today.year - 18, today.month, min(today.day, 28))
    body = adult(dob=turning.isoformat())

    # Eighteen today or earlier this month: an adult, with no guardian asked.
    submitted(client, token_of(client, gym), body)


def test_a_minor_with_a_guardian_is_queued(client: TestClient, gym: uuid.UUID) -> None:
    token = token_of(client, gym)
    body = minor()
    # A child given their parent's phone has none of their own.
    body["phone"] = body["guardian_phone"]

    submitted(client, token, body)

    [request] = queue(client, gym)
    assert request["phone"] is None
    assert request["guardian"] == {
        "name": "Marta Pérez",
        "phone": body["guardian_phone"],
        "email": "marta@example.cl",
    }


def test_an_adults_guardian_fields_are_ignored(client: TestClient, gym: uuid.UUID) -> None:
    body = adult(guardian_name="Alguien", guardian_phone=new_phone(), guardian_email="a@b.cl")

    submitted(client, token_of(client, gym), body)

    assert queue(client, gym)[0]["guardian"] is None


def test_the_honeypot_answers_like_a_submission_and_stores_nothing(
    client: TestClient, gym: uuid.UUID
) -> None:
    response = submit(client, token_of(client, gym), adult(website="https://spam.example"))

    assert (response.status_code, response.content) == (202, b"")
    assert queue(client, gym) == []


@pytest.fixture
def tight(app: FastAPI) -> Iterator[None]:
    app.state.join_limits = JoinLimits(
        per_ip=MemoryRateLimiter(limit=3, window_seconds=3600),
        per_link=MemoryRateLimiter(limit=ROOMY, window_seconds=3600),
    )
    yield
    app.state.join_limits = roomy_limits()


@pytest.mark.usefixtures("tight")
def test_sending_is_rate_limited_per_ip(client: TestClient, gym: uuid.UUID, db: Database) -> None:
    token = token_of(client, gym)
    for _ in range(3):
        submitted(client, token, adult())

    refused = submit(client, token, adult())

    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    assert len(queue(client, gym)) == 3
    # Per IP, whichever link it is for: another gym's too.
    elsewhere = with_privacy(client, seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}"))
    assert submit(client, token_of(client, elsewhere), adult()).status_code == 429


@pytest.mark.usefixtures("tight")
def test_only_a_submission_that_would_be_stored_spends_the_limit(
    client: TestClient, gym: uuid.UUID
) -> None:
    token = token_of(client, gym)
    body = minor()
    del body["guardian_email"]
    for _ in range(5):
        assert submit(client, "inventado-" + "x" * 20, adult()).status_code == 404
        assert submit(client, token, body).status_code == 422

    for _ in range(3):
        submitted(client, token, adult())
    assert submit(client, token, adult()).status_code == 429


@pytest.mark.usefixtures("tight")
def test_the_limit_is_per_forwarded_client_address(
    app: FastAPI, gym: uuid.UUID, db: Database
) -> None:
    """Behind Caddy, uvicorn takes the client's address from X-Forwarded-For
    (`FORWARDED_ALLOW_IPS`); the limit is that address's, not the proxy's."""
    proxied = ProxyHeadersMiddleware(app, trusted_hosts="*")  # type: ignore[arg-type]
    with TestClient(proxied) as through_caddy:  # type: ignore[arg-type]
        token = token_of(through_caddy, gym)
        ana = {"X-Forwarded-For": "203.0.113.7"}
        for _ in range(3):
            assert (
                through_caddy.post(f"/api/join/{token}", json=adult(), headers=ana).status_code
                == 202
            )
        assert (
            through_caddy.post(f"/api/join/{token}", json=adult(), headers=ana).status_code == 429
        )

        beto = {"X-Forwarded-For": "198.51.100.4"}
        assert (
            through_caddy.post(f"/api/join/{token}", json=adult(), headers=beto).status_code == 202
        )


def test_sending_is_rate_limited_per_link(app: FastAPI, client: TestClient, gym: uuid.UUID) -> None:
    app.state.join_limits = JoinLimits(
        per_ip=MemoryRateLimiter(limit=ROOMY, window_seconds=3600),
        per_link=MemoryRateLimiter(limit=2, window_seconds=3600),
    )
    try:
        token = token_of(client, gym)
        submitted(client, token, adult())
        submitted(client, token, adult())

        assert submit(client, token, adult()).status_code == 429
        # The honeypot counts too, so a script cannot tell it apart by the limit.
        assert submit(client, token, adult(website="x")).status_code == 429
        assert submit(client, token_of(client, gym), adult()).status_code == 202
    finally:
        app.state.join_limits = roomy_limits()


@dataclasses.dataclass
class FakeHumanCheck:
    passes: str
    site_key: str | None = "site-key"
    seen: list[tuple[str | None, str | None]] = dataclasses.field(default_factory=list)

    async def verify(self, token: str | None, ip: str | None) -> bool:
        self.seen.append((token, ip))
        return token == self.passes


def test_a_human_check_must_pass(app: FastAPI, client: TestClient, gym: uuid.UUID) -> None:
    check = FakeHumanCheck(passes="ok")
    integrations = app.state.integrations
    app.state.integrations = dataclasses.replace(integrations, human_check=check)
    try:
        token = token_of(client, gym)
        assert client.get(f"/api/join/{token}").json()["human_check_site_key"] == "site-key"

        refused = submit(client, token, adult(human_check_token="bad"))
        assert (refused.status_code, refused.json()) == (400, {"detail": "human_check_failed"})
        assert submit(client, token, adult()).status_code == 400
        assert queue(client, gym) == []

        submitted(client, token, adult(human_check_token="ok"))
        assert check.seen[-1] == ("ok", "testclient")
        assert len(queue(client, gym)) == 1

        # Neither a made-up link nor a form the API refuses spends a check.
        seen = len(check.seen)
        assert (
            submit(client, "inventado-" + "x" * 20, adult(human_check_token="ok")).status_code
            == 404
        )
        assert submit(client, token, adult(phone=None, human_check_token="ok")).status_code == 422
        assert len(check.seen) == seen
    finally:
        app.state.integrations = integrations


def test_nothing_in_the_answers_says_who_is_known(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    """A phone, RUT and email this gym has, another gym has, or nobody has: the form
    answers the same."""
    here = adult()
    add_person(client, gym, "Ana Pérez", phone=here["phone"])
    elsewhere = adult()
    add_person(client, seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}"), "Ana", elsewhere["phone"])
    token = token_of(client, gym)

    answers = [submit(client, token, body) for body in (here, elsewhere, adult())]

    assert {(a.status_code, a.content, a.headers.get("content-type")) for a in answers} == {
        (202, b"", None)
    }


# --- the queue ------------------------------------------------------------------------


def test_the_queue_warns_of_a_rut_or_email_already_in_this_gym(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    token = token_of(client, gym)
    phone = new_phone()
    add_person(client, gym, "Ana Antigua", phone=phone)  # ana.antigua@example.cl
    rut = new_rut()
    beto = add_person(client, gym, "Beto")
    client.patch(f"/api/people/{beto}", json={"rut": rut}, headers=as_gym(gym))
    sin_rut = client.post(
        "/api/people",
        json={"name": "Carla", "email": "carla@example.cl"},
        headers=as_gym(gym),
    ).json()["id"]
    # Known to another gym only: this gym's queue says nothing of it.
    other_rut = new_rut()
    add_person(client, seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}"), "Ana", rut=other_rut)

    submitted(client, token, adult(phone=phone))
    submitted(client, token, adult(rut=format_rut(rut)))
    submitted(client, token, adult(rut=None, email="CARLA@example.cl"))
    submitted(client, token, adult(rut=other_rut))
    # A RUT given, the email finds nobody: the RUT says who they are.
    submitted(client, token, adult(email="carla@example.cl"))

    by_phone, by_rut, by_email, unknown, email_with_rut = queue(client, gym)
    # A phone finds nobody.
    assert (by_phone["rut_in_gym"], by_phone["email_in_gym"]) == (None, None)
    assert by_rut["rut_in_gym"] == {"id": beto, "name": "Beto"}
    assert (by_email["rut_in_gym"], by_email["email_in_gym"]) == (
        None,
        {"id": sin_rut, "name": "Carla"},
    )
    assert (unknown["rut_in_gym"], unknown["email_in_gym"]) == (None, None)
    assert email_with_rut["email_in_gym"] is None


def test_the_queue_says_which_emails_approving_leaves_unused(
    client: TestClient, gym: uuid.UUID
) -> None:
    token = token_of(client, gym)
    rut = new_rut()
    add_person(client, gym, "Ana Antigua", rut=rut)  # ana.antigua@example.cl
    submitted(client, token, adult(rut=rut, email="ana.nueva@example.cl"))
    submitted(client, token, adult(rut=rut, email="ANA.ANTIGUA@example.cl"))
    submitted(client, token, adult())

    new_email, same_email, unknown = queue(client, gym)
    assert new_email["ignored_email"] == "ana.nueva@example.cl"
    assert same_email["ignored_email"] is None
    assert unknown["ignored_email"] is None


def test_the_queue_comes_a_page_at_a_time(client: TestClient, gym: uuid.UUID) -> None:
    token = token_of(client, gym)
    for name in ("Primera", "Segunda", "Tercera"):
        submitted(client, token, adult(first_name=name))

    page = client.get("/api/join-requests?limit=2&offset=1", headers=as_gym(gym)).json()

    assert page["total"] == 3
    assert [r["first_name"] for r in page["items"]] == ["Segunda", "Tercera"]


def test_coaches_see_the_queue_and_members_do_not(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    submitted(client, token_of(client, gym), adult())
    coach = add_staff(db, gym, "coach")
    member = uuid.UUID(add_person(client, gym, "Socio"))

    assert len(queue(client, gym, coach)) == 1
    assert client.get("/api/join-requests", headers=as_gym(gym, member)).status_code == 403


def test_another_gyms_requests_are_not_here(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    other = with_privacy(client, seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}"))
    theirs = one_request(client, other, token_of(client, other), adult())

    assert queue(client, gym) == []
    assert approve(client, gym, theirs).status_code == 404
    assert client.delete(f"/api/join-requests/{theirs}", headers=as_gym(gym)).status_code == 404
    assert len(queue(client, other)) == 1


def test_approving_adds_a_new_person_and_tells_them(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    body = adult(email=f"{uuid.uuid4().hex[:8]}@example.cl")
    request = one_request(client, gym, token_of(client, gym), body)
    mailer.sent.clear()

    answer = approved(client, gym, request)

    assert answer["membership_id"] is None
    assert record(db, gym, answer["person_id"]) == {
        "name": "Ana Pérez",
        "email": body["email"],
        "rut": body["rut"],
        "dob": date.fromisoformat(ADULT_DOB),
        "phone": body["phone"],
        "no_whatsapp": False,
    }
    assert queue(client, gym) == []
    # "Sin plan": in the list with no membership.
    [row] = [
        r
        for r in client.get("/api/people", headers=as_gym(gym)).json()["items"]
        if r["id"] == answer["person_id"]
    ]
    assert row["membership"] is None
    [email] = mailer.sent
    assert email.to == body["email"]
    assert email.subject.endswith("aprobó tu inscripción")
    assert "Tu inscripción quedó aprobada." in email.text
    assert "/api/auth/callback" not in email.text
    assert sent_notices(db, gym)[-1] == ("join_approved", answer["person_id"], "sent")


def test_approving_someone_another_gym_knows_attaches_that_person(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rut = new_rut()
    other = seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}")
    known = add_person(client, other, "Ana Otra", rut=rut)
    body = adult(rut=rut, email="ana.aqui@example.cl")
    request = one_request(client, gym, token_of(client, gym), body)

    answer = approved(client, gym, request)

    assert answer["person_id"] == known
    # This gym's record is what the form said; the other gym's is untouched.
    assert record(db, gym, known)["name"] == "Ana Pérez"
    assert record(db, gym, known)["email"] == "ana.aqui@example.cl"
    assert record(db, other, known)["name"] == "Ana Otra"
    assert record(db, other, known)["email"] == "ana.otra@example.cl"


def test_approving_someone_already_here_keeps_their_record(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    rut = new_rut()
    ana = add_person(client, gym, "Ana Antigua", rut=rut)
    request = one_request(client, gym, token_of(client, gym), adult(rut=rut))

    answer = approved(client, gym, request)

    assert answer["person_id"] == ana
    assert record(db, gym, ana)["name"] == "Ana Antigua"
    assert record(db, gym, ana)["email"] == "ana.antigua@example.cl"
    assert queue(client, gym) == []


def test_approving_refuses_an_email_someone_with_another_rut_has(
    client: TestClient, gym: uuid.UUID
) -> None:
    address = f"{uuid.uuid4().hex[:8]}@example.cl"
    client.post(
        "/api/people",
        json={"name": "Otra", "rut": new_rut(), "email": address},
        headers=as_gym(gym),
    )
    request = one_request(client, gym, token_of(client, gym), adult(email=address))

    refused = approve(client, gym, request)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "email_in_gym", "field": "email"}
    assert len(queue(client, gym)) == 1


def test_a_member_already_here_is_linked_and_never_given_a_second_plan(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mensual = plan(client, gym)
    rut = new_rut()
    ana = add_person(client, gym, "Ana Antigua", rut=rut)
    started = client.post(
        "/api/memberships", json={"person_id": ana, "plan_id": mensual}, headers=as_gym(gym)
    )
    assert started.status_code == 201, started.text
    request = one_request(client, gym, token_of(client, gym), adult(rut=rut))
    mailer.sent.clear()

    refused = approve(client, gym, request, plan_id=mensual)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {"code": "has_membership", "field": "plan_id"}
    assert len(queue(client, gym)) == 1

    answer = approved(client, gym, request)
    assert (answer["person_id"], answer["membership_id"]) == (ana, None)
    memberships = client.get(f"/api/memberships?person_id={ana}", headers=as_gym(gym)).json()
    assert len(memberships) == 1
    assert mailer.sent == []
    assert queue(client, gym) == []


def test_approving_a_minor_adds_them_with_their_guardian(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    body = minor()
    request = one_request(client, gym, token_of(client, gym), body)
    mailer.sent.clear()

    answer = approved(client, gym, request)

    juan = record(db, gym, answer["person_id"])
    assert (juan["name"], juan["phone"]) == ("Juan Pérez", None)
    guardian = guardian_of(db, gym, answer["person_id"])
    assert guardian is not None
    marta = record(db, gym, str(guardian))
    assert (marta["name"], marta["phone"], marta["email"]) == (
        "Marta Pérez",
        body["guardian_phone"],
        "marta@example.cl",
    )
    [email] = mailer.sent
    assert email.to == "marta@example.cl"
    assert "Hola, Marta Pérez:" in email.text
    assert "La inscripción de Juan Pérez quedó aprobada." in email.text


def test_a_minors_guardian_already_here_is_linked(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    marta = add_person(client, gym, "Marta")  # marta@example.cl
    token = token_of(client, gym)
    # Found by their email, whatever phone the form gives.
    first = approved(client, gym, one_request(client, gym, token, minor()))
    second = approved(
        client,
        gym,
        one_request(
            client, gym, token, minor(first_name="Sofía", guardian_email="MARTA@example.cl")
        ),
    )

    assert guardian_of(db, gym, first["person_id"]) == uuid.UUID(marta)
    assert guardian_of(db, gym, second["person_id"]) == uuid.UUID(marta)
    assert record(db, gym, marta)["email"] == "marta@example.cl"


def test_owner_and_admin_approve_with_a_plan(
    client: TestClient, db: Database, gym: uuid.UUID, mailer: RecordingMailer
) -> None:
    mensual = plan(client, gym)
    admin = add_staff(db, gym, "admin")
    body = adult(email=f"{uuid.uuid4().hex[:8]}@example.cl")
    request = one_request(client, gym, token_of(client, gym), body)
    mailer.sent.clear()

    response = approve(client, gym, request, by=admin, plan_id=mensual)

    assert response.status_code == 200, response.text
    answer = response.json()
    membership = client.get(f"/api/memberships/{answer['membership_id']}", headers=as_gym(gym))
    assert membership.json()["person_id"] == answer["person_id"]
    assert membership.json()["plan_id"] == mensual
    assert membership.json()["started_on"] == seeded_today().isoformat()
    [email] = mailer.sent
    assert email.to == body["email"]
    assert "en el plan Mensual quedó lista" in email.text
    assert "/api/auth/callback?token=" in email.text
    assert sent_notices(db, gym)[-1] == ("welcome", answer["person_id"], "sent")


def test_a_coach_approves_but_does_not_give_a_plan(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    mensual = plan(client, gym)
    coach = add_staff(db, gym, "coach")
    request = one_request(client, gym, token_of(client, gym), adult())

    refused = approve(client, gym, request, by=coach, plan_id=mensual)
    assert refused.status_code == 403
    assert len(queue(client, gym)) == 1

    answer = approve(client, gym, request, by=coach)
    assert answer.status_code == 200, answer.text
    assert answer.json()["membership_id"] is None


def test_approving_with_a_deactivated_plan_writes_nothing(
    client: TestClient, gym: uuid.UUID
) -> None:
    mensual = plan(client, gym)
    client.patch(f"/api/plans/{mensual}", json={"active": False}, headers=as_gym(gym))
    request = one_request(client, gym, token_of(client, gym), adult())
    people = client.get("/api/people", headers=as_gym(gym)).json()["total"]

    assert approve(client, gym, request, plan_id=mensual).status_code == 422

    assert len(queue(client, gym)) == 1
    assert client.get("/api/people", headers=as_gym(gym)).json()["total"] == people


def test_a_request_is_approved_once(client: TestClient, gym: uuid.UUID) -> None:
    request = one_request(client, gym, token_of(client, gym), adult())
    approved(client, gym, request)

    assert approve(client, gym, request).status_code == 404


def test_rejecting_deletes_the_request(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    request = one_request(client, gym, token_of(client, gym), adult())

    assert client.delete(f"/api/join-requests/{request}", headers=as_gym(gym)).status_code == 204

    assert queue(client, gym) == []
    rows = run(
        db.admin_url, lambda c: c.fetch("SELECT id FROM join_request WHERE gym_id = $1", gym)
    )
    assert rows == []
    assert client.delete(f"/api/join-requests/{request}", headers=as_gym(gym)).status_code == 404


# --- the nightly job ------------------------------------------------------------------


def test_requests_left_for_30_days_are_deleted(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    token = token_of(client, gym)
    submitted(client, token, adult(first_name="Vieja"))
    submitted(client, token, adult(first_name="Reciente"))
    day = seeded_today()
    old = start_of_day(day - timedelta(days=31))
    edge = start_of_day(day - timedelta(days=30))
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE join_request SET created_at = CASE first_name"
            " WHEN 'Vieja' THEN $2::timestamptz ELSE $3::timestamptz END WHERE gym_id = $1",
            gym,
            old,
            edge,
        ),
    )

    async def job(conn: asyncpg.Connection) -> bool:
        async with conn.transaction():
            return await join_requests.delete_stale(conn, day)

    assert run(db.owner_url, job) is True

    assert [r["first_name"] for r in queue(client, gym)] == ["Reciente"]


def start_of_day(day: date) -> datetime:
    return start_of_local_day(day, DEFAULT_TIMEZONE)


def test_the_tables_are_this_gyms(client: TestClient, db: Database, gym: uuid.UUID) -> None:
    submitted(client, token_of(client, gym), adult())
    other = seed_gym(db, f"otra-{uuid.uuid4().hex[:6]}")

    seen = run(db.api_url, in_gym(other, "SELECT * FROM join_request"))
    links = run(db.api_url, in_gym(other, "SELECT * FROM join_link"))

    assert (seen, links) == ([], [])


def test_a_request_queued_before_0036_with_the_guardians_email_is_approved(
    client: TestClient, db: Database, gym: uuid.UUID
) -> None:
    # As 0031's form left one: a minor's own email and phone, the guardian's.
    phone = new_phone()
    request = run(
        db.admin_url,
        lambda c: c.fetchval(
            "INSERT INTO join_request (gym_id, first_name, last_name, rut, phone, email, dob,"
            " guardian_name, guardian_phone, guardian_email, consented_at)"
            " VALUES ($1, 'Juan', 'Pérez', $2, $3, 'marta.vieja@example.cl', $4, 'Marta Pérez',"
            " $3, 'marta.vieja@example.cl', now()) RETURNING id",
            gym,
            new_rut(),
            phone,
            date.fromisoformat(minor_dob()),
        ),
    )

    answer = approved(client, gym, str(request))

    juan = record(db, gym, answer["person_id"])
    assert (juan["email"], juan["phone"]) == (None, None)
    guardian = guardian_of(db, gym, answer["person_id"])
    assert guardian is not None
    assert record(db, gym, str(guardian))["email"] == "marta.vieja@example.cl"
