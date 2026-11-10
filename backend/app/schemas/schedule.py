"""The weekly schedule (#167, migration 0035): recurring classes and closed days.

A slot is one class of the timetable: a class type on some weekdays (ISO, 1 is
Monday), at a local start time, for `duration_minutes`, with a default coach and an
optional default topic, valid from a date and, if set, until one. A closed day is a
date, in the gym's timezone, with no classes.
"""

import uuid
from datetime import date, datetime, time
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.classes import never_null
from app.schemas.sessions import Duration, Topic

MAX_LABEL = 100


def _weekdays(value: list[int]) -> list[int]:
    """Each once, Monday first."""
    return sorted(set(value))


Weekdays = Annotated[
    list[Annotated[int, Field(ge=1, le=7)]],
    Field(min_length=1, max_length=7),
    AfterValidator(_weekdays),
]


def _whole_minute(value: time | None) -> time | None:
    if value is not None and (value.second or value.microsecond or value.tzinfo):
        raise ValueError("a start time is a local hour and minute")
    return value


StartTime = Annotated[time, AfterValidator(_whole_minute)]


def _valid_range(valid_from: date | None, valid_to: date | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError("valid_to is before valid_from")


class SlotCreate(BaseModel):
    """A new slot; it is valid from today in the gym's timezone unless told otherwise."""

    model_config = ConfigDict(extra="forbid")

    class_type_id: uuid.UUID
    weekdays: Weekdays
    start_time: StartTime
    duration_minutes: Duration
    coach_id: uuid.UUID
    topic: Topic = None
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _range(self) -> "SlotCreate":
        _valid_range(self.valid_from, self.valid_to)
        return self


class SlotUpdate(BaseModel):
    """Change a slot from `from_date` on (today in the gym's timezone by default).

    Only the fields sent change. Classes before `from_date`, and any that has started or
    has attendance, stay as they are: a change from a date after the slot's
    `valid_from` ends the slot the day before and starts a new one with the change
    (`app.api.schedule`). `valid_to: null` makes it open-ended."""

    model_config = ConfigDict(extra="forbid")

    from_date: date | None = None
    class_type_id: uuid.UUID | None = None
    weekdays: Weekdays | None = None
    start_time: StartTime | None = None
    duration_minutes: Duration | None = None
    coach_id: uuid.UUID | None = None
    topic: Topic = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _set(self) -> "SlotUpdate":
        never_null(
            self,
            "from_date",
            "class_type_id",
            "weekdays",
            "start_time",
            "duration_minutes",
            "coach_id",
        )
        _valid_range(self.from_date, self.valid_to)
        return self


class Slot(BaseModel):
    id: uuid.UUID
    class_type_id: uuid.UUID
    class_type_name: str
    program_id: uuid.UUID
    program_name: str
    # Whether its class type is active: a deactivated one's slot makes no classes.
    class_type_active: bool
    weekdays: list[int]
    start_time: time
    duration_minutes: int
    coach_id: uuid.UUID
    coach_name: str
    topic: str | None
    valid_from: date
    valid_to: date | None
    created_at: datetime
    updated_at: datetime


Label = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=MAX_LABEL),
    AfterValidator(lambda value: value or None),
]


class ClosedDayChange(BaseModel):
    """What a closed day is, "Feriado" say; none is fine."""

    model_config = ConfigDict(extra="forbid")

    label: Label = None


class ClosedDay(BaseModel):
    day: date
    label: str | None
