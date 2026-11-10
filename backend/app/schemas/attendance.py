"""Attendance (migration 0023): a session's roster, marking it, and a person's counts."""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.membership import MembershipStatus, PlanKind
from app.schemas.grades import Rank

# More than a class holds, well short of a request worth refusing for its size.
MAX_MARKS = 500

Marks = Annotated[list[uuid.UUID], Field(max_length=MAX_MARKS)]


class AttendanceChange(BaseModel):
    """`PATCH /api/sessions/{id}/attendance`: memberships to mark present and to unmark.

    Either is idempotent, so a change sent twice, as an offline phone resending its
    queue does, lands once: marking someone already present, or unmarking someone who
    is not, changes nothing.
    """

    model_config = ConfigDict(extra="forbid")

    mark: Marks = []
    unmark: Marks = []

    @model_validator(mode="after")
    def _disjoint(self) -> "AttendanceChange":
        if both := set(self.mark) & set(self.unmark):
            raise ValueError(f"marked and unmarked at once: {', '.join(map(str, sorted(both)))}")
        return self


class TrialGuest(BaseModel):
    """`POST /api/sessions/{id}/trials`: start someone on a trial plan, present at it."""

    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID
    plan_id: uuid.UUID


class RosterMember(BaseModel):
    """One person on a session's roster, by the membership the roster marks."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    name: str
    plan_name: str
    plan_kind: PlanKind
    status: MembershipStatus
    # Credits left on a pack, free classes left on a trial; `None` on other plans.
    credits_remaining: int | None
    # A period past due and not paid in full: they can still train, the coach nudges.
    overdue: bool
    # Days since their last class before this one; `None` if this is their first.
    days_absent: int | None
    rank: Rank | None
    present: bool


class Roster(BaseModel):
    """`GET /api/sessions/{id}/roster`: who may be marked, by name, and who is.

    Everyone with a Trial, Active, Lapsed or Frozen membership open to the class's
    program (a plan in that program, or a plan open to any class), and anyone already
    marked.
    """

    session_id: uuid.UUID
    present: int
    members: list[RosterMember]


class AlreadyMember(BaseModel):
    """The 409 for a trial guest who already has a live membership: mark that one."""

    code: str = "already_member"
    membership_id: uuid.UUID


class PersonAttendance(BaseModel):
    """`GET /api/people/{id}/attendance`: the classes they attended, over every
    membership they hold here, by the gym's calendar."""

    # Today and the 29 days before it.
    last_30_days: int
    total: int
    # Since the day of their current rank, not counting classes on that day; `None`
    # until they have a rank.
    since_promotion: int | None
