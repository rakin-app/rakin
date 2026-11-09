"""The signed-in person's own side of the gym: what the student page (/me) reads.

Any session in a gym may use it, staff or member, since it answers only about the
person acting. For now that is a guardian's dependents (migration 0009); the rest of
the page comes with #64 and #65.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import SHOWN_MEMBERSHIP, shown_membership
from app.domain.billing import SETTLING_KINDS
from app.domain.dates import local_date
from app.domain.ledger import EntryKind, EntryStatus
from app.schemas.guardians import Balance, Dependent
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(prefix="/api/me", tags=["me"])

# Each of the guardian's dependents, with the membership the list shows and their
# balance over every membership they hold here. The ledger is read through
# `ledger_entry_own` (0009): a guardian sees their dependents' entries and no others.
DEPENDENTS = f"""
    SELECT gp.person_id AS id, gp.name,
           m.id AS membership_id, m.status, m.plan_id, pl.name AS plan_name,
           (SELECT coalesce(sum(greatest(bp.amount_due_clp - coalesce((
                       SELECT sum(e.amount_clp) FROM ledger_entry e
                       WHERE e.billing_period_id = bp.id AND e.status = :validated
                         AND e.kind = ANY(CAST(:settling AS text[]))), 0), 0)), 0)
            FROM billing_period bp JOIN membership bm ON bm.id = bp.membership_id
            WHERE bm.person_id = gp.person_id AND bp.due_date <= :today) AS owed_clp,
           (SELECT coalesce(sum(e.amount_clp), 0)
            FROM ledger_entry e JOIN membership em ON em.id = e.membership_id
            WHERE em.person_id = gp.person_id
              AND e.kind = :payment AND e.status = :pending) AS pending_clp
    FROM guardian_link gl
    JOIN gym_person gp ON gp.gym_id = gl.gym_id AND gp.person_id = gl.dependent_person_id
    {SHOWN_MEMBERSHIP}
    WHERE gl.guardian_person_id = :guardian
    ORDER BY lower(gp.name), gp.person_id
"""


async def _today(session: AsyncSession, gym_id: uuid.UUID) -> date:
    """Today in the gym's timezone: a period due today is owed today."""
    zone = await session.scalar(text("SELECT timezone FROM gym WHERE id = :id"), {"id": gym_id})
    return local_date(datetime.now(UTC), str(zone))


@router.get("/dependents")
async def my_dependents(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> list[Dependent]:
    """Whom the signed-in person pays for in this gym, each with their balance."""
    rows = await session.execute(
        text(DEPENDENTS),
        {
            "guardian": tenant.person_id,
            "today": await _today(session, tenant.gym_id),
            "validated": EntryStatus.VALIDATED.value,
            "pending": EntryStatus.PENDING.value,
            "payment": EntryKind.PAYMENT.value,
            "settling": sorted(k.value for k in SETTLING_KINDS),
        },
    )
    return [
        Dependent(
            id=row.id,
            name=row.name,
            membership=shown_membership(row),
            balance=Balance(owed_clp=row.owed_clp, pending_clp=row.pending_clp),
        )
        for row in rows
    ]
