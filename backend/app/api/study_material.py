"""Material de estudio (#537, migration 0088): notes and links a coach shares on a class.

A coach puts material on one class (`/api/sessions/{id}/material`), or on a recurring
class (`/api/schedule/{id}/material`) so it shows on each of its classes from a date on
until it is removed. From a class of the schedule, `recurring` puts it on that class's
recurring class from the class's date. Its audience is chosen when it is shared: who
attended the class it shows on, the class's program, or the members of some plans.
Nothing reaches a member by default.

Any staff member reads a class's material, as they read the class. Whoever runs
classes (`attendance`) adds it to a class they coach, and, managing the gym's classes
too (`gym_setup`), to any; they and whoever shared it change it and remove it: the
timer's rule. An edit and a removal each write a row in
the gym's log (`study_material_changed`, `study_material_removed`). Removing hides it
from members at once; nothing deletes it.

A member reads theirs on the student page (`/api/me/material`), newest first and a page
at a time (#548: material never expires, so the list only grows): what
reaches them or one of their dependents, which the database decides
(`study_material_class_for`), not this module, with the class it reached them through
and, for a guardian it reaches only through their dependents, whom.

Deleting a recurring class's slot removes the material on it alone, with its row in the
log (`study_material_slot_gone`, `app.api.schedule`).
"""

import json
import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import gym_timezone, unprocessable
from app.domain.dates import gym_today
from app.permissions import FORBIDDEN, AttendanceSession, Permission, StaffSession, holds
from app.schemas.study_material import (
    Audience,
    Material,
    MaterialChange,
    MaterialIn,
    MyMaterial,
    MyMaterialPage,
)
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(tags=["classes"])
mine = APIRouter(prefix="/api/me", tags=["me"])

CurrentTenant = Annotated[Tenant, Depends(current_tenant)]

SESSION_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
SLOT_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "slot not found")
NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "material not found")

# Every material as staff read it, with the plans it names and who shared it.
SELECT = """
    SELECT m.id, m.title, m.body, m.links, m.audience, m.session_id, m.starts_on,
           gp.name AS shared_by_name, m.created_at, m.updated_at,
           coalesce((SELECT json_agg(json_build_object('id', p.id, 'name', p.name)
                                     ORDER BY lower(p.name), p.id)
                     FROM study_material_plan mp JOIN plan p ON p.id = mp.plan_id
                     WHERE mp.material_id = m.id), '[]') AS plans
    FROM study_material m
    LEFT JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.created_by
"""

NEWEST = " ORDER BY m.created_at DESC, m.id"

# What shows on a class: its own, and its recurring class's from the class's date on.
ON_SESSION = f"""{SELECT}
    WHERE m.removed_at IS NULL AND (m.session_id = :session OR (
        m.starts_on <= :day AND EXISTS (
            SELECT FROM study_material_slot ms
            WHERE ms.material_id = m.id AND ms.slot_id = :slot)))
    {NEWEST}
"""

ON_SLOT = f"""{SELECT}
    WHERE m.removed_at IS NULL AND EXISTS (
        SELECT FROM study_material_slot ms WHERE ms.material_id = m.id AND ms.slot_id = :slot)
    {NEWEST}
"""

INSERT = text(
    "INSERT INTO study_material (gym_id, session_id, starts_on, title, body, links,"
    " audience, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :session, :starts_on, :title, :body,"
    " :links, :audience, current_setting('app.person_id')::uuid)"
    " RETURNING id"
)

LINK_SLOT = text(
    "INSERT INTO study_material_slot (gym_id, material_id, slot_id)"
    " VALUES (current_setting('app.gym_id')::uuid, :material, :slot)"
)

LINK_PLANS = text(
    "INSERT INTO study_material_plan (gym_id, material_id, plan_id)"
    " SELECT current_setting('app.gym_id')::uuid, :material, p"
    " FROM unnest(CAST(:plans AS uuid[])) AS p"
)

# `now()` is the transaction's, as the policy wants it (0088).
INSERT_AUDIT = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, action, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :action, CAST(:detail AS jsonb))"
)

