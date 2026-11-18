"""The operator a panel request acts as: `OperatorSession`.

A request on a gym's host gets a 404, whatever it carries: the panel is the base
host's alone, so a gym's address never shows it is there. Elsewhere, a request with no
`__Host-platform` cookie, or one whose session is not live (ended, past its 8 hours, or
its operator revoked), gets a 401, the first before any database work.

The endpoint then gets the operator, their session's hash, which every `platform_*`
function checks again (migration 0076), and a transaction to call those in. A gym's
session plays no part: it is read from another cookie, into `request.state`, and
nothing here looks at it.

`require_fresh` is for what cannot be undone: it asks that the operator proved who they
are in the last `FRESH`, and otherwise answers `401 {"code": "reauth"}`, for the panel
to ask for a code.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.hosts import Hosts, host_gym
from app.magiclink.tokens import hash_token
from app.magiclink.web import is_secure
from app.permissions import GATES, OPERATOR

# `__Host-`, as the gym's session cookie: Secure, on Path=/, with no Domain, so it never
# reaches a gym's host.
COOKIE_NAME = "__Host-platform"
# For an `http://` base URL, local development only, as `app.magiclink`'s.
DEV_COOKIE_NAME = "platform"

# How recent a proof the irreversible actions ask for.
FRESH = timedelta(minutes=10)


def platform_cookie_name(base_url: str) -> str:
    """`__Host-platform`, or the plain `platform` the `http://` base URL of local dev needs."""
    return COOKIE_NAME if is_secure(base_url) else DEV_COOKIE_NAME


def on_the_base_host(request: Request) -> None:
    """A 404 on a gym's host: the one its `HostMiddleware` found, or any host naming a
    slug, a gym or not."""
    hosts: Hosts = request.app.state.hosts
    if host_gym(request.state) is not None or hosts.slug_of(request.headers.get("host", "")):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


@dataclass(frozen=True)
class Operator:
    id: uuid.UUID
    email: str
    name: str
    # When they last proved who they are: signing in, or a code since (`require_fresh`).
    fresh_at: datetime
    expires_at: datetime
    # What every `platform_*` function takes, to check the session itself.
    session_hash: bytes
    db: AsyncSession


NOT_SIGNED_IN = HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")


async def operator_session(request: Request) -> AsyncIterator[Operator]:
    on_the_base_host(request)
    token = request.cookies.get(platform_cookie_name(request.app.state.settings.public_base_url))
    if not token:
        raise NOT_SIGNED_IN
    session_hash = hash_token(token)
    async with request.app.state.sessionmaker() as db, db.begin():
        row = (
            await db.execute(
                text(
                    "SELECT operator_id, email, name, fresh_at, expires_at"
                    " FROM platform_live_session(:h)"
                ),
                {"h": session_hash},
            )
        ).one_or_none()
        if row is None:
            raise NOT_SIGNED_IN
        # Commits when the endpoint returns, rolls back if it raises.
        yield Operator(
            row.operator_id, row.email, row.name, row.fresh_at, row.expires_at, session_hash, db
        )


GATES[operator_session] = OPERATOR

# scope="function", as `TenantSession`: the commit happens before the response is sent.
OperatorSession = Annotated[Operator, Depends(operator_session, scope="function")]


def require_fresh(operator: Operator, now: datetime | None = None) -> None:
    """A 401 `reauth` unless `operator` proved who they are within `FRESH`."""
    if (now or datetime.now(UTC)) - operator.fresh_at > FRESH:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "reauth"})
