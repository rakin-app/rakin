"""Cargos (`/api/titles`): the gym's own roles, each a name and a set of permissions.

Rakin defines only the list of permissions and the presets (`app.permissions`,
docs/design/expenses-and-officers.md, sections 1, 2 and 8); the gym names its roles,
ticks what each may do and marks which its students see:

- `GET`: the roles, with how many hold each today, and whether the gym has yet to choose
  how its team is organised.
- `POST`: a new role; `PATCH /{id}`: its name, permissions or visibility. What a
  permission implies is stored with it (`money_write` brings `money_read`). An edit
  applies to everyone holding the role at once.
- `POST /{id}/archive`: a role is archived, never deleted, so the history still reads
  who held it; it leaves Cargos and every picker. One somebody holds today or from a
  later day is refused (409): end those appointments first, so nobody keeps what an
  archived role allowed without anyone seeing it.
- `POST /presets`: add a preset's roles beside the gym's, each unless the gym already
  has a live role of its name, so adding one twice adds nothing twice.
- `POST /setup`: the first-run setup of a new gym, once: a preset, or none. Every gym is
  created with the Academia roles (migration 0065); choosing another, or none, archives
  them, since nobody holds them yet.

Creating, editing and archiving follow the strictly-fewer rule (section 4): the role,
before and after, holds a proper subset of the permissions of whoever does it, so
nobody grants a permission they lack. Each is audited: `title_created`, and
`title_changed` with the role before and after.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.staff import NOT_FEWER_ROLE, acting_standing, gym_today, record
from app.permissions import (
    ACADEMIA,
    PRESETS,
    Permission,
    Standing,
    TeamSession,
    manages,
    may_change_role,
    preset_title_id,
    with_implied,
)
from app.schemas.staff import (
    PresetChoice,
    SetupChoice,
    Title,
    TitleChange,
    TitleDraft,
    Titles,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/titles", tags=["staff"])

NO_TITLE = HTTPException(status.HTTP_404_NOT_FOUND, "no such role in this gym")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the gym has a role of that name")
HELD = HTTPException(
    status.HTTP_409_CONFLICT, "somebody holds this role: end their appointments first"
)
CHOSEN = HTTPException(status.HTTP_409_CONFLICT, "the gym has chosen how its team is organised")

TITLE_CREATED = "title_created"
TITLE_CHANGED = "title_changed"

Acting = Annotated[Tenant, Depends(current_tenant)]

# The gym's own live roles, with how many hold each today. `system` roles (#320) are
# Rakin's, not the gym's to edit.
SELECT_TITLES = """
    SELECT t.id, t.name, t.permissions, t.public, t.preset,
           (SELECT count(DISTINCT st.person_id) FROM staff_title st
            WHERE st.title_id = t.id AND st.starts_on <= :today
              AND (st.ends_on IS NULL OR :today < st.ends_on)) AS holders
    FROM gym_title t
    WHERE t.archived_at IS NULL AND t.system IS NULL
"""

# Has a gym chosen, or has it appointed anyone already (a gym seeded with its team)?
SETUP_PENDING = """
    SELECT g.roles_chosen_at IS NULL AND NOT EXISTS (SELECT FROM staff_title)
    FROM gym g
"""

# Someone holds the role today or from a later day.
HELD_LIVE = """
    SELECT true FROM staff_title st
    WHERE st.title_id = :id AND (st.ends_on IS NULL OR st.ends_on > greatest(st.starts_on, :today))
    LIMIT 1
