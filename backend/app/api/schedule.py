"""The current gym's weekly schedule: its slots and its closed days (#167, migration 0035).

A slot is a class of the timetable, "Lun/Mié/Vie 19:00, 90 min, Fundamentos". Its
sessions are made ahead of time, through the next `HORIZON_DAYS` days in the gym's
timezone today included (`app.domain.schedule`): every night by the `schedule` job
(`app.jobs.schedule`), and here when a slot is saved. One slot makes one session per
date, however often it runs.

Changing a slot changes it from a date on, today by default ("esta y las siguientes"
from a class is the change from that class's date). Nothing before that date changes,
and neither does a class that has started or has attendance: those are what happened.
A change from after the slot's first date ends the slot the day before and starts a
new one with the change, so the timetable before it still reads as it was. The
classes from the date on that have not started and have no attendance are made to
match: moved to the new time, with the new type, coach and duration, and the slot's
topic and tags where the class still had the old ones; cancelled ones stay cancelled. Those on
a weekday the slot no longer runs, or after it ends, are deleted, and the dates it now
runs that have no class get one. A class changed alone ("solo esta clase",
`PATCH /api/sessions/{id}`) keeps its slot and date; a later change of its slot
rewrites it like the rest.

Deleting a slot deletes its classes that have not started and have no attendance;
the others stay, as one-off classes.

A closed day ("Cerrado") is a date with no classes: the schedule makes none on it, and
closing one deletes the scheduled classes that fall on it that have not started and
have no attendance. "Falls on it" is where the class is now, its `starts_at` on that
date in the gym's timezone: a class moved off the day on its own stays, and one moved
onto it goes. Reopening it makes the date's classes again, except one moved elsewhere,
which still holds its slot and date.

No class is made whose start has passed, so saving a slot in the evening makes today's
class only if it has yet to begin.

Saving a slot makes its classes through the horizon again, a deleted one included;
the nightly run only adds the dates after the last it made, so a class deleted on its
own stays deleted.

Only an owner or admin may read or change the schedule.
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.class_tags import require_tags, set_tags, tags_of_slot
from app.api.sessions import (
    gym_timezone,
    require_class_type,
    require_coach,
    unprocessable,
)
from app.domain.dates import gym_today, start_of_local_day
from app.domain.schedule import horizon
from app.roles import AdminSession
from app.schemas.classes import ClassKind
from app.schemas.schedule import ClosedDay, ClosedDayChange, Slot, SlotCreate, SlotUpdate
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/schedule", tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "slot not found")

SELECT_SLOT = f"""
    SELECT s.id, s.class_type_id, c.name AS class_type_name, c.program_id,
           p.name AS program_name, c.active AS class_type_active, s.weekdays,
           s.start_time, s.duration_minutes, s.coach_id, gp.name AS coach_name, s.topic,
           {tags_of_slot("s")} AS tags, s.valid_from, s.valid_to, s.created_at, s.updated_at
    FROM schedule_slot s
    JOIN class_type c ON c.id = s.class_type_id
    JOIN program p ON p.id = c.program_id
    JOIN gym_person gp ON gp.person_id = s.coach_id
