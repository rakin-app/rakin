"""The gym's grading scheme, as stored under `gym.settings["grading"]`.

Ranks are ordered lowest first. A rank's key is unique across the ranks and the kids
ladder together, since a promotion names only the rank; a sub-rank's key is unique
within its rank. Keys are lower-case ASCII, digits and dashes (`blue`, `kyu-10`, `3`).
A gym with no scheme stored reads as having none: no ranks, no kids ladder.
"""

from collections import Counter
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain import grading

Key = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=40)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
# What a "ready for promotion" flag counts (v2): classes since the last promotion, or
# time in the current rank.
GoalMetric = Literal["classes_since_promotion", "time_in_rank"]

MAX_RANKS = 60
MAX_SUB_RANKS = 20


def _repeated(keys: list[str]) -> list[str]:
    return sorted(k for k, n in Counter(keys).items() if n > 1)


class SubRank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Key
    label: Label


class Rank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Key
    label: Label
    sub_ranks: Annotated[list[SubRank], Field(max_length=MAX_SUB_RANKS)] = []

    @model_validator(mode="after")
    def _sub_rank_keys_are_unique(self) -> "Rank":
        if repeated := _repeated([s.key for s in self.sub_ranks]):
            raise ValueError(f"sub-rank keys repeated in {self.key}: {', '.join(repeated)}")
        return self


class GradingScheme(BaseModel):
    """Replaced whole on a change. Empty lists mean no ranks, or no separate kids ladder."""

    model_config = ConfigDict(extra="forbid")

    ranks: Annotated[list[Rank], Field(max_length=MAX_RANKS)]
    kids_ladder: Annotated[list[Rank], Field(max_length=MAX_RANKS)] = []
    goal_metric: GoalMetric | None = None

    @model_validator(mode="after")
    def _rank_keys_are_unique(self) -> "GradingScheme":
        if repeated := _repeated([r.key for r in (*self.ranks, *self.kids_ladder)]):
            raise ValueError(f"rank keys repeated: {', '.join(repeated)}")
        if self.goal_metric is not None and not (self.ranks or self.kids_ladder):
            raise ValueError("a goal metric needs ranks")
        return self

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "GradingScheme":
        return cls.model_validate(settings.get("grading", {"ranks": []}))

    def rank(self, key: str) -> Rank | None:
        """The rank `key` names, in the ranks or the kids ladder."""
        return next((r for r in (*self.ranks, *self.kids_ladder) if r.key == key), None)


class Preset(BaseModel):
    key: str
    label: str
    scheme: GradingScheme


PRESETS = [Preset.model_validate(p) for p in grading.PRESETS]