"""


def _ordered(permissions: frozenset[Permission]) -> list[Permission]:
    return [p for p in Permission if p in permissions]


def _title(row: Any, acting: Standing) -> Title:
    permissions = frozenset(map(Permission, row.permissions))
    return Title(
        id=row.id,
        name=row.name,
        permissions=_ordered(permissions),
        public=row.public,
        preset=row.preset,
        holders=row.holders,
        manageable=manages(acting, permissions),
    )


def _state(name: str, permissions: frozenset[Permission], public: bool) -> dict[str, Any]:
    """A role as its log row records it."""
    return {"name": name, "permissions": _ordered(permissions), "public": public}


async def _name_taken(
    session: AsyncSession, name: str, other_than: uuid.UUID | None = None
) -> bool:
    taken = await session.scalar(
        text(
            "SELECT true FROM gym_title WHERE archived_at IS NULL AND lower(name) = lower(:name)"
            " AND id IS DISTINCT FROM :id"
        ),
        {"name": name, "id": other_than},
    )
    return bool(taken)


async def _create(
    session: AsyncSession,
    name: str,
    permissions: frozenset[Permission],
    public: bool,
    preset: str | None = None,
    title_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Add a role after the gym's others, and log it; a 409 when its name is taken."""
    created: uuid.UUID | None = await session.scalar(
        text(
            "INSERT INTO gym_title (id, gym_id, name, permissions, public, preset, sort)"
            " SELECT coalesce(CAST(:id AS uuid), gen_random_uuid()),"
            "        current_setting('app.gym_id')::uuid, :name, :permissions, :public, :preset,"
            "        coalesce((SELECT max(sort) FROM gym_title), 0) + 1"
            " ON CONFLICT DO NOTHING RETURNING id"
        ),
        {
            "id": title_id,
            "name": name,
            "permissions": [p.value for p in _ordered(permissions)],
            "public": public,
            "preset": preset,
        },
    )
    if created is None:
        raise NAME_TAKEN
    await record(
        session,
        TITLE_CREATED,
        {"title_id": created, "preset": preset, **_state(name, permissions, public)},
        None,
    )
    return created


async def _live(session: AsyncSession, title_id: uuid.UUID) -> Any:
    """The gym's own live role, locked until the request commits."""
    row = (
        await session.execute(
            text(
                "SELECT id, name, permissions, public FROM gym_title"
                " WHERE id = :id AND archived_at IS NULL AND system IS NULL FOR UPDATE"
            ),
            {"id": title_id},
        )
    ).one_or_none()
    if row is None:
        raise NO_TITLE
    return row


async def _archive(session: AsyncSession, row: Any) -> None:
    await session.execute(
        text("UPDATE gym_title SET archived_at = now() WHERE id = :id"), {"id": row.id}
    )
    state = _state(row.name, frozenset(map(Permission, row.permissions)), row.public)
    await record(
        session,
        TITLE_CHANGED,
        {
            "title_id": row.id,
            "before": {**state, "archived": False},
            "after": {**state, "archived": True},
        },
        None,
    )


async def _add_preset(session: AsyncSession, acting: Standing, preset: str) -> list[uuid.UUID]:
    """Add the roles of `preset` the gym has no live role of the name of; a 403, adding
    none, when one of them is not strictly fewer than `acting`."""
    missing = [t for t in PRESETS[preset] if not await _name_taken(session, t.name)]
    if not all(manages(acting, t.permissions) for t in missing):
        raise NOT_FEWER_ROLE
    gym_id = uuid.UUID(await session.scalar(text("SELECT current_setting('app.gym_id')")))
    added = []
    for title in missing:
        # The id 0065 gives a preset's role, while it is free: an archived one keeps it.
        derived = preset_title_id(gym_id, preset, title.key)
        free = not await session.scalar(
            text("SELECT true FROM gym_title WHERE id = :id"), {"id": derived}
        )
        added.append(
            await _create(
                session,
                title.name,
                title.permissions,
                title.public,
                preset,
                derived if free else None,
            )
        )
    return added


async def _titles(session: AsyncSession, acting: Standing) -> list[Title]:
    rows = await session.execute(
        text(f"{SELECT_TITLES} ORDER BY t.sort, lower(t.name), t.id"),
        {"today": await gym_today(session)},
    )
    return [_title(row, acting) for row in rows]


