"""What the person acting may do in a gym, and the sessions that require it (#308).

A gym defines its own roles (`gym_title`: a name and a set of permissions) and
appoints people to them (`staff_title`, from one day to another). A person is on the
team when they have a `staff` row and either hold the account (`staff.account_holder`,
the titular: exactly one per gym, holding every permission) or a current appointment.
Their permissions are the union of the roles they hold today, in the gym's timezone,
tested on every request: an appointment ending today grants nothing today, one starting
tomorrow nothing yet, whatever a job has or has not run
(docs/design/expenses-and-officers.md, sections 1 to 3 and 7).

A gym-scoped endpoint takes the session for the one permission it needs instead of a
bare `TenantSession` (#310): `StaffSession` for anyone on the team (the roster, the
schedule, what a class is), `LedgerReadSession` to read money (`money_read`),
`LedgerSession` to record it and to start, change, freeze or end a student's plan
(`money_write`), `MembersSession` for the members (`members_manage`: groups, the join
link, enrolling, Dar de baja), `MembersAddSession` to add a student without a plan and
keep their record (`members_add`), `AttendanceSession` to run a class (`attendance`),
`AdminSession` for the gym's setup (`gym_setup`), `TeamSession` for the team
(`team_manage`), and `OwnerSession` for the titular alone (deleting a member, #157).
Without it, the request is a 403; without a tenant, still a 401, before any database
work. An endpoint every staff member may read but whose answer carries money (a plan's
price, a membership's discount) takes `SeesMoney` too, and leaves the amounts out
without `money_read` (#205). Each gate is listed in `GATES`, which
`tests/test_endpoint_permissions.py` reads to fail on an endpoint that asks for none.

The team is managed by the strictly-fewer rule (section 4, `manages`): you appoint, end
or change an appointment only for a person whose permissions are a proper subset of
yours, and only to a role whose permissions are a proper subset of yours. The titular
manages everyone, and nobody manages the titular.

Every gym starts with the Academia preset's roles, Administrador and Coach, carrying
what today's admin and coach do (migration 0065). The database holds the same
permissions on its own: every policy that once named a role asks `app_can` (migration
0067), which reads the titular flag and the current appointments as `STANDING_IN_GYM`
does, so an endpoint that took the wrong session still reads no money it may not.
`staff.role` is still written by the staff API alongside the appointments, and read by
nothing, until #313.

Each permission is its own literal: two that hold the same people today are never
defined as one another, so narrowing one later narrows only it
(`tests/test_permissions.py` holds them apart).
"""

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy import Tenant, TenantSession, current_tenant


class Permission(StrEnum):
    MONEY_READ = "money_read"
    MONEY_WRITE = "money_write"
    EXPENSES_READ = "expenses_read"
    EXPENSES_WRITE = "expenses_write"
    MEMBERS_MANAGE = "members_manage"
    MEMBERS_ADD = "members_add"
    ATTENDANCE = "attendance"
    GYM_SETUP = "gym_setup"
    TEAM_MANAGE = "team_manage"


# What holding one permission brings with it. Stored on the role, never inferred at
# read time: a role with `money_write` lists `money_read` too, and a CHECK refuses one
# without it (migration 0065).
IMPLIES: dict[Permission, Permission] = {
    Permission.MONEY_WRITE: Permission.MONEY_READ,
    Permission.EXPENSES_WRITE: Permission.EXPENSES_READ,
    Permission.MEMBERS_MANAGE: Permission.MEMBERS_ADD,
}


@dataclass(frozen=True)
class PresetTitle:
    """A role a preset adds to a gym. `key` names it within the preset, for its id."""

    key: str
    name: str
    permissions: frozenset[Permission]
    public: bool


# What every gym starts with, today's admin and coach (migration 0065 adds them to each
# gym when it is created, under `preset_title_id`). A coach adds a student without a
# plan and runs their own classes, nothing else of `members_manage`.
ACADEMIA = "academia"
ADMINISTRADOR = PresetTitle(
    "administrador",
    "Administrador",
    frozenset(
        {
            Permission.MONEY_READ,
            Permission.MONEY_WRITE,
            Permission.MEMBERS_MANAGE,
            Permission.MEMBERS_ADD,
            Permission.ATTENDANCE,
            Permission.GYM_SETUP,
            Permission.TEAM_MANAGE,
        }
    ),
    public=False,
)
COACH = PresetTitle(
    "coach", "Coach", frozenset({Permission.ATTENDANCE, Permission.MEMBERS_ADD}), public=True
)

