"""A gym's plans: five kinds, each with its own parameters.

The body is told apart by `kind`, and each kind takes exactly its own parameters
(docs/technical.md#sport-agnostic-design): a `period_months` on a monthly plan is a
422, not ignored. A trial's `free_classes` and `free_days` are stored in `credits` and
`credit_expiry_days` (migration 0007); `from_row` and `to_columns` translate.

The kind is set on create. An edit changes the name, the price or the kind's own
parameters, the program, and `active`: a plan is deactivated, never deleted. Any kind
may name the program it is for (`program_id`, migration 0016). A coach reads a plan
without its price (`PlanForCoach`, #205).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

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


class _CreditsTerms(_Plan):
    kind: Literal[PlanKind.CREDITS]
    credits: Count
    credit_expiry_days: Count


class _DropinTerms(_Plan):
    kind: Literal[PlanKind.DROPIN]


class MonthlyPlanCreate(_MonthlyTerms):
    price_clp: Price


class PrepaidPlanCreate(_PrepaidTerms):
    price_clp: Price


class CreditsPlanCreate(_CreditsTerms):
    price_clp: Price


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
    MonthlyPlanCreate | PrepaidPlanCreate | CreditsPlanCreate | DropinPlanCreate | TrialPlanCreate,
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
    anchor: Anchor | None = None
    period_months: Count | None = None
    credits: Count | None = None
    credit_expiry_days: Count | None = None
    free_classes: Count | None = None
    free_days: Count | None = None
    # `null` takes the plan out of its program.
    program_id: uuid.UUID | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _never_null(self) -> "PlanUpdate":
        for field in ("name", "active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class _Stored(BaseModel):
    id: uuid.UUID
    active: bool
    created_at: datetime


class MonthlyPlan(MonthlyPlanCreate, _Stored):
    pass


class PrepaidPlan(PrepaidPlanCreate, _Stored):
    pass


class CreditsPlan(CreditsPlanCreate, _Stored):
    pass


class DropinPlan(DropinPlanCreate, _Stored):
    pass


class TrialPlan(TrialPlanCreate, _Stored):
    pass


Plan = Annotated[
    MonthlyPlan | PrepaidPlan | CreditsPlan | DropinPlan | TrialPlan,
    Field(discriminator="kind"),
]
PLAN: TypeAdapter[Plan] = TypeAdapter(Plan)


class MonthlyPlanForCoach(_MonthlyTerms, _Stored):
    pass


class PrepaidPlanForCoach(_PrepaidTerms, _Stored):
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
    | CreditsPlanForCoach
    | DropinPlanForCoach
    | TrialPlan,
    Field(discriminator="kind"),
]
PLAN_FOR_COACH: TypeAdapter[PlanForCoach] = TypeAdapter(PlanForCoach)


def for_coach(plan: Plan) -> PlanForCoach:
    return PLAN_FOR_COACH.validate_python(plan.model_dump(exclude={"price_clp"}))


KIND_MODELS: dict[PlanKind, type[_Plan]] = {
    PlanKind.MONTHLY: MonthlyPlanCreate,
    PlanKind.PREPAID: PrepaidPlanCreate,
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
    "anchor",
    "period_months",
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
