"""The members who stopped coming, as the owner's dashboard lists them (#50)."""

import uuid
from datetime import date, datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel


class Bucket(IntEnum):
    """How long they have been away: 14 to 29 days, or 30 and more."""

    DAYS_14 = 14
    DAYS_30 = 30


class PaymentStatus(StrEnum):
    # Every period due is paid.
    UP_TO_DATE = "up_to_date"
    # A membership of theirs, in any status, has a period past due and not paid in full
    # (`v_overdue`, #207).
    OVERDUE = "overdue"
    # On a trial only, which charges nothing.
    TRIAL = "trial"


class InactiveMember(BaseModel):
    """Someone with a trial or Active membership and no class for at least 14 days."""

    person_id: uuid.UUID
    name: str
    # Their last class, gym-local; `None` if they have not come to one yet.
    last_attended_on: date | None
    # Days since `last_attended_on`, or if `None` since their membership started, or was
    # entered in Rakin if that is later (an import).
    days_absent: int
    bucket: Bucket
    payment_status: PaymentStatus
    # What the overdue periods still owe; 0 unless `payment_status` is overdue.
    overdue_clp: int
    # Whom the nudge goes to: the guardian, for a dependent (`app.contacts`), else them.
    contact_name: str
    # The `wa.me` link with the nudge prefilled; `None` when the gym has WhatsApp off or
    # whoever it goes to has no phone.
    whatsapp_url: str | None
    # When a nudge about them was last opened from the list, if one was.
    nudged_at: datetime | None


class Nudged(BaseModel):
    """`POST /api/inactive/{person_id}/nudge`: the `message_log` row it wrote."""

    message_id: uuid.UUID
    sent_at: datetime
