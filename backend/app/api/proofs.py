"""A student pays by transfer and uploads the proof ("Subir comprobante", #35).

Proofs never pass through the API process. The browser asks for an upload URL
(`POST /api/me/proofs`), PUTs the file straight to object storage, and then claims the
payment (`POST /api/me/payments`): a `pending` transfer for one billing period, pointing
at the proof, which an admin later validates or rejects (#36). The claim checks that the
file is really there, so a failed upload never leaves a pending entry with nothing to
look at.

Anyone signed in to a gym may claim for their own memberships and their dependents'
(migration 0011 holds the database to the same). Each person's proofs live under their
own prefix, `proofs/<gym_id>/<person_id>/`, and a claim takes only a key from it.

The claimant then gets a "proof received" email, or their guardian does
(`app.contacts`), and admins see the pending count (`GET /api/ledger/pending`).
"""

import logging
import re
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.ledger import ENTRY_COLUMNS
from app.contacts import Contact, contact_for
from app.domain.billing import SETTLING_KINDS
from app.domain.ledger import EntryKind, EntryStatus
from app.domain.money import format_clp
from app.integrations import Integrations, get_integrations
from app.integrations.blobstore import ALLOWED_CONTENT_TYPES, MAX_UPLOAD_BYTES
from app.integrations.mailer import Email, MailDeliveryError, Mailer
from app.schemas.ledger import Entry, Method
from app.schemas.proofs import OpenPeriod, ProofClaim, ProofUpload, ProofUploadRequest
from app.tenancy import Tenant, TenantSession, current_tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["me"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "billing period not found")

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def proof_prefix(tenant: Tenant) -> str:
    """Where `tenant`'s proofs are stored; migration 0011 checks the same prefix."""
    return f"proofs/{tenant.gym_id}/{tenant.person_id}/"


def is_own_proof(tenant: Tenant, key: str) -> bool:
    return re.fullmatch(re.escape(proof_prefix(tenant)) + _UUID, key) is not None


# The billing periods of the person's memberships and their dependents', each with what
# validated entries have paid on it and what proofs claim and await review. Everything
# is held to the current gym by RLS, and the ledger to the person's own entries
# (`ledger_entry_own`, 0010).
PAYABLE = """
    SELECT bp.id, bp.membership_id, m.person_id, gp.name AS person_name,
           pl.name AS plan_name, bp.period_start, bp.period_end, bp.due_date,
           bp.amount_due_clp, coalesce(s.paid, 0) AS paid_clp,
           coalesce(s.pending, 0) AS pending_clp
    FROM billing_period bp
    JOIN membership m ON m.id = bp.membership_id
    JOIN plan pl ON pl.id = m.plan_id
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    LEFT JOIN LATERAL (
        SELECT (sum(e.amount_clp) FILTER (
                    WHERE e.status = :validated AND e.kind = ANY(CAST(:settling AS text[]))
               ))::bigint AS paid,
               (sum(e.amount_clp) FILTER (
                    WHERE e.status = :pending AND e.kind = :payment
               ))::bigint AS pending
        FROM ledger_entry e WHERE e.billing_period_id = bp.id
    ) s ON true
    WHERE (m.person_id = :me OR m.person_id IN (
        SELECT g.dependent_person_id FROM guardian_link g WHERE g.guardian_person_id = :me))
"""

OPEN_PERIODS = (
    PAYABLE
    + " AND coalesce(s.paid, 0) < bp.amount_due_clp"
    + " ORDER BY bp.due_date, lower(gp.name), bp.id"
)
ONE_PERIOD = PAYABLE + " AND bp.id = :id"

CLAIM = text(
    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
    " status, method, claimed_by, claimed_at, proof_object_key)"
    " VALUES (current_setting('app.gym_id')::uuid, :membership_id, :billing_period_id,"
    " :amount_clp, :kind, :status, :method, current_setting('app.person_id')::uuid, now(),"
    f" :proof_key) RETURNING {ENTRY_COLUMNS}"
)


def _params(tenant: Tenant, **extra: Any) -> dict[str, Any]:
    return {
        "me": tenant.person_id,
        "validated": EntryStatus.VALIDATED.value,
        "pending": EntryStatus.PENDING.value,
        "payment": EntryKind.PAYMENT.value,
        "settling": sorted(k.value for k in SETTLING_KINDS),
        **extra,
    }


def _open_period(row: Any) -> OpenPeriod:
    paid = min(row.paid_clp, row.amount_due_clp)
    return OpenPeriod(
        id=row.id,
        membership_id=row.membership_id,
        person_id=row.person_id,
        person_name=row.person_name,
        plan_name=row.plan_name,
        period_start=row.period_start,
        period_end=row.period_end,
        due_date=row.due_date,
        amount_due_clp=row.amount_due_clp,
        paid_clp=paid,
        outstanding_clp=row.amount_due_clp - paid,
        pending_clp=row.pending_clp,
    )


