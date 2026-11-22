"""A gym's plans: six kinds, each with its own parameters.

The body is told apart by `kind`, and each kind takes exactly its own parameters
(docs/technical.md#sport-agnostic-design): a `period_months` on a monthly plan is a
422, not ignored. A trial's `free_classes` and `free_days` are stored in `credits` and
`credit_expiry_days` (migration 0007); `from_row` and `to_columns` translate.

The kind is set on create. An edit changes the name, the price or the kind's own
parameters, the program, and `active`: a plan is deactivated, never deleted. Any kind
may name the program it is for (`program_id`, migration 0016). A coach reads a plan
without its price (`PlanForCoach`, #205).

A plan a member joins and pays on again (monthly, prepaid, fixed-period, credits) may
carry an enrolment fee, `enrolment_fee_clp` (#355): a matrícula charged once as a
membership on it starts (`app.api.enrolment`). Money, so a coach does not read it.

A fixed-period plan (#351) runs from `period_start` to `period_end`, the same days for
every member on it, and is copied for the next period (`NextPeriod`).
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.domain.membership import PlanKind

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# The day of the month a monthly plan bills on: the member's signup day, or the 1st.
Anchor = Literal["signup", "first"]
# Bounded so a value the column cannot hold is a 422, not a driver error and a 500.
# `period_months`, `credits` and `credit_expiry_days` are `integer`; `price_clp` is
# `bigint`, capped well below it at a price no gym charges (CLP 100M is about USD 100k).
INT4_MAX = 2**31 - 1
MAX_PRICE_CLP = 100_000_000
Price = Annotated[int, Field(ge=0, le=MAX_PRICE_CLP)]
Count = Annotated[int, Field(gt=0, le=INT4_MAX)]
# None is no fee; a fee of nothing is no fee too, and is refused rather than stored.
Fee = Annotated[int, Field(gt=0, le=MAX_PRICE_CLP)]


class _Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    # The program the plan is for, and so its members' (migration 0016); none for a
    # plan open to any class, such as a drop-in.
    program_id: uuid.UUID | None = None


# Each priced kind's terms without its price: what a coach reads of it (#205).


class _MonthlyTerms(_Plan):
    kind: Literal[PlanKind.MONTHLY]
    anchor: Anchor


class _PrepaidTerms(_Plan):
    kind: Literal[PlanKind.PREPAID]
    period_months: Count


def period_ends_after_start(end: date, info: ValidationInfo) -> date:
    """A period's `period_end`, refused when before its `period_start` (`period_order`)."""
    start = info.data.get("period_start")
    if start is not None and end < start:
        raise PydanticCustomError("period_order", "period_end is before period_start")
    return end


class _FixedPeriodTerms(_Plan):
    kind: Literal[PlanKind.FIXED_PERIOD]
    period_start: date
    period_end: date

    check_order = field_validator("period_end")(period_ends_after_start)


class _CreditsTerms(_Plan):
    kind: Literal[PlanKind.CREDITS]
    credits: Count
    credit_expiry_days: Count


class _DropinTerms(_Plan):
    kind: Literal[PlanKind.DROPIN]


class MonthlyPlanCreate(_MonthlyTerms):
    price_clp: Price
    enrolment_fee_clp: Fee | None = None


class PrepaidPlanCreate(_PrepaidTerms):
    price_clp: Price
    enrolment_fee_clp: Fee | None = None


class FixedPeriodPlanCreate(_FixedPeriodTerms):
    price_clp: Price
    enrolment_fee_clp: Fee | None = None


class CreditsPlanCreate(_CreditsTerms):
    price_clp: Price
    enrolment_fee_clp: Fee | None = None


class DropinPlanCreate(_DropinTerms):
    price_clp: Price


class TrialPlanCreate(_Plan):
    """Free: no price. Lasts `free_classes` classes, `free_days` days, or whichever
    comes first."""

    kind: Literal[PlanKind.TRIAL]
    free_classes: Count | None = None
    free_days: Count | None = None

    @model_validator(mode="after")
    def _limited(self) -> "TrialPlanCreate":
        if self.free_classes is None and self.free_days is None:
            raise ValueError("a trial needs free_classes, free_days or both")
        return self


