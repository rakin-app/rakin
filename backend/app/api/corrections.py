"""The record of every correction of a student's billing (#277).

Each correction writes an `audit_event` row (migration 0048) in its own transaction:
who made it (`app.person_id`), when, the reason, whose billing it changed, what it
touched, and the period and the membership's balance before and after it, read under
the correction's locks (`app.api.ledger.locked_period`). A void and an adjustment write
one each (`app.api.ledger`); a plan voided by mistake writes one per period it voids,
each marked `plan_void` (`app.api.memberships`).

`GET /api/ledger/people/{id}/corrections` reads a person's rows, newest first, for the
ficha's "Correcciones". Owner and admin only (`LedgerSession`); RLS holds a coach to it
as well, and refuses an insert naming another actor or another gym (0048).
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.roles import LedgerSession
from app.schemas.ledger import Correction, Corrections, Figures

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

LEDGER_CORRECTED = "ledger_corrected"

# The membership's running balance (`v_balance`, 0014): owed if positive, credit if not.
BALANCE = text(
    "SELECT coalesce(sum(balance_clp), 0)::bigint FROM v_balance WHERE membership_id = :id"
)

# Whose the membership is; `now()` is the transaction's, as the policy wants it.
INSERT_CORRECTION = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, reason, detail)"
    " SELECT current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, m.person_id, :action, :reason,"
    " CAST(:detail AS jsonb)"
    " FROM membership m WHERE m.id = :membership_id"
)


async def balance(session: AsyncSession, membership_id: uuid.UUID) -> int:
    return int(await session.scalar(BALANCE, {"id": membership_id}) or 0)


async def record_correction(
    session: AsyncSession,
    *,
    membership_id: uuid.UUID,
    billing_period_id: uuid.UUID,
    entry_ids: list[uuid.UUID],
    purpose: str | None,
    reason: str | None,
    before: Figures,
    after: Figures,
    **detail: Any,
) -> None:
    """Record a correction of the membership's period that wrote `entry_ids`: `purpose`
    as the entry's (`None` for a plain adjustment, `void` for a void)."""
    await session.execute(
        INSERT_CORRECTION,
        {
            "action": LEDGER_CORRECTED,
            "reason": reason,
            "membership_id": membership_id,
            "detail": json.dumps(
                {
                    "purpose": purpose,
                    "membership_id": str(membership_id),
                    "billing_period_id": str(billing_period_id),
                    "entry_ids": [str(e) for e in entry_ids],
                    "before": before.model_dump(),
                    "after": after.model_dump(),
                    **detail,
                }
            ),
        },
    )


# A person's corrections, newest first, with who made each and the period it touched.
CORRECTIONS = text(
    """
    SELECT a.id, a.at, a.action, a.reason, a.detail, actor.name AS actor_name,
           bp.period_start, p.name AS plan_name, count(*) OVER () AS total
    FROM audit_event a
    LEFT JOIN gym_person actor ON actor.gym_id = a.gym_id AND actor.person_id = a.actor_id
    LEFT JOIN billing_period bp ON bp.id = (a.detail->>'billing_period_id')::uuid
    LEFT JOIN membership m ON m.id = (a.detail->>'membership_id')::uuid
    LEFT JOIN plan p ON p.id = m.plan_id
    WHERE a.person_id = :person
    -- A plan's voids share their transaction's time: the latest period first.
    ORDER BY a.at DESC, bp.period_start DESC NULLS LAST, a.id DESC
    LIMIT :limit
    """
)

# Years of fixes are a few dozen rows; past this, "Ver todas" shows the latest.
CORRECTIONS_LIMIT = 200


def figures(value: Any) -> Figures | None:
    return Figures.model_validate(value) if isinstance(value, dict) else None


def correction(row: Any) -> Correction:
    detail = row.detail if isinstance(row.detail, dict) else json.loads(row.detail)
    return Correction(
        id=row.id,
        at=row.at,
        action=row.action,
        purpose=detail.get("purpose"),
        plan_void=bool(detail.get("plan_void")),
        reason=row.reason,
        actor_name=row.actor_name,
        period_start=row.period_start,
        plan_name=row.plan_name,
        before=figures(detail.get("before")),
        after=figures(detail.get("after")),
    )


@router.get("/people/{person_id}/corrections")
async def person_corrections(person_id: uuid.UUID, session: LedgerSession) -> Corrections:
    """Every correction of the person's billing, newest first: the ficha's "Correcciones"."""
    rows = (
        await session.execute(CORRECTIONS, {"person": person_id, "limit": CORRECTIONS_LIMIT})
    ).all()
    return Corrections(total=int(rows[0].total) if rows else 0, items=[correction(r) for r in rows])
