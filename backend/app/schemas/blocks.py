"""The class timer's data (migration 0024): block kinds, a session's blocks, time totals.

A block kind is one of the gym's names for a part of a class (Calentamiento, Técnica,
Sparring), and `is_sparring` says its time is sparring. A session's plan is its blocks
in order, each with its kind and planned seconds; a sparring kind's block is rounds
instead, and its seconds are the rounds' (`rounds * round_seconds`), rest not
included. What a block actually ran is recorded once it has, and a student's time is
the blocks of every session they attended.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.schemas.classes import ClassKind, Name, never_null

# A block is at most four hours, a round at most an hour, and a plan at most 30 blocks:
# bounds that only a typo reaches.
MAX_BLOCK_SECONDS = 4 * 60 * 60
MAX_ROUND_SECONDS = 60 * 60
MAX_ROUNDS = 100
MAX_BLOCKS = 30

BlockSeconds = Annotated[int, Field(ge=1, le=MAX_BLOCK_SECONDS)]
RoundSeconds = Annotated[int, Field(ge=1, le=MAX_ROUND_SECONDS)]
RestSeconds = Annotated[int, Field(ge=0, le=MAX_ROUND_SECONDS)]
Rounds = Annotated[int, Field(ge=1, le=MAX_ROUNDS)]


# --- block kinds ------------------------------------------------------------------


class BlockKindCreate(BaseModel):
    """A new kind goes last in the gym's order."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    is_sparring: StrictBool = False


class BlockKindUpdate(BaseModel):
    """Only the fields sent change; none can be cleared."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    is_sparring: StrictBool | None = None
    archived: StrictBool | None = None

    @model_validator(mode="after")
    def _set(self) -> "BlockKindUpdate":
        never_null(self, "name", "is_sparring", "archived")
        return self


class BlockKindOrder(BaseModel):
    """Every one of the gym's block kinds, by id, in the order they should be shown."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID]


class BlockKind(BaseModel):
    id: uuid.UUID
    name: str
    is_sparring: bool
    position: int
    archived: bool
    created_at: datetime


class BlockKindInUse(BaseModel):
    code: Literal["block_kind_in_use"] = "block_kind_in_use"
    # How many session blocks are of the kind.
    blocks: int


class BlockKindsInUse(BaseModel):
    """409 body: sessions' blocks are of this kind, so it can be archived but not
    deleted, and whether it is sparring is fixed."""

    detail: BlockKindInUse


# --- a session's plan -------------------------------------------------------------


class PlannedBlock(BaseModel):
    """One block of a plan as sent. `id` is the caller's, so a phone that resends its
    plan offline keeps each block's recorded actuals; one is made up when absent.

    A block of a sparring kind sends its rounds and may leave `planned_seconds` out
    (it is `rounds_planned * round_seconds`); any other block sends `planned_seconds`
    and no rounds. Which the kind is, is the API's check."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID | None = None
    block_kind_id: uuid.UUID
    planned_seconds: BlockSeconds | None = None
    rounds_planned: Rounds | None = None
    round_seconds: RoundSeconds | None = None
    rest_seconds: RestSeconds | None = None


class PlanReplace(BaseModel):
    """The session's whole plan, in order. A block kept by `id` keeps its actuals."""

    model_config = ConfigDict(extra="forbid")

    blocks: Annotated[list[PlannedBlock], Field(max_length=MAX_BLOCKS)]

    @model_validator(mode="after")
    def _ids_once(self) -> "PlanReplace":
        ids = [b.id for b in self.blocks if b.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("a block id appears twice")
        return self


class BlockActual(BaseModel):
    """What a block ran: its seconds (rest not included, for rounds), and for a sparring
    block the rounds completed. Recording it again replaces it, so a retry is safe."""

    model_config = ConfigDict(extra="forbid")

    actual_seconds: Annotated[int, Field(ge=0, le=MAX_BLOCK_SECONDS)]
    rounds_completed: Annotated[int, Field(ge=0, le=MAX_ROUNDS)] | None = None


class SessionBlock(BaseModel):
    id: uuid.UUID
    position: int
    block_kind_id: uuid.UUID
    block_kind_name: str
    is_sparring: bool
    planned_seconds: int
    # Null until the block has run.
    actual_seconds: int | None
    rounds_planned: int | None
    rounds_completed: int | None
    round_seconds: int | None
    rest_seconds: int | None


class SessionPlan(BaseModel):
    """A session's blocks in order. An open mat's plan is one sparring block."""

    session_id: uuid.UUID
    class_kind: ClassKind
    blocks: list[SessionBlock]


class SuggestedBlock(BaseModel):
    """A block of the plan to start from: no id and nothing recorded."""

    block_kind_id: uuid.UUID
    block_kind_name: str
    is_sparring: bool
    planned_seconds: int
    rounds_planned: int | None
    round_seconds: int | None
    rest_seconds: int | None


class SuggestedPlan(BaseModel):
    """The plan of the latest other session of the same class type that has one, with
    its archived kinds left out; none when there is no such session."""

    session_id: uuid.UUID
    from_session_id: uuid.UUID | None
    blocks: list[SuggestedBlock]


# --- a person's time --------------------------------------------------------------


class KindTime(BaseModel):
    block_kind_id: uuid.UUID
    name: str
    is_sparring: bool
    seconds: int


class TimeTotals(BaseModel):
    """Over the sessions the person was marked present at, each counted once: the
    seconds every block ran, by kind (those with any, in the gym's order), the sparring
    ones summed, and the open mats' alone. `classes` counts the sessions of a class
    type that counts as a class, `open_mats` those of an open mat."""

    by_kind: list[KindTime]
    sparring_seconds: int
    open_mat_seconds: int
    classes: int
    open_mats: int


class PersonTime(BaseModel):
    """This month (from `month_start`, the 1st on the gym's calendar) and all time."""

    timezone: str
    month_start: date
    this_month: TimeTotals
    all_time: TimeTotals
