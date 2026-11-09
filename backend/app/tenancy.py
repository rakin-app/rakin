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
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Tenant:
    gym_id: uuid.UUID
    person_id: uuid.UUID


def current_tenant(request: Request) -> Tenant:
    tenant = getattr(request.state, "tenant", None)
    if not isinstance(tenant, Tenant):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return tenant


async def tenant_session(
    request: Request, tenant: Annotated[Tenant, Depends(current_tenant)]
) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "SELECT set_config('app.gym_id', :gym_id, true),"
                " set_config('app.person_id', :person_id, true)"
            ),
            {"gym_id": str(tenant.gym_id), "person_id": str(tenant.person_id)},
        )
        # Commits when the endpoint returns, rolls back if it raises.
        yield session


# scope="function" commits before the response is sent, so a failed commit is a 500
# rather than a 200 for a write that never landed.
TenantSession = Annotated[AsyncSession, Depends(tenant_session, scope="function")]
