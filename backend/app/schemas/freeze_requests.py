"""A freeze request (#270): a student, or their guardian, asks for a freeze, and the
owner or an admin answers it.

Dates are gym-local, as a freeze's: `from_date` its first day and `to_date` the day
the membership is Active again.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.schemas.memberships import Freeze

# Why: a short list the page offers, with `note` for the rest; `otro` is all note.
FreezeReason = Literal["lesion", "viaje", "salud", "otro"]

# How a reason reads in the freeze it becomes, and in the email to staff.
REASON_LABELS: dict[str, str] = {
    "lesion": "Lesión",
    "viaje": "Viaje",
    "salud": "Salud",
    "otro": "Otro",
}

FreezeRequestStatus = Literal["pending", "approved", "rejected", "withdrawn"]

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _blank_is_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


class FreezeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: uuid.UUID
    from_date: date
    to_date: date
    reason: FreezeReason
    note: Note | None = None

    @model_validator(mode="before")
    @classmethod
    def _blank_note(cls, data: object) -> object:
        if isinstance(data, dict) and "note" in data:
            return {**data, "note": _blank_is_none(data["note"])}
        return data

    @model_validator(mode="after")
    def _checked(self) -> "FreezeRequestCreate":
        if self.to_date <= self.from_date:
            raise ValueError("to_date must be after from_date")
        if self.reason == "otro" and self.note is None:
            raise ValueError("a reason of otro needs a note")
        return self


class FreezeApproval(BaseModel):
    """Other dates than the ones asked for, when the admin changes them; what is
    omitted stays as asked."""

    model_config = ConfigDict(extra="forbid")

    from_date: date | None = None
    to_date: date | None = None


class FreezeRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Note | None = None

    @model_validator(mode="before")
    @classmethod
    def _blank_note(cls, data: object) -> object:
        if isinstance(data, dict) and "note" in data:
            return {**data, "note": _blank_is_none(data["note"])}
        return data


class FreezeRequest(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    # The member whose plan it is, and who asked: themselves, or their guardian.
    person_id: uuid.UUID
    person_name: str
    requested_by: uuid.UUID
    requested_by_name: str
    plan_name: str
    from_date: date
    to_date: date
    reason: FreezeReason
    note: str | None
    status: FreezeRequestStatus
    # A rejection's note, written for the member.
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class FreezeRefusal(BaseModel):
    """Why a request cannot be made: the membership is not Active (`not_active`), it
    has a freeze running or booked (`has_freeze`), or a request waits already
    (`has_pending`)."""

    code: Literal["not_active", "has_freeze", "has_pending"]


class MyPlan(BaseModel):
    """A running membership on the student page, theirs or a dependent's, with what
    "Pedir congelamiento" needs: its freeze, the request waiting, and the last one
    answered lately."""

    membership_id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    plan_name: str
    status: Literal["active", "frozen"]
    freeze: Freeze | None
    pending_request: FreezeRequest | None
    last_decided: FreezeRequest | None
