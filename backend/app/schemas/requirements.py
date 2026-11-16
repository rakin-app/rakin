"""The gym's requirements and a person's records of them, as the API takes and answers
them (migration 0061). The rules of a state live in `app.domain.requirements`."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.domain.custom_fields import VisibleTo
from app.domain.requirements import RequirementState
from app.schemas.classes import never_null

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
# Ten years: anything longer is a typo, or a requirement done once.
ValidMonths = Annotated[int, Field(ge=1, le=120)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class Requirement(BaseModel):
    id: uuid.UUID
    name: str
    # How long one lasts; `None` for one done once.
    valid_months: int | None
    sensitive: bool
    visible_to: VisibleTo
    active: bool


class RequirementCreate(BaseModel):
    """A new requirement goes last in the gym's order. `sensitive` and `visible_to` are
    the owner's to set; without them it is not sensitive, and seen by every staff role,
    or by the owner alone when sensitive."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    valid_months: ValidMonths | None = None
    sensitive: StrictBool = False
    visible_to: VisibleTo | None = None


class RequirementUpdate(BaseModel):
    """Only the fields sent change. `valid_months: null` makes it one done once; nothing
    else can be cleared. Marking it sensitive without a `visible_to` narrows it to the
    owner."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    valid_months: ValidMonths | None = None
    active: StrictBool | None = None
    sensitive: StrictBool | None = None
    visible_to: VisibleTo | None = None

    @model_validator(mode="after")
    def _set(self) -> "RequirementUpdate":
        never_null(self, "name", "active", "sensitive", "visible_to")
        return self


class RequirementOrder(BaseModel):
    """Every requirement the caller sees, by id, in the order they should be shown."""

    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID]


class PersonRequirement(BaseModel):
    """One of the gym's active requirements on a person, with their current record:
    the latest recorded. `done_on`, `expires_on`, `note` and `recorded_at` are `None`
    while there is none."""

    id: uuid.UUID
    name: str
    valid_months: int | None
    sensitive: bool
    state: RequirementState
    done_on: date | None
    # The last day it is in force; `None` when done once, or never done.
    expires_on: date | None
    note: str | None
    recorded_at: datetime | None


class RequirementRecord(BaseModel):
    """It was done on `done_on`, today at the latest; a blank note is none."""

    model_config = ConfigDict(extra="forbid")

    done_on: date
    note: Note | None = None


class MyRequirement(BaseModel):
    """A requirement as the student page shows it: no note, which is the staff's."""

    id: uuid.UUID
    name: str
    state: RequirementState
    done_on: date | None
    expires_on: date | None


class PersonRequirements(BaseModel):
    """The signed-in person's requirements, or one of their dependents'."""

    person_id: uuid.UUID
    name: str
    requirements: list[MyRequirement]
