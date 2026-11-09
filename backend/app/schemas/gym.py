"""The gym's own settings: profile, timezone, grace days, reminders, channels, bank details.

`name` and `timezone` are columns on `gym`; the rest live as keys of `gym.settings`
beside the grading scheme and custom fields, which this API leaves alone. A key not
yet stored reads as its default, so a new gym answers with a complete document.

The bank details are what a student is shown on their page to pay by transfer, so the
RUT is normalised like any other (`76123456-0`).
"""

from collections.abc import Mapping
from typing import Annotated, Any, Literal
from zoneinfo import available_timezones

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.domain.membership import DEFAULT_GRACE_DAYS
from app.schemas.people import Email, Name, Rut

# Overdue reminders go out on the due date, then every this many days (docs/technical.md).
DEFAULT_REMINDER_EVERY_DAYS = 3

_TIMEZONES = frozenset(available_timezones())


def _timezone(value: str) -> str:
    if value not in _TIMEZONES:
        raise ValueError("not an IANA timezone")
    return value


Timezone = Annotated[str, AfterValidator(_timezone)]
GraceDays = Annotated[StrictInt, Field(ge=0, le=60)]
ReminderEveryDays = Annotated[StrictInt, Field(ge=1, le=30)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Banks print account numbers with dashes as often as without; keep what the gym typed.
AccountNumber = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9][0-9-]{2,28}[0-9]$")
]
AccountType = Literal["Cuenta Corriente", "Cuenta Vista", "Cuenta RUT", "Cuenta de Ahorro"]


class BankAccount(BaseModel):
    """Where students transfer to. `email` is the address a transfer notice goes to."""

    model_config = ConfigDict(extra="forbid")

    bank: Text
    account_type: AccountType
    holder: Text
    rut: Rut
    number: AccountNumber
    email: Email | None = None


class Channels(BaseModel):
    """Which channels the gym reaches students on, beside email.

    Email is always on: it is the system of record and carries the magic links.
    `whatsapp` turns on the `wa.me` reminder links on the admin's lists.
    """

    model_config = ConfigDict(extra="forbid")

    whatsapp: StrictBool = True


class GymSettings(BaseModel):
    name: str
    # The gym's address in URLs; set when the gym is created, not editable here.
    slug: str
    timezone: str
    grace_days: int
    reminder_every_days: int
    channels: Channels
    bank_account: BankAccount | None

    @classmethod
    def from_row(
        cls, name: str, slug: str, timezone: str, settings: Mapping[str, Any]
    ) -> "GymSettings":
        return cls(
            name=name,
            slug=slug,
            timezone=timezone,
            grace_days=settings.get("grace_days", DEFAULT_GRACE_DAYS),
            reminder_every_days=settings.get("reminder_every_days", DEFAULT_REMINDER_EVERY_DAYS),
            channels=settings.get("channels", {}),
            bank_account=settings.get("bank_account"),
        )


# The `gym.settings` keys this API owns; any other key there is left as it is.
SETTINGS_KEYS = ("grace_days", "reminder_every_days", "channels", "bank_account")


class GymSettingsUpdate(BaseModel):
    """Only the fields sent change. `channels` and `bank_account` are replaced whole;
    `null` clears the bank details. The rest cannot be null."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    timezone: Timezone | None = None
    grace_days: GraceDays | None = None
    reminder_every_days: ReminderEveryDays | None = None
    channels: Channels | None = None
    bank_account: BankAccount | None = None

    @model_validator(mode="after")
    def _only_bank_account_is_cleared(self) -> "GymSettingsUpdate":
        cleared = {f for f in self.model_fields_set if getattr(self, f) is None}
        if cleared - {"bank_account"}:
            raise ValueError(f"{', '.join(sorted(cleared - {'bank_account'}))} cannot be null")
        return self