PlanCreate = Annotated[
    MonthlyPlanCreate
    | PrepaidPlanCreate
    | FixedPeriodPlanCreate
    | CreditsPlanCreate
    | DropinPlanCreate
    | TrialPlanCreate,
    Field(discriminator="kind"),
]
PLAN_CREATE: TypeAdapter[PlanCreate] = TypeAdapter(PlanCreate)


class PlanUpdate(BaseModel):
    """Only the fields sent change. Parameters must be the plan's own kind's, and the
    plan must still be complete afterwards: a `null` that leaves it without a required
    one is a 422."""

    # `extra="forbid"` makes a `kind` here a 422 rather than silently ignored.
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    price_clp: Price | None = None
    # `null` takes the fee off.
    enrolment_fee_clp: Fee | None = None
    anchor: Anchor | None = None
    period_months: Count | None = None
    period_start: date | None = None
    period_end: date | None = None
    credits: Count | None = None
    credit_expiry_days: Count | None = None
    free_classes: Count | None = None
    free_days: Count | None = None
    # `null` takes the plan out of its program.
    program_id: uuid.UUID | None = None
    active: bool | None = None
    # With `anchor`, move the memberships on the plan to the day it gives them from their
    # next period not billed (#547), as `GET /{id}/anchor-moves` quotes it; with the
    # anchor the plan has, those still on another day. Without, they keep the day they
    # bill on and only new members take the new one, and a change of the anchor
    # withdraws a move pending to a day it no longer gives.
    move_members: bool = False

    @model_validator(mode="after")
    def _never_null(self) -> "PlanUpdate":
        for field in ("name", "active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.move_members and self.anchor is None:
            raise PydanticCustomError("move_needs_anchor", "move_members needs an anchor")
        return self


class _Stored(BaseModel):
    id: uuid.UUID
    active: bool
    created_at: datetime


class MonthlyPlan(MonthlyPlanCreate, _Stored):
    pass


class PrepaidPlan(PrepaidPlanCreate, _Stored):
    pass


class FixedPeriodPlan(FixedPeriodPlanCreate, _Stored):
    pass


class CreditsPlan(CreditsPlanCreate, _Stored):
    pass


class DropinPlan(DropinPlanCreate, _Stored):
    pass


class TrialPlan(TrialPlanCreate, _Stored):
    pass


Plan = Annotated[
    MonthlyPlan | PrepaidPlan | FixedPeriodPlan | CreditsPlan | DropinPlan | TrialPlan,
    Field(discriminator="kind"),
]
PLAN: TypeAdapter[Plan] = TypeAdapter(Plan)


class MonthlyPlanForCoach(_MonthlyTerms, _Stored):
    pass


class PrepaidPlanForCoach(_PrepaidTerms, _Stored):
    pass


class FixedPeriodPlanForCoach(_FixedPeriodTerms, _Stored):
    pass


class CreditsPlanForCoach(_CreditsTerms, _Stored):
    pass


class DropinPlanForCoach(_DropinTerms, _Stored):
    pass


# A plan as a coach reads it: what it is and how it runs, never what it costs. Coaches
# never see money (`app.roles`), in the screens or in what the API sends them (#205).
# A trial has no price, so it reads the same.
PlanForCoach = Annotated[
    MonthlyPlanForCoach
    | PrepaidPlanForCoach
    | FixedPeriodPlanForCoach
    | CreditsPlanForCoach
    | DropinPlanForCoach
    | TrialPlan,
    Field(discriminator="kind"),
]
PLAN_FOR_COACH: TypeAdapter[PlanForCoach] = TypeAdapter(PlanForCoach)


def for_coach(plan: Plan) -> PlanForCoach:
    return PLAN_FOR_COACH.validate_python(
        plan.model_dump(exclude={"price_clp", "enrolment_fee_clp"})
    )


KIND_MODELS: dict[PlanKind, type[_Plan]] = {
    PlanKind.MONTHLY: MonthlyPlanCreate,
    PlanKind.PREPAID: PrepaidPlanCreate,
    PlanKind.FIXED_PERIOD: FixedPeriodPlanCreate,
    PlanKind.CREDITS: CreditsPlanCreate,
    PlanKind.DROPIN: DropinPlanCreate,
    PlanKind.TRIAL: TrialPlanCreate,
}

# The trial's names for the columns it shares with a credits plan.
TRIAL_COLUMNS = {"free_classes": "credits", "free_days": "credit_expiry_days"}
COLUMNS = (
    "name",
    "kind",
    "program_id",
    "price_clp",
    "enrolment_fee_clp",
    "anchor",
    "period_months",
    "period_start",
    "period_end",
    "credits",
    "credit_expiry_days",
)


def from_row(row: dict[str, Any]) -> dict[str, Any]:
    """A `plan` row as the fields of its kind (and `id`, `active`, `created_at`)."""
    kind = PlanKind(row["kind"])
    if kind is PlanKind.TRIAL:
        row = {**row, **{field: row[column] for field, column in TRIAL_COLUMNS.items()}}
    keep = KIND_MODELS[kind].model_fields.keys() | _Stored.model_fields.keys()
    return {k: v for k, v in row.items() if k in keep}


def to_columns(plan: _Plan) -> dict[str, Any]:
    """A plan's fields as every `plan` column, null for other kinds' parameters."""
    fields = plan.model_dump()
    if fields["kind"] == PlanKind.TRIAL:
        fields["price_clp"] = 0
        for field, column in TRIAL_COLUMNS.items():
            fields[column] = fields.pop(field)
    return {column: fields.get(column) for column in COLUMNS}


# The most memberships one "Duplicar para el próximo período" moves.
MAX_MOVED = 5_000


class NextPeriod(BaseModel):
    """A fixed-period plan copied for the period after its own (#351): the copy's
    name, price and dates (it keeps the plan's enrolment fee), and the memberships on
    the plan to move onto it, each from the day after it is paid through
    (`app.domain.membership.plan_change_starts`). `period_start` must come after the
    plan's `period_end` (`after_period`)."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    price_clp: Price
    period_start: date
    period_end: date
    membership_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MOVED)

    check_order = field_validator("period_end")(period_ends_after_start)


class NextPeriodResult(BaseModel):
    plan: FixedPeriodPlan
    # How many memberships now move to it.
    moved: int


class PlanMembership(BaseModel):
    """A membership on a plan now, Active or Frozen, as the plan's list shows it."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    name: str
    status: Literal["active", "frozen"]
    # A change to another plan already pending, which a move replaces.
    next_plan_name: str | None


class AnchorMove(BaseModel):
    """A membership on a monthly plan as a change of the plan's anchor would move it
    (#547), from its first period not billed: the day it bills on and the one it would,
    the transition period to the new day, prorated (`starts_on` to `ends_on`, for
    `amount_due_clp`), and the first whole period on the new day (`next_starts_on`, for
    `next_amount_clp`). Both after its discount."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    name: str
    status: Literal["active", "frozen"]
    from_day: int
    to_day: int
    starts_on: date
    ends_on: date
    amount_due_clp: int
    next_starts_on: date
    next_amount_clp: int


class AnchorWithdrawal(BaseModel):
    """A membership whose move pending to `pending_day` a change of its plan's anchor
    withdraws (#547): it stays on `stays_on`, the day it bills on."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    name: str
    status: Literal["active", "frozen"]
    pending_day: int
    stays_on: int


class AnchorMoves(BaseModel):
    """A change of a monthly plan's anchor quoted (#547): who `move_members` moves, and
    whose pending move it withdraws without it."""

    moves: list[AnchorMove]
    withdrawn: list[AnchorWithdrawal]
