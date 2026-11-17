"""Check-in at the door (#348): open access, a day's visits, and who may be checked in."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.domain.membership import MembershipStatus, PlanKind
from app.schemas.requirements import RequirementFlag


class CheckIn(BaseModel):
    """`POST /api/check-in/{class_type_id}`: the membership to check in, as the search
    found it."""

    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID


class Visitor(BaseModel):
    """Someone at the door, by the membership a check-in marks, with their plan's state:
    the screen warns of a lapsed plan or a pack with too few credits, never refuses."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    name: str
    rut: str | None
    plan_name: str
    plan_kind: PlanKind
    status: MembershipStatus
    # Credits left on a pack, free classes left on a trial; `None` on other plans.
    credits_remaining: int | None
    # A period past due and not paid in full: they can still come in.
    overdue: bool


class Candidate(Visitor):
    """A search result: when they came in today, `None` if they have not, and the
    requirements the caller sees that they lack or whose record expired (#350)."""

    checked_in_at: datetime | None
    unmet_requirements: list[RequirementFlag] = []


class Arrival(Visitor):
    """A visit today: when they were checked in (`attendance.marked_at`)."""

    marked_at: datetime
    credits_consumed: int


class Door(BaseModel):
    """`GET /api/check-in`: one open-access class type and its day so far, in the gym's
    timezone. `session_id` is the day's session, `None` until the first check-in makes
    it; `cancelled` says an admin cancelled it, which refuses check-ins until it is
    reactivated. Arrivals are newest first."""

    class_type_id: uuid.UUID
    name: str
    program_id: uuid.UUID
    program_name: str
    credit_cost: int
    date: date
    timezone: str
    session_id: uuid.UUID | None
    cancelled: bool
    arrivals: list[Arrival]
