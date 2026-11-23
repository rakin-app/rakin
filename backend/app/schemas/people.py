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
    Field,
    PastDate,
    StringConstraints,
    model_validator,
)

from app.domain.membership import MembershipStatus
from app.domain.phone import normalize_phone
from app.domain.rut import normalize_rut
from app.domain.vocabulary import DEFAULT, Vocabulary
from app.permissions import Permission
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
# Someone under 18 is enrolled, imported or edited only with a guardian (#368).
MINOR_NEEDS_GUARDIAN = "a minor needs a guardian"


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
    # A minor by birth date with no guardian here: nothing is sent to them until one is
    # added, "Falta apoderado" (#368).
    missing_guardian: bool
    name: str
    email: str | None
    rut: str | None
    dob: date | None
    # The day they left this gym (dado de baja); null while they are here.
    left_on: date | None
    # Why they left, as the gym wrote it (#294). It is personal, so a coach's read leaves
    # it out: null for them, whatever it holds. Never health data, which a gym may not
    # keep (#384), though the text is the gym's.
    left_reason: str | None = None
    # The plan their Dar de baja ended, which "Deshacer baja" brings back with them in
    # one step (#549); null while they are here, or when that leave ended none it can.
    left_with: uuid.UUID | None = None
    # History from before Rakin (#293): the day they first trained here, and how many
    # classes they had. Read by the ficha only, never by billing.
    member_since: date | None
    prior_classes: int
    # When this gym added them, not when the identity was first seen.
    created_at: datetime
    updated_at: datetime
    # An anonymous record (#372): someone who paid and asked to be deleted, kept for the
    # books with nothing about them. Nothing of it can be edited.
    anonymised: bool = False


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
    `send_welcome` emails the welcome, with its sign-in link: about the plan, or with no
    plan that they are on the gym's roster (#246). With no email to send it to, theirs
    or their guardian's, nothing goes.
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
        return self


class WelcomeSent(BaseModel):
    """The latest welcome about someone, as `message_log` recorded it: `failed` with the
    relay's refusal or an address no mail reaches, `suppressed` when its address was."""

    status: Literal["sent", "failed", "suppressed"]
    sent_at: datetime
    to: str


class Suppression(BaseModel):
    """Why no mail goes to an address (#104): Resend reported a hard `bounce` (with what
    the receiving server said, if anything) or a spam `complaint`, on `since`."""

    reason: Literal["bounce", "complaint"]
    detail: str | None
    since: datetime


class WelcomeState(BaseModel):
    """Their sign-in link, on the ficha (#246): the address a welcome goes to, theirs or
    their guardian's (`guardian` names them then), `None` with neither; the latest
    welcome sent about them, if any; and, when no mail goes to that address, why."""

    to: str | None
    guardian: str | None
    last: WelcomeSent | None
    suppressed: Suppression | None = None


def _said(value: str | None) -> str | None:
    """A reason left blank is no reason."""
    return value or None


# Why someone left (#294): free text the chips fill ("Precio", "Motivo personal"), and no more
# than a line. Blank is not said.
LeftReason = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(_said),
]


class Leaving(BaseModel):
    """Dar de baja: the day they left, today in the gym's timezone when omitted, and
    never later nor more than `HISTORY_WINDOW_YEARS` back; and why, if the gym says."""

    model_config = ConfigDict(extra="forbid")

    left_on: date | None = None
    left_reason: LeftReason = None


# How far back history may go: a typo guard, not a rule (a founder's first students).
# Billing's own dates keep their five years (`STARTED_ON_WINDOW_YEARS`).
HISTORY_WINDOW_YEARS = 60


