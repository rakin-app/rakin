"""The current gym's class tags: list, create, rename, archive, and hours per tag (#243).

A tag is one of the gym's names for a recurring focus (migration 0041): "Pasaje de
guardia", "Fuerza". A name is unique in the gym, case ignored: a second "fuerza" is a
409. There is no delete: a tag is archived (`PATCH {"archived": true}`), which keeps
it on the classes that have it, counting in their hours, and puts it on no class
from then on (a 422, `archived_tag`). Any staff role may read them, since a coach tags
their class; only an owner or admin may change them.

Hours per tag are a class's duration added to every tag it carries, over a gym month
or year: for the gym (`GET /api/class-tags/hours`), the classes held, that is begun
and not cancelled; for a person (`GET /api/people/{id}/tag-hours`, and the student
page's `GET /api/me/classes`), the classes they attended. A cancelled class counts
nowhere. A class with no duration set adds no minutes; each stretch says how many it
counted and lists the latest, so their tags' hours are never silently short (#257).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND as PERSON_NOT_FOUND
from app.api.people import in_gym
from app.api.programs import execute_refusing
from app.domain.dates import gym_today, start_of_local_day
from app.roles import AdminSession, StaffSession
from app.schemas.class_tags import (
    ClassTag,
    ClassTagCreate,
    ClassTagUpdate,
    NoDuration,
    TagHours,
    TagHoursRow,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(tags=["classes"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "class tag not found")
NAME_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the gym already has a tag by this name")
REFUSALS = {"class_tag_name_key": NAME_TAKEN}

# RLS on `class_tag` keeps every query to the current gym.
SELECT_TAG = "SELECT id, name, archived, created_at FROM class_tag"
ORDER = " ORDER BY archived, lower(name), created_at"

# The tags a class or a slot carries, by name, as a JSON list `TagOn` reads; `owner` is
# the session's or slot's alias and `link` its tag table.
TAGS_OF = """
    coalesce((
        SELECT jsonb_agg(jsonb_build_object('id', t.id, 'name', t.name, 'archived', t.archived)
                         ORDER BY lower(t.name), t.id)
        FROM {link} lt JOIN class_tag t ON t.id = lt.tag_id
        WHERE lt.{column} = {owner}.id
    ), '[]'::jsonb)
"""


def _unprocessable(field: str, kind: str, msg: str) -> RequestValidationError:
    # `app.api.sessions.unprocessable`, which imports this module.
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", field)}])


async def _timezone(session: AsyncSession, tenant: Tenant) -> str:
    zone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return zone


def tags_of_session(alias: str) -> str:
    return TAGS_OF.format(link="session_tag", column="session_id", owner=alias)


def tags_of_slot(alias: str) -> str:
    return TAGS_OF.format(link="schedule_slot_tag", column="slot_id", owner=alias)


async def _get(session: AsyncSession, tag_id: uuid.UUID, *, lock: bool = False) -> ClassTag:
    sql = f"{SELECT_TAG} WHERE id = :id{' FOR UPDATE' if lock else ''}"
    row = (await session.execute(text(sql), {"id": tag_id})).one_or_none()
    if row is None:
        raise NOT_FOUND
    return ClassTag.model_validate(row, from_attributes=True)


async def require_tags(
    session: AsyncSession, wanted: list[uuid.UUID], kept: list[uuid.UUID], field: str
) -> None:
    """A 422 on `field` unless every one of `wanted` is a tag of this gym, and those not
    already in `kept` are not archived: an archived tag stays where it is, and goes on
    nothing new."""
    rows = await session.execute(
        text("SELECT id, archived FROM class_tag WHERE id = ANY(:ids)"), {"ids": wanted}
    )
    archived = {row.id: row.archived for row in rows}
    if set(wanted) - archived.keys():
        raise _unprocessable(field, "unknown_tag", "no such tag")
    if any(archived[tag] for tag in wanted if tag not in kept):
        raise _unprocessable(field, "archived_tag", "the tag is archived")


async def set_tags(
    session: AsyncSession,
    link: str,
    column: str,
    owner_id: uuid.UUID,
    wanted: list[uuid.UUID],
) -> None:
    """Make `owner_id`'s tags in `link` (`session_tag` or `schedule_slot_tag`) be `wanted`."""
    await session.execute(
        text(f"DELETE FROM {link} WHERE {column} = :owner AND NOT tag_id = ANY(:ids)"),
        {"owner": owner_id, "ids": wanted},
    )
    await session.execute(
        text(
            f"INSERT INTO {link} (gym_id, {column}, tag_id)"
            " SELECT current_setting('app.gym_id')::uuid, :owner, unnest(CAST(:ids AS uuid[]))"
            " ON CONFLICT DO NOTHING"
        ),
        {"owner": owner_id, "ids": wanted},
    )


@router.get("/api/class-tags")
async def list_class_tags(session: StaffSession, archived: bool | None = None) -> list[ClassTag]:
    """By name, archived ones last; `?archived=false` for the ones a class may take."""
    where = "" if archived is None else " WHERE archived = :archived"
    result = await session.execute(text(SELECT_TAG + where + ORDER), {"archived": archived})
    return [ClassTag.model_validate(row, from_attributes=True) for row in result]


@router.post(
    "/api/class-tags",
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_409_CONFLICT: {"description": "name taken"}},
)
async def create_class_tag(body: ClassTagCreate, session: AdminSession) -> ClassTag:
    result = await execute_refusing(
        session,
        text(
            "INSERT INTO class_tag (gym_id, name)"
            " VALUES (current_setting('app.gym_id')::uuid, :name) RETURNING id"
        ),
        body.model_dump(),
        REFUSALS,
    )
    return await _get(session, result.scalar_one())


