"""Object storage for payment proofs and other uploads.

Files never pass through the API process on their way in or out: the API hands the
browser a presigned URL, and the browser PUTs or GETs the bytes there directly.
`S3BlobStore` presigns against any S3-compatible service (Garage in the self-host
profile, a real provider when hosted). `LocalBlobStore` keeps files on local disk and
signs its own URLs, which `app/api/blobs.py` serves, so an instance with no object
storage still takes uploads.
"""

import asyncio
import hashlib
import hmac
import os
import re
import tempfile
import time
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import quote, urlencode

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

# Path segments of letters, digits, `.`, `_` and `-`, none starting with a dot: no
# `..`, no absolute paths, nothing a filesystem or an S3 console treats specially.
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*")
MAX_KEY_LENGTH = 512
# What a transfer proof can be. Anything a browser renders as a document (HTML, SVG)
# is out: a download served from the app's origin would run its script there. Every
# store signs the content type into the upload URL, so this binds S3 as well.
ALLOWED_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"}
)
# The largest upload any store takes. A phone photo of a transfer is a few MB, a bank's
# PDF receipt far less. Every store signs the exact size into the upload URL, so a
# client cannot send more than it asked for.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def validate_key(key: str) -> str:
    if len(key) > MAX_KEY_LENGTH or _KEY.fullmatch(key) is None:
        raise ValueError(f"invalid blob key: {key!r}")
    return key


def validate_content_type(content_type: str) -> str:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"content type not allowed: {content_type!r}")
    return content_type


def validate_size(size: int) -> int:
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_UPLOAD_BYTES:
        raise ValueError(f"size must be 1 to {MAX_UPLOAD_BYTES} bytes, got {size!r}")
    return size


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    # Send these with the PUT, unchanged; the signature covers them. It covers the
    # body's size as well, which a browser sends as `Content-Length` on its own.
    headers: dict[str, str]


@dataclass(frozen=True)
class StoredBlob:
    size: int
    content_type: str


class BlobStore(Protocol):
    def presign_upload(self, key: str, content_type: str, size: int) -> PresignedUpload:
        """A URL the browser PUTs the file to, with exactly this content type and size.

        Raises `ValueError` for a content type outside `ALLOWED_CONTENT_TYPES` or a size
        outside 1 to `MAX_UPLOAD_BYTES`.
        """
        ...

    def presign_download(self, key: str) -> str:
        """A URL the browser GETs the file from."""
        ...

    async def stat(self, key: str) -> StoredBlob | None:
        """The stored file's size and content type, or None if there is none."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the file; a key with no file is not an error."""
        ...


class S3BlobStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        public_endpoint_url: str,
        region: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        ttl_seconds: int,
    ) -> None:
        def client(endpoint: str) -> "S3Client":
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                # Path-style: Garage and most self-hosted stores have no per-bucket DNS.
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )

        self.bucket = bucket
        self.ttl_seconds = ttl_seconds
        # Server-side calls go to the internal endpoint; URLs are signed for the one
        # the browser reaches, since the host is part of the signature.
        self._client = client(endpoint_url)
        self._presigner = client(public_endpoint_url)

    def presign_upload(self, key: str, content_type: str, size: int) -> PresignedUpload:
        url = self._presigner.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": validate_key(key),
                "ContentType": validate_content_type(content_type),
                # Signed as `content-length`: the store refuses a body of any other size.
                "ContentLength": validate_size(size),
            },
            ExpiresIn=self.ttl_seconds,
        )
        return PresignedUpload(url=url, headers={"Content-Type": content_type})

    def presign_download(self, key: str) -> str:
        return self._presigner.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": validate_key(key)},
            ExpiresIn=self.ttl_seconds,
        )

    async def stat(self, key: str) -> StoredBlob | None:
        validate_key(key)
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return StoredBlob(size=head["ContentLength"], content_type=head["ContentType"])

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)


Operation = Literal["put", "get"]


