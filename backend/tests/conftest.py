import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

# Nothing listens here, so connecting fails fast with "connection refused".
UNREACHABLE_DB = "postgresql+asyncpg://rakin:rakin@127.0.0.1:1/rakin"


def make_settings(**overrides: object) -> Settings:
    # _env_file=None keeps a developer's `.env` out of the tests.
    return Settings(_env_file=None, **{"environment": "test", **overrides})  # type: ignore[arg-type]


@pytest.fixture
def unreachable_app() -> FastAPI:
    return create_app(make_settings(database_url=UNREACHABLE_DB, healthz_db_timeout_seconds=1.0))


@pytest.fixture
def client(unreachable_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(unreachable_app) as c:
        yield c


@pytest.fixture
def postgres_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url
