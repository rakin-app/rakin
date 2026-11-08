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
    return require_test_database_url()


def require_test_database_url() -> str:
    """TEST_DATABASE_URL, or skip; usable from fixtures of any scope."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        # CI sets REQUIRE_POSTGRES so a missing database fails instead of skipping.
        if os.environ.get("REQUIRE_POSTGRES"):
            pytest.fail("REQUIRE_POSTGRES is set but TEST_DATABASE_URL is not")
        pytest.skip("TEST_DATABASE_URL not set")
    return url
