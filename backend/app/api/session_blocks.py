"""A session's blocks (migration 0028): its plan, what each block ran, the plan to start
from, and a person's time from the sessions they attended.

A coach runs a class from a timer as a sequence of blocks. The plan is the session's
blocks in order, replaced whole (`PUT .../blocks`) before or while the class runs. Each
block has an id the caller may choose, so a phone that resends its plan offline keeps
what was recorded: a block kept by id keeps its actuals, one left out is dropped with
them. What a block ran is recorded on it (`PUT .../blocks/{id}/actual`), and recording
it again replaces it, so the timer's offline queue may retry. A block stopped early
records the seconds it ran.

A block of a sparring kind is rounds: planned, completed, each round's seconds and the
rest between them. Its seconds are the rounds' alone (`rounds * round_seconds`), rest
not included, since that is the time spent sparring. An open mat's plan is one sparring
block. An archived kind is planned no more, but a block already of it may stay.

The plan to start from (`GET .../blocks/suggested`) is the latest other session of the
same class type that has one and was not cancelled, for the coach to adjust: the usual
class is a couple of taps.

The same two writes correct a class's record after it (#163, "Editar registro"): its
blocks' kinds, what each ran, blocks added and removed, held to the same rules. A
cancelled class (migration 0033) runs no timer: either write to it is a 409.

A person's time (`GET /api/people/{id}/time`, and their own on `GET /api/me/time`) is
the blocks of every session they were marked present at, late or not: everyone present
gets the whole session. Sessions count once even if two of the person's memberships
were marked. This month is from the 1st on the gym's calendar.

Any staff role may read them, coaches included, since time involves no money. Only the
session's coach, or an owner or admin, may change its plan or record its blocks.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND as PERSON_NOT_FOUND
from app.api.people import in_gym
from app.api.programs import execute_refusing
from app.domain.dates import gym_today, start_of_local_day
from app.roles import ADMIN_ROLES, FORBIDDEN, StaffSession, role_in_gym
from app.schemas.blocks import (
    MAX_BLOCK_SECONDS,
    BlockActual,
    KindTime,
    PersonTime,
    PlannedBlock,
    PlanReplace,
    SessionBlock,
    SessionPlan,
    SuggestedBlock,
    SuggestedPlan,
    TimeTotals,
)
from app.schemas.classes import ClassKind
from app.tenancy import Tenant, current_tenant

router = APIRouter(tags=["classes"])

SESSION_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
BLOCK_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
# A block id the caller chose that is another session's block.
ID_TAKEN = HTTPException(status.HTTP_409_CONFLICT, "the block id is another session's")
CANCELLED = HTTPException(status.HTTP_409_CONFLICT, "the class is cancelled")

CurrentTenant = Annotated[Tenant, Depends(current_tenant)]

# RLS keeps every table to the current gym.
SELECT_BLOCKS = """
    SELECT b.id, b.position, b.block_kind_id, k.name AS block_kind_name, k.is_sparring,
           b.planned_seconds, b.actual_seconds, b.rounds_planned, b.rounds_completed,
           b.round_seconds, b.rest_seconds
    FROM session_block b JOIN block_kind k ON k.id = b.block_kind_id
"""

INSERT_BLOCK = """
    INSERT INTO session_block (id, gym_id, session_id, position, block_kind_id,
        planned_seconds, actual_seconds, rounds_planned, rounds_completed, round_seconds,
        rest_seconds)
    VALUES (:id, current_setting('app.gym_id')::uuid, :session, :position, :block_kind_id,
        :planned_seconds, :actual_seconds, :rounds_planned, :rounds_completed,
        :round_seconds, :rest_seconds)
"""

# The person's sessions, each once, from an instant on (or all of them).
ATTENDED = """
    SELECT DISTINCT s.id, c.kind, c.counts_as_class
    FROM attendance a
    JOIN membership m ON m.id = a.membership_id
    JOIN session s ON s.id = a.session_id
    JOIN class_type c ON c.id = s.class_type_id
    WHERE m.person_id = :person {since}
"""

COUNTS = """
    SELECT count(*) FILTER (WHERE counts_as_class) AS classes,
           count(*) FILTER (WHERE kind = 'open_mat') AS open_mats
    FROM ({attended}) attended
