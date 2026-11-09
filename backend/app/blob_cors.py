"""The bucket's CORS rule, which a hosted `BLOB_STORE=s3` needs.

The browser PUTs proofs (and GETs them back) at `S3_PUBLIC_ENDPOINT_URL`, another
origin than the app's, so the bucket has to answer the browser's preflight for
`PUBLIC_BASE_URL`. Garage's CLI cannot set the rule and providers differ in their
consoles, so this sets it through the S3 API (`PutBucketCors`), which R2, S3 and
Garage all take:

    python -m app.blob_cors            # print the rule it would set; changes nothing
    python -m app.blob_cors --apply    # set it (replaces the bucket's CORS rules)
    python -m app.blob_cors --check    # send a browser's preflight and report

`--apply` needs a key that may change the bucket's settings, which the api's own key
usually may not: pass an admin key as `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` for
that one run. `--check` needs no key at all.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.integrations.blobstore import s3_client
from app.settings import Settings, get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3.type_defs import CORSRuleTypeDef

# What `S3BlobStore` signs: PUT with a `Content-Type`, GET for downloads. Browsers
# set `Content-Length` themselves, and it needs no preflight. Lowercase, because a
# browser lists the headers it will send in lowercase and Garage matches them
# case-sensitively (S3 and R2 do not care).
METHODS = ["PUT", "GET"]
HEADERS = ["content-type"]
MAX_AGE_SECONDS = 3600
# Any key: a preflight never reaches an object, only the bucket's rules.
PROBE_KEY = "cors-check"


def origin(url: str) -> str:
    """`scheme://host[:port]` of a URL, as a browser sends it in `Origin`."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"not an absolute URL: {url!r}")
    return f"{parts.scheme}://{parts.netloc}"


def cors_rule(settings: Settings) -> "CORSRuleTypeDef":
    return {
        "AllowedOrigins": [origin(settings.public_base_url)],
        "AllowedMethods": METHODS,
        "AllowedHeaders": HEADERS,
        "ExposeHeaders": ["ETag"],
        "MaxAgeSeconds": MAX_AGE_SECONDS,
    }


def apply(settings: Settings) -> None:
    client = s3_client(
        settings.s3_endpoint_url,
        settings.s3_region,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
    )
    client.put_bucket_cors(
        Bucket=settings.s3_bucket, CORSConfiguration={"CORSRules": [cors_rule(settings)]}
    )


@dataclass(frozen=True)
class Preflight:
    status: int
    allow_origin: str | None
    allow_methods: str | None

    def allows(self, origin: str, method: str) -> bool:
        methods = {m.strip().upper() for m in (self.allow_methods or "").split(",")}
        return (
            200 <= self.status < 300
            and self.allow_origin in {origin, "*"}
            and method.upper() in methods
        )


def preflight(settings: Settings, method: str = "PUT", timeout: float = 10.0) -> Preflight:
    """The bucket's answer to the preflight a browser on `PUBLIC_BASE_URL` sends."""
    url = f"{settings.s3_public_endpoint_url.rstrip('/')}/{settings.s3_bucket}/{PROBE_KEY}"
    request = urllib.request.Request(
        url,
        method="OPTIONS",
        headers={
            "Origin": origin(settings.public_base_url),
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, headers = response.status, response.headers
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, exc.headers
    return Preflight(
        status=status,
        allow_origin=headers.get("Access-Control-Allow-Origin"),
        allow_methods=headers.get("Access-Control-Allow-Methods"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set or check the bucket's CORS rule.")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true", help="set the rule on the bucket")
    action.add_argument("--check", action="store_true", help="send a browser's preflight")
    args = parser.parse_args(argv)

    settings = get_settings()
    if settings.blob_store != "s3":
        print(f"BLOB_STORE={settings.blob_store}: same-origin, no CORS rule needed")
        return 0

    if args.check:
        app_origin = origin(settings.public_base_url)
        failed = False
        for method in METHODS:
            answer = preflight(settings, method)
            ok = answer.allows(app_origin, method)
            failed |= not ok
            print(
                f"{'ok' if ok else 'FAIL'}: {method} from {app_origin}: "
                f"status {answer.status}, allow-origin {answer.allow_origin}, "
                f"allow-methods {answer.allow_methods}"
            )
        return 1 if failed else 0

    rule = json.dumps({"CORSRules": [cors_rule(settings)]}, indent=2)
    if not args.apply:
        print(f"bucket {settings.s3_bucket} at {settings.s3_endpoint_url} would get:\n{rule}")
        print("dry run: nothing changed; pass --apply to set it", file=sys.stderr)
        return 0
    apply(settings)
    print(f"bucket {settings.s3_bucket}: CORS set for {origin(settings.public_base_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
