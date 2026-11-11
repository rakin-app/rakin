"""What only the local-disk store does: the parts S3 would do on its own servers."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.integrations.blobstore import LocalBlobStore, StoredBlob
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


@pytest.mark.parametrize("body", [b"x" * 11, b"x" * 9], ids=["larger", "smaller"])
def test_a_body_of_another_size_than_signed_is_refused_and_leaves_nothing(
    client: TestClient, tmp_path: Path, body: bytes
) -> None:
    presigned = store(client).presign_upload("big.pdf", "application/pdf", 10)

    response = client.put(presigned.url, content=body, headers=presigned.headers)

    assert response.status_code == 403
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.parametrize("chunks", [[b"x" * 6, b"x" * 6], [b"x" * 9]], ids=["larger", "smaller"])
def test_a_stream_that_belies_its_content_length_is_not_stored(
    client: TestClient, tmp_path: Path, chunks: list[bytes]
) -> None:
    # The route checks the header; the write checks what actually arrives.
    async def stream() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    with pytest.raises(ValueError, match="signed"):
        asyncio.run(store(client).write("a.pdf", "application/pdf", 10, stream()))
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == []


def test_stat_reports_size_and_type(client: TestClient) -> None:
    s = store(client)
    presigned = s.presign_upload("p/a.pdf", "application/pdf", 3)
    client.put(presigned.url, content=b"pdf", headers=presigned.headers)

    assert asyncio.run(s.stat("p/a.pdf")) == StoredBlob(size=3, content_type="application/pdf")
    assert asyncio.run(s.stat("p/none.pdf")) is None


def test_a_url_signed_with_another_secret_is_refused(client: TestClient, tmp_path: Path) -> None:
    forger = LocalBlobStore(
        root=tmp_path,
        secret_key="someone-elses-secret-key",
        ttl_seconds=900,
    )
    presigned = forger.presign_upload("a.png", "image/png", 1)

    assert client.put(presigned.url, content=b"x", headers=presigned.headers).status_code == 403


def test_urls_are_root_relative(client: TestClient) -> None:
    s = store(client)
    assert s.presign_download("a/b.png").startswith("/api/blobs/a/b.png?")
    assert s.presign_upload("a/b.png", "image/png", 1).url.startswith("/api/blobs/a/b.png?")


def test_the_routes_exist_only_for_the_local_store() -> None:
    app = create_app(make_settings(database_url=UNREACHABLE_DB, blob_store="s3"))

    assert not any(getattr(r, "path", "").startswith("/api/blobs") for r in app.routes)


def test_a_download_is_an_attachment_that_never_renders(client: TestClient) -> None:
    presigned = store(client).presign_upload("proofs/p.png", "image/png", 3)
    client.put(presigned.url, content=b"png", headers=presigned.headers)

    response = client.get(store(client).presign_download("proofs/p.png"))

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"


def test_an_upload_url_cannot_be_forged_for_a_type_outside_the_allow_list(
    client: TestClient,
) -> None:
    # The route re-checks, in case a URL was signed by a store with a wider list.
    url = store(client)._sign("put", "x.html", "text/html", 8)

    response = client.put(url, content=b"<script>", headers={"Content-Type": "text/html"})

    assert response.status_code == 403


@pytest.mark.parametrize("sig", ["%C3%A9", "%E2%9C%93" * 32])
def test_a_non_ascii_signature_is_refused_not_a_server_error(client: TestClient, sig: str) -> None:
    assert client.get(f"/api/blobs/x.png?exp=9999999999&sig={sig}").status_code == 403


@pytest.mark.parametrize(("first", "second"), [("a", "a/b.png"), ("a/b.png", "a")])
def test_a_key_nested_under_another_is_a_conflict(
    client: TestClient, first: str, second: str
) -> None:
    for k in (first, second):
        presigned = store(client).presign_upload(k, "image/png", len(k))
        response = client.put(presigned.url, content=k.encode(), headers=presigned.headers)

    assert response.status_code == 409
    assert client.get(store(client).presign_download(first)).content == first.encode()
    asyncio.run(store(client).delete(second))  # a directory is not a blob: no error
