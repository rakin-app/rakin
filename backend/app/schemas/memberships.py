"""A person's membership of a plan: start one, change its plan, freeze or cancel it,
read it.

Dates are calendar dates in the gym's timezone (`app.domain.dates`): `started_on`,
`current_period_end` (paid through, or the last day of a pack or trial), the day a
pending plan change takes effect, and a freeze's first and last days. A freeze can
start on a later day, and end early or change its end or reason while it runs or
before it starts (#115).
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from app.domain.dates import add_months
from app.domain.membership import MembershipStatus, PlanKind

# How far `started_on` may be from today: room to backfill a gym's history or book a
# start ahead, and far from the edge of `date`'s range.
STARTED_ON_WINDOW_YEARS = 5

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class MembershipStart(BaseModel):
    """A plan to start someone on, from a day: as a membership starts, and as a new
    member or one reactivated can start one (#157)."""

    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    # Today in the gym's timezone when omitted; a past day records an existing member.
    started_on: date | None = None

    @field_validator("started_on")
    @classmethod
    def _near_today(cls, value: date | None) -> date | None:
        # system date: UTC's today, a day either side of any gym's; the window is years wide.
        today = datetime.now(UTC).date()
        months = 12 * STARTED_ON_WINDOW_YEARS
        if value is not None and not add_months(today, -months) <= value <= add_months(
            today, months
        ):
            raise ValueError(f"started_on must be within {STARTED_ON_WINDOW_YEARS} years of today")
        return value


class MembershipCreate(MembershipStart):
    person_id: uuid.UUID
    # The welcome, when there is an email to send it to; "Asignar plan" on the ficha
    # may leave it out (#249).
    send_welcome: bool = True


class HasLeftConflict(BaseModel):
    code: Literal["has_left"] = "has_left"


class HasLeft(BaseModel):
    """409 body: the person has left the gym (dado de baja); reactivate them first."""

    detail: HasLeftConflict


class PlanChange(BaseModel):
    """The plan to move to next period; the membership's own plan withdraws a pending
    change."""

    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID


class PlanChangeQuote(BaseModel):
    """What a change to a plan would do, before it is saved (#249): the day it takes
    effect, the current plan running until then, and the first period it bills, from
    that day until `period_end`, for `amount_due_clp` after the membership's discount."""

    starts_on: date
    period_end: date
    amount_due_clp: int


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class FreezeCreate(BaseModel):
    """A freeze from `from_date` until `to_date`, the day the membership is Active
    again."""

    model_config = ConfigDict(extra="forbid")

    # Today in the gym's timezone when omitted; a later day books it ahead.
    from_date: date | None = None
    to_date: date
    reason: Reason


class FreezeEdit(BaseModel):
    """A new end or reason for the freeze running or booked; what is omitted stays."""

    model_config = ConfigDict(extra="forbid")

    to_date: date | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def _something(self) -> "FreezeEdit":
        if self.to_date is None and self.reason is None:
            raise ValueError("an edit needs a to_date or a reason")
        return self


class Freeze(BaseModel):
    id: uuid.UUID
    # Its first day, and the day it ends, when the membership is Active again.
    from_date: date
    to_date: date
    reason: str
    # False on a freeze booked ahead, until the `freezes` job starts it on `from_date`.
    started: bool


class PendingPlanChange(BaseModel):
    plan_id: uuid.UUID
    plan_name: str
    # The first day the plan applies: the start of the first period not yet billed.
    starts_on: date


class MembershipForCoach(BaseModel):
    """A membership as a coach reads it: without its discount, since coaches never see
    money (`app.roles`, #205)."""

    id: uuid.UUID
    person_id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str
    plan_kind: PlanKind
    status: MembershipStatus
    # The day of the month a monthly plan bills on; null on every other kind.
    anchor_day: int | None
    started_on: date
    current_period_end: date | None
    credits_remaining: int | None
    next_plan: PendingPlanChange | None
    # The freeze it is in, while Frozen; the one booked ahead, while Active.
    freeze: Freeze | None
    cancel_reason: str | None
    cancelled_at: datetime | None
    created_at: datetime


class Membership(MembershipForCoach):
    discount_pct: int


def for_coach(membership: Membership) -> MembershipForCoach:
    return MembershipForCoach.model_validate(membership.model_dump(exclude={"discount_pct"}))
