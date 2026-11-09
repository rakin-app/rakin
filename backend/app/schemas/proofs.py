"""A student's transfer proof: the upload URL they ask for, and the payment they claim.

The proof goes from the browser straight to object storage (`app.integrations.blobstore`):
the API only presigns the PUT and, once it has landed, records a pending payment that
points at it (#35). The size and content type are fixed when the URL is signed, so the
store refuses any other.
"""

import uuid
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.integrations.blobstore import MAX_UPLOAD_BYTES, validate_content_type
from app.schemas.ledger import Amount


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
