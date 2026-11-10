"""A person as one gym knows them: create, edit, read, and the member list.

Inputs are normalised here, so the database only ever sees E.164 phones and
`76123456-0` RUTs. The phone is the person's global identity and is set once, on
create: changing it means moving the gym's record to another identity, which this
API does not do yet.
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

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
from app.schemas.memberships import MembershipStart

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
    # The day they left this gym (dado de baja); null while they are here.
    left_on: date | None
    # When this gym added them, not when the identity was first seen.
    created_at: datetime
    updated_at: datetime


# `phone_in_gym`: the phone is already someone's in this gym; `rut_in_gym`: the RUT.
DuplicateCode = Literal["phone_in_gym", "rut_in_gym"]


class PersonConflict(BaseModel):
    code: DuplicateCode = "phone_in_gym"
    person_id: uuid.UUID


class PersonInGym(BaseModel):
    """409 body: the phone or RUT already belongs to someone in this gym, `person_id`."""

    detail: PersonConflict


class ExistingGuardian(BaseModel):
    """Someone already in this gym answers for the new member."""

    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID


class NewGuardian(BaseModel):
    """Someone new answers for them, added by their phone as anyone is."""

    model_config = ConfigDict(extra="forbid")

    phone: Phone
    name: Name
    email: Email | None = None


class Enrolment(BaseModel):
    """A member added by hand (#157): their record, the guardian a minor needs, the
    gym's custom fields, and the plan they start on, all or nothing.

    A dependent may come without a phone, as kids do; anyone else needs one, since it
    is who they are (#18). `fields` are written as `PATCH .../fields` writes them.
    `send_welcome` emails the welcome a membership sends, and needs a plan.
    """

    model_config = ConfigDict(extra="forbid")

    phone: Phone | None = None
    name: Name
    email: Email | None = None
    rut: Rut | None = None
    dob: PastDate | None = None
    guardian: ExistingGuardian | NewGuardian | None = None
    fields: dict[str, Any] = {}
    membership: MembershipStart | None = None
    send_welcome: bool = False

    @model_validator(mode="after")
    def _reachable(self) -> "Enrolment":
        if self.phone is None and self.guardian is None:
            raise ValueError("a member needs a phone, or a guardian who has one")
        if self.send_welcome and self.membership is None:
            raise ValueError("the welcome is about a plan: send_welcome needs a membership")
        return self


class Leaving(BaseModel):
    """Dar de baja: the day they left, today in the gym's timezone when omitted, and
    never later."""

    model_config = ConfigDict(extra="forbid")

    left_on: date | None = None


class Return(BaseModel):
    """Reactivar, and with `membership` start them on a plan again."""

    model_config = ConfigDict(extra="forbid")

    membership: MembershipStart | None = None


# Why `DELETE /api/people/{id}` keeps someone (migration 0032).
ForgetCode = Literal["ledger", "staff", "guardian"]


class ForgetConflict(BaseModel):
    code: ForgetCode


class Deletion(BaseModel):
    """Whether they can be deleted: `refused` says why not, null when they can."""

    refused: ForgetCode | None


class ForgetRefused(BaseModel):
    """409 body: accounting keeps their ledger, they are staff, or they answer for a
    dependent."""

    detail: ForgetConflict


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
    # The day they left, on the "Dados de baja" list (migration 0032).
    left_on: date | None


class MemberPage(BaseModel):
    items: list[MemberRow]
    # Every match, not just this page's.
    total: int


class MyRole(BaseModel):
    """The person acting's role in the current gym; `None` for a member. `person_id` is
    who they are, for a screen that answers differently to the coach of a class."""

    role: Role | None
    person_id: uuid.UUID
