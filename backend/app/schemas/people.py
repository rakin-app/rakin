"""A person as one gym knows them: create, edit, read, and the member list.

Inputs are normalised here, so the database only ever sees E.164 phones and
`76123456-0` RUTs. Someone is their RUT, or with none an email in this gym (migration
0036), so a person needs one of the two; a dependent may have neither. The phone is a
contact, this gym's to edit like the email, and finds nobody. A RUT edited here
changes this gym's record only, not who the person is.

A member needs a phone, since the gym reaches them on WhatsApp, unless the gym ticks
"No tiene WhatsApp" (`no_whatsapp`); a minor's is their guardian's. Staff need none.
The schemas check what the body alone can say; the API checks the rest (who is staff,
who has a guardian).
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
from app.schemas.theme import Theme

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


def require_identity(rut: str | None, email: str | None) -> None:
    """Refuse someone with neither a RUT nor an email: nothing would say who they are."""
    if rut is None and email is None:
        raise ValueError("a person needs a RUT or an email")


PHONE_REQUIRED = "a phone is required unless no_whatsapp is set"


def require_phone(phone: str | None, no_whatsapp: bool) -> None:
    """Refuse a member's contact with no phone, unless "No tiene WhatsApp" is ticked."""
    if phone is None and not no_whatsapp:
        raise ValueError(PHONE_REQUIRED)


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    rut: Rut | None = None
    email: Email | None = None
    phone: Phone | None = None
    no_whatsapp: bool = False
    dob: PastDate | None = None

    @model_validator(mode="after")
    def _identified(self) -> "PersonCreate":
        require_identity(self.rut, self.email)
        return self


class PersonUpdate(BaseModel):
    """Only the fields sent change; `null` clears an optional one."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    email: Email | None = None
    phone: Phone | None = None
    no_whatsapp: bool | None = None
    rut: Rut | None = None
    dob: PastDate | None = None

    @model_validator(mode="after")
    def _name_is_never_cleared(self) -> "PersonUpdate":
        for column in ("name", "no_whatsapp"):
            if column in self.model_fields_set and getattr(self, column) is None:
                raise ValueError(f"{column} cannot be null")
        return self


class Person(BaseModel):
    id: uuid.UUID
    phone: str | None
    # "No tiene WhatsApp": no WhatsApp link goes to them (#165).
    no_whatsapp: bool
    # A member with no phone and the box unticked: "Falta teléfono".
    missing_phone: bool
    # No RUT and no email, and nobody's dependent: "Falta RUT".
    missing_rut: bool
    name: str
    email: str | None
    rut: str | None
    dob: date | None
    # The day they left this gym (dado de baja); null while they are here.
    left_on: date | None
    # When this gym added them, not when the identity was first seen.
    created_at: datetime
    updated_at: datetime


# `rut_in_gym`: the RUT is already someone's in this gym; `email_in_gym`: someone
# added with no RUT has an email someone here already has.
DuplicateCode = Literal["rut_in_gym", "email_in_gym"]


class PersonConflict(BaseModel):
    code: DuplicateCode
    person_id: uuid.UUID


class PersonInGym(BaseModel):
    """409 body: the RUT, or the email of someone with none, already belongs to someone
    in this gym, `person_id`."""

    detail: PersonConflict


class ExistingGuardian(BaseModel):
    """Someone already in this gym answers for the new member."""

    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID


class NewGuardian(BaseModel):
    """Someone new answers for them, added by their RUT or email as anyone is."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    rut: Rut | None = None
    email: Email | None = None
    # The guardian is who the gym messages about the minor, so theirs is required.
    phone: Phone | None = None
    no_whatsapp: bool = False

    @model_validator(mode="after")
    def _identified(self) -> "NewGuardian":
        require_identity(self.rut, self.email)
        require_phone(self.phone, self.no_whatsapp)
        return self


class Enrolment(BaseModel):
    """A member added by hand (#157): their record, the guardian a minor needs, the
    gym's custom fields, and the plan they start on, all or nothing.

    A dependent may come with neither a RUT nor an email, as kids do; anyone else needs
    one, since it is who they are (#165). An adult needs a phone, unless `no_whatsapp`;
    a minor's own is optional, since their guardian's is the one the gym uses.
    `fields` are written as `PATCH .../fields` writes them.
    `send_welcome` emails the welcome a membership sends, and needs a plan.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name
    rut: Rut | None = None
    email: Email | None = None
    phone: Phone | None = None
    no_whatsapp: bool = False
    dob: PastDate | None = None
    guardian: ExistingGuardian | NewGuardian | None = None
    fields: dict[str, Any] = {}
    membership: MembershipStart | None = None
    send_welcome: bool = False

    @model_validator(mode="after")
    def _reachable(self) -> "Enrolment":
        if self.guardian is None:
            require_identity(self.rut, self.email)
            require_phone(self.phone, self.no_whatsapp)
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
    no_whatsapp: bool
    missing_phone: bool
    missing_rut: bool
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
    who they are, for a screen that answers differently to the coach of a class; `name`
    and `email` as this gym has them (Ajustes → Cuenta), and the gym's own name.
    `student_page`: whether they hold a membership here or pay for a dependent, so the
    admin shell links staff who also train to their student page (#214)."""

    role: Role | None
    person_id: uuid.UUID
    name: str | None
    email: str | None
    gym_name: str
    student_page: bool
    # The gym's theme (#199): every signed-in screen wears it, whoever reads it.
    theme: Theme
    # Where the gym's logo's files are (`app.logos.logo_path`); None with no logo (#223).
    gym_logo: str | None = None
    # Whether any of the gym's activities grades students (#245): every belt and rank
    # on the gym's screens shows only then.
    uses_grades: bool = False
