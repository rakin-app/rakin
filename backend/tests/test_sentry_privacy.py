"""What an error sends to Sentry (#373): nothing that names a person."""

import asyncio
import json
import logging
from typing import Any

import asyncpg
import pytest
import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import Captured, require_test_database_url

# Built, so the source lines an event carries around a frame never hold them whole.
RUT = "12.345." + "678-5"
NAME = "Zoraida " + "Quintanilla"
COOKIE = "secret-" + "cookie"
logger = logging.getLogger(__name__)


def sent(transport: Captured) -> str:
    """Every event the client sent, as the JSON that would have crossed the wire."""
    sentry_sdk.flush()
    events = [e for env in transport.envelopes if (e := env.get_event()) is not None]
    assert events, "no event reached the transport"
    return json.dumps(events)


def app_that_fails(fail: Any) -> TestClient:
    app = FastAPI()

    @app.post("/people")
    async def save(request: Request) -> None:
        person = await request.json()
        rut = person["rut"]  # a local the SDK would attach to the frame
        await fail(rut)

    return TestClient(app, raise_server_exceptions=False)


def test_an_error_while_saving_a_person_sends_no_body_local_or_query(sentry: Captured) -> None:
    async def fail(rut: str) -> None:
        # An outgoing request on the way, as httpx's integration and its log line leave it.
        url = f"https://api.example/check?rut={rut}"
        sentry_sdk.add_breadcrumb(
            category="httplib", data={"url": url.split("?")[0], "http.query": f"rut={rut}"}
        )
        sentry_sdk.add_breadcrumb(category="httpx", message=f"HTTP Request: GET {url} 200")
        raise ValueError("could not save")

    client = app_that_fails(fail)
    client.cookies.set("session", COOKIE)
    response = client.post(f"/people?rut={RUT}", json={"rut": RUT, "name": NAME})

    assert response.status_code == 500
    payload = sent(sentry)
    assert "could not save" in payload  # the event did go out
    for leak in (RUT, NAME, COOKIE):
        assert leak not in payload
    event = json.loads(payload)[0]
    assert "data" not in event["request"]
    assert "query_string" not in event["request"]
    assert "cookies" not in event["request"]
    crumbs = event["breadcrumbs"]["values"]
    assert crumbs[-1]["message"] == "HTTP Request: GET https://api.example/check 200"
    frames = event["exception"]["values"][-1]["stacktrace"]["frames"]
    assert not any("vars" in frame for frame in frames)


@pytest.mark.postgres
def test_a_unique_violation_sends_its_sqlstate_and_constraint_not_the_row(
    sentry: Captured,
) -> None:
    async def fail(rut: str) -> None:
        engine = create_async_engine(require_test_database_url())
        try:
            async with engine.connect() as conn:
                await conn.execute(
                    text("CREATE TEMP TABLE person (rut text CONSTRAINT person_rut_key UNIQUE)")
                )
                for _ in range(2):
                    await conn.execute(text("INSERT INTO person VALUES (:rut)"), {"rut": rut})
        finally:
            await engine.dispose()

    client = app_that_fails(fail)
    assert client.post("/people", json={"rut": RUT}).status_code == 500

    payload = sent(sentry)
    assert RUT not in payload
    event = json.loads(payload)[0]
    # asyncpg's error, SQLAlchemy's adaptation of it, and the `IntegrityError` it raises.
    values = [v for v in event["exception"]["values"] if v["module"] != "builtins"]
    assert [v["type"] for v in values] == [
        "UniqueViolationError",
        "AsyncAdapt_asyncpg_dbapi.UniqueViolationError",
        "IntegrityError",
    ]
    for value in values:
        assert value["value"] == "sqlstate=23505 constraint=person_rut_key (message withheld)"


@pytest.mark.postgres
def test_a_logged_driver_error_sends_no_row_values(sentry: Captured) -> None:
    async def violate() -> None:
        url = require_test_database_url().replace("postgresql+asyncpg", "postgresql")
        conn = await asyncpg.connect(url)
        try:
            await conn.execute("CREATE TEMP TABLE person (rut text UNIQUE)")
            for _ in range(2):
                await conn.execute("INSERT INTO person VALUES ($1)", RUT)
        finally:
            await conn.close()

    try:
        asyncio.run(violate())
    except asyncpg.UniqueViolationError:
        logger.exception("job failed")

    payload = sent(sentry)
    assert RUT not in payload
    [value] = json.loads(payload)[0]["exception"]["values"]
    assert value["value"] == "sqlstate=23505 constraint=person_rut_key (message withheld)"