# The board of a club (section 2). No gym is given it yet: Cargos adds it (#311).
CLUB_FEDERADO = "club_federado"
PRESIDENTE = PresetTitle(
    "presidente",
    "Presidente",
    frozenset({Permission.MONEY_READ, Permission.EXPENSES_READ, Permission.TEAM_MANAGE}),
    public=True,
)
TESORERO = PresetTitle(
    "tesorero",
    "Tesorero",
    frozenset(
        {
            Permission.MONEY_READ,
            Permission.MONEY_WRITE,
            Permission.EXPENSES_READ,
            Permission.EXPENSES_WRITE,
        }
    ),
    public=True,
)
SECRETARIO = PresetTitle(
    "secretario",
    "Secretario",
    frozenset({Permission.MEMBERS_MANAGE, Permission.MEMBERS_ADD}),
    public=True,
)
DIRECTOR = PresetTitle("director", "Director", frozenset(), public=True)
DELEGADO = PresetTitle("delegado", "Delegado", frozenset({Permission.ATTENDANCE}), public=True)
PRESETS: dict[str, tuple[PresetTitle, ...]] = {
    ACADEMIA: (ADMINISTRADOR, COACH),
    CLUB_FEDERADO: (PRESIDENTE, TESORERO, SECRETARIO, DIRECTOR, DELEGADO, COACH),
}


def preset_title_id(gym_id: uuid.UUID, preset: str, key: str) -> uuid.UUID:
    """The id of a preset's role in a gym, as `gym_title_preset_id` (0065) derives it."""
    return uuid.UUID(hashlib.md5(f"{gym_id}/gym_title/{preset}/{key}".encode()).hexdigest())


@dataclass(frozen=True)
class Standing:
    """Someone on the team: whether they hold the account, and what they may do."""

    account_holder: bool
    permissions: frozenset[Permission]

    def holds(self, *needed: Permission) -> bool:
        return self.permissions.issuperset(needed)


NOBODY = Standing(account_holder=False, permissions=frozenset())
"""The standing of someone not on the team, as the rule of section 4 weighs them."""


def manages(acting: Standing, permissions: frozenset[Permission]) -> bool:
    """Whether `acting` may manage a person or a role holding `permissions` (section 4):
    the titular any, anyone else only a proper subset of their own, never by count. So
    nobody grants a permission they lack."""
    return acting.account_holder or permissions < acting.permissions


def may_change_role(
    acting: Standing, before: frozenset[Permission], after: frozenset[Permission]
) -> bool:
    """Whether `acting` may edit a role from `before` to `after`: the rule holds of
    both, so a role nobody may touch is not edited into one they may (#311's Cargos)."""
    return manages(acting, before) and manages(acting, after)


FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, "not allowed for your role in this gym")

# An appointment `st` is current today in the gym's timezone (`g`): half-open, so the
# day it ends on is the first without it.
CURRENT_APPOINTMENT = """
    st.starts_on <= (now() AT TIME ZONE g.timezone)::date
    AND (st.ends_on IS NULL OR (now() AT TIME ZONE g.timezone)::date < st.ends_on)
"""

# One query: the staff row, the titular flag, and the union of the permissions of the
# person's current appointments. `appointed` tells a role with no permissions from none.
STANDING_IN_GYM = f"""
    SELECT s.account_holder,
           bool_or(st.id IS NOT NULL) AS appointed,
           coalesce(array_agg(DISTINCT p.permission)
                    FILTER (WHERE p.permission IS NOT NULL), '{{}}') AS permissions
    FROM staff s
    JOIN gym g ON g.id = s.gym_id
    LEFT JOIN staff_title st
        ON st.gym_id = s.gym_id AND st.person_id = s.person_id AND {CURRENT_APPOINTMENT}
    LEFT JOIN gym_title t ON t.id = st.title_id
    LEFT JOIN LATERAL unnest(t.permissions) AS p (permission) ON true
    WHERE s.gym_id = :gym_id AND s.person_id = :person_id
    GROUP BY s.account_holder
"""


