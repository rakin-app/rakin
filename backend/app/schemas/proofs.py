"""A student's transfer proof: the upload URL they ask for, and the payment they claim.

The proof goes from the browser straight to object storage (`app.integrations.blobstore`):
the API only presigns the PUT and, once it has landed, records a pending payment that
points at it (#35). The size and content type are fixed when the URL is signed, so the
store refuses any other. An admin then reviews it, validating or rejecting it (#36).
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.integrations.blobstore import MAX_UPLOAD_BYTES, validate_content_type
from app.schemas.ledger import Amount, Method, Note


class ProofUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # JPEG, PNG, WebP, HEIC or PDF (`ALLOWED_CONTENT_TYPES`); anything else is a 422.
    content_type: Annotated[str, AfterValidator(validate_content_type)]
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=MAX_UPLOAD_BYTES)]


class ProofUpload(BaseModel):
    # Claim the payment with this key once the PUT succeeds.
    key: str
    # PUT the file here with these headers, and a body of exactly `size_bytes`.
    url: str
    headers: dict[str, str]
    expires_in_seconds: int


class ProofClaim(BaseModel):
    """A pending transfer for one period, and the proof uploaded for it."""

    model_config = ConfigDict(extra="forbid")

    billing_period_id: uuid.UUID
    # Up to the price ceiling, and possibly more than is outstanding: what was paid
    # beyond it becomes a credit when an admin validates the claim (#36).
    amount_clp: Amount
    proof_key: Annotated[str, Field(max_length=512)]


class OpenPeriod(BaseModel):
    """A billing period the signed-in person can pay: their own or a dependent's."""

    id: uuid.UUID
    membership_id: uuid.UUID
    # Whose membership it is: the person acting, or one of their dependents.
    person_id: uuid.UUID
    person_name: str
    plan_name: str
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int
    paid_clp: int
    outstanding_clp: int
    # Claimed by a proof and not yet reviewed.
    pending_clp: int


class PendingCount(BaseModel):
    """Proofs waiting for an admin to validate or reject them."""

    count: int


class ReviewPeriod(BaseModel):
    """The billing period a proof claims to pay, as validated payments leave it."""

    id: uuid.UUID
    period_start: date
    period_end: date
    due_date: date
    amount_due_clp: int
    paid_clp: int
    outstanding_clp: int


class RecentPayment(BaseModel):
    amount_clp: int
    paid_at: datetime


class ProofReview(BaseModel):
    """A pending proof, with what an admin needs to validate or reject it in one tap
    ("Validar comprobante", #36)."""

    id: uuid.UUID
    membership_id: uuid.UUID
    person_id: uuid.UUID
    person_name: str
    # What the claim says was paid, and when it was sent.
    amount_clp: int
    method: Method | None
    claimed_at: datetime | None
    # Who sent it: the student, or their guardian.
    claimed_by_name: str | None
    # Where the browser GETs the proof, or None when the file is missing from storage.
    proof_url: str | None
    proof_content_type: str | None
    plan_name: str
    plan_kind: str
    anchor_day: int | None
    period: ReviewPeriod
    # What the membership still owes on its other periods already due.
    prior_balance_clp: int
    # The membership's latest validated payments, newest first, at most three.
    last_payments: list[RecentPayment]
    # Classes attended in the last 30 days; None until attendance is recorded (#44).
    attendance_30d: int | None


class ProofRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required: it is what the student is told.
    note: Note
