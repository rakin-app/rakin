"""Gym activities (#245, migration 0043): what the gym teaches, and whether it grades.

An activity is one discipline the gym teaches, "Ballet" or "Escalada", unique in the gym
with case ignored. `uses_grades` is whether it grades students: belts and ranks show
only in a gym where at least one activity does. The screen offers presets with their
own default for it; the API takes whatever the gym sends.

`preset` is the key of the preset it came from (#344, `app.domain.vocabulary`), or
None for one the gym named itself; it stays when the activity is renamed. `words` are
what a gym of that sport calls itself, its members and its coach: the gym's first
activity sets them, and Ajustes offers the others' as a suggestion.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from app.domain.vocabulary import PresetKey, Vocabulary
from app.schemas.classes import Name, never_null


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    uses_grades: StrictBool = False
    preset: PresetKey | None = None


class ActivityUpdate(BaseModel):
    """Only the fields sent change; none can be cleared."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    uses_grades: StrictBool | None = None

    @model_validator(mode="after")
    def _set(self) -> "ActivityUpdate":
        never_null(self, "name", "uses_grades")
        return self


class Activity(BaseModel):
    id: uuid.UUID
    name: str
    uses_grades: bool
    preset: PresetKey | None = None
    # The preset's words; None with no preset.
    words: Vocabulary | None = None
    # The class types that belong to it.
    class_types: int
    created_at: datetime
