"""The contract every `BlobStore` passes: the browser's side of presigned URLs.

Each test runs against the local-disk store (through the app's `/api/blobs` routes) and
against S3. The S3 run needs a real S3-compatible server at `TEST_S3_ENDPOINT_URL`
(CI starts Garage), because the contract is mostly about what the server refuses.
"""

import asyncio
import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.integrations import build_blob_store
from app.integrations.blobstore import BlobStore, LocalBlobStore, S3BlobStore
from app.main import create_app
from tests.conftest import UNREACHABLE_DB, make_settings

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


@dataclass
class Harness:
    store: BlobStore
    http: httpx.Client
    # A download URL for `key` that has already expired.
    expired_download: Callable[[str], str]


def local_harness(tmp_path: Path) -> Iterator[Harness]:
    settings = make_settings(
        database_url=UNREACHABLE_DB,
        blob_store="local",
        blob_local_dir=tmp_path,
        public_base_url="http://testserver",
    )
    app = create_app(settings)

    def expired_download(key: str) -> str:
        past = LocalBlobStore(
            root=tmp_path,
            base_url="http://testserver",
            secret_key=settings.secret_key,
            ttl_seconds=60,
            clock=lambda: time.time() - 61,
        )
        return past.presign_download(key)

    with TestClient(app) as client:
        yield Harness(app.state.integrations.blob_store, client, expired_download)


def s3_harness() -> Iterator[Harness]:
    endpoint = os.environ.get("TEST_S3_ENDPOINT_URL")
    if not endpoint:
        if os.environ.get("REQUIRE_S3"):
            pytest.fail("REQUIRE_S3 is set but TEST_S3_ENDPOINT_URL is not")
        pytest.skip("TEST_S3_ENDPOINT_URL not set")
    settings = make_settings(
        blob_store="s3", s3_endpoint_url=endpoint, s3_public_endpoint_url=endpoint
    )

    def expired_download(key: str) -> str:
        store = S3BlobStore(
            endpoint_url=endpoint,
            public_endpoint_url=endpoint,
            region=settings.s3_region,
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            ttl_seconds=1,
        )
        url = store.presign_download(key)
        time.sleep(2)
        return url

    with httpx.Client(timeout=10) as client:
        yield Harness(build_blob_store(settings), client, expired_download)


@pytest.fixture(params=["local", pytest.param("s3", marks=pytest.mark.s3)])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Harness]:
    if request.param == "local":
        yield from local_harness(tmp_path)
    else:
        yield from s3_harness()


@pytest.fixture
def key() -> str:
    # Unique per test, so runs against a shared bucket never see each other's files.
    return f"test/{uuid.uuid4()}/proof.png"


def assert_refused(response: httpx.Response) -> None:
    # Stores differ on the code (AWS says 403 to an expired URL, Garage 400), so the
    # contract is a client error that is not "no such file".
    assert 400 <= response.status_code < 500, response.status_code
    assert response.status_code != 404


def upload(h: Harness, key: str, body: bytes, content_type: str = "image/png") -> httpx.Response:
    presigned = h.store.presign_upload(key, content_type)
    return h.http.put(presigned.url, content=body, headers=presigned.headers)


def test_an_upload_can_be_downloaded(harness: Harness, key: str) -> None:
    assert upload(harness, key, PNG).status_code == 200

    response = harness.http.get(harness.store.presign_download(key))

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_a_second_upload_replaces_the_first(harness: Harness, key: str) -> None:
    upload(harness, key, b"first", "text/plain")
    upload(harness, key, b"second", "text/plain")

    assert harness.http.get(harness.store.presign_download(key)).content == b"second"


def test_an_upload_with_another_content_type_is_refused(harness: Harness, key: str) -> None:
    presigned = harness.store.presign_upload(key, "image/png")

    response = harness.http.put(presigned.url, content=PNG, headers={"Content-Type": "text/html"})

    assert_refused(response)
    assert harness.http.get(harness.store.presign_download(key)).status_code == 404


def test_a_download_url_does_not_upload(harness: Harness, key: str) -> None:
    url = harness.store.presign_download(key)

    response = harness.http.put(url, content=PNG, headers={"Content-Type": "image/png"})

    assert_refused(response)
    assert harness.http.get(url).status_code == 404


def test_a_tampered_signature_is_refused(harness: Harness, key: str) -> None:
    upload(harness, key, PNG)
    url = harness.store.presign_download(key)
    # Flip the last character of the signature, which ends the query in both stores.
    tampered = url[:-1] + ("0" if url[-1] != "0" else "1")

    assert_refused(harness.http.get(tampered))


def test_a_url_for_one_key_does_not_open_another(harness: Harness, key: str) -> None:
    other = key.replace("proof.png", "other.png")
    upload(harness, other, PNG)
    url = harness.store.presign_download(key).replace("proof.png", "other.png")

    assert_refused(harness.http.get(url))


def test_an_expired_url_is_refused(harness: Harness, key: str) -> None:
    upload(harness, key, PNG)

    assert_refused(harness.http.get(harness.expired_download(key)))


def test_a_missing_file_is_not_found(harness: Harness, key: str) -> None:
    assert harness.http.get(harness.store.presign_download(key)).status_code == 404


def test_delete_removes_the_file_and_tolerates_a_missing_one(harness: Harness, key: str) -> None:
    upload(harness, key, PNG)

    asyncio.run(harness.store.delete(key))
    asyncio.run(harness.store.delete(key))

    assert harness.http.get(harness.store.presign_download(key)).status_code == 404


@pytest.mark.parametrize(
    "bad_key",
    ["", "/abs", "../up", "a/../b", "a//b", ".hidden", "a/.b", "sp ace", "a\\b", "x" * 513],
)
def test_unsafe_keys_are_refused(harness: Harness, bad_key: str) -> None:
    with pytest.raises(ValueError, match="key"):
        harness.store.presign_upload(bad_key, "image/png")
    with pytest.raises(ValueError, match="key"):
        harness.store.presign_download(bad_key)


@pytest.mark.parametrize("bad_type", ["", "image", "text/html\r\nX-Evil: 1", "Image/PNG"])
def test_malformed_content_types_are_refused(harness: Harness, key: str, bad_type: str) -> None:
    with pytest.raises(ValueError, match="content type"):
        harness.store.presign_upload(key, bad_type)
