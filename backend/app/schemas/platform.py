import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from pydantic_core import PydanticCustomError

from app.domain.grading import resolve
from app.gyms import SCHEMES, NewGym, signing_problem
from app.hosts import slug_problem, slug_refusal
from app.schemas.people import Email, Name, Phone


def host_label(value: str) -> str:
    """`value`, if a gym may have it as its slug; else a refusal of its own type,
    `slug_format` or `slug_reserved`, for the form to say why."""
    refusal = slug_refusal(value)
    if refusal is not None:
        raise PydanticCustomError(f"slug_{refusal}", slug_problem(value) or refusal)
    return value


def signed_since_they_exist(value: date | None) -> date | None:
    """`value`, if the current terms can have been signed then; else why not."""
    problem = None if value is None else signing_problem(value)
    if problem is not None:
        raise PydanticCustomError(*problem)
    return value


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
    # The Términos de encargo in force, the latest accepted, and when (#499).
    terms_version: str | None
    terms_accepted_at: datetime | None
    # Whether it accepted the current versions of both texts: `pending` never accepted
    # any, and takes no data; `outdated` accepted earlier ones.
    terms_state: Literal["pending", "outdated", "current"]
    # People with a plan active or frozen.
    members: int
    staff: int
    # The latest attendance, ledger entry or sign-in there; None for a gym with none.
    last_activity: datetime | None
    # Suspended from the panel (#439): nobody signs in there, and its jobs do not run.
    status: Literal["active", "suspended"]
    # Whether the latest sign-in link to its owner did not go (`owner_link_failed`).
    owner_link_failed: bool
    # Since when it is suspended; None for an active gym.
    suspended_at: datetime | None


class SlugCheck(BaseModel):
    """What a slug would be: where the gym would be served, and why it cannot, if so."""

    address: str
    problem: Literal["format", "reserved", "taken"] | None


class PresetOption(BaseModel):
    key: str
    label: str


class NewGymChoices(BaseModel):
    """What the panel's new-gym form offers: the grading presets, and the time zones a
    gym may be in."""

    grading: list[PresetOption]
    timezones: list[str]


class PanelNewGym(NewGym):
    """A gym as the panel creates it (#437): `app.gyms.NewGym`, pending its terms, which
    its titular accepts in the app (#499), and each refusal its own type for the form
    to say why.

    The panel never creates an exempt gym: `--no-processor-terms` is the command
    line's, for an instance the company does not host.
    """

    terms_exempt: Literal[False] = False

    @field_validator("slug")
    @classmethod
    def _a_host_label(cls, value: str) -> str:
        return host_label(value)

    @field_validator("grading")
    @classmethod
    def _a_preset(cls, value: str) -> str:
        value = resolve(value)
        if value not in SCHEMES:
            raise PydanticCustomError("unknown_preset", "not a grading preset")
        return value


class CreatedGym(BaseModel):
    id: uuid.UUID
    slug: str
    # Where it is served, at once: `https://<slug>.<BASE_DOMAIN>`.
    address: str


class OwnerLink(BaseModel):
    # Whether the link went: False when the mail did not, which the list keeps showing.
    sent: bool
    # Whether it was the invitation to accept the terms (#499), for a gym that has not
    # accepted the current ones, rather than the plain sign-in link.
    invite: bool = False


class TermsSignature(BaseModel):
    """One acceptance of the terms (#499): in the app, by whom, or signed outside it,
    on the date of its copy. One from before #499 names no Términos de servicio."""

    accepted_at: datetime
    channel: Literal["in_app", "outside"]
    service_version: str | None
    processor_version: str
    accepted_by_name: str | None
    signed_on: date | None


class SlugAlias(BaseModel):
    """A slug the gym had, and until when its address redirects to the gym's own."""

    slug: str
    address: str
    until: datetime


class RemovalDates(BaseModel):
    """The end of service of the Términos de encargo, clause 14 (`app.platform.removal`):
    of the removal started on `started_on`, or of one started today when it is None."""

    export_days: int
    deletion_days: int
    backup_days: int
    # The day the removal started; None while none has.
    started_on: date | None
    # The day the gym asked in writing for its deletion before its window ended.
    early_deletion_on: date | None
    export_until: date
    # The first day its rows and files may be deleted (`python -m app.gyms delete`).
    deletion_from: date
    deleted_by: date
    backups_gone_by: date


class PlatformGymDetail(BaseModel):
    """One gym as its edit screen shows it (#438)."""

    id: uuid.UUID
    slug: str
    name: str
    address: str
    titular_name: str | None
    titular_email: str | None
    titular_phone: str | None
    # Whether the titular ever signed in there: once they have, their address is
    # changed only through a handover (#321), never here.
    titular_signed_in: bool
    # Every acceptance, the latest first, the versions current today, and the state.
    terms: list[TermsSignature]
    terms_version: str
    service_terms_version: str
    terms_state: Literal["pending", "outdated", "current"]
    aliases: list[SlugAlias]
    # Since when it is suspended (#439), and why; both None for an active gym.
    suspended_at: datetime | None
    suspended_reason: str | None
    # For a suspended gym, the dates its removal keeps, or one started today would
    # (`app.platform.removal`); None for an active one, which cannot be removed.
    removal: RemovalDates | None


class GymEdit(BaseModel):
    """What the panel changes of a gym (#438); a field left out, or null, stays as it is.
    The titular's email only while they have never signed in to the gym."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    owner_name: Name | None = None
    owner_phone: Phone | None = None
    owner_email: Email | None = None


class GymEdited(BaseModel):
    # The fields that changed; none when every value was the one it had.
    fields: list[str]


class TermsToRecord(BaseModel):
    """An acceptance of the current terms made outside the app: the date on the copy
    signed, which records both texts."""

    model_config = ConfigDict(extra="forbid")

    signed_on: date

    _signed_since_they_exist = field_validator("signed_on")(signed_since_they_exist)


class TermsRecorded(BaseModel):
    # False when the gym had signed these versions already: its first date stays.
    recorded: bool


class NewSlug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str

    _a_host_label = field_validator("slug")(host_label)


class Renamed(BaseModel):
    slug: str
    address: str
    # The slug it had, and until when its address redirects here; None when the slug
    # was the gym's already and nothing changed.
    old_slug: str
    until: datetime | None


class Suspension(BaseModel):
    """Why the gym is suspended (#439): the operator's words, kept with it and logged."""

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Suspended(BaseModel):
    # False when the gym was so already: nothing changed, and nothing was logged.
    changed: bool


class RemovalStart(BaseModel):
    """The gym's slug, typed again, to start its removal (#377)."""

    model_config = ConfigDict(extra="forbid")

    slug: str


class EarlyDeletion(BaseModel):
    """The day the gym asked in writing for its deletion before its window ends."""

    model_config = ConfigDict(extra="forbid")

    asked_on: date


class ReauthCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
