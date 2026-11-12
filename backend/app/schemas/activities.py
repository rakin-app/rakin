"""Gym activities (#245, migration 0042): what the gym teaches, and whether it grades.

An activity is one discipline the gym teaches, "Ballet" or "Escalada", unique in the gym
with case ignored. `uses_grades` is whether it grades students: belts and ranks show
only in a gym where at least one activity does. The screen offers presets with their
own default for it; the API takes whatever the gym sends.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator

from app.schemas.classes import Name, never_null


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    uses_grades: StrictBool = False


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
    # The class types that belong to it.
    class_types: int
    created_at: datetime
