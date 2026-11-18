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
from pydantic import BaseModel, ValidationError
from sentry_sdk.types import Event, Hint
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.sentry import init_sentry
from tests.conftest import Captured, make_settings, require_test_database_url

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


def unique_violation() -> asyncpg.UniqueViolationError:
    """The error a second insert of `RUT` raises, straight from asyncpg."""

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
    except asyncpg.UniqueViolationError as exc:
        return exc
    raise AssertionError("the second insert went through")


@pytest.mark.postgres
def test_a_logged_driver_error_sends_no_row_values(sentry: Captured) -> None:
    exc = unique_violation()
    try:
        raise exc
    except asyncpg.UniqueViolationError:
        # Quoted as a parameter too, so the text would reach the log message.
        logger.exception("job failed: %s", exc)

    payload = sent(sentry)
    assert RUT not in payload
    event = json.loads(payload)[0]
    summary = "sqlstate=23505 constraint=person_rut_key (message withheld)"
    [value] = event["exception"]["values"]
    assert value["value"] == summary
    assert event["logentry"]["formatted"] == f"job failed: {summary}"
    assert event["logentry"]["params"] == [summary]


class Person(BaseModel):
    rut: int


def validation_error() -> ValidationError:
    try:
        Person(rut=RUT)
    except ValidationError as exc:
        return exc
    raise AssertionError("a RUT parsed as an int")


VALIDATION_SUMMARY = "Person: rut int_parsing (message withheld)"


def test_a_validation_error_sends_the_field_not_the_input(sentry: Captured) -> None:
    exc = validation_error()
    assert RUT in str(exc)  # pydantic quotes the `input_value`
    try:
        raise exc
    except ValidationError:
        logger.exception(f"import failed: {exc}")

    payload = sent(sentry)
    assert RUT not in payload
    event = json.loads(payload)[0]
    [value] = event["exception"]["values"]
    assert value["value"] == VALIDATION_SUMMARY
    assert event["logentry"]["message"] == f"import failed: {VALIDATION_SUMMARY}"


def test_an_exception_logged_as_a_parameter_sends_no_input(sentry: Captured) -> None:
    exc = validation_error()

    logger.error("import failed: %s", exc)  # no exc_info: only the parameter has it

    payload = sent(sentry)
    assert RUT not in payload
    logentry = json.loads(payload)[0]["logentry"]
    assert logentry["formatted"] == f"import failed: {VALIDATION_SUMMARY}"
    assert logentry["params"] == [VALIDATION_SUMMARY]


def test_a_logged_exception_kept_as_a_breadcrumb_sends_no_input(sentry: Captured) -> None:
    logger.warning("row skipped: %s", validation_error())  # a breadcrumb, not an event

    sentry_sdk.capture_message("import finished")

    payload = sent(sentry)
    assert RUT not in payload
    crumbs = json.loads(payload)[0]["breadcrumbs"]["values"]
    assert crumbs[-1]["message"] == f"row skipped: {VALIDATION_SUMMARY}"


def test_a_callers_before_send_runs_on_the_scrubbed_event() -> None:
    seen: list[Event] = []

    def keep(event: Event, hint: Hint) -> Event | None:
        seen.append(event)
        return None  # and drops it

    transport = Captured()
    settings = make_settings(sentry_dsn="https://public@sentry.invalid/1")
    assert init_sentry(settings, transport=transport, before_send=keep)
    try:
        try:
            raise validation_error()
        except ValidationError:
            logger.exception("import failed")
        sentry_sdk.flush()
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.init()  # no DSN: a client that sends nothing

    [event] = seen
    assert RUT not in json.dumps(event, default=str)
    assert not [env for env in transport.envelopes if env.get_event() is not None]