"""

# Seconds by kind, of the kinds with any, in the gym's order.
BY_KIND = """
    SELECT k.id AS block_kind_id, k.name, k.is_sparring,
           sum(b.actual_seconds) AS seconds,
           coalesce(sum(b.actual_seconds) FILTER (WHERE attended.kind = 'open_mat'), 0)
               AS open_mat_seconds
    FROM ({attended}) attended
    JOIN session_block b ON b.session_id = attended.id
    JOIN block_kind k ON k.id = b.block_kind_id
    WHERE b.actual_seconds > 0
    GROUP BY k.id
    ORDER BY k.archived, k.position, lower(k.name), k.id
"""


@dataclass(frozen=True)
class _Held:
    id: uuid.UUID
    coach_id: uuid.UUID
    class_type_id: uuid.UUID
    kind: ClassKind
    cancelled: bool


@dataclass(frozen=True)
class _Kind:
    is_sparring: bool
    archived: bool


def _unprocessable(loc: tuple[Any, ...], kind: str, msg: str) -> RequestValidationError:
    return RequestValidationError([{"type": kind, "msg": msg, "loc": ("body", *loc)}])


async def _held(session: AsyncSession, session_id: uuid.UUID, *, lock: bool = False) -> _Held:
    row = (
        await session.execute(
            text(
                "SELECT s.id, s.coach_id, s.class_type_id, c.kind,"
                " s.cancelled_at IS NOT NULL AS cancelled FROM session s"
                " JOIN class_type c ON c.id = s.class_type_id WHERE s.id = :id"
                + (" FOR UPDATE OF s" if lock else "")
            ),
            {"id": session_id},
        )
    ).one_or_none()
    if row is None:
        raise SESSION_NOT_FOUND
    return _Held(row.id, row.coach_id, row.class_type_id, ClassKind(row.kind), row.cancelled)


async def _runs(session: AsyncSession, tenant: Tenant, held: _Held) -> None:
    """A 403 unless the person acting is the session's coach, an owner or an admin; a
    409 if the class is cancelled."""
    if held.coach_id != tenant.person_id and await role_in_gym(session, tenant) not in ADMIN_ROLES:
        raise FORBIDDEN
    if held.cancelled:
        raise CANCELLED


async def _plan(session: AsyncSession, held: _Held) -> SessionPlan:
    result = await session.execute(
        text(f"{SELECT_BLOCKS} WHERE b.session_id = :session ORDER BY b.position"),
        {"session": held.id},
    )
    blocks = [SessionBlock.model_validate(row, from_attributes=True) for row in result]
    return SessionPlan(session_id=held.id, class_kind=held.kind, blocks=blocks)


def sparred_at_most(completed: int, planned: int, round_seconds: int) -> int:
    """The most seconds a sparring block may record: its completed rounds, and the round
    after them stopped part-way, if one was planned. Rest is never included."""
    return min(completed + 1, planned) * round_seconds


def _columns(
    index: int, block: PlannedBlock, kind: _Kind, kept: SessionBlock | None
) -> dict[str, Any]:
    """The block's row, held to its kind's rules, with what `kept` had recorded."""

    def refuse(field: str, code: str, msg: str) -> RequestValidationError:
        return _unprocessable(("blocks", index, field), code, msg)

    rounds = ("rounds_planned", "round_seconds", "rest_seconds")
    planned = block.planned_seconds
    if kind.is_sparring:
        for field in rounds:
            if getattr(block, field) is None:
                raise refuse(field, "missing", "a sparring block is rounds")
        assert block.rounds_planned is not None and block.round_seconds is not None
        sparred = block.rounds_planned * block.round_seconds
        if planned is not None and planned != sparred:
            raise refuse(
                "planned_seconds", "planned_seconds_mismatch", "not rounds * round_seconds"
            )
        if sparred > MAX_BLOCK_SECONDS:
            raise refuse("rounds_planned", "less_than_equal", "the rounds are too long")
        planned = sparred
    else:
        if planned is None:
            raise refuse("planned_seconds", "missing", "a block needs its seconds")
        for field in rounds:
            if getattr(block, field) is not None:
                raise refuse(field, "not_sparring", "only a sparring block has rounds")
    # What ran was of the kind it ran as: a block given another kind starts unrecorded.
    if kept is not None and (
        kept.block_kind_id != block.block_kind_id or kept.is_sparring != kind.is_sparring
    ):
        kept = None
    actual = None if kept is None else kept.actual_seconds
    completed = None
    if kept is not None and kind.is_sparring and kept.rounds_completed is not None:
        assert block.rounds_planned is not None and block.round_seconds is not None
        completed = min(kept.rounds_completed, block.rounds_planned)
        if actual is not None:
            actual = min(
                actual, sparred_at_most(completed, block.rounds_planned, block.round_seconds)
            )
    return {
        "id": block.id or uuid.uuid4(),
        "position": index,
        "block_kind_id": block.block_kind_id,
        "planned_seconds": planned,
        "actual_seconds": actual,
        "rounds_planned": block.rounds_planned,
        "rounds_completed": completed,
        "round_seconds": block.round_seconds,
        "rest_seconds": block.rest_seconds,
    }


@router.get("/api/sessions/{session_id}/blocks")
async def get_plan(session_id: uuid.UUID, session: StaffSession) -> SessionPlan:
    return await _plan(session, await _held(session, session_id))


@router.put(
    "/api/sessions/{session_id}/blocks",
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "a block id is another session's, or the class is cancelled"
        }
    },
)
async def replace_plan(
    session_id: uuid.UUID, body: PlanReplace, tenant: CurrentTenant, session: StaffSession
) -> SessionPlan:
    """The session's plan, replaced whole. Sending the same plan again changes nothing."""
    held = await _held(session, session_id, lock=True)
    await _runs(session, tenant, held)
    kinds = {
        row.id: _Kind(row.is_sparring, row.archived)
        for row in await session.execute(
            text(
                "SELECT id, is_sparring, archived FROM block_kind"
                " WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": list({b.block_kind_id for b in body.blocks})},
        )
    }
    existing = {b.id: b for b in (await _plan(session, held)).blocks}
    rows = []
    for index, block in enumerate(body.blocks):
        kind = kinds.get(block.block_kind_id)
        loc = ("blocks", index, "block_kind_id")
        if kind is None:
            raise _unprocessable(loc, "unknown_block_kind", "no such block kind")
        kept = existing.get(block.id) if block.id is not None else None
        if kind.archived and (kept is None or kept.block_kind_id != block.block_kind_id):
            raise _unprocessable(loc, "archived_block_kind", "the block kind is archived")
        rows.append(_columns(index, block, kind, kept))
    if held.kind is ClassKind.OPEN_MAT and (
        len(rows) != 1 or not kinds[rows[0]["block_kind_id"]].is_sparring
    ):
        raise _unprocessable(("blocks",), "open_mat_plan", "an open mat is one sparring block")

    await session.execute(
        text("DELETE FROM session_block WHERE session_id = :session"), {"session": held.id}
    )
    for row in rows:
        await execute_refusing(
            session,
            text(INSERT_BLOCK),
            {**row, "session": held.id},
            {"session_block_pkey": ID_TAKEN},
        )
    return await _plan(session, held)


