"""Class tags (#243, migration 0041): the gym's recurring focuses, and the hours in each.

A tag is one of the gym's names for what classes keep coming back to, "Pasaje de
guardia" or "Fuerza", unique in the gym with case ignored. An archived one stays on
the classes that have it and still counts, but is put on no class from then on.

A class's hours are its duration (0035): each class adds all of it to every tag it
carries, so a class of two tags counts in both. One with no duration set adds none.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.schemas.classes import Name, never_null

# More than any class is about; it keeps a request from naming every tag there is.
MAX_TAGS = 20


def _each_once(value: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(value))


# A class's or a slot's tags, each once in the order sent; `[]` is none.
TagIds = Annotated[list[uuid.UUID], Field(max_length=MAX_TAGS), AfterValidator(_each_once)]


class ClassTagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class ClassTagUpdate(BaseModel):
    """Only the fields sent change; none can be cleared."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    archived: StrictBool | None = None

    @model_validator(mode="after")
    def _set(self) -> "ClassTagUpdate":
        never_null(self, "name", "archived")
        return self


class ClassTag(BaseModel):
    id: uuid.UUID
    name: str
    archived: bool
    created_at: datetime


class TagOn(BaseModel):
    """A tag as a class or a slot carries it."""

    id: uuid.UUID
    name: str
    archived: bool


class TagHoursRow(BaseModel):
    """One tag's classes over a stretch, and the minutes they lasted."""

    tag_id: uuid.UUID
    name: str
    archived: bool
    classes: int
    minutes: int


class NoDuration(BaseModel):
    """A class counted that has no duration set, so adds no minutes (#257)."""

    session_id: uuid.UUID
    starts_at: datetime
    class_type_name: str


class TagHours(BaseModel):
    """Hours per tag from `first_day` to `last_day`, both included, on the gym's
    calendar: most minutes first. `untagged_minutes` is the classes with no tag.
    `no_duration_classes` is how many classes counted have no duration, so add no
    minutes anywhere; `no_duration` the latest of them, to go set one."""

    first_day: date
    last_day: date
    tags: list[TagHoursRow]
    untagged_minutes: int
    no_duration_classes: int = 0
    no_duration: list[NoDuration] = []
