"""Staff roles per gym, and the sessions that require one.

Permissions follow the role, not the person: the same person can be owner at one gym
and a student at another (docs/product.md#users). A role is the `staff` row for the
person and the gym the request acts in, read on every request, so a change takes
effect on the next one.

A gym-scoped endpoint takes the session for the roles it serves instead of a bare
`TenantSession`: `StaffSession` for any staff role, `AdminSession` for owner and
admin changing how the gym is set up (its plans and settings), `LedgerSession` for owner and admin
on the ledger, `OwnerSession` for the owner alone (deleting a member, #157). Without the
role, the request is a 403; without a tenant, still a 401, before any database work.

The ledger is closed to coaches at the database too (migration 0006): RLS lets the
API read or write `ledger_entry` only for an owner or admin in `app.person_id`, so an
endpoint that took the wrong session still returns no ledger rows to a coach. The
exceptions are about the person acting: anyone may read the entries of their own
memberships and their dependents' (migration 0010), and add a pending transfer to one
of them, backed by a proof they uploaded (migration 0012).
"""

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy import Tenant, TenantSession, current_tenant


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    COACH = "coach"


STAFF_ROLES = frozenset(Role)
# Coaches never see money: the owner "will not share finances with part-time coaches".
LEDGER_ROLES = frozenset({Role.OWNER, Role.ADMIN})
# The gym's setup (plans, prices, settings and bank details) is the people who run it.
ADMIN_ROLES = frozenset({Role.OWNER, Role.ADMIN})
OWNER_ROLES = frozenset({Role.OWNER})

FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, "not allowed for your role in this gym")

ROLE_IN_GYM = "SELECT role FROM staff WHERE gym_id = :gym_id AND person_id = :person_id"


async def role_in_gym(session: AsyncSession, tenant: Tenant) -> Role | None:
    role = await session.scalar(
        text(ROLE_IN_GYM), {"gym_id": tenant.gym_id, "person_id": tenant.person_id}
    )
    return None if role is None else Role(role)


def requires(roles: frozenset[Role]) -> Callable[..., Awaitable[AsyncSession]]:
    """A dependency: the request's `TenantSession`, once its person holds one of `roles`."""

    async def session_for_role(
        tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
    ) -> AsyncSession:
        if await role_in_gym(session, tenant) not in roles:
            raise FORBIDDEN
        return session

    return session_for_role


StaffSession = Annotated[AsyncSession, Depends(requires(STAFF_ROLES))]
AdminSession = Annotated[AsyncSession, Depends(requires(ADMIN_ROLES))]
LedgerSession = Annotated[AsyncSession, Depends(requires(LEDGER_ROLES))]
OwnerSession = Annotated[AsyncSession, Depends(requires(OWNER_ROLES))]
