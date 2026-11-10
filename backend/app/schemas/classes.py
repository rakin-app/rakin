"""A gym's programs and class types (migration 0016).

A program is a group of students the gym teaches (adults, kids, competition), named by
the gym. A class type is a kind of class in one program, with the credits an
attendance costs a credits membership. Both are deactivated, never deleted.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# No class costs more than a pack holds; the cap keeps a typo from becoming a class
# that empties every pack at once.
MAX_CREDIT_COST = 100
CreditCost = Annotated[int, Field(ge=0, le=MAX_CREDIT_COST)]


class ClassKind(StrEnum):
    """A class, or an open mat: rounds of sparring only, which by default is not a class."""

    CLASS = "class"
    OPEN_MAT = "open_mat"


def counts_by_default(kind: ClassKind) -> bool:
    """Whether attending a class type of `kind` counts as a class, unless the gym says."""
    return kind is ClassKind.CLASS


def never_null(model: BaseModel, *fields: str) -> None:
    for field in fields:
        if field in model.model_fields_set and getattr(model, field) is None:
            raise ValueError(f"{field} cannot be null")


class ProgramCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class ProgramUpdate(BaseModel):
    """Only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _set(self) -> "ProgramUpdate":
        never_null(self, "name", "active")
        return self


class Program(BaseModel):
    id: uuid.UUID
    name: str
    active: bool
    created_at: datetime


class ClassTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    program_id: uuid.UUID
    credit_cost: CreditCost = 1
    kind: ClassKind = ClassKind.CLASS
    # `counts_by_default(kind)` unless sent.
    counts_as_class: bool | None = None


class ClassTypeUpdate(BaseModel):
    """Only the fields sent change. A class type may move to another program. A new
    `kind` without `counts_as_class` takes that kind's default."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    program_id: uuid.UUID | None = None
    credit_cost: CreditCost | None = None
    kind: ClassKind | None = None
    counts_as_class: bool | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _set(self) -> "ClassTypeUpdate":
        never_null(self, "name", "program_id", "credit_cost", "kind", "counts_as_class", "active")
        return self


class ClassType(BaseModel):
    id: uuid.UUID
    name: str
    program_id: uuid.UUID
    program_name: str
    credit_cost: int
    kind: ClassKind
    counts_as_class: bool
    active: bool
    created_at: datetime