"""

ORDER_SLOTS = " ORDER BY s.weekdays[1], s.start_time, lower(c.name), s.valid_from"

# A slot's classes that the schedule may still change: not started, nobody marked.
UNTOUCHED = (
    "slot_id = :slot AND starts_at > now()"
    " AND NOT EXISTS (SELECT FROM attendance a WHERE a.session_id = session.id)"
)

SLOT_FIELDS = (
    "class_type_id",
    "weekdays",
    "start_time",
    "duration_minutes",
    "coach_id",
    "topic",
    "valid_from",
    "valid_to",
)


async def _get(session: AsyncSession, slot_id: uuid.UUID, *, lock: bool = False) -> Slot:
    sql = f"{SELECT_SLOT} WHERE s.id = :id{' FOR UPDATE OF s' if lock else ''}"
    row = (await session.execute(text(sql), {"id": slot_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return Slot.model_validate(row, from_attributes=True)


async def generate(
    session: AsyncSession,
    first: date,
    last: date,
    *,
    slot_id: uuid.UUID | None = None,
    refill: bool = False,
) -> int:
    """Make the classes due from `first` to `last` (see migration 0035); how many."""
    made: int = await session.scalar(
        text("SELECT schedule_sessions(:first, :last, :slot, :refill)"),
        {"first": first, "last": last, "slot": slot_id, "refill": refill},
    )
    return made


async def _refill(session: AsyncSession, zone: str, slot_id: uuid.UUID) -> None:
    await generate(session, *horizon(gym_today(zone)), slot_id=slot_id, refill=True)


async def _delete_sessions(session: AsyncSession, where: str, params: dict[str, Any]) -> None:
    """Delete the sessions `where` matches, with their timer blocks. Callers match only
    ones nobody is marked at, so no credits are owed back."""
    result = await session.execute(text(f"SELECT id FROM session WHERE {where}"), params)
    ids = list(result.scalars())
    if not ids:
        return
    await session.execute(
        text("DELETE FROM session_block WHERE session_id = ANY(:ids)"), {"ids": ids}
    )
    await session.execute(text("DELETE FROM session WHERE id = ANY(:ids)"), {"ids": ids})


@router.get("")
async def list_slots(session: AdminSession) -> list[Slot]:
    """Every slot, ended ones included, by first weekday and start time."""
    result = await session.execute(text(f"{SELECT_SLOT}{ORDER_SLOTS}"))
    return [Slot.model_validate(row, from_attributes=True) for row in result]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_slot(
    body: SlotCreate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Slot:
    """A new slot, its classes made through the horizon at once."""
    await require_class_type(session, body.class_type_id)
    await require_coach(session, body.coach_id)
    await require_tags(session, body.tag_ids, [], "tag_ids")
    zone = await gym_timezone(session, tenant)
    valid_from = body.valid_from or gym_today(zone)
    if body.valid_to is not None and body.valid_to < valid_from:
        raise unprocessable("valid_to", "before_valid_from", "valid_to is before valid_from")
    slot_id = await session.scalar(
        text(
            "INSERT INTO schedule_slot (gym_id, class_type_id, weekdays, start_time,"
            " duration_minutes, coach_id, topic, valid_from, valid_to)"
            " VALUES (current_setting('app.gym_id')::uuid, :class_type_id, :weekdays,"
            " :start_time, :duration_minutes, :coach_id, :topic, :valid_from, :valid_to)"
            " RETURNING id"
        ),
        {**body.model_dump(exclude={"tag_ids"}), "valid_from": valid_from},
    )
    await set_tags(session, "schedule_slot_tag", "slot_id", slot_id, body.tag_ids)
    await _refill(session, zone, slot_id)
    return await _get(session, slot_id)


async def _require_plans_fit(session: AsyncSession, slot_id: uuid.UUID, start: date) -> None:
    """A 422 unless every class about to become an open mat has a plan that fits one:
    none, or one sparring block, as `PATCH /api/sessions/{id}` holds a class to."""
    misfit = await session.scalar(
        text(
            f"SELECT true FROM session WHERE {UNTOUCHED} AND slot_date >= :start"
            " AND EXISTS (SELECT FROM session_block b WHERE b.session_id = session.id)"
            " AND NOT (SELECT count(*) = 1 AND bool_and(k.is_sparring)"
            "  FROM session_block b JOIN block_kind k ON k.id = b.block_kind_id"
            "  WHERE b.session_id = session.id)"
            " LIMIT 1"
        ),
        {"slot": slot_id, "start": start},
    )
    if misfit:
        raise unprocessable(
            "class_type_id", "open_mat_plan", "an open mat is one sparring block; fix its blocks"
        )


@router.patch("/{slot_id}")
async def update_slot(
    slot_id: uuid.UUID,
    body: SlotUpdate,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> Slot:
    """Change the slot from `from_date` on; the slot in effect from then, which is a
    new one when the change starts after the slot's first date."""
    current = await _get(session, slot_id, lock=True)
    zone = await gym_timezone(session, tenant)
    sent = body.model_dump(exclude_unset=True)
    start: date = sent.pop("from_date", None) or gym_today(zone)
    old_tags = [tag.id for tag in current.tags]
    changes = {
        k: v
        for k, v in sent.items()
        if (set(v) != set(old_tags) if k == "tag_ids" else v != getattr(current, k))
    }
    if not changes:
        return current
    if current.valid_to is not None and start > current.valid_to:
        raise unprocessable("from_date", "after_valid_to", "the slot has ended by then")
    if "class_type_id" in changes:
        await require_class_type(session, changes["class_type_id"])
        kind = await session.scalar(
            text("SELECT kind FROM class_type WHERE id = :id"), {"id": changes["class_type_id"]}
        )
        if kind == ClassKind.OPEN_MAT:
            await _require_plans_fit(session, slot_id, start)
    if "coach_id" in changes:
        await require_coach(session, changes["coach_id"])
    retag = "tag_ids" in changes
    new_tags: list[uuid.UUID] = changes.pop("tag_ids", old_tags)
    if retag:
        await require_tags(session, new_tags, old_tags, "tag_ids")
    values = {**current.model_dump(include=set(SLOT_FIELDS)), **changes}
    in_place = start <= current.valid_from
    if not in_place:
        values["valid_from"] = start
    if values["valid_to"] is not None and values["valid_to"] < values["valid_from"]:
        raise unprocessable("valid_to", "before_valid_from", "valid_to is before valid_from")

    if in_place:
        target = slot_id
        await session.execute(
            text(
                "UPDATE schedule_slot SET class_type_id = :class_type_id, weekdays = :weekdays,"
                " start_time = :start_time, duration_minutes = :duration_minutes,"
                " coach_id = :coach_id, topic = :topic, valid_to = :valid_to,"
                " updated_at = now() WHERE id = :id"
            ),
            {**values, "id": slot_id},
        )
    else:
        # The old slot ends the day before; a new one takes its classes from `start` on,
        # and where it had got to, so the nightly run carries on from there.
        target = await session.scalar(
            text(
                "INSERT INTO schedule_slot (gym_id, class_type_id, weekdays, start_time,"
                " duration_minutes, coach_id, topic, valid_from, valid_to, generated_until)"
                " SELECT gym_id, :class_type_id, :weekdays, :start_time, :duration_minutes,"
                " :coach_id, :topic, :valid_from, :valid_to, generated_until"
                " FROM schedule_slot WHERE id = :id RETURNING id"
            ),
            {**values, "id": slot_id},
        )
        await session.execute(
            text("UPDATE schedule_slot SET valid_to = :end, updated_at = now() WHERE id = :id"),
            {"id": slot_id, "end": start - timedelta(days=1)},
        )
        await session.execute(
            text(
                "UPDATE session SET slot_id = :target WHERE slot_id = :id AND slot_date >= :start"
            ),
            {"id": slot_id, "target": target, "start": start},
        )
    if retag or not in_place:
        await set_tags(session, "schedule_slot_tag", "slot_id", target, new_tags)

    params = {"slot": target, "start": start}
    # Dates the slot no longer runs on lose their classes, ...
    await _delete_sessions(
        session,
        f"{UNTOUCHED} AND slot_date >= :start AND (NOT extract(isodow FROM slot_date)::smallint"
        " = ANY (:weekdays) OR slot_date > coalesce(CAST(:valid_to AS date), 'infinity'))",
        {**params, "weekdays": values["weekdays"], "valid_to": values["valid_to"]},
    )
    # ... the rest match it, ...
    await session.execute(
        text(
            "UPDATE session SET class_type_id = :class_type_id, coach_id = :coach_id,"
            " duration_minutes = :duration_minutes,"
            " starts_at = (slot_date + CAST(:start_time AS time)) AT TIME ZONE :zone,"
            " topic = CASE WHEN topic IS NOT DISTINCT FROM CAST(:old_topic AS text)"
            "  THEN CAST(:topic AS text) ELSE topic END,"
            " updated_at = now()"
            f" WHERE {UNTOUCHED} AND slot_date >= :start"
        ),
        {
            **params,
            **{k: values[k] for k in ("class_type_id", "coach_id", "duration_minutes", "topic")},
            "start_time": values["start_time"],
            "zone": zone,
            "old_topic": current.topic,
        },
    )
    if retag:
        await _retag(session, target, start, old_tags, new_tags)
    # ... and the dates it now runs on get theirs.
    await _refill(session, zone, target)
    return await _get(session, target)


