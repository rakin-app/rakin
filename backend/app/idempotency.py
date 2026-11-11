"""One run per submission: the `Idempotency-Key` header (#201).

The web app sends a fresh key with every mutating request it makes for one submission
of a form. This middleware claims the key in `idempotency_key` (migration 0038) before
the request runs, so a second request with the same key, a double tap, does not run:

- while the first is still running, the second waits for it (up to `wait_seconds`,
  then a 409 `request_in_progress`), and then
- gets the first one's stored answer back, status and body, with
  `Idempotent-Replayed: true`.

A key is scoped to the gym and the person acting (the request's tenant), or to
nobody for an anonymous request (the join form). A key sent again for another method
or path is a 422 `idempotency_key_reused`. Only a 2xx answer is kept: a request that
was refused or failed had no effect (its transaction rolled back), so its key is
released and a retry with the same key runs again. Keys are kept `TTL`; each claim
deletes its own scope's older keys.

A request without the header runs as before. So do the sign-in routes under
`/api/auth`, whose answers set cookies that a replay would not carry.

It runs inside the session middleware, which sets the tenant, and each of its steps is
a short transaction of its own, outside the endpoint's: the claim commits before the
request runs, so a concurrent request with the same key sees it.
"""

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.tenancy import Tenant

HEADER = b"idempotency-key"
REPLAYED_HEADER = b"idempotent-replayed"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
EXCLUDED_PREFIX = "/api/auth/"
TTL = timedelta(hours=24)
SCOPE = "gym_id IS NOT DISTINCT FROM :gym_id AND person_id IS NOT DISTINCT FROM :person_id"
# What a client may send: a UUID, or any short printable token.
_VALID_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

Sessionmaker = Callable[[], async_sessionmaker[AsyncSession]]


@dataclass(frozen=True)
class Stored:
    fingerprint: str
    status_code: int | None
    content_type: str | None
    body: bytes | None


@dataclass(frozen=True)
class KeyScope:
    gym_id: uuid.UUID | None
    person_id: uuid.UUID | None
    key: str


class IdempotencyMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        sessionmaker: Sessionmaker,
        wait_seconds: float = 15.0,
        poll_seconds: float = 0.05,
    ) -> None:
        self.app = app
        self.sessionmaker = sessionmaker
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        key = _key_of(scope)
        if key is None:
            await self.app(scope, receive, send)
            return
        tenant = scope.get("state", {}).get("tenant")
        if isinstance(tenant, Tenant):
            where = KeyScope(tenant.gym_id, tenant.person_id, key)
        else:
            where = KeyScope(None, None, key)
        fingerprint = f"{scope['method']} {scope['path']}"

        deadline = time.monotonic() + self.wait_seconds
        while True:
            if await self._claim(where, fingerprint):
                await self._run(where, scope, receive, send)
                return
            stored = await self._stored(where)
            if stored is None:
                continue  # released by a request that failed: claim it again
            if stored.fingerprint != fingerprint:
                await _error(send, 422, "idempotency_key_reused", "La clave ya se usó.")
                return
            if stored.status_code is not None:
                await _replay(send, stored)
                return
            if time.monotonic() >= deadline:
                await _error(send, 409, "request_in_progress", "La solicitud sigue en curso.")
                return
            await asyncio.sleep(self.poll_seconds)

    async def _run(self, where: KeyScope, scope: Scope, receive: Receive, send: Send) -> None:
        status = 500
        content_type: str | None = None
        chunks: list[bytes] = []

        async def capture(message: Message) -> None:
            nonlocal status, content_type
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message.get("headers", []):
                    if name.lower() == b"content-type":
                        content_type = value.decode("latin-1")
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except BaseException:
            await asyncio.shield(self._release(where))
            raise
        if 200 <= status < 300:
            await self._store(where, status, content_type, b"".join(chunks))
        else:
            await self._release(where)

    @asynccontextmanager
    async def _session(self, where: KeyScope) -> AsyncIterator[AsyncSession]:
        """A transaction of its own, as the key's scope sees the table (RLS, 0038)."""
        async with self.sessionmaker()() as session, session.begin():
            await session.execute(
                text(
                    "SELECT set_config('app.gym_id', :gym_id, true),"
                    " set_config('app.person_id', :person_id, true)"
                ),
                {
                    "gym_id": "" if where.gym_id is None else str(where.gym_id),
                    "person_id": "" if where.person_id is None else str(where.person_id),
                },
            )
            yield session

    def _params(self, where: KeyScope, **more: object) -> dict[str, object]:
        return {"gym_id": where.gym_id, "person_id": where.person_id, "key": where.key, **more}

    async def _claim(self, where: KeyScope, fingerprint: str) -> bool:
        """Whether this request claimed the key; False if another holds it."""
        async with self._session(where) as session:
            await session.execute(
                text(
                    f"DELETE FROM idempotency_key WHERE {SCOPE}"
                    " AND created_at < now() - CAST(:ttl AS interval)"
                ),
                self._params(where, ttl=TTL),
            )
            claimed = await session.execute(
                text(
                    "INSERT INTO idempotency_key (gym_id, person_id, key, fingerprint)"
                    " VALUES (:gym_id, :person_id, :key, :fingerprint)"
                    " ON CONFLICT (gym_id, person_id, key) DO NOTHING RETURNING 1"
                ),
                self._params(where, fingerprint=fingerprint),
            )
            return claimed.first() is not None

    async def _stored(self, where: KeyScope) -> Stored | None:
        async with self._session(where) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT fingerprint, status_code, content_type, body"
                        f" FROM idempotency_key WHERE {SCOPE} AND key = :key"
                    ),
                    self._params(where),
                )
            ).first()
        return None if row is None else Stored(*row)

    async def _store(
        self, where: KeyScope, status: int, content_type: str | None, body: bytes
    ) -> None:
        async with self._session(where) as session:
            await session.execute(
                text(
                    "UPDATE idempotency_key"
                    " SET status_code = :status, content_type = :content_type, body = :body"
                    f" WHERE {SCOPE} AND key = :key"
                ),
                self._params(where, status=status, content_type=content_type, body=body),
            )

    async def _release(self, where: KeyScope) -> None:
        async with self._session(where) as session:
            await session.execute(
                text(f"DELETE FROM idempotency_key WHERE {SCOPE} AND key = :key"),
                self._params(where),
            )


def _key_of(scope: Scope) -> str | None:
    """The request's key, if this request is one the middleware acts on."""
    if scope["type"] != "http" or scope["method"] not in MUTATING:
        return None
    if scope["path"].startswith(EXCLUDED_PREFIX):
        return None
    raw = dict(scope["headers"]).get(HEADER)
    if raw is None:
        return None
    key = raw.decode("latin-1").strip()
    return key if _VALID_KEY.match(key) else None


async def _replay(send: Send, stored: Stored) -> None:
    headers = [(REPLAYED_HEADER, b"true")]
    if stored.content_type is not None:
        headers.append((b"content-type", stored.content_type.encode("latin-1")))
    await send({"type": "http.response.start", "status": stored.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": stored.body or b""})


async def _error(send: Send, status: int, code: str, detail: str) -> None:
    body = json.dumps({"detail": {"code": code, "message": detail}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
