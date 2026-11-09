"""A person's ranks: the promotion log (`grade_event`, migration 0016) and what it says
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


class Rank(BaseModel):
    """A rank and sub-rank as the scheme labels them: `Azul`, `2 grados`."""

    rank_key: str
    rank_label: str
    sub_rank: str | None
    sub_rank_label: str | None
    awarded_on: date

    @classmethod
    def labelled(
        cls, scheme: GradingScheme, rank_key: str, sub_rank: str | None, awarded_on: date
    ) -> "Rank":
        rank = scheme.rank(rank_key)
        sub = None
        if rank is not None and sub_rank is not None:
            sub = next((s for s in rank.sub_ranks if s.key == sub_rank), None)
        return cls(
            rank_key=rank_key,
            rank_label=rank.label if rank else rank_key,
            sub_rank=sub_rank,
            sub_rank_label=None if sub_rank is None else sub.label if sub else sub_rank,
            awarded_on=awarded_on,
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
