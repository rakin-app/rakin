import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

from app.gyms import SCHEMES, NewGym, signing_problem, terms_problem
from app.hosts import slug_problem, slug_refusal


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


class SlugCheck(BaseModel):
    """What a slug would be: where the gym would be served, and why it cannot, if so."""

    address: str
    problem: Literal["format", "reserved", "taken"] | None


class PresetOption(BaseModel):
    key: str
    label: str


class NewGymChoices(BaseModel):
    """What the panel's new-gym form offers: the grading presets, the Términos de
    encargo's current version, and the time zones a gym may be in."""

    grading: list[PresetOption]
    terms_version: str
    timezones: list[str]


class PanelNewGym(NewGym):
    """A gym as the panel creates it (#437): `app.gyms.NewGym`, with the Términos de
    encargo required, and each refusal its own type for the form to say why.

    The panel never creates a gym without the terms: `--no-processor-terms` is the
    command line's, for an instance the company does not host.
    """

    processor_terms: str
    signed_on: date

    @field_validator("slug")
    @classmethod
    def _a_host_label(cls, value: str) -> str:
        refusal = slug_refusal(value)
        if refusal is not None:
            raise PydanticCustomError(f"slug_{refusal}", slug_problem(value) or refusal)
        return value

    @field_validator("processor_terms")
    @classmethod
    def _the_current_terms(cls, value: str | None) -> str | None:
        problem = None if value is None else terms_problem(value)
        if problem is not None:
            raise PydanticCustomError(*problem)
        return value

    @field_validator("signed_on")
    @classmethod
    def _signed_since_they_exist(cls, value: date | None) -> date | None:
        problem = None if value is None else signing_problem(value)
        if problem is not None:
            raise PydanticCustomError(*problem)
        return value

    @field_validator("grading")
    @classmethod
    def _a_preset(cls, value: str) -> str:
        if value not in SCHEMES:
            raise PydanticCustomError("unknown_preset", "not a grading preset")
        return value


class CreatedGym(BaseModel):
    id: uuid.UUID
    slug: str
    # Where it is served, at once: `https://<slug>.<BASE_DOMAIN>`.
    address: str
