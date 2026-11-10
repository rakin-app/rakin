"""A person as one gym knows them: create, edit, read, and the member list.

Inputs are normalised here, so the database only ever sees E.164 phones and
`76123456-0` RUTs. The phone is the person's global identity and is set once, on
create: changing it means moving the gym's record to another identity, which this
API does not do yet.
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    PastDate,
    StringConstraints,
    model_validator,
)

from app.domain.membership import MembershipStatus
from app.domain.phone import normalize_phone
from app.domain.rut import normalize_rut
from app.roles import Role

# Enough to catch a typo or a phone in the email box; delivery is the real check.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _email(value: str) -> str:
    if _EMAIL.fullmatch(value) is None:
        raise ValueError("not an email address")
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_email)
]
Phone = Annotated[str, AfterValidator(normalize_phone)]
Rut = Annotated[str, AfterValidator(normalize_rut)]


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Phone
    name: Name
    email: Email | None = None
    rut: Rut | None = None
    dob: PastDate | None = None


class PersonUpdate(BaseModel):
    """Only the fields sent change; `null` clears an optional one."""

    # `extra="forbid"` makes a `phone` here a 422 rather than silently ignored.
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    email: Email | None = None
    rut: Rut | None = None
    dob: PastDate | None = None

    @model_validator(mode="after")
    def _name_is_never_cleared(self) -> "PersonUpdate":
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class Person(BaseModel):
    id: uuid.UUID
    phone: str | None
    name: str
    email: str | None
    rut: str | None
    dob: date | None
    # When this gym added them, not when the identity was first seen.
    created_at: datetime
    updated_at: datetime


class PhoneConflict(BaseModel):
    code: Literal["phone_in_gym"] = "phone_in_gym"
    person_id: uuid.UUID


class PhoneInGym(BaseModel):
    """409 body: the phone already belongs to someone in this gym, `person_id`."""

    detail: PhoneConflict


class MembershipSummary(BaseModel):
    """The membership a list row shows: the person's latest one that is not cancelled,
    else their latest."""

    id: uuid.UUID
    status: MembershipStatus
    plan_id: uuid.UUID
    plan_name: str


class PersonRef(BaseModel):
    id: uuid.UUID
    name: str


class MemberRow(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    rut: str | None
    membership: MembershipSummary | None
    # Who pays for them in this gym, and how many they pay for (migration 0010).
    guardian: PersonRef | None
    dependents: int


class MemberPage(BaseModel):
    items: list[MemberRow]
    # Every match, not just this page's.
    total: int


class MyRole(BaseModel):
    """The person acting's role in the current gym; `None` for a member. `person_id` is
    who they are, for a screen that answers differently to the coach of a class."""

    role: Role | None
    person_id: uuid.UUID
