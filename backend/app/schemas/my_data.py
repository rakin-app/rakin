"""Mis datos (#371): everything the gym holds on the signed-in person, and on each
dependent they are the guardian of. The page and its JSON download are this document.

Amounts are pesos, days are the gym's dates, and moments carry their offset. Ids are
the gym's own, so one row can be told from another; the staff who recorded a row are
left out, but for the names a person would know them by (who gave a consent).
"""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.grades import Rank
from app.schemas.gym import Privacy


class Someone(BaseModel):
    """A guardian or a dependent: who the gym links the person to."""

    person_id: uuid.UUID
    name: str


class MyRecord(BaseModel):
    """The person as this gym recorded them (`gym_person`)."""

    name: str
    rut: str | None
    email: str | None
    phone: str | None
    dob: date | None
    no_whatsapp: bool
    # The day they first trained here, if it was before the gym used Rakin (#293).
    member_since: date | None
    # The classes attended before the gym used Rakin (#293).
    prior_classes: int | None
    left_on: date | None
    left_reason: str | None
    added_at: datetime
    updated_at: datetime


class MyField(BaseModel):
    """A custom field's value: every one the gym holds, sensitive or archived too."""

    key: str
    label: str
    value: Any
    sensitive: bool
    archived: bool


class MyMembership(BaseModel):
    id: uuid.UUID
    plan_name: str
    status: str
    started_at: datetime
    current_period_end: date | None
    credits_remaining: int | None
    discount_pct: int | None
    discount_reason: str | None
    next_plan_name: str | None
    next_plan_from: date | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    cancel_undone_at: datetime | None
    reactivated_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime


class MyPlanEvent(BaseModel):
    membership_id: uuid.UUID
    kind: str
    occurred_on: date


class MyFreeze(BaseModel):
    membership_id: uuid.UUID
    from_date: date
    to_date: date | None
    reason: str | None
    created_at: datetime


class MyFreezeRequest(BaseModel):
    membership_id: uuid.UUID
    from_date: date
    to_date: date | None
    reason: str | None
    note: str | None
    status: str
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class MyPeriod(BaseModel):
    """A cobro of a plan: what a period owes."""

    id: uuid.UUID
    membership_id: uuid.UUID
    plan_name: str
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int
    discount_pct: int | None
    discount_reason: str | None


class MyExtraCharge(BaseModel):
    """A cobro extra's line for the person: an enrolment fee, an event, a uniform."""

    id: uuid.UUID
    title: str
    amount_due_clp: int
    due_date: date | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime


class MyEntry(BaseModel):
    """A ledger entry: a charge, a payment, a refund or an adjustment, on a period or a
    cobro extra. `note` only where the student page shows one (`student_note_sql`)."""

    id: uuid.UUID
    kind: str
    status: str
    amount_clp: int
    method: str | None
    billing_period_id: uuid.UUID | None
    extra_line_id: uuid.UUID | None
    purpose: str | None
    has_proof: bool
    note: str | None
    claimed_at: datetime | None
    validated_at: datetime | None
    created_at: datetime


class MyHistoryPayment(BaseModel):
    """A payment recorded from before the gym used Rakin (#335)."""

    id: uuid.UUID
    paid_on: date
    amount_clp: int
    method: str | None
    covers_month: date | None
    plan_name: str | None
    source: str
    created_at: datetime


class MyVisit(BaseModel):
    """A class attended."""

    session_id: uuid.UUID
    starts_at: datetime
    class_type_name: str
    program_name: str
    credits_consumed: int | None
    marked_at: datetime


class MyGrade(Rank):
    """A promotion, as the gym's scheme labels it."""

    id: uuid.UUID


class MyRequirement(BaseModel):
    """A record of a requirement: a waiver signed, a medical certificate."""

    id: uuid.UUID
    requirement_name: str
    done_on: date
    recorded_at: datetime


class MyConsentEvent(BaseModel):
    id: uuid.UUID
    action: str
    source: str
    by_name: str | None
    template_on: date | None
    details_on: date | None
    at: datetime


class MyMessage(BaseModel):
    """A message the gym sent the person: an email or a WhatsApp reminder, and what it
    carried, without its links' secrets."""

    id: uuid.UUID
    channel: str
    template: str
    to_address: str
    status: str
    error: str | None
    payload: dict[str, Any] | None
    sent_at: datetime


class MyTitle(BaseModel):
    title_name: str
    starts_on: date
    ends_on: date | None
    public_contact: str | None


class MyStaff(BaseModel):
    """The person's place on the gym's team, if they have one."""

    role: str
    account_holder: bool
    titles: list[MyTitle]
    added_at: datetime


class PersonData(BaseModel):
    """Everything the gym holds on one person."""

    person_id: uuid.UUID
    record: MyRecord
    guardians: list[Someone]
    dependents: list[Someone]
    fields: list[MyField]
    memberships: list[MyMembership]
    plan_events: list[MyPlanEvent]
    freezes: list[MyFreeze]
    freeze_requests: list[MyFreezeRequest]
    periods: list[MyPeriod]
    extra_charges: list[MyExtraCharge]
    entries: list[MyEntry]
    history_payments: list[MyHistoryPayment]
    attendance: list[MyVisit]
    grades: list[MyGrade]
    requirements: list[MyRequirement]
    consents: list[MyConsentEvent]
    messages: list[MyMessage]
    charge_groups: list[str]
    # When they unsubscribed from the gym's emails, if they did.
    unsubscribed_at: datetime | None
    staff: MyStaff | None


class MyDataGym(BaseModel):
    name: str
    # Where its days are: what the moments above are read in.
    timezone: str
    # Who is responsible for the data and where to write about it; `None` until the
    # gym fills in its privacy details.
    privacy: Privacy | None


class MyData(BaseModel):
    exported_at: datetime
    gym: MyDataGym
    # The person signed in first, then each dependent, by name.
    people: list[PersonData]