async def _retag(
    session: AsyncSession,
    slot_id: uuid.UUID,
    start: date,
    old: list[uuid.UUID],
    new: list[uuid.UUID],
) -> None:
    """Give the slot's new tags to its classes from `start` on that it may still change
    and that still carry its old ones, as the topic is; a class tagged on its own keeps
    its tags. An archived tag goes on none, as the schedule makes none with it.

    "Its old ones" are what the schedule put on the class: every old tag for a class
    made before one of them was archived, the old tags not archived for one made after.
    So a class matches when its tags are within the old ones and hold every old one
    still in use."""
    params = {"slot": slot_id, "start": start, "old": old, "new": new}
    tags_of = "ARRAY(SELECT tag_id FROM session_tag WHERE session_id = session.id)"
    retagged = (
        f"SELECT id FROM session WHERE {UNTOUCHED} AND slot_date >= :start"
        f" AND {tags_of} <@ CAST(:old AS uuid[])"
        f" AND {tags_of} @> ARRAY(SELECT id FROM class_tag"
        "  WHERE id = ANY(CAST(:old AS uuid[])) AND NOT archived)"
    )
    ids = list((await session.execute(text(retagged), params)).scalars())
    if not ids:
        return
    await session.execute(
        text("DELETE FROM session_tag WHERE session_id = ANY(:ids)"), {"ids": ids}
    )
    await session.execute(
        text(
            "INSERT INTO session_tag (gym_id, session_id, tag_id)"
            " SELECT current_setting('app.gym_id')::uuid, s.id, t.id"
            " FROM unnest(CAST(:ids AS uuid[])) AS s (id)"
            " CROSS JOIN class_tag t WHERE t.id = ANY(:new) AND NOT t.archived"
        ),
        {"ids": ids, "new": new},
    )


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(slot_id: uuid.UUID, session: AdminSession) -> None:
    """Delete the slot and its classes yet to happen; the rest stay as one-off classes."""
    await _get(session, slot_id, lock=True)
    await _delete_sessions(session, UNTOUCHED, {"slot": slot_id})
    await session.execute(
        text("UPDATE session SET slot_id = NULL, slot_date = NULL WHERE slot_id = :id"),
        {"id": slot_id},
    )
    await session.execute(text("DELETE FROM schedule_slot WHERE id = :id"), {"id": slot_id})


