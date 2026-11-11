"""Cobros extra and the groups they target, as the API reads and writes them (#195).

A cobro is drafted in a wizard: its details, whom it is for (`Target`), how much
(`amount_mode`, `amount_clp` and any per-person `overrides`), and its message. The
draft is previewed (`ExtraChargePreview`) before it is created, so the admin sees each
person's amount, the remainder of a split, and who has no email to be told by.

Once created, each person has a line, with what they owe, have paid and have claimed
by a proof, and the line's status: pendiente, comprobante enviado, pagado or anulado.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.domain.extra_charges import AmountMode, Category, LineStatus, TargetKind
from app.schemas.ledger import Amount, Method, Note, PersonRef, SignedAmount
from app.schemas.plans import MAX_PRICE_CLP

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

# A cobro charges at most this many people at once: a whole gym, with room.
MAX_PEOPLE = 1000

# An override may be nothing at all: a scholarship.
LineAmount = Annotated[int, Field(ge=0, le=MAX_PRICE_CLP)]


# --- groups -----------------------------------------------------------------------


class GroupSummary(BaseModel):
    id: uuid.UUID
    name: str
    size: int


class Group(BaseModel):
    id: uuid.UUID
    name: str
    members: list[PersonRef]


class GroupWrite(BaseModel):
    """A group as the admin saves it: its name and the people in it, a fixed list."""

    model_config = ConfigDict(extra="forbid")

    name: GroupName
    person_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_PEOPLE)]


# --- the draft --------------------------------------------------------------------


class Target(BaseModel):
    """Whom a cobro is for. Each kind names what it needs: a program, a group, or the
    people themselves."""

    model_config = ConfigDict(extra="forbid")

    kind: TargetKind
    program_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    person_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_PEOPLE)] = []

    @model_validator(mode="after")
    def names_what_it_needs(self) -> Self:
        needs = {
            TargetKind.ACTIVE: (False, False, False),
            TargetKind.PROGRAM: (True, False, False),
            TargetKind.GROUP: (False, True, False),
            TargetKind.PEOPLE: (False, False, True),
        }[self.kind]
        given = (self.program_id is not None, self.group_id is not None, bool(self.person_ids))
        if given != needs:
            raise ValueError(f"a {self.kind} target names only what it needs")
        return self


class Override(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    amount_clp: LineAmount


class AmountDraft(BaseModel):
    """Whom, and how much: what the split preview needs."""

    model_config = ConfigDict(extra="forbid")

    target: Target
    amount_mode: AmountMode
    # Each person's, or the total to divide.
    amount_clp: Amount
    overrides: Annotated[list[Override], Field(max_length=MAX_PEOPLE)] = []


class ExtraChargePreview(AmountDraft):
    """The draft so far. The title and due date, once given, prefill the WhatsApp
    messages for the people who have no email. The wizard sends the whole draft, so
    what the preview does not need is ignored."""

    model_config = ConfigDict(extra="ignore")

    title: Title | None = None
    due_date: date | None = None


class ExtraChargeCreate(AmountDraft):
    title: Title
    description: LongText | None = None
    # What the email says, above the amount.
    message: LongText | None = None
    category: Category
    due_date: date
    # Email each person their amount (their guardian, for a dependent).
    notify: bool = True


class PreviewLine(BaseModel):
    person: PersonRef
    amount_clp: int
    overridden: bool
    # Whom the notice goes to: them, or their guardian.
    contact_name: str
    on_behalf: bool
    has_email: bool
    # A `wa.me` link for someone with no email, once the draft has a title.
    whatsapp_url: str | None


class Preview(BaseModel):
    lines: list[PreviewLine]
    total_clp: int
    # A split's remainder, a peso more each for the first `remainder_clp` people.
    remainder_clp: int
    # A split's even share, before the remainder and any override.
    share_clp: int | None


# --- cobros and their lines -------------------------------------------------------


class RefundableLinePayment(BaseModel):
    id: uuid.UUID
    amount_clp: int
    method: Method | None
    validated_at: datetime | None
    refundable_clp: int


class Line(BaseModel):
    id: uuid.UUID
    person: PersonRef
    # Who pays for them, when they are a dependent.
    guardian: PersonRef | None
    amount_due_clp: int
    overridden: bool
    paid_clp: int
    outstanding_clp: int
    pending_clp: int
    status: LineStatus
    cancelled_at: datetime | None
    has_email: bool
    # A reminder on WhatsApp, for a line still owed, when the gym uses it.
    whatsapp_url: str | None
    # The proof waiting for review, if one does.
    pending_proof_id: uuid.UUID | None
    refundable_payments: list[RefundableLinePayment]


class ExtraChargeSummary(BaseModel):
    id: uuid.UUID
    title: str
    category: Category
    due_date: date
    amount_mode: AmountMode
    amount_clp: int
    target_kind: TargetKind
    target_label: str | None
    created_at: datetime
    # Lines not cancelled, and of them those paid in full.
    lines: int
    paid_lines: int
    # What the lines not cancelled owe, and what they have been paid.
    due_clp: int
    collected_clp: int


class ExtraCharge(ExtraChargeSummary):
    description: str | None
    message: str | None
    people: list[Line]


class LineAmountChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_clp: LineAmount


class LineCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Divide the total again among the lines left: a split nobody has paid yet.
    resplit: bool = False


class CancelPreview(BaseModel):
    """What cancelling a line would leave: whether the total can be divided again, and
    each other line's amount if it is."""

    resplit_allowed: bool
    amounts: dict[uuid.UUID, int]


class LinePayment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_clp: Amount
    method: Method
    note: Note | None = None


class LineAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_clp: SignedAmount
    note: Note

    @model_validator(mode="after")
    def not_zero(self) -> Self:
        if self.amount_clp == 0:
            raise ValueError("an adjustment is not zero")
        return self


class Reminded(BaseModel):
    # Emails sent, and lines with no email to send one to.
    sent: int
    without_email: int


# --- the person's own -------------------------------------------------------------


class MyExtraLine(BaseModel):
    """A cobro line the signed-in person can pay: their own or a dependent's."""

    id: uuid.UUID
    extra_charge_id: uuid.UUID
    title: str
    category: Category
    message: str | None
    due_date: date
    person_id: uuid.UUID
    person_name: str
    amount_due_clp: int
    paid_clp: int
    outstanding_clp: int
    pending_clp: int
    status: LineStatus
