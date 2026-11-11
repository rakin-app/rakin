"""A gym's public privacy notice (#168): which gym's it is, and what it says of it."""

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.dates import gym_today
from app.integrations.humancheck import TurnstileCheck
from app.main import create_app
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import DEFAULT_TIMEZONE, Database, migrate, seed_gym, throwaway_database
from tests.test_gym_settings import PRIVACY

pytestmark = pytest.mark.postgres

URL = "/api/privacy"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def app(db: Database) -> FastAPI:
    app = create_app(
        make_settings(
            database_url=db.api_url, public_base_url="https://rakin.cl", base_domain="rakin.cl"
        )
    )
    app.add_middleware(FakeAuth)
    return app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def new_gym(db: Database) -> tuple[uuid.UUID, str]:
    slug = f"dojo-{uuid.uuid4().hex[:6]}"
    return seed_gym(db, slug), slug


def fill_in(client: TestClient, gym: uuid.UUID, **privacy: Any) -> None:
    response = client.patch(
        "/api/gym/settings", json={"privacy": {**PRIVACY, **privacy}}, headers=as_gym(gym)
    )
    assert response.status_code == 200, response.text


def on_host(slug: str) -> dict[str, str]:
    return {"host": f"{slug}.rakin.cl"}


def notice(slug: str) -> dict[str, Any]:
    return {
        "gym": slug,
        "gym_logo": None,
        "legal_name": "Academia Sur SpA",
        "rut": "76432109-K",
        "email": "privacidad@academiasur.example.com",
        "address": "Av. Pedro de Valdivia 1234, Providencia",
        "updated_on": gym_today(DEFAULT_TIMEZONE).isoformat(),
        "human_check": False,
    }


def test_the_gyms_host_shows_its_notice_to_anyone(client: TestClient, db: Database) -> None:
    gym, slug = new_gym(db)
    fill_in(client, gym)

    response = client.get(URL, headers=on_host(slug))

    assert response.status_code == 200
    assert response.json() == notice(slug)


def test_the_address_is_optional(client: TestClient, db: Database) -> None:
    gym, slug = new_gym(db)
    fill_in(client, gym, address=None)

    assert client.get(URL, headers=on_host(slug)).json()["address"] is None


def test_a_gym_that_has_not_filled_it_in_has_none(client: TestClient, db: Database) -> None:
    _, slug = new_gym(db)

    response = client.get(URL, headers=on_host(slug))

    assert (response.status_code, response.json()) == (404, {"detail": "no_privacy_notice"})


def test_the_base_host_shows_none_to_a_visitor(client: TestClient) -> None:
    assert client.get(URL).status_code == 404
    assert client.get(URL, headers={"host": "nadie.rakin.cl"}).status_code == 404


def test_on_the_base_host_it_is_the_sessions_gym(client: TestClient, db: Database) -> None:
    gym, slug = new_gym(db)
    fill_in(client, gym)

    response = client.get(URL, headers=as_gym(gym))

    assert response.json() == notice(slug)


def test_the_host_wins_over_the_session(client: TestClient, db: Database) -> None:
    (here, here_slug), (there, _) = new_gym(db), new_gym(db)
    fill_in(client, here)
    fill_in(client, there, legal_name="Otra SpA")

    response = client.get(URL, headers={**on_host(here_slug), **as_gym(there)})

    assert response.json() == notice(here_slug)


def test_the_join_form_on_the_base_host_names_its_link(client: TestClient, db: Database) -> None:
    gym, slug = new_gym(db)
    fill_in(client, gym)
    link = client.post("/api/join-link", json={}, headers=as_gym(gym)).json()

    response = client.get(URL, params={"link": link["token"]})

    assert response.json() == notice(slug)
    assert client.get(URL, params={"link": "x" * 32}).status_code == 404
    assert client.get(URL, params={"link": "x" * 65}).status_code == 422


def test_it_says_whether_the_join_form_checks_for_humans(
    app: FastAPI, client: TestClient, db: Database
) -> None:
    gym, slug = new_gym(db)
    fill_in(client, gym)
    integrations = app.state.integrations
    turnstile = TurnstileCheck(site_key="site", secret_key="secret")
    app.state.integrations = dataclasses.replace(integrations, human_check=turnstile)
    try:
        assert client.get(URL, headers=on_host(slug)).json()["human_check"] is True
    finally:
        app.state.integrations = integrations
