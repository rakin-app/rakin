"""The terms a gym accepts in the app (#499): the page, what the titular fills in, and
the record of each acceptance (`app.api.terms`)."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from app.domain.rut import format_rut
from app.schemas.people import Email, Name, Phone, Rut

Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]

TermsState = Literal["pending", "outdated", "current"]


class BreachContact(BaseModel):
    """Who the company tells of a breach (Términos de encargo, clause 12)."""

    model_config = ConfigDict(extra="forbid")

    name_and_role: Line
    email: Email
    phone: Phone

    def line(self) -> str:
        """As the text names them: "Ana Pérez, gerente, ana@…, +56 9 …"."""
        return f"{self.name_and_role}, {self.email}, {self.phone}"


class TermsFilled(BaseModel):
    """What the titular fills in of the texts' blanks (`app.legal.terms.BLANKS`): the
    gym's legal identity, who represents it, and one or two contacts for a breach."""

    model_config = ConfigDict(extra="forbid")

    legal_name: Line
    rut: Rut
    address: Line
    representative: Name
    breach_contacts: Annotated[list[BreachContact], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def _another_email(self) -> "TermsFilled":
        # The text asks the second contact for another address than the first's.
        emails = [c.email.lower() for c in self.breach_contacts]
        if len(set(emails)) != len(emails):
            raise PydanticCustomError(
                "same_contact_email", "the second contact needs another email"
            )
        return self

    def values(self) -> dict[str, str]:
        """The blanks the titular fills, by field, as the texts show them."""
        first = self.breach_contacts[0]
        second = self.breach_contacts[1].line() if len(self.breach_contacts) > 1 else "ninguno"
        return {
            "legal_name": self.legal_name,
            "rut": format_rut(self.rut),
            "address": self.address,
            "representative": self.representative,
            "contact_name": first.name_and_role,
            "contact_email": first.email,
            "contact_phone": first.phone,
            "second_contact": second,
        }


class TermsChange(BaseModel):
    version: str
    html: str


class TermsDocument(BaseModel):
    """One text as the page shows it: rendered for the gym, its owner's blanks empty."""

    key: Literal["service", "processor"]
    title: str
    version: str
    html: str
    # What changed in each version after the one the gym last accepted, the latest
    # first; empty for a gym that accepted none.
    changes: list[TermsChange]


class TermsPage(BaseModel):
    """What the acceptance page shows and asks (`GET /api/terms`)."""

    state: TermsState
    gym_name: str
    documents: list[TermsDocument]
    # What the form starts with: the latest acceptance's values, or the titular's name.
    prefill: dict[str, object]
    # Each checkbox's words, `{legal_name}` standing for the razón social typed.
    declarations: dict[str, str]
    subprocessors: list[str]


class TermsAcceptance(BaseModel):
    """`POST /api/terms/accept`: the versions the page showed, and what was filled in.
    Both boxes ticked, which the page asks before it lets the button go."""

    model_config = ConfigDict(extra="forbid")

    service_version: str
    processor_version: str
    filled: TermsFilled
    accept_service: Literal[True]
    accept_processor: Literal[True]


class TermsAccepted(BaseModel):
    id: uuid.UUID
    accepted_at: datetime


class TermsRecord(BaseModel):
    """One acceptance, as Ajustes lists it."""

    id: uuid.UUID
    accepted_at: datetime
    channel: Literal["in_app", "outside"]
    service_version: str | None
    processor_version: str
    accepted_by_name: str | None
    # The date on the copy signed outside the app; None in the app.
    signed_on: date | None
    # Whether a copy can be downloaded: only of one made in the app.
    has_copy: bool
