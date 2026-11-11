"""The join link (#154): the gym's link, the public form behind it, and the requests it
leaves for staff to approve.

The form's fields are normalised as a person's are (`app.schemas.people`), so a
request holds E.164 phones and `76123456-0` RUTs, and approving one adds the person
exactly as staff adding them would.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PastDate, StringConstraints

from app.member_import.rows import ErrorCode
from app.schemas.people import Email, PersonRef, Phone, Rut

# Each half of the name; the person's name is both, as one.
NamePart = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
GuardianName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]

# Under this age on the day they send it, the form asks for a guardian.
ADULT_AGE = 18


def age_on(dob: date, today: date) -> int:
    """Whole years from `dob` to `today`; someone born on 29 February turns a year
    older on 1 March in a year without one."""
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


class JoinLinkOptions(BaseModel):
    """What a link may say besides its token: the program it pre-selects and the last
    day it works, in the gym's timezone. Either is optional; `null` clears it."""

    model_config = ConfigDict(extra="forbid")

    program_id: uuid.UUID | None = None
    expires_on: date | None = None


class JoinLink(BaseModel):
    url: str
    token: str
    program_id: uuid.UUID | None
    program_name: str | None
    expires_on: date | None
    # Past `expires_on`: the link answers as an invalid one until it is changed.
    expired: bool
    created_at: datetime


class JoinForm(BaseModel):
    """What the public form shows for a link that works."""

    gym: str
    # Where the gym's logo's files are (`app.logos.logo_path`); None with no logo (#223).
    gym_logo: str | None = None
    program: str | None
    # The gym's today, which says who is a minor.
    today: date
    # The human check's widget key (`app.integrations.humancheck`), when there is one.
    human_check_site_key: str | None


class JoinSubmission(BaseModel):
    """The public form, sent. A minor's guardian is required by the endpoint, which
    knows the gym's today; an adult's guardian fields are ignored."""

    model_config = ConfigDict(extra="forbid")

    first_name: NamePart
    last_name: NamePart
    # Who they are when they give one (#165); with none, their email is.
    rut: Rut | None = None
    # An adult's email is required; a minor may leave it to their guardian's. An
    # adult's phone is required too, the gym's way to reach them on WhatsApp, unless
    # `no_whatsapp`; a minor's is optional, and their guardian's required instead.
    phone: Phone | None = None
    email: Email | None = None
    dob: PastDate
    guardian_name: GuardianName | None = None
    guardian_phone: Phone | None = None
    guardian_email: Email | None = None
    # "No tiene WhatsApp", for the adult, or for a minor's guardian.
    no_whatsapp: bool = False
    consent: Literal[True]
    # The honeypot: a field people never see, so only a script fills it in.
    website: Annotated[str, Field(max_length=200)] = ""
    # The human check widget's answer, when the form shows one.
    human_check_token: Annotated[str, Field(max_length=4096)] | None = None


class JoinGuardian(BaseModel):
    name: str
    phone: str | None
    email: str


class JoinRequest(BaseModel):
    """A request waiting in the queue, with whoever in this gym it may already be."""

    id: uuid.UUID
    first_name: str
    last_name: str
    rut: str | None
    phone: str | None
    email: str | None
    dob: date
    no_whatsapp: bool
    guardian: JoinGuardian | None
    program_id: uuid.UUID | None
    program_name: str | None
    created_at: datetime
    # Someone in this gym with the request's RUT, or, for a request with none, its
    # email: whom approving links.
    rut_in_gym: PersonRef | None
    email_in_gym: PersonRef | None
    # The request's email, when approving leaves it unused: someone here has the RUT,
    # and keeps the email this gym has for them.
    ignored_email: str | None


class JoinRequestPage(BaseModel):
    items: list[JoinRequest]
    # Every request waiting, not just this page's.
    total: int


class JoinApproval(BaseModel):
    """`plan_id` starts a membership on it; owner and admin only. Without one, the
    member is added with no plan."""

    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID | None = None


class JoinApproved(BaseModel):
    person_id: uuid.UUID
    membership_id: uuid.UUID | None


# The importer's refusals of the family link, or `has_membership`: approving with a
# plan someone who already holds a live membership here.
JoinRefusalCode = ErrorCode | Literal["has_membership"]


class JoinRefusal(BaseModel):
    """409 body: the family link the request asks for is one the gym cannot make
    (migration 0010), or the person is a member already, on `field`."""

    code: JoinRefusalCode
    field: str


class JoinRefused(BaseModel):
    detail: JoinRefusal
