"""Guardians and dependents: a gym's family links, and what a guardian sees of each kid.

A dependent may have no RUT and no email (kids seldom have either to hand), so adding
a new one takes a name and nothing else. With neither there is no identity to find,
so such a dependent is a new person (migrations 0010, 0036); one with their own RUT is
the person that RUT is, as anyone is.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, PastDate

from app.schemas.people import Email, MembershipSummary, Name, PersonRef, Phone, Rut


class Family(BaseModel):
    """Who answers for this person, or whom they answer for: never both (0010)."""

    guardian: PersonRef | None
    dependents: list[PersonRef]


class LinkDependent(BaseModel):
    """Make someone already in this gym a dependent."""

    model_config = ConfigDict(extra="forbid")

    person_id: uuid.UUID


class NewDependent(BaseModel):
    """Add someone new to this gym as a dependent."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    email: Email | None = None
    rut: Rut | None = None
    phone: Phone | None = None
    dob: PastDate | None = None


# `has_guardian`: the dependent already has one in this gym. `one_level`: the guardian
# is someone's dependent, or the dependent someone's guardian.
ConflictCode = Literal["has_guardian", "one_level"]


class FamilyConflict(BaseModel):
    code: ConflictCode


class FamilyRefused(BaseModel):
    """409 body."""

    detail: FamilyConflict


class Balance(BaseModel):
    """What a dependent owes, in CLP, from the ledger.

    `owed_clp` is what is still outstanding on billing periods already due: each
    period's amount less the validated payments and credits settling it, never below
    zero (`app.domain.billing`). `pending_clp` is payments sent but not yet validated.
    """

    owed_clp: int
    pending_clp: int


class Dependent(BaseModel):
    """One of the signed-in guardian's dependents, as their page shows them.

    The dependent's attendance (0023) and rank (0018) join this when the student page
    shows them.
    """

    id: uuid.UUID
    name: str
    membership: MembershipSummary | None
    balance: Balance
