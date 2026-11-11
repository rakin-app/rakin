"""The payment reminders an admin sends by WhatsApp from their own phone (#55)."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel

from app.notices.whatsapp import PAYMENT_DUE_TODAY, PAYMENT_OVERDUE, PROOF_REJECTED_FOLLOWUP


class ReminderKind(StrEnum):
    """Which message the reminder is, as `message_log.template` names it."""

    DUE_TODAY = PAYMENT_DUE_TODAY
    OVERDUE = PAYMENT_OVERDUE
    # A proof for the period was rejected after the last reminder, or with none yet.
    REJECTED = PROOF_REJECTED_FOLLOWUP


class PaymentReminder(BaseModel):
    """A period of an Active membership that is due by today, or whose proof was
    rejected, not paid in full and with no proof waiting for review."""

    billing_period_id: uuid.UUID
    membership_id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    plan_name: str
    period_start: date
    due_date: date
    outstanding_clp: int
    # Days past the due date: 0 on it, negative before it (a rejected proof sent early).
    days_overdue: int
    kind: ReminderKind
    # The admin's note on the rejected proof, for `rejected`.
    rejection_note: str | None
    # Whom it goes to: the guardian, for a dependent (`app.contacts`), else them.
    contact_name: str
    # The `wa.me` link with the reminder prefilled; `None` when the gym has WhatsApp
    # off or whoever it goes to has no phone.
    whatsapp_url: str | None
    # Reminders about this period opened so far, and when the last one was.
    reminders_sent: int
    reminded_at: datetime | None
    # Time for the next one: none sent yet, a rejection not followed up, or the gym's
    # `reminder_every_days` since the last.
    reminder_due: bool


class Reminded(BaseModel):
    """`POST /api/reminders/{billing_period_id}`: the `message_log` row it wrote."""

    message_id: uuid.UUID
    sent_at: datetime
    kind: ReminderKind
    # This one's number among the period's reminders: 1 for the first ("1.er aviso").
    ordinal: int
