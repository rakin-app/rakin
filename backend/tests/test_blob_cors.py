import os

import pytest

from app import blob_cors
from app.blob_cors import Preflight, cors_rule, origin, preflight
from app.integrations.blobstore import s3_client
from app.settings import Settings
from tests.conftest import make_settings


def test_origin_drops_path_and_query() -> None:
    assert origin("https://staging.rakin.app/") == "https://staging.rakin.app"
    assert origin("http://localhost:8080/x?y=1") == "http://localhost:8080"
    with pytest.raises(ValueError):
        origin("staging.rakin.app")


def test_rule_allows_what_the_s3_store_signs_from_the_app_origin() -> None:
    rule = cors_rule(make_settings(public_base_url="https://staging.rakin.app"))

    assert rule["AllowedOrigins"] == ["https://staging.rakin.app"]
    assert set(rule["AllowedMethods"]) == {"PUT", "GET"}
    assert rule["AllowedHeaders"] == ["content-type"]


@pytest.mark.parametrize(
    ("answer", "allowed"),
    [
        (Preflight(200, "https://a.example", "GET, PUT"), True),
        (Preflight(200, "*", "PUT"), True),
        (Preflight(200, "https://b.example", "PUT"), False),
        (Preflight(200, "https://a.example", "GET"), False),
        (Preflight(403, None, None), False),
    ],
)
def test_preflight_allows(answer: Preflight, allowed: bool) -> None:
    assert answer.allows("https://a.example", "PUT") is allowed


def test_dry_run_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(blob_cors, "get_settings", lambda: make_settings(blob_store="s3"))
    monkeypatch.setattr(blob_cors, "apply", lambda _: pytest.fail("dry run applied"))

    assert blob_cors.main([]) == 0
    assert '"AllowedOrigins"' in capsys.readouterr().out


def test_local_store_needs_no_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(blob_cors, "get_settings", lambda: make_settings(blob_store="local"))

    assert blob_cors.main(["--apply"]) == 0
    assert "no CORS rule needed" in capsys.readouterr().out


@pytest.fixture
def s3_settings() -> Settings:
    endpoint = os.environ.get("TEST_S3_ENDPOINT_URL")
    if not endpoint:
        if os.environ.get("REQUIRE_S3"):
            pytest.fail("REQUIRE_S3 is set but TEST_S3_ENDPOINT_URL is not")
        pytest.skip("TEST_S3_ENDPOINT_URL not set")
    return make_settings(
        blob_store="s3",
        s3_endpoint_url=endpoint,
        s3_public_endpoint_url=endpoint,
        public_base_url="https://staging.rakin.app",
    )


@pytest.mark.s3
def test_applied_rule_answers_the_browsers_preflight(s3_settings: Settings) -> None:
    blob_cors.apply(s3_settings)

    client = s3_client(
        s3_settings.s3_endpoint_url,
        s3_settings.s3_region,
        s3_settings.s3_access_key_id,
        s3_settings.s3_secret_access_key,
    )
    rules = client.get_bucket_cors(Bucket=s3_settings.s3_bucket)["CORSRules"]
    assert [r["AllowedOrigins"] for r in rules] == [["https://staging.rakin.app"]]
    for method in ("PUT", "GET"):
        assert preflight(s3_settings, method).allows("https://staging.rakin.app", method)

    other = s3_settings.model_copy(update={"public_base_url": "https://evil.example"})
    assert not preflight(other).allows("https://evil.example", "PUT")