# What reaches the person acting or a dependent, as the database decides, whoever they
# are: a coach who trains reads only theirs here. Each with the class it reached them
# through (`study_material_class_for`), theirs first, and its day; and, when it reaches
# only dependents of theirs, whom, by name.
MINE = """
    SELECT m.id, m.title, m.body, m.links, c.name AS class_type_name,
           p.name AS program_name, m.starts_on IS NOT NULL AS recurring,
           coalesce(m.starts_on, (s.starts_at AT TIME ZONE g.timezone)::date) AS day,
           gp.name AS shared_by_name, m.created_at,
           CASE WHEN own.class_type_id IS NULL THEN theirs.names
                ELSE ARRAY[]::text[] END AS for_names
    FROM study_material m
    JOIN gym g ON g.id = m.gym_id
    LEFT JOIN session s ON s.id = m.session_id
    CROSS JOIN LATERAL (
        SELECT study_material_class_for(m.id, m.session_id, m.starts_on, m.audience, :me)
            AS class_type_id
    ) own
    CROSS JOIN LATERAL (
        SELECT array_agg(d.name ORDER BY lower(d.name), d.person_id) AS names,
               (array_agg(d.class_type_id ORDER BY lower(d.name), d.person_id))[1]
                   AS class_type_id
        FROM (
            SELECT dp.person_id, dp.name,
                   study_material_class_for(m.id, m.session_id, m.starts_on, m.audience,
                                            dp.person_id) AS class_type_id
            FROM guardian_link l
            JOIN gym_person dp ON dp.gym_id = l.gym_id
                              AND dp.person_id = l.dependent_person_id
            WHERE l.guardian_person_id = :me
        ) d
        WHERE d.class_type_id IS NOT NULL
    ) theirs
    JOIN class_type c ON c.id = coalesce(own.class_type_id, theirs.class_type_id)
    JOIN program p ON p.id = c.program_id
    LEFT JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.created_by
    WHERE m.removed_at IS NULL
      AND (CAST(:before_at AS timestamptz) IS NULL
           OR m.created_at < CAST(:before_at AS timestamptz)
           OR (m.created_at = CAST(:before_at AS timestamptz)
               AND m.id > CAST(:before_id AS uuid)))
    ORDER BY m.created_at DESC, m.id
    LIMIT :limit
"""

# How many a page of the student page's material holds, unless it asks for fewer.
MINE_PAGE = 20
MINE_PAGE_MAX = 50

EDITABLE = ("title", "body", "links", "audience", "starts_on")


def _material(row: Any) -> Material:
    values = dict(row._mapping)
    if isinstance(values["plans"], str):
        values["plans"] = json.loads(values["plans"])
    return Material.model_validate(values)


async def _list(session: AsyncSession, sql: str, params: dict[str, Any]) -> list[Material]:
    return [_material(row) for row in await session.execute(text(sql), params)]