def holder_of(permission: Permission) -> str:
    """A condition on the `staff` row `s`: its person holds `permission` today, as the
    titular or by a current appointment. For queries that list who may do something."""
    return f"""(s.account_holder OR EXISTS (
        SELECT FROM staff_title st
        JOIN gym_title t ON t.id = st.title_id
        JOIN gym g ON g.id = st.gym_id
        WHERE st.gym_id = s.gym_id AND st.person_id = s.person_id
          AND '{permission.value}' = ANY (t.permissions) AND {CURRENT_APPOINTMENT}
    ))"""


async def standing_in_gym(session: AsyncSession, tenant: Tenant) -> Standing | None:
    """The person acting's standing in the gym; `None` when they are not on the team:
    no `staff` row, or one with neither the titular flag nor a current appointment."""
    return await standing_of(session, tenant.gym_id, tenant.person_id)


async def standing_of(
    session: AsyncSession, gym_id: uuid.UUID, person_id: uuid.UUID | None
) -> Standing | None:
    """`person_id`'s standing in `gym_id`, as `standing_in_gym` reads the person acting's."""
    row = (
        await session.execute(text(STANDING_IN_GYM), {"gym_id": gym_id, "person_id": person_id})
    ).one_or_none()
    if row is None:
        return None
    if row.account_holder:
        return Standing(account_holder=True, permissions=frozenset(Permission))
    if not row.appointed:
        return None
    return Standing(account_holder=False, permissions=frozenset(map(Permission, row.permissions)))


async def permissions_in_gym(session: AsyncSession, tenant: Tenant) -> frozenset[Permission] | None:
    """What the person acting may do in the gym; `None` when they are not on the team.
    The titular holds every permission."""
    standing = await standing_in_gym(session, tenant)
    return None if standing is None else standing.permissions


async def holds(session: AsyncSession, tenant: Tenant, *needed: Permission) -> bool:
    """Whether the person acting is on the team and holds every one of `needed`."""
    standing = await standing_in_gym(session, tenant)
    return standing is not None and standing.holds(*needed)


Gate = Callable[..., Awaitable[AsyncSession]]

# Each session dependency that refuses whoever may not use an endpoint, and what it asks:
# the permissions it needs (none: being on the team), or `TITULAR`.
TITULAR = "titular"
GATES: dict[Gate, frozenset[Permission] | str] = {}


def requires(*needed: Permission) -> Gate:
    """A dependency: the request's `TenantSession`, once its person is on the team and
    holds every one of `needed` (with none, being on the team is enough)."""

    async def session_for(
        tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
    ) -> AsyncSession:
        standing = await standing_in_gym(session, tenant)
        if standing is None or not standing.holds(*needed):
            raise FORBIDDEN
        return session

    GATES[session_for] = frozenset(needed)
    return session_for


async def account_holder_session(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> AsyncSession:
    """The request's `TenantSession`, once its person holds the account. Not a
    permission: no role carries it (section 1 of the design)."""
    standing = await standing_in_gym(session, tenant)
    if standing is None or not standing.account_holder:
        raise FORBIDDEN
    return session


GATES[account_holder_session] = TITULAR

StaffSession = Annotated[AsyncSession, Depends(requires())]
LedgerReadSession = Annotated[AsyncSession, Depends(requires(Permission.MONEY_READ))]
LedgerSession = Annotated[AsyncSession, Depends(requires(Permission.MONEY_WRITE))]
MembersSession = Annotated[AsyncSession, Depends(requires(Permission.MEMBERS_MANAGE))]
MembersAddSession = Annotated[AsyncSession, Depends(requires(Permission.MEMBERS_ADD))]
AttendanceSession = Annotated[AsyncSession, Depends(requires(Permission.ATTENDANCE))]
AdminSession = Annotated[AsyncSession, Depends(requires(Permission.GYM_SETUP))]
TeamSession = Annotated[AsyncSession, Depends(requires(Permission.TEAM_MANAGE))]
OwnerSession = Annotated[AsyncSession, Depends(account_holder_session)]


async def sees_money(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> bool:
    """Whether the person acting may see amounts: they hold `money_read`."""
    return await holds(session, tenant, Permission.MONEY_READ)


SeesMoney = Annotated[bool, Depends(sees_money)]
