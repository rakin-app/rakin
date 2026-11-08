import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.logging import JsonFormatter, configure_logging, request_id_var


def access_lines(out: str) -> list[dict[str, object]]:
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [line for line in lines if line["logger"] == "app.access"]


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    response = client.get("/healthz")

    assert len(response.headers["x-request-id"]) == 32


def test_incoming_request_id_is_reused(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "abc-123"})

    assert response.headers["x-request-id"] == "abc-123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


def test_access_log_is_one_json_line_per_request_with_request_id(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")  # rebind the handler to pytest's captured stdout
    capsys.readouterr()

    client.get("/healthz", headers={"X-Request-ID": "req-1"})

    [line] = access_lines(capsys.readouterr().out)
    assert line["request_id"] == "req-1"
    assert line["method"] == "GET"
    assert line["path"] == "/healthz"
    assert line["status"] == 503
    assert line["level"] == "INFO"


def test_logs_inside_a_request_carry_its_request_id(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging("INFO")
    capsys.readouterr()

    client.get("/healthz", headers={"X-Request-ID": "req-2"})

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    warning = next(line for line in lines if line["logger"] == "app.api.health")
    assert warning["request_id"] == "req-2"
    assert "exc_info" in warning


def test_formatter_omits_request_id_outside_a_request() -> None:
    record = logging.makeLogRecord({"msg": "boot", "levelname": "INFO", "name": "x"})

    payload = json.loads(JsonFormatter().format(record))

    assert request_id_var.get() is None
    assert payload["message"] == "boot"
    assert "request_id" not in payload
