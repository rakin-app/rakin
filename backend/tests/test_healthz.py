import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_healthz_reports_503_when_database_is_unreachable(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "error"}


def test_healthz_times_out_instead_of_hanging() -> None:
    # A non-routable address makes the connect hang; the timeout must cut it short.
    app = create_app(
        make_settings(
            database_url="postgresql+asyncpg://rakin:rakin@10.255.255.1:5432/rakin",
            healthz_db_timeout_seconds=0.2,
        )
    )
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 503


@pytest.mark.postgres
def test_healthz_reports_ok_against_real_postgres(postgres_url: str) -> None:
    app = create_app(make_settings(database_url=postgres_url))
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