async def _one(session: AsyncSession, material_id: uuid.UUID) -> Material:
    row = (
        await session.execute(
            text(f"{SELECT} WHERE m.id = :id AND m.removed_at IS NULL"), {"id": material_id}
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    return _material(row)


async def _may_share(
    session: AsyncSession, tenant: Tenant, coaches: set[uuid.UUID], shared_by: uuid.UUID | None
) -> None:
    """A 403 unless the person acting, who holds `attendance` (`AttendanceSession`),
    coaches the class, shared the material, or manages the classes (`gym_setup`): the
    timer's rule (`app.api.session_blocks`)."""
    if tenant.person_id in coaches or tenant.person_id == shared_by:
        return
    if not await holds(session, tenant, Permission.GYM_SETUP):
        raise FORBIDDEN


async def _require_plans(session: AsyncSession, plan_ids: list[uuid.UUID]) -> None:
    found = await session.scalar(
        text("SELECT count(*) FROM plan WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": list(set(plan_ids))},
    )
    if found != len(set(plan_ids)):
        raise unprocessable("plan_ids", "unknown_plan", "no such plan")


async def _insert(
    session: AsyncSession,
    body: MaterialIn,
    *,
    session_id: uuid.UUID | None,
    slot_id: uuid.UUID | None,
    starts_on: date | None,
) -> Material:
    await _require_plans(session, body.plan_ids)
    material: uuid.UUID = await session.scalar(
        INSERT,
        {
            "session": session_id,
            "starts_on": starts_on,
            "title": body.title,
            "body": body.body,
            "links": body.links,
            "audience": body.audience.value,
        },
    )
    if slot_id is not None:
        await session.execute(LINK_SLOT, {"material": material, "slot": slot_id})
    if body.plan_ids:
        await session.execute(LINK_PLANS, {"material": material, "plans": list(set(body.plan_ids))})
    return await _one(session, material)


async def _session_row(session: AsyncSession, session_id: uuid.UUID) -> Any:
    row = (
        await session.execute(
            text(
                "SELECT s.id, s.coach_id, s.slot_id, s.slot_date,"
                " (s.starts_at AT TIME ZONE g.timezone)::date AS day"
                " FROM session s JOIN gym g ON g.id = s.gym_id WHERE s.id = :id"
            ),
            {"id": session_id},
        )
    ).one_or_none()
    if row is None:
        raise SESSION_NOT_FOUND
    return row


async def _slot_coach(session: AsyncSession, slot_id: uuid.UUID) -> uuid.UUID:
    coach: uuid.UUID | None = await session.scalar(
        text("SELECT coach_id FROM schedule_slot WHERE id = :id"), {"id": slot_id}
    )
    if coach is None:
        raise SLOT_NOT_FOUND
    return coach


@router.get("/api/sessions/{session_id}/material")
async def session_material(session_id: uuid.UUID, session: StaffSession) -> list[Material]:
    """What shows on the class, newest first: its own, and its recurring class's from
    the class's date on."""
    row = await _session_row(session, session_id)
    return await _list(
        session, ON_SESSION, {"session": row.id, "slot": row.slot_id, "day": row.slot_date}
    )


@router.post("/api/sessions/{session_id}/material", status_code=status.HTTP_201_CREATED)
async def share_on_session(
    session_id: uuid.UUID, body: MaterialIn, tenant: CurrentTenant, session: AttendanceSession
) -> Material:
    """Share material on the class, or with `recurring` on its recurring class from
    `starts_on`, the class's date unless told (a 422 `not_recurring` for a one-off
    class)."""
    row = await _session_row(session, session_id)
    await _may_share(session, tenant, {row.coach_id}, None)
    if not body.recurring:
        if body.starts_on is not None:
            raise unprocessable("starts_on", "not_recurring", "only a recurring one has a date")
        return await _insert(session, body, session_id=row.id, slot_id=None, starts_on=None)
    if row.slot_id is None:
        raise unprocessable("recurring", "not_recurring", "the class is not of the schedule")
    return await _insert(
        session,
        body,
        session_id=None,
        slot_id=row.slot_id,
        starts_on=body.starts_on or row.slot_date,
    )


@router.get("/api/schedule/{slot_id}/material")
async def slot_material(slot_id: uuid.UUID, session: StaffSession) -> list[Material]:
    """The recurring class's material, newest first."""
    await _slot_coach(session, slot_id)
    return await _list(session, ON_SLOT, {"slot": slot_id})


@router.post("/api/schedule/{slot_id}/material", status_code=status.HTTP_201_CREATED)
async def share_on_slot(
    slot_id: uuid.UUID, body: MaterialIn, tenant: CurrentTenant, session: AttendanceSession
) -> Material:
    """Share material on the recurring class, from `starts_on`, today unless told."""
    coach = await _slot_coach(session, slot_id)
    await _may_share(session, tenant, {coach}, None)
    starts_on = body.starts_on or gym_today(await gym_timezone(session, tenant))
    return await _insert(session, body, session_id=None, slot_id=slot_id, starts_on=starts_on)


async def _held(session: AsyncSession, tenant: Tenant, material_id: uuid.UUID) -> Any:
    """The material, locked, once the person acting may change it."""
    row = (
        await session.execute(
            text(
                "SELECT m.id, m.title, m.body, m.links, m.audience, m.starts_on,"
                " m.created_by, s.coach_id AS session_coach,"
                " ARRAY(SELECT sl.coach_id FROM study_material_slot ms"
                "  JOIN schedule_slot sl ON sl.id = ms.slot_id"
                "  WHERE ms.material_id = m.id) AS slot_coaches,"
                " ARRAY(SELECT mp.plan_id FROM study_material_plan mp"
                "  WHERE mp.material_id = m.id) AS plan_ids"
                " FROM study_material m LEFT JOIN session s ON s.id = m.session_id"
                " WHERE m.id = :id AND m.removed_at IS NULL FOR UPDATE OF m"
            ),
            {"id": material_id},
        )
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    coaches = {*row.slot_coaches, *([row.session_coach] if row.session_coach else [])}
    await _may_share(session, tenant, coaches, row.created_by)
    return row


async def _audit(session: AsyncSession, action: str, **detail: Any) -> None:
    await session.execute(INSERT_AUDIT, {"action": action, "detail": json.dumps(detail)})


def _shown(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


@router.patch("/api/material/{material_id}")
async def change_material(
    material_id: uuid.UUID, body: MaterialChange, tenant: CurrentTenant, session: AttendanceSession
) -> Material:
    """Change what was sent, with a row in the log of each field before and after.
    Nothing that changes nothing is logged. Only a recurring one has `starts_on`."""
    row = await _held(session, tenant, material_id)
    sent = body.model_fields_set
    after: dict[str, Any] = {f: getattr(body, f) for f in EDITABLE if f in sent}
    if "audience" in after:
        after["audience"] = after["audience"].value
    if "starts_on" in after and row.starts_on is None:
        raise unprocessable("starts_on", "not_recurring", "only a recurring one has a date")
    audience = Audience(after.get("audience", row.audience))
    old_plans = sorted(map(str, row.plan_ids))
    plans = old_plans
    if "plan_ids" in sent and body.plan_ids is not None:
        await _require_plans(session, body.plan_ids)
        plans = sorted({str(p) for p in body.plan_ids})
    if audience is not Audience.PLANS:
        if body.plan_ids:
            raise unprocessable("plan_ids", "value_error", "only an audience of plans names plans")
        plans = []
    elif not plans:
        raise unprocessable("plan_ids", "value_error", "an audience of plans names at least one")
    changed = {f: v for f, v in after.items() if getattr(row, f) != v}
    before = {f: _shown(getattr(row, f)) for f in changed}
    shown_after = {f: _shown(v) for f, v in changed.items()}
    if plans != old_plans:
        before["plan_ids"], shown_after["plan_ids"] = old_plans, plans
    if not shown_after:
        return await _one(session, material_id)

    assignments = "".join(f"{f} = :{f}, " for f in changed)
    await session.execute(
        text(
            f"UPDATE study_material SET {assignments}updated_at = now(),"
            " updated_by = current_setting('app.person_id')::uuid WHERE id = :id"
        ),
        {**changed, "id": material_id},
    )
    if plans != old_plans:
        await session.execute(
            text("DELETE FROM study_material_plan WHERE material_id = :id"), {"id": material_id}
        )
        if plans:
            await session.execute(LINK_PLANS, {"material": material_id, "plans": plans})
    await _audit(
        session,
        "study_material_changed",
        material_id=str(material_id),
        before=before,
        after=shown_after,
    )
    return await _one(session, material_id)


@router.delete("/api/material/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_material(
    material_id: uuid.UUID, tenant: CurrentTenant, session: AttendanceSession
) -> Response:
    """Remove it: members no longer see it, and the log keeps who removed it."""
    row = await _held(session, tenant, material_id)
    await session.execute(
        text(
            "UPDATE study_material SET removed_at = now(),"
            " removed_by = current_setting('app.person_id')::uuid WHERE id = :id"
        ),
        {"id": material_id},
    )
    await _audit(session, "study_material_removed", material_id=str(material_id), title=row.title)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _cursor(material: MyMaterial) -> str:
    """Where the page after `material` starts: its `created_at` and id, the list's order."""
    return f"{material.created_at.isoformat()}_{material.id}"


def _after(cursor: str) -> tuple[datetime, uuid.UUID]:
    """A cursor `_cursor` wrote, or a 422."""
    at, _, material = cursor.rpartition("_")
    try:
        parsed = (datetime.fromisoformat(at), uuid.UUID(material))
    except ValueError:
        parsed = None
    if parsed is not None and parsed[0].tzinfo is not None:
        return parsed
    raise RequestValidationError(
        [{"type": "value_error", "msg": "not a cursor of this list", "loc": ("query", "before")}]
    )


@mine.get("/material")
async def my_material(
    tenant: CurrentTenant,
    session: TenantSession,
    before: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MINE_PAGE_MAX)] = MINE_PAGE,
) -> MyMaterialPage:
    """The material that reaches the signed-in person or a dependent, newest first, a
    page at a time: `before`, the `next` of the page before, reads the one after it,
    nothing repeated or skipped. One that reaches only dependents names them
    (`for_names`)."""
    at, material = _after(before) if before is not None else (None, None)
    result = await session.execute(
        text(MINE),
        {"me": tenant.person_id, "limit": limit + 1, "before_at": at, "before_id": material},
    )
    items = [MyMaterial.model_validate(row, from_attributes=True) for row in result]
    more = len(items) > limit
    items = items[:limit]
    return MyMaterialPage(items=items, next=_cursor(items[-1]) if more else None)