class FormerStudent(BaseModel):
    """ "Agregar exalumno" (#294): someone who trained here before Rakin and has left.
    Who they are, by RUT or email; a phone if the gym has one, though nobody will write
    to them; the day they started, if known, and the day they left, with why. No plan
    and no welcome. The API checks both days against the gym's today and
    `HISTORY_WINDOW_YEARS`, and that they started before they left."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    rut: Rut | None = None
    email: Email | None = None
    phone: Phone | None = None
    member_since: date | None = None
    left_on: date
    left_reason: LeftReason = None

    @model_validator(mode="after")
    def _identified(self) -> "FormerStudent":
        require_identity(self.rut, self.email)
        if self.member_since is not None and self.member_since > self.left_on:
            raise ValueError("member_since is left_on at the latest")
        return self


# Classes before Rakin: a lifetime of daily training, and then some.
MAX_PRIOR_CLASSES = 20_000


class PersonHistory(BaseModel):
    """ "Fecha de inicio y clases" (#293): the day they first trained here, null when not
    known, and how many classes they had before Rakin. The API checks the date against
    the gym's today and `HISTORY_WINDOW_YEARS`."""

    model_config = ConfigDict(extra="forbid")

    member_since: date | None
    prior_classes: Annotated[int, Field(ge=0, le=MAX_PRIOR_CLASSES)]


class Return(BaseModel):
    """Reactivar, and with `membership` start them on a plan again."""

    model_config = ConfigDict(extra="forbid")

    membership: MembershipStart | None = None


# Why `DELETE /api/people/{id}` keeps someone (migration 0032).
# Why someone cannot be deleted (#256): `payment`, the gym kept money of theirs, refunded
# first; `pending`, a proof of theirs waits for review, rejected first; `owes`, a charge
# of theirs is still owed, voided first; `staff`, they are on the gym's staff or coached
# here; `guardian`, they answer for a dependent here.
# `moved`: a payment of theirs moved to a sibling (#280), whose entry names it.
ForgetCode = Literal["payment", "pending", "owes", "moved", "staff", "guardian"]


class ForgetConflict(BaseModel):
    code: ForgetCode
    # The money it is about, on `payment` (what the gym kept) and `owes` (what is owed).
    amount_clp: int | None = None


class Deletion(BaseModel):
    """Whether they can be deleted: `refused` says why not, null when they can."""

    refused: ForgetCode | None
    amount_clp: int | None = None


class Forgetting(BaseModel):
    """`DELETE /api/people/{id}`: why, for the gym's log (`audit_event`, #256)."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ForgetRefused(BaseModel):
    """409 body: money of theirs still stands, they are staff, or they answer for a
    dependent."""

    detail: ForgetConflict


# Why someone cannot be anonymised (`anonymise_refusal`, 0099): `anonymised`, they
# already are; `running`, they are not dado de baja or a plan of theirs has not ended;
# `pending`, a proof waits; `owes`, a charge not voided is owed; `staff` and `guardian`
# as for a deletion. Money the gym kept is no reason: the books keep it.
AnonymiseCode = Literal["anonymised", "running", "pending", "owes", "staff", "guardian"]


class AnonymiseConflict(BaseModel):
    code: AnonymiseCode
    # What is owed, on `owes`.
    amount_clp: int | None = None


class Anonymisation(BaseModel):
    """Whether they can be anonymised: `refused` says why not, null when they can."""

    refused: AnonymiseCode | None
    amount_clp: int | None = None


class AnonymiseRefused(BaseModel):
    """409 body: why they were not anonymised."""

    detail: AnonymiseConflict


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
    missing_guardian: bool
    rut: str | None
    membership: MembershipSummary | None
    # Who pays for them in this gym, and how many they pay for (migration 0010).
    guardian: PersonRef | None
    dependents: int
    # The day they left, on the "Dados de baja" list (migration 0032).
    left_on: date | None
    # The shown membership has a period not yet settled, overdue or due soon: the row's
    # "Pagar" (#265). Always `false` for a coach, who never sees money.
    owes: bool


class MemberPage(BaseModel):
    items: list[MemberRow]
    # Every match, not just this page's.
    total: int


class PracticeNames(BaseModel):
    """What the screens call the gym's free practice, its block and the "Sparring en
    total" of a person's time, and the open mat made of it (#346, `app.domain.practice`):
    "Sparring" and "Open mat", "Escalada libre" twice."""

    block: str
    open_mat: str


class MyRole(BaseModel):
    """The person acting's role in the current gym; `None` for a member. `person_id` is
    who they are, for a screen that answers differently to the coach of a class; `name`
    and `email` as this gym has them (Ajustes → Cuenta), and the gym's own name.
    `student_page`: whether they hold a membership here or pay for a dependent, so the
    admin shell links staff who also train to their student page (#214).

    `permissions` is what they may do here (`app.permissions`), `None` when they are not
    on the team; `account_holder` whether they hold the gym's account, and with it every
    permission (#308)."""

    role: Role | None
    permissions: list[Permission] | None
    account_holder: bool
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
    # What the gym calls itself, its members and its coach (#344).
    vocabulary: Vocabulary = DEFAULT
    # What the gym calls its free practice and its open mat (#346).
    practice: PracticeNames = PracticeNames(block="Sparring", open_mat="Open mat")
    # Whether the gym accepted the current terms (#499), and who accepts them for it.
    terms: Literal["pending", "outdated", "current"] = "current"
    titular_name: str | None = None