closed = APIRouter(prefix="/api/closed-days", tags=["classes"])


@closed.get("")
async def list_closed_days(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> list[ClosedDay]:
    """The closed days from today on, earliest first."""
    today = gym_today(await gym_timezone(session, tenant))
    result = await session.execute(
        text("SELECT day, label FROM closed_day WHERE day >= :today ORDER BY day"),
        {"today": today},
    )
    return [ClosedDay.model_validate(row, from_attributes=True) for row in result]


@closed.put("/{day}")
async def close_day(
    day: date,
    body: ClosedDayChange,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: AdminSession,
) -> ClosedDay:
    """Close `day`, or relabel it; the scheduled classes on it yet to happen are deleted."""
    zone = await gym_timezone(session, tenant)
    await session.execute(
        text(
            "INSERT INTO closed_day (gym_id, day, label)"
            " VALUES (current_setting('app.gym_id')::uuid, :day, :label)"
            " ON CONFLICT (gym_id, day) DO UPDATE SET label = excluded.label"
        ),
        {"day": day, "label": body.label},
    )
    # By where the class is now, not the date the schedule made it for.
    await _delete_sessions(
        session,
        "slot_id IS NOT NULL AND starts_at >= :start AND starts_at < :end"
        " AND starts_at > now()"
        " AND NOT EXISTS (SELECT FROM attendance a WHERE a.session_id = session.id)",
        {
            "start": start_of_local_day(day, zone),
            "end": start_of_local_day(day + timedelta(days=1), zone),
        },
    )
    return ClosedDay(day=day, label=body.label)


@closed.delete("/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def reopen_day(
    day: date, tenant: Annotated[Tenant, Depends(current_tenant)], session: AdminSession
) -> None:
    """Reopen `day`: the schedule makes its classes again, if it is within the horizon."""
    await session.execute(text("DELETE FROM closed_day WHERE day = :day"), {"day": day})
    first, last = horizon(gym_today(await gym_timezone(session, tenant)))
    if first <= day <= last:
        await generate(session, day, day, refill=True)