async def _one(session: AsyncSession, acting: Standing, title_id: uuid.UUID) -> Title:
    row = (
        await session.execute(
            text(f"{SELECT_TITLES} AND t.id = :id"),
            {"id": title_id, "today": await gym_today(session)},
        )
    ).one()
    return _title(row, acting)


@router.get("")
async def list_titles(tenant: Acting, session: TeamSession) -> Titles:
    acting = await acting_standing(session, tenant)
    pending = bool(await session.scalar(text(SETUP_PENDING)))
    return Titles(titles=await _titles(session, acting), setup_pending=pending)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_title(body: TitleDraft, tenant: Acting, session: TeamSession) -> Title:
    acting = await acting_standing(session, tenant)
    permissions = with_implied(frozenset(body.permissions))
    if not manages(acting, permissions):
        raise NOT_FEWER_ROLE
    created = await _create(session, body.name, permissions, body.public)
    return await _one(session, acting, created)


@router.patch("/{title_id}")
async def change_title(
    title_id: uuid.UUID, body: TitleChange, tenant: Acting, session: TeamSession
) -> Title:
    """Rename a role, change what it may do or who sees it. Its holders' history keeps
    the name it had when they were appointed."""
    acting = await acting_standing(session, tenant)
    row = await _live(session, title_id)
    before = frozenset(map(Permission, row.permissions))
    after = before if body.permissions is None else with_implied(frozenset(body.permissions))
    if not may_change_role(acting, before, after):
        raise NOT_FEWER_ROLE
    name = row.name if body.name is None else body.name
    public = row.public if body.public is None else body.public
    if name.lower() != row.name.lower() and await _name_taken(session, name, title_id):
        raise NAME_TAKEN
    old, new = _state(row.name, before, row.public), _state(name, after, public)
    if new != old:
        await session.execute(
            text(
                "UPDATE gym_title SET name = :name, permissions = :permissions, public = :public"
                " WHERE id = :id"
            ),
            {**new, "id": title_id},
        )
        await record(
            session, TITLE_CHANGED, {"title_id": title_id, "before": old, "after": new}, None
        )
    return await _one(session, acting, title_id)


@router.post("/{title_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_title(title_id: uuid.UUID, tenant: Acting, session: TeamSession) -> Response:
    acting = await acting_standing(session, tenant)
    row = await _live(session, title_id)
    if not manages(acting, frozenset(map(Permission, row.permissions))):
        raise NOT_FEWER_ROLE
    held = await session.scalar(
        text(HELD_LIVE), {"id": title_id, "today": await gym_today(session)}
    )
    if held:
        raise HELD
    await _archive(session, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/presets", status_code=status.HTTP_201_CREATED)
async def add_preset(body: PresetChoice, tenant: Acting, session: TeamSession) -> list[Title]:
    """ "Agregar plantilla": the preset's roles the gym has not, by name; the ones added."""
    acting = await acting_standing(session, tenant)
    added = set(await _add_preset(session, acting, body.preset))
    return [t for t in await _titles(session, acting) if t.id in added]


@router.post("/setup")
async def choose_setup(body: SetupChoice, tenant: Acting, session: TeamSession) -> Titles:
    """A new gym's first choice: keep the Academia roles it was created with, or have
    the Club federado's, or none; a 409 once it has chosen, or appointed anyone."""
    acting = await acting_standing(session, tenant)
    if not await session.scalar(text(SETUP_PENDING)):
        raise CHOSEN
    if body.preset != ACADEMIA:
        academia = await session.execute(
            text(
                "SELECT id, name, permissions, public FROM gym_title"
                " WHERE preset = :preset AND archived_at IS NULL FOR UPDATE"
            ),
            {"preset": ACADEMIA},
        )
        for row in academia.all():
            await _archive(session, row)
        if body.preset is not None:
            await _add_preset(session, acting, body.preset)
    await session.execute(text("UPDATE gym SET roles_chosen_at = now()"))
    return Titles(titles=await _titles(session, acting), setup_pending=False)
