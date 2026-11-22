"""Material de estudio (#537): notes and links a coach shares on a class, for an audience.

A material is on one class, or on a recurring class from a date on, and reaches the
audience chosen for it: who attended, the class's program, or members of some plans.
Links are `https` addresses shown as plain links with their host: nothing is embedded
and the server fetches none of them (migration 0088).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

MAX_LINKS = 10
MAX_PLANS = 50

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


def _https(value: str) -> str:
    """An `https` address with a host and no spaces, as migration 0088 holds it."""
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or any(c.isspace() for c in value):
        raise ValueError("only an https link is accepted")
    return value


Link = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=9, max_length=2000),
    AfterValidator(_https),
]


class Audience(StrEnum):
    """Who sees it besides the staff: "Quienes asistieron", "El programa", "Planes"."""

    ATTENDEES = "attendees"
    PROGRAM = "program"
    PLANS = "plans"


def _plans_fit(audience: Audience | None, plan_ids: list[uuid.UUID] | None) -> None:
    if audience is not None and audience is not Audience.PLANS and plan_ids:
        raise ValueError("only an audience of plans names plans")


class MaterialIn(BaseModel):
    """New material. On a session, `recurring` puts it on the session's recurring class
    from `starts_on` (the session's date unless told) instead of on the session alone.
    On a recurring class, it is always from `starts_on`, today unless told."""

    model_config = ConfigDict(extra="forbid")

    title: Title
    body: Body | None = None
    links: list[Link] = Field(default=[], max_length=MAX_LINKS)
    audience: Audience
    plan_ids: list[uuid.UUID] = Field(default=[], max_length=MAX_PLANS)
    recurring: bool = False
    starts_on: date | None = None

    @model_validator(mode="after")
    def _fits(self) -> "MaterialIn":
        if self.audience is Audience.PLANS and not self.plan_ids:
            raise ValueError("an audience of plans names at least one")
        _plans_fit(self.audience, self.plan_ids)
        return self


class MaterialChange(BaseModel):
    """An edit: only the fields sent change. `body` sent as null clears it. Changing the
    audience to `plans` sends `plan_ids` with it, unless it named plans already; the
    plans of any other audience are dropped."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    body: Body | None = None
    links: list[Link] | None = Field(default=None, max_length=MAX_LINKS)
    audience: Audience | None = None
    plan_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_PLANS)
    # Only for a recurring one.
    starts_on: date | None = None

    @model_validator(mode="after")
    def _fits(self) -> "MaterialChange":
        for field in ("title", "links", "audience", "starts_on"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be cleared")
        _plans_fit(self.audience, self.plan_ids)
        return self


class PlanName(BaseModel):
    id: uuid.UUID
    name: str


class Material(BaseModel):
    """A material as staff read it on a class: everything, and who may change it."""

    id: uuid.UUID
    title: str
    body: str | None
    links: list[str]
    audience: Audience
    plans: list[PlanName]
    # The session it is on, or, for a recurring one, null and the date it shows from.
    session_id: uuid.UUID | None
    starts_on: date | None
    shared_by_name: str | None
    created_at: datetime
    updated_at: datetime | None


class MyMaterial(BaseModel):
    """A material on the student page: what it is, the class it reached them through and
    its day, who shared it. A recurring one's day is the one it shows from."""

    id: uuid.UUID
    title: str
    body: str | None
    links: list[str]
    class_type_name: str
    program_name: str
    day: date
    recurring: bool
    shared_by_name: str | None
    created_at: datetime
    # The dependents it reaches, by name, when it does not reach the signed-in person:
    # a guardian's "Para León".
    for_names: list[str]


class MyMaterialPage(BaseModel):
    """A page of the student page's material, newest first (#548). `next`, when there
    is older material, is what `before` takes to read the page after this one."""

    items: list[MyMaterial]
    next: str | None