@router.get("/periods")
async def open_periods(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> list[OpenPeriod]:
    """What the signed-in person can pay in this gym, theirs and their dependents',
    earliest due first."""
    rows = await session.execute(text(OPEN_PERIODS), _params(tenant))
    return [_open_period(row) for row in rows]


@router.post("/proofs", status_code=status.HTTP_201_CREATED)
async def request_upload(
    body: ProofUploadRequest,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    integrations: Annotated[Integrations, Depends(get_integrations)],
    request: Request,
) -> ProofUpload:
    """A URL to PUT one proof to, of exactly this type and size, under the person's
    own prefix. Nothing is recorded until the payment is claimed with its key."""
    key = proof_prefix(tenant) + str(uuid.uuid4())
    upload = integrations.blob_store.presign_upload(key, body.content_type, body.size_bytes)
    return ProofUpload(
        key=key,
        url=upload.url,
        headers=upload.headers,
        expires_in_seconds=request.app.state.settings.blob_url_ttl_seconds,
    )


@router.post("/payments", status_code=status.HTTP_201_CREATED)
async def claim_payment(
    body: ProofClaim,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: TenantSession,
    integrations: Annotated[Integrations, Depends(get_integrations)],
    background: BackgroundTasks,
) -> Entry:
    """Record a pending transfer for one period, backed by an uploaded proof."""
    if not is_own_proof(tenant, body.proof_key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not one of your uploads")
    stored = await integrations.blob_store.stat(body.proof_key)
    # The store already refused anything else at upload; checked again, since an
    # upload URL is only as strict as the store that signed it.
    if (
        stored is None
        or stored.content_type not in ALLOWED_CONTENT_TYPES
        or stored.size > MAX_UPLOAD_BYTES
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "proof not uploaded")

    row = (
        await session.execute(text(ONE_PERIOD), _params(tenant, id=body.billing_period_id))
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    if row.paid_clp >= row.amount_due_clp:
        raise HTTPException(status.HTTP_409_CONFLICT, "billing period is already paid in full")

    try:
        # A savepoint, so a refusal leaves the request's transaction usable for the 409.
        async with session.begin_nested():
            result = await session.execute(
                CLAIM,
                {
                    "membership_id": row.membership_id,
                    "billing_period_id": row.id,
                    "amount_clp": body.amount_clp,
                    "kind": EntryKind.PAYMENT.value,
                    "status": EntryStatus.PENDING.value,
                    "method": Method.TRANSFER.value,
                    "proof_key": body.proof_key,
                },
            )
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "__cause__", None), "constraint_name", None)
        if constraint != "ledger_entry_proof_object_key":
            raise
        raise HTTPException(status.HTTP_409_CONFLICT, "this proof is already claimed") from None
    entry = Entry.model_validate(dict(result.one()._mapping))

    contact = await contact_for(session, row.person_id)
    gym_name = await session.scalar(
        text("SELECT name FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    if contact is None or not contact.email:
        logger.info("proof received: no email to send it to", extra={"entry_id": str(entry.id)})
        return entry
    try:
        email = proof_received(
            contact,
            gym=str(gym_name),
            amount_clp=entry.amount_clp,
            period_start=row.period_start,
            period_end=row.period_end,
            dependent_name=row.person_name if contact.on_behalf_of else None,
        )
    # An address the gym typed wrong must not cost the student their claim.
    except ValueError:
        logger.warning("proof received not sent", extra={"entry_id": str(entry.id)}, exc_info=True)
        return entry
    # After the response, which is after the entry has committed.
    background.add_task(_send, integrations.mailer, email, entry.id)
    return entry


def proof_received(
    contact: Contact,
    *,
    gym: str,
    amount_clp: int,
    period_start: date,
    period_end: date,
    dependent_name: str | None,
) -> Email:
    """The "proof received" notice: what was claimed, and that someone will review it."""
    assert contact.email is not None
    whose = f" de {dependent_name}" if dependent_name else ""
    return Email(
        to=contact.email,
        subject="Recibimos tu comprobante",
        text=(
            f"Hola, {contact.name}:\n\n"
            f"Recibimos tu comprobante de {format_clp(amount_clp)}{whose} en {gym},"
            f" por el período del {period_start:%d-%m-%Y} al {period_end:%d-%m-%Y}.\n\n"
            "Lo revisaremos y te avisaremos cuando el pago quede validado.\n"
        ),
    )


async def _send(mailer: Mailer, email: Email, entry_id: uuid.UUID) -> None:
    try:
        await mailer.send(email)
    # After the response: there is no one left to tell but the log.
    except MailDeliveryError:
        logger.warning("proof received not sent", extra={"entry_id": str(entry_id)}, exc_info=True)
