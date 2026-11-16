"""The consent register (#370, migration 0058): what each member's data rest on, and the
record of who accepted which notice when.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.people import PersonRef

ConsentAction = Literal["notice_accepted", "consent_given", "consent_withdrawn"]

# An adult's data rest on the membership contract; a minor's, or a dependent's with no
# birth date, on their guardian's consent (docs/legal-research.md, row 1).
Basis = Literal["contract", "guardian_consent"]

# A guardian's consent, as their latest act left it; `missing` before any.
ConsentState = Literal["given", "withdrawn", "missing"]


class NoticeVersion(BaseModel):
    """The privacy notice as the person read it: the template's date
    (`TEMPLATE_UPDATED_ON`) and the gym's details' (`updated_on`). Either one older than
    the notice now is a 409 `stale_notice`."""

    model_config = ConfigDict(extra="forbid")

    template_on: date
    details_on: date


class ConsentEvent(BaseModel):
    action: ConsentAction
    at: datetime
    # Who acted: the person, or their guardian. None once they are no longer in this gym.
    by: PersonRef | None
    # `join`, the join form; `page`, the guardian's page.
    source: Literal["join", "page"]
    # The notice's version; none on a withdrawal, or a request sent before 0058.
    template_on: date | None
    details_on: date | None


class PersonConsent(BaseModel):
    """What the ficha shows: the basis, the guardian's consent when it is the basis,
    and every act, newest first."""

    basis: Basis
    # Null when the basis is the contract.
    consent: ConsentState | None
    events: list[ConsentEvent]


class DependentConsent(BaseModel):
    """One of the signed-in guardian's dependents whose data rest on their consent."""

    id: uuid.UUID
    name: str
    consent: ConsentState
    # When the latest act was; null while `missing`.
    at: datetime | None
