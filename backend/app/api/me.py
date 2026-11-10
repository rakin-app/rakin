"""The signed-in person's own side of the gym: what the student page (/me) reads.

Any session in a gym may use it, staff or member, since it answers only about the
person acting: their staff role, if any, a guardian's dependents (migration 0010), and
the student page itself (#65), and their time on the mat (#141).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.attendance import attended
from app.api.grades import current_rank, readable_scheme
from app.api.people import SHOWN_MEMBERSHIP, shown_membership
from app.api.proofs import OPEN_PERIODS, payable_params, to_open_period
from app.api.session_blocks import person_time_of
from app.domain.billing import SETTLING_KINDS, settled_amount
from app.domain.dates import gym_today, start_of_local_day
from app.domain.ledger import EntryKind, EntryStatus
from app.roles import role_in_gym
from app.schemas.blocks import PersonTime
from app.schemas.guardians import Balance, Dependent
from app.schemas.me import MyAttendance, MyPage, MyPayment, NextPayment, NextPaymentStatus
from app.schemas.people import MyRole
from app.tenancy import Tenant, TenantSession, current_tenant

router = APIRouter(prefix="/api/me", tags=["me"])

# Each of the guardian's dependents, with the membership the list shows and their
# balance over every membership they hold here. The ledger is read through
# `ledger_entry_own` (0010): a guardian sees their dependents' entries and no others.
DEPENDENTS = f"""
    SELECT gp.person_id AS id, gp.name,
           m.id AS membership_id, m.status, m.plan_id, pl.name AS plan_name,
           (SELECT coalesce(sum(greatest(bp.amount_due_clp - coalesce((
                       SELECT sum({settled_amount("e")}) FROM ledger_entry e
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

# The payments on the person's memberships and their dependents'. Newest recorded first;
# entries recorded at the same moment go by the period they pay, latest first.
# Only a rejection's note is shown: it is written for the student, other notes are not.
PAYMENTS = """
    SELECT e.id, m.person_id, gp.name AS person_name, e.amount_clp, e.status,
           bp.period_start, e.claimed_at, e.validated_at,
           CASE WHEN e.status = :rejected THEN e.note END AS note, e.created_at
    FROM ledger_entry e
    JOIN membership m ON m.id = e.membership_id
    JOIN gym_person gp ON gp.gym_id = m.gym_id AND gp.person_id = m.person_id
    LEFT JOIN billing_period bp ON bp.id = e.billing_period_id
    WHERE e.kind = :payment
      AND (m.person_id = :me OR m.person_id IN (
          SELECT g.dependent_person_id FROM guardian_link g WHERE g.guardian_person_id = :me))
    ORDER BY e.created_at DESC, bp.period_start DESC NULLS LAST, e.id
    LIMIT :limit
"""

# How far back "Mis pagos" goes: a year of monthly payments.
PAYMENTS_SHOWN = 12


async def _today(session: AsyncSession, gym_id: uuid.UUID) -> date:
    """Today in the gym's timezone: a period due today is owed today."""
    zone = await session.scalar(text("SELECT timezone FROM gym WHERE id = :id"), {"id": gym_id})
    return gym_today(str(zone))


@router.get("/role")
async def my_role(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> MyRole:
    """The signed-in person's staff role in this gym, or none for a member: what the
    admin screens show, such as the pending-proofs badge only to who reads the ledger."""
    return MyRole(role=await role_in_gym(session, tenant))


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


@router.get("/time")
async def my_time(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> PersonTime:
    """The signed-in person's time on the mat, as `GET /api/people/{id}/time` gives it:
    what the student page's "Tu tiempo en el tatami" shows."""
    return await person_time_of(session, tenant.gym_id, tenant.person_id)


@router.get("/page")
async def my_page(
    tenant: Annotated[Tenant, Depends(current_tenant)], session: TenantSession
) -> MyPage:
    """The student page: what is due next and where to pay it, what was paid, the
    person's rank and their classes."""
    gym = (
        await session.execute(
            text(
                "SELECT name, timezone, settings -> 'bank_account' AS bank_account,"
                " settings"
                " FROM gym WHERE id = :id"
            ),
            {"id": tenant.gym_id},
        )
    ).one()
    name = await session.scalar(
        text("SELECT name FROM gym_person WHERE person_id = :me"), {"me": tenant.person_id}
    )
    today = gym_today(str(gym.timezone))

    first = (await session.execute(text(OPEN_PERIODS), payable_params(tenant))).first()
    next_payment = None
    if first is not None:
        period = to_open_period(first)
        status: NextPaymentStatus = (
            "in_review"
            if period.pending_clp > 0
            else "overdue"
            if period.due_date < today
            else "due"
        )
        next_payment = NextPayment(period=period, status=status)

    payments = await session.execute(
        text(PAYMENTS),
        {
            "me": tenant.person_id,
            "payment": EntryKind.PAYMENT.value,
            "rejected": EntryStatus.REJECTED.value,
            "limit": PAYMENTS_SHOWN,
        },
    )
    total, this_month, _ = await attended(
        session,
        tenant.person_id,
        recent=start_of_local_day(today.replace(day=1), str(gym.timezone)),
        since=None,
    )
    return MyPage(
        gym_name=gym.name,
        timezone=gym.timezone,
        person_id=tenant.person_id,
        name=name or "",
        next_payment=next_payment,
        bank_account=gym.bank_account,
        rank=await current_rank(session, tenant.person_id, readable_scheme(gym.settings)),
        attendance=MyAttendance(this_month=this_month, total=total),
        payments=[MyPayment.model_validate(dict(row._mapping)) for row in payments],
    )
