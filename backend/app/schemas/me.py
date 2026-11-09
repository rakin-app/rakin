"""The student page ("Mi página", #65): what the signed-in person reads about themselves.

One document for the page: the next payment and where to transfer it, and the payments
already sent with how each was reviewed, and the person's belt. The attendance card
joins it with its table (#44).
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.ledger import EntryStatus
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
    records it: pending while a proof awaits review, then validated or rejected."""

    id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    amount_clp: int
    status: EntryStatus
    # The period it pays, when it pays one.
    period_start: date | None
    # When the proof was sent, or the admin recorded it.
    claimed_at: datetime | None
    # When it was validated or rejected.
    validated_at: datetime | None
    # Why it was rejected: the admin's note, written for the student.
    note: str | None
    created_at: datetime


class MyPage(BaseModel):
    gym_name: str
    # Dates on the page are the gym's, not the phone's.
    timezone: str
    # Who is signed in, to tell their own payments from a dependent's.
    person_id: uuid.UUID
    name: str
    # The earliest open period, theirs or a dependent's; `None` when nothing is owed.
    next_payment: NextPayment | None
    # Where to transfer; `None` until the gym sets it (`PATCH /api/gym/settings`).
    bank_account: BankAccount | None
    # Their latest promotion here (`grade_event`, 0018); `None` until they have one.
    rank: Rank | None
    # Newest first, at most `PAYMENTS_SHOWN`.
    payments: list[MyPayment]
