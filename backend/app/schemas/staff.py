"""The gym's team: who is on it, their appointments to the gym's roles, the roles
themselves (Cargos) and the history of every appointment (#311).

An invite names the person as a member is added, by RUT if they give one, and needs
an email: Rakin signs staff in by a link to it (docs/technical.md, magic links), and
with no RUT the email is who they are in this gym. The phone is optional. It appoints
them to one or more of the gym's roles, from a day (today unless given) and until
another, if given. The titular is not a role anyone is invited to or appointed to.

A term is half-open: `ends_on` is the first day without it, so it ends after it
starts. One that ends on the day it starts was ended on the day it was made, or
before it began, and granted nothing; it is kept for the history.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.permissions import Permission
from app.roles import Role
from app.schemas.people import Email, Name, Phone, Rut

TitleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
PresetKey = Literal["academia", "club_federado"]
PublicContact = Literal["email", "phone"]


class Term(BaseModel):
    """From `starts_on` (today, in the gym's timezone, unless given) until the day before
    `ends_on`, or open."""

    model_config = ConfigDict(extra="forbid")

    starts_on: date | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def ends_after_it_starts(self) -> Self:
        if self.starts_on and self.ends_on and self.ends_on <= self.starts_on:
            raise ValueError("ends_on must come after starts_on")
        return self


class StaffInvite(Term):
    name: Name
    email: Email
    rut: Rut | None = None
    phone: Phone | None = None
    # At least one, each once.
    title_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def each_role_once(self) -> Self:
        if len(set(self.title_ids)) != len(self.title_ids):
            raise ValueError("each role once")
        return self


class Appointment(Term):
    """One of the gym's roles to appoint someone to."""

    title_id: uuid.UUID


class AppointmentCorrection(BaseModel):
    """A typo fixed on an appointment: its dates, or the contact shown with it. Never who
    holds it or which role: that is ending it and appointing again. Only what is sent
    changes; `ends_on: null` makes it open. `public_contact` may only be cleared here:
    showing a contact is the officer's own choice (section 9)."""

    model_config = ConfigDict(extra="forbid")

    starts_on: date | None = None
    ends_on: date | None = None
    public_contact: None = None


class StaffAppointment(BaseModel):
    """An appointment that holds today or from a later day. `title_name` is the role's
    name today; `manageable`, whether the person acting may end or correct it."""

    id: uuid.UUID
    title_id: uuid.UUID
    title_name: str
    starts_on: date
    ends_on: date | None
    public_contact: PublicContact | None
    manageable: bool


class StaffMember(BaseModel):
    person_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    # The role the `staff` row still names, until #313: never what they may do.
    role: Role
    # When they joined the team.
    since: datetime
    account_holder: bool
    # What they may do today: the union of their current roles; every one for the titular.
    permissions: list[Permission]
    appointments: list[StaffAppointment]
    # Whether the person acting may appoint them, end or correct their appointments.
    manageable: bool


class HistoryEntry(BaseModel):
    """An appointment as it was: `title_name` is the role's name when it was made."""

    id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    title_name: str
    starts_on: date
    ends_on: date | None


class StaffConflict(BaseModel):
    code: Literal["already_staff"] = "already_staff"
    person_id: uuid.UUID


class AlreadyStaff(BaseModel):
    """409 body: the RUT or email is someone's already on this gym's staff."""

    detail: StaffConflict


class TitleDraft(BaseModel):
    """A role as Cargos saves it. What a permission implies is added on save."""

    model_config = ConfigDict(extra="forbid")

    name: TitleName
    permissions: list[Permission] = []
    public: bool = False


class TitleChange(BaseModel):
    """What an edit of a role changes; only what is sent."""

    model_config = ConfigDict(extra="forbid")

    name: TitleName | None = None
    permissions: list[Permission] | None = None
    public: bool | None = None


class Title(BaseModel):
    """One of the gym's roles. `holders`: how many hold it today; `manageable`, whether
    the person acting may edit it, archive it and appoint to it."""

    id: uuid.UUID
    name: str
    permissions: list[Permission]
    public: bool
    preset: PresetKey | None
    holders: int
    manageable: bool


class Titles(BaseModel):
    """The gym's roles, and whether it has yet to choose how its team is organised:
    a new gym chooses a preset, or none, in Equipo's first-run setup."""

    titles: list[Title]
    setup_pending: bool


class PresetChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: PresetKey


class SetupChoice(BaseModel):
    """The first-run setup's answer: a preset, or none (`null`)."""

    model_config = ConfigDict(extra="forbid")

    preset: PresetKey | None