@router.put(
    "/api/sessions/{session_id}/blocks/{block_id}/actual",
    responses={status.HTTP_409_CONFLICT: {"description": "the class is cancelled"}},
)
async def record_actual(
    session_id: uuid.UUID,
    block_id: uuid.UUID,
    body: BlockActual,
    tenant: CurrentTenant,
    session: StaffSession,
) -> SessionBlock:
    """What the block ran. A sparring block also says the rounds completed, at most
    those planned, and its seconds are the rounds' alone, rest not included: at most
    the completed rounds and part of the next one, if one was planned
    (`sparred_at_most`), else a 422 `less_than_equal` on `actual_seconds`. So 3 of 5
    rounds of 300 s record at most 1200: 900 for the three, and up to 300 for a fourth
    stopped part-way. Any other block has no rounds."""
    held = await _held(session, session_id, lock=True)
    await _runs(session, tenant, held)
    row = (
        await session.execute(
            text(f"{SELECT_BLOCKS} WHERE b.session_id = :session AND b.id = :id"),
            {"session": held.id, "id": block_id},
        )
    ).one_or_none()
    if row is None:
        raise BLOCK_NOT_FOUND
    block = SessionBlock.model_validate(row, from_attributes=True)
    if block.is_sparring:
        if body.rounds_completed is None:
            raise _unprocessable(("rounds_completed",), "missing", "a sparring block is rounds")
        assert block.rounds_planned is not None and block.round_seconds is not None
        if body.rounds_completed > block.rounds_planned:
            raise _unprocessable(
                ("rounds_completed",), "less_than_equal", "more rounds than were planned"
            )
        bound = sparred_at_most(body.rounds_completed, block.rounds_planned, block.round_seconds)
        if body.actual_seconds > bound:
            raise _unprocessable(
                ("actual_seconds",), "less_than_equal", "more than the rounds ran, rest excluded"
            )
    elif body.rounds_completed is not None:
        raise _unprocessable(
            ("rounds_completed",), "not_sparring", "only a sparring block has rounds"
        )
    await session.execute(
        text(
            "UPDATE session_block SET actual_seconds = :actual_seconds,"
            " rounds_completed = :rounds_completed, updated_at = now() WHERE id = :id"
        ),
        {**body.model_dump(), "id": block_id},
    )
    return block.model_copy(update=body.model_dump())