class LocalBlobStore:
    """Files under `root`, behind HMAC-signed URLs served by `app/api/blobs.py`.

    `root/data/<key>` holds the bytes and `root/meta/<key>` the content type they were
    uploaded with.
    """

    PATH_PREFIX = "/api/blobs/"

    def __init__(
        self,
        *,
        root: Path,
        base_url: str,
        secret_key: str,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = root
        self.base_url = base_url.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self._secret = hashlib.sha256(b"rakin-blobstore\0" + secret_key.encode()).digest()
        self._clock = clock

    def presign_upload(self, key: str, content_type: str, size: int) -> PresignedUpload:
        url = self._sign(
            "put", validate_key(key), validate_content_type(content_type), validate_size(size)
        )
        return PresignedUpload(url=url, headers={"Content-Type": content_type})

    def presign_download(self, key: str) -> str:
        return self._sign("get", validate_key(key), "", None)

    async def stat(self, key: str) -> StoredBlob | None:
        validate_key(key)
        found = await asyncio.to_thread(self.stored, key)
        if found is None:
            return None
        path, content_type = found
        size = (await asyncio.to_thread(path.stat)).st_size
        return StoredBlob(size=size, content_type=content_type)

    async def delete(self, key: str) -> None:
        validate_key(key)
        for path in (self._data(key), self._meta(key)):
            # A directory is other keys nested under this one, not this blob.
            if await asyncio.to_thread(path.is_file):
                await asyncio.to_thread(path.unlink, missing_ok=True)

    def verify(
        self,
        op: Operation,
        key: str,
        content_type: str,
        size: int | None,
        expires: str,
        signature: str,
    ) -> bool:
        """Whether a URL's query was signed by `presign_*` and has not expired.

        `size` is the upload's (None for a download)."""
        try:
            validate_key(key)
            expires_at = int(expires)
        except ValueError:
            return False
        expected = self._signature(op, key, content_type, size, expires_at).encode()
        # Bytes: `compare_digest` raises on a `str` with non-ASCII characters.
        return hmac.compare_digest(expected, signature.encode()) and self._clock() < expires_at

    async def write(
        self, key: str, content_type: str, size: int, chunks: AsyncIterable[bytes]
    ) -> None:
        """Store an upload of exactly `size` bytes; raises `ValueError` for any other.

        Keys are paths, so one cannot nest under another (`a` and `a/b`): that raises
        `OSError` and leaves both as they were.
        """
        data = self._data(key)
        await asyncio.to_thread(data.parent.mkdir, parents=True, exist_ok=True)
        # Written beside the target and renamed into place, so a reader never sees half
        # a file and a failed upload leaves the previous one.
        fd, tmp_name = await asyncio.to_thread(tempfile.mkstemp, dir=data.parent, prefix=".up-")
        tmp = Path(tmp_name)
        try:
            received = 0
            with os.fdopen(fd, "wb") as out:
                async for chunk in chunks:
                    received += len(chunk)
                    if received > size:
                        raise ValueError("upload larger than signed")
                    await asyncio.to_thread(out.write, chunk)
            if received != size:
                raise ValueError("upload smaller than signed")
            meta = self._meta(key)
            await asyncio.to_thread(meta.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(meta.write_text, content_type)
            await asyncio.to_thread(tmp.replace, data)
        finally:
            await asyncio.to_thread(tmp.unlink, missing_ok=True)

    def stored(self, key: str) -> tuple[Path, str] | None:
        """The file and its content type, or None if there is no such blob."""
        data, meta = self._data(key), self._meta(key)
        if not data.is_file():
            return None
        content_type = meta.read_text() if meta.is_file() else "application/octet-stream"
        return data, content_type

    def _sign(self, op: Operation, key: str, content_type: str, size: int | None) -> str:
        expires_at = int(self._clock()) + self.ttl_seconds
        query = {"op": op, "exp": str(expires_at)}
        if content_type:
            query["ct"] = content_type
        if size is not None:
            query["len"] = str(size)
        query["sig"] = self._signature(op, key, content_type, size, expires_at)
        return f"{self.base_url}{self.PATH_PREFIX}{quote(key)}?{urlencode(query)}"

    def _signature(
        self, op: Operation, key: str, content_type: str, size: int | None, expires_at: int
    ) -> str:
        length = "" if size is None else str(size)
        message = f"{op}\n{key}\n{content_type}\n{length}\n{expires_at}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _data(self, key: str) -> Path:
        return self.root / "data" / key

    def _meta(self, key: str) -> Path:
        return self.root / "meta" / key
