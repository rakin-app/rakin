"""The gym a request acts in, and the database transaction scoped to it.

Every gym-scoped endpoint takes a `TenantSession`, through the role it requires
(`app.roles`). It opens one transaction per request and runs `SET LOCAL app.gym_id`
(as `set_config(..., true)`, which takes a bound parameter) before the endpoint sees
the session, so RLS limits every query to that gym and a missed `WHERE` returns
nothing. `app.person_id`, who is acting, is set the same way, for the policies that
depend on their role (migration 0006). Both settings are local to the transaction:
they are gone when the connection returns to the pool.

The gym and person come from the authenticated context, `request.state.tenant`,
which the auth layer sets. A request without one gets a 401 and never opens a
session.

A write waits on the gym's terms (#499). On a mutating request the session reads the
gym's terms state once (`app_terms_state`, 0081) and keeps it in
`request.state.terms_state`: while it is `pending`, the gym never having accepted any,
the request is a `409 terms_pending`, whoever makes it, so nothing goes in before the
titular accepts. An `outdated` gym, which accepted an earlier version, keeps working:
only its titular's writes wait on the new one, in the gates (`app.permissions`).
Reads stay open either way, so the acceptance page loads and a gym that declines can
still take its data. The acceptance endpoints themselves open their session with
`ungated_session` (`app.api.terms`).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal import PROCESSOR_TERMS_VERSION, SERVICE_TERMS_VERSION


@dataclass(frozen=True)
class Tenant:
    gym_id: uuid.UUID
    person_id: uuid.UUID


@dataclass(frozen=True)
class SignIn:
    """How the request's session began: the address its link or code went to, and
    when. `request.state.sign_in`, for the record of an acceptance of the terms."""

    email: str
    at: datetime


def current_tenant(request: Request) -> Tenant:
    tenant = getattr(request.state, "tenant", None)
    if not isinstance(tenant, Tenant):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return tenant


# The methods that write, which wait on the terms here and are deduplicated by
# `app.idempotency`.
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

TERMS_PENDING = "terms_pending"
TERMS_OUTDATED = "terms_outdated"


async def terms_state(session: AsyncSession) -> str:
    """The terms state of the gym `session` acts in: `pending`, `outdated` or `current`."""
    return str(
        await session.scalar(
            text("SELECT app_terms_state(:service, :processor)"),
            {"service": SERVICE_TERMS_VERSION, "processor": PROCESSOR_TERMS_VERSION},
        )
    )


@asynccontextmanager
async def _open(request: Request, tenant: Tenant, *, gated: bool) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "SELECT set_config('app.gym_id', :gym_id, true),"
                " set_config('app.person_id', :person_id, true)"
            ),
            {"gym_id": str(tenant.gym_id), "person_id": str(tenant.person_id)},
        )
        if gated and request.method in MUTATING:
            request.state.terms_state = await terms_state(session)
            if request.state.terms_state == "pending":
                raise HTTPException(status.HTTP_409_CONFLICT, {"code": TERMS_PENDING})
        # Commits when the endpoint returns, rolls back if it raises.
        yield session


async def tenant_session(
    request: Request, tenant: Annotated[Tenant, Depends(current_tenant)]
) -> AsyncIterator[AsyncSession]:
    async with _open(request, tenant, gated=True) as session:
        yield session


async def ungated_session(
    request: Request, tenant: Annotated[Tenant, Depends(current_tenant)]
) -> AsyncIterator[AsyncSession]:
    """A `tenant_session` that does not wait on the gym's terms: accepting them."""
    async with _open(request, tenant, gated=False) as session:
        yield session


# scope="function" commits before the response is sent, so a failed commit is a 500
# rather than a 200 for a write that never landed.
TenantSession = Annotated[AsyncSession, Depends(tenant_session, scope="function")]
