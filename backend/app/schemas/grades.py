"""A person's ranks: the promotion log (`grade_event`, migration 0018) and what it says
they hold now.

A promotion stores the keys of the gym's grading scheme; the labels shown are the
scheme's as it stands when read. A key the scheme no longer has (a rank the gym has
since removed) reads with its key as its label, so the history still says something.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.grading import GradingScheme, Key

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class GradeAward(BaseModel):
    """`POST /api/people/{id}/grades`: a rank of the gym's scheme, and its sub-rank when
    the rank has sub-ranks. `awarded_on` defaults to today in the gym's timezone and may
    be earlier, never later."""

    model_config = ConfigDict(extra="forbid")

    rank_key: Key
    sub_rank: Key | None = None
    awarded_on: date | None = None
    note: Note | None = None


class Belt(BaseModel):
    """How to draw a rank: its colours from the scheme, and the stripes on the bar. The
    first sub-rank is the one a rank starts at, with none; each one after it adds one."""

    colors: list[str]
    stripes: int
    max_stripes: int


class Rank(BaseModel):
    """A rank and sub-rank as the scheme labels them: `Azul`, `2 grados`."""

    rank_key: str
    rank_label: str
    sub_rank: str | None
    sub_rank_label: str | None
    awarded_on: date
    # `None` when the scheme gives the rank no colours: it shows as its label.
    belt: Belt | None = None

    @classmethod
    def labelled(
        cls, scheme: GradingScheme, rank_key: str, sub_rank: str | None, awarded_on: date
    ) -> "Rank":
        rank = scheme.rank(rank_key)
        sub = None
        if rank is not None and sub_rank is not None:
            sub = next((s for s in rank.sub_ranks if s.key == sub_rank), None)
        belt = None
        if rank is not None and rank.colors:
            keys = [s.key for s in rank.sub_ranks]
            belt = Belt(
                colors=rank.colors,
                stripes=keys.index(sub_rank) if sub_rank in keys else 0,
                max_stripes=max(len(keys) - 1, 0),
            )
        return cls(
            rank_key=rank_key,
            rank_label=rank.label if rank else rank_key,
            sub_rank=sub_rank,
            sub_rank_label=None if sub_rank is None else sub.label if sub else sub_rank,
            awarded_on=awarded_on,
            belt=belt,
        )


class GradeEvent(Rank):
    id: uuid.UUID
    # Who recorded it, by this gym's name for them; `None` for a promotion loaded
    # without one.
    awarded_by_name: str | None
    note: str | None
    created_at: datetime


class Grading(BaseModel):
    """`GET /api/people/{id}/grades`: the person's rank and how they got there."""

    # Their latest award; `None` until they get one.
    current: Rank | None
    # Newest first: by `awarded_on`, then by when it was recorded.
    events: list[GradeEvent]
