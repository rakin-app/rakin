import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class OperatorMe(BaseModel):
    email: str
    name: str
    # Until when the irreversible actions need no new code (`app.platform.session.FRESH`).
    fresh_until: datetime


class PlatformGym(BaseModel):
    """A gym as the panel lists it: counts and dates, never its members' data."""

    id: uuid.UUID
    slug: str
    name: str
    # Where it is served, `https://<slug>.<BASE_DOMAIN>`.
    address: str
    timezone: str
    created_at: datetime
    # Who holds the account, from the gym's own record of them; None for a gym with none.
    titular_name: str | None
    titular_email: str | None
    # The Términos de encargo in force: the latest signed, and whether it is the current.
    terms_version: str | None
    terms_signed_on: date | None
    terms_current: bool
    # People with a plan active or frozen.
    members: int
    staff: int
    # The latest attendance, ledger entry or sign-in there; None for a gym with none.
    last_activity: datetime | None
    # Suspension comes with #439.
    status: Literal["active"]
