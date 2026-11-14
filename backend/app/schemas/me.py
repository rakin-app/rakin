"""The student page ("Mi página", #65): what the signed-in person reads about themselves.

One document for the page: the next payment and where to transfer it, the cobros extra
still owed, and the payments already sent with how each was reviewed, the person's
belt, and how many classes they have attended. Beside it, the classes themselves
(`MyClasses`, #243).
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.ledger import EntryKind, EntryStatus
from app.schemas.class_tags import TagHours, TagOn
from app.schemas.extra_charges import MyExtraLine
from app.schemas.freeze_requests import MyPlan
from app.schemas.grades import Rank
from app.schemas.gym import BankAccount
from app.schemas.proofs import OpenPeriod

# `in_review`: a proof claims it and awaits review. `overdue`: past its due date with
# nothing claimed. `due`: neither.
NextPaymentStatus = Literal["in_review", "overdue", "due"]


class NextPayment(BaseModel):
    period: OpenPeriod
    status: NextPaymentStatus


class MyPayment(BaseModel):
    """A payment on one of the person's memberships or a dependent's, as the ledger
    records it: pending while a proof awaits review, then validated or rejected. Or a
    refund of one, or an adjustment of what a period owes (#210), each validated as it
    is made."""

    id: uuid.UUID
    # `payment`, `refund` (money given back, so a payment counts less) or `adjustment`:
    # positive in the student's favour, negative owed on top; with no period, credit
    # carried from an overpayment.
    kind: EntryKind = EntryKind.PAYMENT
    person_id: uuid.UUID
    person_name: str
    amount_clp: int
    status: EntryStatus
    # The period it pays, when it pays one.
    period_start: date | None
    # The cobro extra it pays instead, when it pays one (#195).
    charge_title: str | None = None
    # When the proof was sent, or the admin recorded it.
    claimed_at: datetime | None
    # When it was validated or rejected.
    validated_at: datetime | None
    # Why it was rejected: the admin's note, written for the student.
    note: str | None
    created_at: datetime


class MyAttendance(BaseModel):
    """Their classes here, over every membership, by the gym's calendar."""

    this_month: int
    total: int


class MyPage(BaseModel):
    gym_name: str
    # Dates on the page are the gym's, not the phone's.
    timezone: str
    # Who is signed in, to tell their own payments from a dependent's.
    person_id: uuid.UUID
    name: str
    # The earliest open period, theirs or a dependent's; `None` when nothing is owed.
    next_payment: NextPayment | None
    # With nothing owed, the day they are paid through: "Pagado hasta" (#196). The
    # earliest of their running memberships' and their dependents'; `None` when none
    # has a period paid yet.
    paid_through: date | None = None
    # Where to transfer; `None` until the gym sets it (`PATCH /api/gym/settings`).
    bank_account: BankAccount | None
    # Their latest promotion here (`grade_event`, 0018); `None` until they have one.
    rank: Rank | None
    attendance: MyAttendance
    # Newest first: at most `PAYMENTS_SHOWN` payments, with the refunds and adjustments
    # made since the oldest of them.
    payments: list[MyPayment]
    # The cobros extra still owed, theirs and their dependents', earliest due first
    # (#195): beside the plan's, never part of `next_payment`.
    extra_charges: list[MyExtraLine] = []
    # Their running memberships and their dependents', for "Pedir congelamiento" (#270).
    plans: list[MyPlan] = []


class MyClass(BaseModel):
    """A class attended, and what it was about (#243): its topic and tags. Never the
    coach's notes, which are staff's alone: who struggled, an injury."""

    session_id: uuid.UUID
    starts_at: datetime
    duration_minutes: int | None
    class_type_name: str
    program_name: str
    topic: str | None
    tags: list[TagOn]


class PersonClasses(BaseModel):
    """One person's classes: the latest `CLASSES_SHOWN` attended, newest first, and the
    hours per tag of those this month and this year, on the gym's calendar."""

    person_id: uuid.UUID
    name: str
    classes: list[MyClass]
    this_month: TagHours
    this_year: TagHours


class MyClasses(BaseModel):
    """The signed-in person's own classes, when they train here, then each dependent's."""

    timezone: str
    people: list[PersonClasses]
