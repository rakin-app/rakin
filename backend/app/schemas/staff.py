"""The gym's staff: who holds a role here, inviting someone to one, changing and
revoking it.

An invite names the person as a member is added, by phone, and needs an email: Rakin
signs staff in by a link to it (docs/technical.md, magic links). The owner is not a
role anyone is invited to or moved into.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.roles import Role
from app.schemas.people import Email, Name, Phone

# The roles an invite or a change may give: owner is not one of them.
InvitableRole = Literal["admin", "coach"]


class StaffInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Phone
    name: Name
    email: Email
    role: InvitableRole


class StaffRoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: InvitableRole


class StaffMember(BaseModel):
    person_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    role: Role
    # When they were given a role here.
    since: datetime


class StaffInvited(StaffMember):
    """An invite's answer. `emailed` is whether an invite email went: not when the
    person is someone another gym has and the invite's email is not one it has for
    them (migration 0024), and this gym has no email of its own for them."""

    emailed: bool


class StaffConflict(BaseModel):
    code: Literal["already_staff"] = "already_staff"
    person_id: uuid.UUID


class AlreadyStaff(BaseModel):
    """409 body: the phone belongs to someone already on this gym's staff."""

    detail: StaffConflict
