"""Sessions: the classes a gym actually held (migration 0020).

A session is one class of a class type, started at a time and taught by a coach, with
the topic and notes the coach writes after it. A blank topic or notes is no topic or
notes: both are stored as null. A class that won't happen is cancelled (0033): it
stays, with `cancelled_at`, and counts for nothing.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    model_validator,
)

from app.schemas.classes import never_null

MAX_TOPIC = 200
MAX_NOTES = 4000


def _blank_is_none(value: str | None) -> str | None:
    return value or None


Topic = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=MAX_TOPIC),
    AfterValidator(_blank_is_none),
]
Notes = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=MAX_NOTES),
    AfterValidator(_blank_is_none),
]


class SessionCreate(BaseModel):
    """Start a class: now, by the person acting, unless told otherwise."""

    model_config = ConfigDict(extra="forbid")

    class_type_id: uuid.UUID
    starts_at: AwareDatetime | None = None
    coach_id: uuid.UUID | None = None
    topic: Topic = None
    notes: Notes = None


class SessionUpdate(BaseModel):
    """Only the fields sent change; `null` or a blank string clears a topic or notes.

    Moving a class, changing its type or its coach is an owner's or admin's; its own
    coach may change only its topic and notes (`app.api.sessions`)."""

    model_config = ConfigDict(extra="forbid")

    topic: Topic = None
    notes: Notes = None
    coach_id: uuid.UUID | None = None
    class_type_id: uuid.UUID | None = None
    starts_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _set(self) -> "SessionUpdate":
        never_null(self, "coach_id", "class_type_id", "starts_at")
        return self


class Session(BaseModel):
    id: uuid.UUID
    class_type_id: uuid.UUID
    class_type_name: str
    program_id: uuid.UUID
    program_name: str
    starts_at: datetime
    coach_id: uuid.UUID
    coach_name: str
    topic: str | None
    notes: str | None
    # When it was cancelled; null for a class that stands.
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # How many are marked at it; 0 is a class whose attendance was never taken.
    present: int


class Day(BaseModel):
    """A day's sessions in the gym's timezone, earliest first."""

    date: date
    timezone: str
    sessions: list[Session]


class Unmarked(BaseModel):
    """The sessions since `since`, a day in the gym's timezone, with no one marked and
    not cancelled."""

    since: date
    timezone: str
    sessions: list[Session]