@router.get("/api/sessions/{session_id}/blocks/suggested")
async def suggested_plan(session_id: uuid.UUID, session: StaffSession) -> SuggestedPlan:
    held = await _held(session, session_id)
    source: uuid.UUID | None = await session.scalar(
        text(
            "SELECT s.id FROM session s"
            " WHERE s.class_type_id = :class_type AND s.id <> :session"
            " AND s.cancelled_at IS NULL"
            " AND EXISTS (SELECT FROM session_block b WHERE b.session_id = s.id)"
            " ORDER BY s.starts_at DESC, s.created_at DESC LIMIT 1"
        ),
        {"class_type": held.class_type_id, "session": held.id},
    )
    blocks: list[SuggestedBlock] = []
    if source is not None:
        result = await session.execute(
            text(
                f"{SELECT_BLOCKS} WHERE b.session_id = :session AND NOT k.archived"
                " ORDER BY b.position"
            ),
            {"session": source},
        )
        blocks = [SuggestedBlock.model_validate(row, from_attributes=True) for row in result]
    return SuggestedPlan(session_id=held.id, from_session_id=source, blocks=blocks)


async def _totals(
    session: AsyncSession, person_id: uuid.UUID, since: datetime | None
) -> TimeTotals:
    attended = ATTENDED.format(since="" if since is None else "AND s.starts_at >= :since")
    params = {"person": person_id, "since": since}
    counts = (await session.execute(text(COUNTS.format(attended=attended)), params)).one()
    rows = (await session.execute(text(BY_KIND.format(attended=attended)), params)).all()
    return TimeTotals(
        by_kind=[KindTime.model_validate(row, from_attributes=True) for row in rows],
        sparring_seconds=sum(row.seconds for row in rows if row.is_sparring),
        open_mat_seconds=sum(row.open_mat_seconds for row in rows),
        classes=counts.classes,
        open_mats=counts.open_mats,
    )


async def person_time_of(
    session: AsyncSession, gym_id: uuid.UUID, person_id: uuid.UUID
) -> PersonTime:
    """The person's time this month and in all, on the gym's calendar."""
    zone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": gym_id}
    )
    month_start = gym_today(zone).replace(day=1)
    return PersonTime(
        timezone=zone,
        month_start=month_start,
        this_month=await _totals(session, person_id, start_of_local_day(month_start, zone)),
        all_time=await _totals(session, person_id, None),
    )


@router.get("/api/people/{person_id}/time")
async def person_time(
    person_id: uuid.UUID, tenant: CurrentTenant, session: StaffSession
) -> PersonTime:
    if not await in_gym(session, person_id):
        raise PERSON_NOT_FOUND
    return await person_time_of(session, tenant.gym_id, person_id)
