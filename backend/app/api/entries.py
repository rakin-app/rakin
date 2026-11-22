"""Writing a ledger entry as the admin acting, validated as they record it.

Shared by the ledger (`app.api.ledger`), the cobro lines it settles (`app.api.extra_lines`)
and the proofs (`app.api.proofs`), so none of them imports another to reach it.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ledger import LedgerEntry
from app.schemas.ledger import Entry

ENTRY_COLUMNS = (
    "id, membership_id, billing_period_id, amount_clp, kind, status, method,"
    " claimed_by, claimed_at, validated_by, validated_at, proof_object_key, note, created_at,"
    " refund_of, extra_line_id, purpose, corrects, coalesce(purpose = 'void', false) AS voids"
)

# Who is acting, as `app.tenancy` set it; the recording admin.
CURRENT_PERSON = "current_setting('app.person_id')::uuid"

# Validated by the admin who records it, at the same moment; `now()` is the
# transaction's, so the payment and its credit carry one time.
INSERT_ENTRY = text(
    "INSERT INTO ledger_entry (gym_id, membership_id, billing_period_id, amount_clp, kind,"
    " status, method, claimed_by, claimed_at, validated_by, validated_at, note, refund_of,"
    " extra_line_id, purpose, corrects)"
    " VALUES (current_setting('app.gym_id')::uuid, :membership_id, :billing_period_id,"
    f" :amount_clp, :kind, :status, :method, {CURRENT_PERSON}, now(), {CURRENT_PERSON}, now(),"
    f" :note, :refund_of, :extra_line_id, :purpose, :corrects) RETURNING {ENTRY_COLUMNS}"
)


def standing_void(entry: str) -> str:
    """`entry`, a `ledger_entry`, is a void no restore stands against (#278): what reads
    its period's charge as voided, and leaves the period out of "Esperado"."""
    return (
        f"{entry}.purpose = 'void' AND NOT EXISTS (SELECT FROM ledger_entry restored"
        f" WHERE restored.corrects = {entry}.id AND restored.purpose = 'restore')"
    )


async def insert_entry(session: AsyncSession, entry: LedgerEntry, **columns: Any) -> Entry:
    """Record `entry`, on a membership's period or a cobro line as `columns` say."""
    result = await session.execute(
        INSERT_ENTRY,
        {
            "amount_clp": entry.amount_clp,
            "kind": entry.kind.value,
            "status": entry.status.value,
            "note": entry.note,
            "purpose": entry.purpose.value if entry.purpose else None,
            "corrects": None,
            "method": None,
            "refund_of": None,
            "membership_id": None,
            "billing_period_id": None,
            "extra_line_id": None,
            **columns,
        },
    )
    return Entry.model_validate(dict(result.one()._mapping))


def moved_join(entry: str) -> str:
    """The other half of a payment moved (#280), for `entry`, a `ledger_entry`, as `mv`:
    the pair shares `corrects` (the payment) and its transaction's `created_at`, one of
    them a refund out and the other a payment in. Its period, plan and person."""
    return f"""
    LEFT JOIN LATERAL (
        SELECT o.billing_period_id, obp.period_start, o.membership_id,
               opl.name AS plan_name, om.person_id, ogp.name AS person_name
        FROM ledger_entry o
        JOIN billing_period obp ON obp.id = o.billing_period_id
        JOIN membership om ON om.id = o.membership_id
        JOIN plan opl ON opl.id = om.plan_id
        JOIN gym_person ogp ON ogp.gym_id = om.gym_id AND ogp.person_id = om.person_id
        WHERE {entry}.purpose = 'move' AND o.purpose = 'move' AND o.corrects = {entry}.corrects
          AND o.kind <> {entry}.kind AND o.created_at = {entry}.created_at
        ORDER BY o.id
        LIMIT 1
    ) mv ON true
"""


MOVED_COLUMNS = (
    "mv.billing_period_id AS moved_period_id, mv.period_start AS moved_period_start,"
    " mv.membership_id AS moved_membership_id, mv.plan_name AS moved_plan_name,"
    " mv.person_id AS moved_person_id, mv.person_name AS moved_person_name"
)
