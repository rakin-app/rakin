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
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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
    # The plan's matrícula, if it has one (#355); `false` is "ya pagó matrícula".
    # Reactivar never charges it, whatever this says.
    charge_enrolment: bool = True

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


class Discount(BaseModel):
    """A fixed percentage off every period a membership bills, and why: a sibling, a
    scholarship, whatever the gym gives one for (#25)."""

    model_config = ConfigDict(extra="forbid")

    pct: Annotated[int, Field(ge=1, le=100)]
    reason: Reason


class DiscountChange(BaseModel):
    """A membership's new discount, from the next period it bills; `null` takes it off."""

    model_config = ConfigDict(extra="forbid")

    discount: Discount | None


class DiscountQuote(BaseModel):
    """What a discount of `pct` would bill, before it is saved: the first period it
    applies to, from `starts_on` until `period_end`, for `amount_due_clp`. The periods
    billed already keep the discount they were billed at."""

    starts_on: date
    period_end: date
    amount_due_clp: int


class MembershipCreate(MembershipStart):
    person_id: uuid.UUID
    # Off every period from the first: a sibling starting with one, say (#25).
    discount: Discount | None = None
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


class ConvertedTrial(BaseModel):
    """A trial a paid plan converted, or would (#27)."""

    id: uuid.UUID
    plan_name: str
    started_on: date
    # Still running: the paid plan starting ends it.
    running: bool


class StartQuote(BaseModel):
    """What starting a plan would do, before it is saved (#271): the day it starts, and
    `billed_through`, the last day a lapsed plan of the person billed, when the start
    moved past it so no day is billed twice; `debt_clp`, what the lapsed plans still
    owe on periods due by today ("Deuda anterior")."""

    starts_on: date
    billed_through: date | None
    debt_clp: int
    # The trial the plan converts (#27): the person's latest one not converted yet, when
    # the plan is a paid one; ended as the plan starts when it is still running.
    converts: ConvertedTrial | None = None


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class Reactivation(BaseModel):
    """ "Reactivar plan" (#284): a lapsed plan Active again, with why, billing on after
    its last period (`last`, catching up the periods since the lapse) or from today.
    "Deshacer baja" (#285) takes the same, the periods since the cancel caught up."""

    model_config = ConfigDict(extra="forbid")

    reason: Reason
    bill_from: Literal["last", "today"] = "last"


class QuotedPeriod(BaseModel):
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int


class ReactivationBill(BaseModel):
    """What a reactivation bills at once: from `bills_from`, these periods, oldest
    first, as the nightly job would bill them tonight, for `total_clp`."""

    bills_from: date
    periods: list[QuotedPeriod]
    total_clp: int


class ReactivationQuote(BaseModel):
    """What `POST .../reactivate` would bill with each `bill_from`, saving nothing."""

    last: ReactivationBill
    today: ReactivationBill


class UncancelQuote(BaseModel):
    """What `POST .../uncancel` would do with each `bill_from`, saving nothing (#285): the
    status the plan returns to, `lapsed` when a period past due plus grace is unpaid,
    which then bills nothing."""

    status: MembershipStatus
    last: ReactivationBill
    today: ReactivationBill


class ReactivationRefusal(StrEnum):
    """Why a plan cannot be reactivated, or its cancel undone (#285), for the ficha to
    say what to do first."""

    # Only a lapsed plan is reactivated.
    NOT_LAPSED = "not_lapsed"
    # Only a cancelled plan's cancel is undone.
    NOT_CANCELLED = "not_cancelled"
    # A plan voided (started by mistake) stays voided.
    VOIDED = "voided"
    # The person has left the gym (dado de baja, #157): reactivate them first.
    HAS_LEFT = "has_left"
    # A pack or a trial ends: the member starts a new one.
    NOT_RECURRING = "not_recurring"
    # A fixed-period plan whose period has ended: the member moves to the next one's plan.
    PERIOD_ENDED = "period_ended"
    # A period past due plus grace is unpaid: the nightly job would lapse it again.
    UNPAID = "unpaid"
    # The person is on another plan (Trial, Active or Frozen).
    LIVE_PLAN = "live_plan"


class ReactivationConflict(BaseModel):
    code: ReactivationRefusal
    message: str
    # On `unpaid`: the oldest such period's, and what the plan owes past grace.
    period_start: date | None = None
    amount_clp: int | None = None
    # On `live_plan`: the other plan's name.
    plan_name: str | None = None


class ReactivationRefused(BaseModel):
    detail: ReactivationConflict


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
    # Voided as started by mistake (#256): cancelled as of its start, its unpaid
    # charges voided. Null on every other membership.
    voided_at: datetime | None = None
    void_reason: str | None = None
    # The trial this plan converted (#27); null on a trial and on a plan with none.
    converted_from: ConvertedTrial | None = None
    created_at: datetime


class Membership(MembershipForCoach):
    discount_pct: int
    # Why it has the discount (#25); null with none, and on one set before reasons were.
    discount_reason: str | None = None


def for_coach(membership: Membership) -> MembershipForCoach:
    return MembershipForCoach.model_validate(
        membership.model_dump(exclude={"discount_pct", "discount_reason"})
    )


class TrialConversions(BaseModel):
    """The trials started in the last `days` days, today's included (#27): how many,
    how many a paid plan converted, and how many are still running. Voided ones are not
    counted, nor a conversion by a plan voided."""

    days: int
    started: int
    converted: int
    running: int