@router.patch(
    "/api/class-tags/{tag_id}", responses={status.HTTP_409_CONFLICT: {"description": "name taken"}}
)
async def update_class_tag(
    tag_id: uuid.UUID, body: ClassTagUpdate, session: AdminSession
) -> ClassTag:
    current = await _get(session, tag_id, lock=True)
    columns = {
        **current.model_dump(include={"name", "archived"}),
        **body.model_dump(exclude_unset=True),
    }
    await execute_refusing(
        session,
        text("UPDATE class_tag SET name = :name, archived = :archived WHERE id = :id"),
        {**columns, "id": tag_id},
        REFUSALS,
    )
    return await _get(session, tag_id)


# --- hours per tag ----------------------------------------------------------------

# The classes counted: not cancelled and begun by now, in the stretch; `{whose}` narrows
# them to a person's attended ones. A class with no duration set lasts no minutes.
COUNTED = """
    SELECT s.id, coalesce(s.duration_minutes, 0) AS minutes FROM session s
    WHERE s.cancelled_at IS NULL AND s.starts_at >= :start AND s.starts_at < :end
      AND s.starts_at <= now() {whose}
"""

ATTENDED_BY = """
    AND EXISTS (SELECT FROM attendance a JOIN membership m ON m.id = a.membership_id
                WHERE a.session_id = s.id AND m.person_id = :person)
"""

BY_TAG = """
    WITH counted AS ({counted})
    SELECT t.id AS tag_id, t.name, t.archived, count(*) AS classes,
           sum(c.minutes)::integer AS minutes
    FROM counted c
    JOIN session_tag st ON st.session_id = c.id
    JOIN class_tag t ON t.id = st.tag_id
    GROUP BY t.id, t.name, t.archived
    ORDER BY minutes DESC, lower(t.name), t.id
"""

NO_DURATION = """
    WITH counted AS ({counted})
    SELECT s.id AS session_id, s.starts_at, ct.name AS class_type_name,
           count(*) OVER () AS total
    FROM counted c
    JOIN session s ON s.id = c.id
    JOIN class_type ct ON ct.id = s.class_type_id
    WHERE s.duration_minutes IS NULL
    ORDER BY s.starts_at DESC, s.id
    LIMIT :listed
"""

# The most classes with no duration a stretch lists; it counts them all.
NO_DURATION_LISTED = 20

UNTAGGED = """
    WITH counted AS ({counted})
    SELECT coalesce(sum(c.minutes), 0)::integer FROM counted c
    WHERE NOT EXISTS (SELECT FROM session_tag st WHERE st.session_id = c.id)
"""


def month_of(day: date) -> tuple[date, date]:
    """The first and last days of `day`'s month."""
    first = day.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return first, following - timedelta(days=1)


def year_of(day: date) -> tuple[date, date]:
    return date(day.year, 1, 1), date(day.year, 12, 31)


async def tag_hours(
    session: AsyncSession,
    zone: str,
    first: date,
    last: date,
    person_id: uuid.UUID | None = None,
) -> TagHours:
    """Hours per tag from `first` to `last` on the gym's calendar: the classes held, or
    with `person_id` the ones that person attended."""
    counted = COUNTED.format(whose="" if person_id is None else ATTENDED_BY)
    params: dict[str, Any] = {
        "start": start_of_local_day(first, zone),
        "end": start_of_local_day(last + timedelta(days=1), zone),
        "person": person_id,
        "listed": NO_DURATION_LISTED,
    }
    rows = await session.execute(text(BY_TAG.format(counted=counted)), params)
    untagged: int = await session.scalar(text(UNTAGGED.format(counted=counted)), params)
    undurated = (await session.execute(text(NO_DURATION.format(counted=counted)), params)).all()
    return TagHours(
        first_day=first,
        last_day=last,
        tags=[TagHoursRow.model_validate(row, from_attributes=True) for row in rows],
        untagged_minutes=untagged,
        no_duration_classes=undurated[0].total if undurated else 0,
        no_duration=[NoDuration.model_validate(row, from_attributes=True) for row in undurated],
    )


def _stretch(today: date, year: int | None, month: int | None) -> tuple[date, date]:
    """`?year=&month=`: that month; `?year=` alone, that year; neither, this month."""
    if year is None:
        if month is not None:
            raise RequestValidationError(
                [{"type": "missing", "msg": "a month needs its year", "loc": ("query", "year")}]
            )
        return month_of(today)
    return year_of(date(year, 1, 1)) if month is None else month_of(date(year, month, 1))


Year = Annotated[int | None, Query(ge=2000, le=2100)]
Month = Annotated[int | None, Query(ge=1, le=12)]


@router.get("/api/class-tags/hours")
async def gym_tag_hours(
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
    year: Year = None,
    month: Month = None,
) -> TagHours:
    """The gym's classes held in the month or year, hours per tag."""
    zone = await _timezone(session, tenant)
    return await tag_hours(session, zone, *_stretch(gym_today(zone), year, month))


@router.get("/api/people/{person_id}/tag-hours")
async def person_tag_hours(
    person_id: uuid.UUID,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: StaffSession,
    year: Year = None,
    month: Month = None,
) -> TagHours:
    """The classes the member attended in the month or year, hours per tag: the ficha's."""
    if not await in_gym(session, person_id):
        raise PERSON_NOT_FOUND
    zone = await _timezone(session, tenant)
    return await tag_hours(session, zone, *_stretch(gym_today(zone), year, month), person_id)
