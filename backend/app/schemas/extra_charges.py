"""Cobros extra and the groups they target, as the API reads and writes them (#195).

A cobro is drafted in a wizard: its details, whom it is for (`Target`), how much
(`amount_mode`, `amount_clp` and any per-person `overrides`), and its message. The
draft is previewed (`ExtraChargePreview`) before it is created, so the admin sees each
person's amount, the remainder of a split, and who has no email to be told by.

A cobro may be paid in instalments (#356): each person then has a line per instalment,
each with its own due date, monthly from the cobro's.

Once created, each person has a line, with what they owe, have paid and have claimed
by a proof, and the line's status: pendiente, comprobante enviado, pagado or anulado.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.domain.extra_charges import (
    MAX_INSTALMENTS,
    AmountMode,
    Category,
    LineStatus,
    TargetKind,
)
from app.schemas.ledger import Amount, Method, Note, PersonRef, SignedAmount
from app.schemas.plans import MAX_PRICE_CLP

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


def _drafted(category: Category) -> Category:
    if category is Category.MATRICULA:
        raise ValueError("a matrícula is charged as a plan starts, not drafted")
    return category


# The kinds an admin drafts: a matrícula comes with a plan's start (#355).
DraftedCategory = Annotated[Category, AfterValidator(_drafted)]

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
    # "En cuotas": each person's amount in this many, monthly from the due date.
    instalments: Annotated[int, Field(ge=1, le=MAX_INSTALMENTS)] = 1


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
    category: DraftedCategory
    # The first instalment's, in instalments.
    due_date: date
    # Email each person their amount (their guardian, for a dependent).
    notify: bool = True


class PreviewLine(BaseModel):
    person: PersonRef
    amount_clp: int
    # In instalments, what each is, the first carrying the remainder; else `[amount_clp]`.
    instalments_clp: list[int]
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
    # When each instalment is due, once the draft has a due date.
    due_dates: list[date]


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
    # Which instalment, from 1; 1 in a cobro paid at once.
    instalment: int
    due_date: date
    # Who pays for them, when they are a dependent.
    guardian: PersonRef | None
    amount_due_clp: int
    overridden: bool
    paid_clp: int
    outstanding_clp: int
    pending_clp: int
    status: LineStatus
    cancelled_at: datetime | None
    # Why it was cancelled ("Anular", #256); null on a line cancelled before reasons.
    cancel_reason: str | None = None
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
    # 1, or how many instalments each person pays it in.
    instalments: int
    target_kind: TargetKind
    target_label: str | None
    created_at: datetime
    # People whose lines not cancelled owe something, and of them those paid in full:
    # "7 de 9 pagaron". People let off at nothing (exentos) are `waived_lines`, in
    # neither. In instalments, someone has paid when every instalment is paid.
    lines: int
    paid_lines: int
    waived_lines: int
    # What the lines not cancelled owe, and what they have been paid.
    due_clp: int
    collected_clp: int


class InstalmentProgress(BaseModel):
    """One instalment of a cobro in instalments, across everyone: "Cuota 2 · 3 de 9
    pagaron · $100.000 de $300.000". Counted as the summary counts, over its lines."""

    instalment: int
    due_date: date
    lines: int
    paid_lines: int
    waived_lines: int
    due_clp: int
    collected_clp: int


class LinkedExpenses(BaseModel):
    """What the gym paid that this cobro recovers, beside what it collected (#318):
    "Gastos asociados $X · Recaudado $Y · Diferencia $Y-X". Both gross, as they were:
    nothing nets, and the cobro's lines are unchanged."""

    # The expenses that name the cobro and count (not voided), and their sum.
    count: int
    expenses_clp: int
    # The summary's `collected_clp`: what the lines not cancelled have been paid.
    collected_clp: int
    # Collected less spent: below zero, the group has not paid it all back.
    difference_clp: int


class ExtraCharge(ExtraChargeSummary):
    description: str | None
    message: str | None
    # Each person's lines, by name, then instalment.
    people: list[Line]
    # Paid and owed per instalment; one entry for a cobro paid at once.
    schedule: list[InstalmentProgress]
    # To whoever also holds `expenses_read`: what the gym spent that it recovers.
    # `None` without it, so the answer says nothing of expenses, not even a zero.
    expenses: LinkedExpenses | None = None


class LineAmountChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_clp: LineAmount


class LineCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Mandatory: why the person no longer owes it (#256).
    reason: Note
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
