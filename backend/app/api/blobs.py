"""Upload and download for `LocalBlobStore`, the stand-in for presigned S3 URLs.

Mounted only when `BLOB_STORE=local`. There is no session here: like an S3 presigned
URL, the signature in the query string is the authorisation, and it covers the
operation, the key, the content type and the expiry.
"""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse

from app.integrations import get_integrations
from app.integrations.blobstore import ALLOWED_CONTENT_TYPES, LocalBlobStore

router = APIRouter(prefix=LocalBlobStore.PATH_PREFIX.rstrip("/"))

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, "invalid or expired signature")

# Downloads come from the app's own origin, unlike S3's, so never let one render as a
# page there: save it instead, never sniff a type, and sandbox it if opened anyway.
DOWNLOAD_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox",
}


def local_store(request: Request) -> LocalBlobStore:
    store = get_integrations(request).blob_store
    assert isinstance(store, LocalBlobStore)
    return store


@router.put("/{key:path}", status_code=status.HTTP_200_OK)
async def upload(
    key: str,
    request: Request,
    exp: Annotated[str, Query()],
    sig: Annotated[str, Query()],
    # Absent from a download URL, whose signature then fails for "put" as well.
    ct: Annotated[str, Query()] = "",
    content_type: Annotated[str | None, Header()] = None,
) -> Response:
    store = local_store(request)
    # S3 rejects a PUT whose Content-Type differs from the signed one; so does this.
    if (
        content_type != ct
        or ct not in ALLOWED_CONTENT_TYPES
        or not store.verify("put", key, ct, exp, sig)
    ):
        raise FORBIDDEN
    try:
        await store.write(key, ct, request.stream())
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "key nests under, or holds, another key"
        ) from exc
    return Response(status_code=status.HTTP_200_OK)


@router.get("/{key:path}")
async def download(
    key: str,
    request: Request,
    exp: Annotated[str, Query()],
    sig: Annotated[str, Query()],
) -> FileResponse:
    store = local_store(request)
    if not store.verify("get", key, "", exp, sig):
        raise FORBIDDEN
    found = store.stored(key)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such blob")
    path, media_type = found
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="attachment",
        headers=DOWNLOAD_HEADERS,
    )
