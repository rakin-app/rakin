"""What only the local-disk store does: the parts S3 would do on its own servers."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.integrations.blobstore import LocalBlobStore
from app.main import create_app
from tests.conftest import UNREACHABLE_DB, make_settings


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(
        make_settings(
            database_url=UNREACHABLE_DB,
            blob_local_dir=tmp_path,
            public_base_url="http://testserver",
        )
    )
    with TestClient(app) as c:
        yield c


def store(client: TestClient) -> LocalBlobStore:
    s = client.app.state.integrations.blob_store  # type: ignore[attr-defined]
    assert isinstance(s, LocalBlobStore)
    return s


def test_an_oversized_upload_is_refused_and_leaves_nothing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalBlobStore, "MAX_UPLOAD_BYTES", 10)
    presigned = store(client).presign_upload("big.bin", "application/octet-stream")

    response = client.put(presigned.url, content=b"x" * 11, headers=presigned.headers)

    assert response.status_code == 413
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == []


def test_a_url_signed_with_another_secret_is_refused(client: TestClient, tmp_path: Path) -> None:
    forger = LocalBlobStore(
        root=tmp_path,
        base_url="http://testserver",
        secret_key="someone-elses-secret-key",
        ttl_seconds=900,
    )
    presigned = forger.presign_upload("a.png", "image/png")

    assert client.put(presigned.url, content=b"x", headers=presigned.headers).status_code == 403


def test_urls_are_absolute_under_the_public_base_url(client: TestClient) -> None:
    assert (
        store(client).presign_download("a/b.png").startswith("http://testserver/api/blobs/a/b.png?")
    )


def test_the_routes_exist_only_for_the_local_store() -> None:
    app = create_app(make_settings(database_url=UNREACHABLE_DB, blob_store="s3"))

    assert not any(getattr(r, "path", "").startswith("/api/blobs") for r in app.routes)
