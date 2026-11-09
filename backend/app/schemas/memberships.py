"""A person's membership of a plan: start one, change its plan, cancel it, read it.

Dates are calendar dates in the gym's timezone (`app.domain.dates`): `started_on`,
`current_period_end` (paid through, or the last day of a pack or trial) and the day
a pending plan change takes effect.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.domain.membership import MembershipStatus, PlanKind

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    plan_id: uuid.UUID
    # Today in the gym's timezone when omitted; a past day records an existing member.
    started_on: date | None = None


class PlanChange(BaseModel):
    """The plan to move to next period; the membership's own plan withdraws a pending
    change."""

    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class PendingPlanChange(BaseModel):
    plan_id: uuid.UUID
    plan_name: str
    # The first day the plan applies: the start of the first period not yet billed.
    starts_on: date


class Membership(BaseModel):
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
    discount_pct: int
    next_plan: PendingPlanChange | None
    cancel_reason: str | None
    cancelled_at: datetime | None
    created_at: datetime
