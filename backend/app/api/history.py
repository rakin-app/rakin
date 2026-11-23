"""A person's history from before Rakin, typed on the ficha (#293).

`PUT /api/people/{id}/history` writes "Fecha de inicio y clases": `member_since`, the
day they first trained here, and `prior_classes`, how many classes they had before
Rakin (migration 0051). Both are facts about the person, kept on `gym_person` and never
on a plan, so no billing code, job, view or export reads them
(docs/design/historical-data.md, section 2). The ficha's "Alumno desde" reads the
earliest of `member_since` and their first plan's start, and its class total adds
`prior_classes` (`app.api.attendance`).

A write that changes either records one `history_set` row in `audit_event`, with each
changed field's before and after, in the same transaction: the write and its record
are both kept or neither is. Owner and admin only, as the policy on `audit_event`
holds the app role to as well (0051).

"Historial de pagos" (#295): what a student paid before Rakin, in `history_payment`
(0055). `GET /api/people/{id}/history/payments` reads them by year for the Historial
card; `POST` there writes "Pagos anteriores", every month of the form in one
transaction, each before the person's first plan (`covers_plan`); `POST
.../payments/{payment_id}/remove` deletes one with a reason and records it as
`history_removed`, the whole row in `detail`.
"""

import json
import uuid
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.people import NOT_FOUND, read_person, refuse_anonymised
from app.domain.dates import add_months, gym_today
from app.permissions import LedgerReadSession, LedgerSession, MembersSession
from app.schemas.history import (
    HistoryPayment,
    HistoryPaymentIn,
    HistoryPayments,
    HistoryPaymentsRead,
    HistoryRemoval,
    HistoryYear,
)
from app.schemas.people import HISTORY_WINDOW_YEARS, Person, PersonHistory
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/people", tags=["people"])

HISTORY_SET = "history_set"

LOCK_HISTORY = text(
    "SELECT member_since, prior_classes FROM gym_person WHERE person_id = :id FOR UPDATE"
)

SET_HISTORY = text(
    "UPDATE gym_person SET member_since = :member_since, prior_classes = :prior_classes,"
    " updated_at = now() WHERE person_id = :id"
)

# `now()` is the transaction's, as the policy wants it.
INSERT_HISTORY_SET = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :person, :action, CAST(:detail AS jsonb))"
)


async def _today(session: AsyncSession, tenant: Tenant) -> date:
    timezone: str = await session.scalar(
        text("SELECT timezone FROM gym WHERE id = :id"), {"id": tenant.gym_id}
    )
    return gym_today(timezone)


def refuse_outside_history(field: str, day: date, today: date) -> None:
    """A 422 for a day of someone's history after the gym's today, or more than
    `HISTORY_WINDOW_YEARS` before it: a typo, not a rule."""
    if day > today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} is today at the latest"
        )
    if day < add_months(today, -12 * HISTORY_WINDOW_YEARS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{field} must be within {HISTORY_WINDOW_YEARS} years of today",
        )


def _shown(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Each field of `after` that differs from `before`, with both, as a `history_set`
    row's `detail` holds them."""
    return {
        field: {"before": _shown(before.get(field)), "after": _shown(value)}
        for field, value in after.items()
        if before.get(field) != value
    }


async def record_history_set(
    session: AsyncSession,
    person_id: uuid.UUID,
    changed: Mapping[str, Any],
    *,
    import_id: uuid.UUID | None = None,
) -> None:
    """The `history_set` row for `changed` (`changes`), in the write's transaction: the
    write and its record are both kept or neither is. Nothing changed, nothing recorded.
    Also why someone left and a former student's dates (#294), and what an import set,
    with the `history_imported` row's id as `import_id` (#297)."""
    if not changed:
        return
    detail = dict(changed) if import_id is None else {"import_id": str(import_id), **changed}
    result = await session.execute(
        INSERT_HISTORY_SET,
        {"person": person_id, "action": HISTORY_SET, "detail": json.dumps(detail)},
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(f"no audit row for the history of person {person_id}")


@router.put("/{person_id}/history")
async def set_history(
    person_id: uuid.UUID,
    body: PersonHistory,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: MembersSession,
) -> Person:
    """Their start and their classes before Rakin, as given. Writing what is already
    there records nothing."""
    await refuse_anonymised(session, person_id)
    record = (await session.execute(LOCK_HISTORY, {"id": person_id})).one_or_none()
    if record is None:
        raise NOT_FOUND
    if body.member_since is not None:
        refuse_outside_history("member_since", body.member_since, await _today(session, tenant))
    after = body.model_dump()
    changed = changes(record._asdict(), after)
    if changed:
        await session.execute(SET_HISTORY, {**after, "id": person_id})
        await record_history_set(session, person_id, changed)
    return await read_person(session, person_id, sees_reason=True)


# --- Historial de pagos (#295) --------------------------------------------------------
#
# What a student paid before Rakin, in `history_payment` (0055), which no billing code,
# job, view or export reads. Owner and admin only (`LedgerSession`), as RLS holds the
# app role to as well. A payment's month (else its day) is before the person's first
# plan here, if they have one: a month on or after it is their plan's, which "Pagado
# hasta" (#286) writes in the ledger where billing sees it.

HISTORY_REMOVED = "history_removed"

COVERS_PLAN = "covers_plan"

# `insert_membership`, every plan's way in, reads this row `FOR SHARE`: a plan started for
# the person waits for the form, or the form for the plan, and `PLAN_FROM` sees it.
LOCK_PERSON = text("SELECT 1 FROM gym_person WHERE person_id = :id FOR UPDATE")

# A plan voided by mistake was never theirs (#256); a cancelled one was.
PLAN_FROM = text(
    "SELECT (min(m.started_at) AT TIME ZONE g.timezone)::date FROM membership m"
    " JOIN gym g ON g.id = m.gym_id WHERE m.person_id = :id AND m.voided_at IS NULL"
    " GROUP BY g.timezone"
)

INSERT_PAYMENT = text(
    "INSERT INTO history_payment (gym_id, person_id, paid_on, amount_clp, method,"
    " covers_month, plan_name, note, source, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :person, :paid_on, :amount_clp, :method,"
    " :covers_month, :plan_name, :note, 'manual', current_setting('app.person_id')::uuid)"
)

PAYMENTS = text(
    """
    SELECT h.id, h.paid_on, h.amount_clp, h.method, h.covers_month, h.plan_name, h.note,
           h.source, i.detail->>'file_name' AS import_name, actor.name AS created_by_name,
           h.created_at
    FROM history_payment h
    LEFT JOIN gym_person actor ON actor.gym_id = h.gym_id AND actor.person_id = h.created_by
    LEFT JOIN audit_event i ON i.id = h.import_id
    WHERE h.person_id = :id
    ORDER BY coalesce(h.covers_month, h.paid_on) DESC, h.paid_on DESC, h.created_at DESC, h.id
    """
)

# The whole row, for its `history_removed` record. No lock to take: the delete is the
# read, and the app role may not update a row.
DELETE_PAYMENT = text(
    "DELETE FROM history_payment WHERE id = :payment AND person_id = :person"
    " RETURNING id, person_id, paid_on, amount_clp, method, covers_month, plan_name, note,"
    " source, import_id, created_by, created_at"
)

INSERT_HISTORY_REMOVED = text(
    "INSERT INTO audit_event (gym_id, at, actor_id, person_id, action, reason, detail)"
    " VALUES (current_setting('app.gym_id')::uuid, now(),"
    " current_setting('app.person_id')::uuid, :person, :action, :reason,"
    " CAST(:detail AS jsonb))"
)


def covered(payment: HistoryPaymentIn) -> date:
    """The day that says which side of the person's first plan a payment is on."""
    return payment.covers_month or payment.paid_on


def in_plan(payment: HistoryPaymentIn, plan_from: date) -> bool:
    """Whether the plan covers it: the month it paid for, from the month the plan began
    (a plan started on the 10th covers that month), else the day it was paid."""
    if payment.covers_month is not None:
        return payment.covers_month >= plan_from.replace(day=1)
    return payment.paid_on >= plan_from


def refuse_covers_plan(payments: list[HistoryPaymentIn], plan_from: date | None) -> None:
    """A 422 `covers_plan` for a payment the person's first plan covers."""
    if plan_from is None:
        return
    inside = [covered(p) for p in payments if in_plan(p, plan_from)]
    if inside:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": COVERS_PLAN,
                "message": "a month on or after their first plan is paid with Pagado hasta",
                "plan_from": plan_from.isoformat(),
                "months": sorted({d.isoformat() for d in inside}),
            },
        )


async def read_history_payments(session: AsyncSession, person_id: uuid.UUID) -> HistoryPaymentsRead:
    rows = (await session.execute(PAYMENTS, {"id": person_id})).all()
    years: dict[int, list[HistoryPayment]] = {}
    for row in rows:
        payment = HistoryPayment.model_validate(row._asdict())
        years.setdefault((payment.covers_month or payment.paid_on).year, []).append(payment)
    return HistoryPaymentsRead(
        plan_from=await session.scalar(PLAN_FROM, {"id": person_id}),
        years=[
            HistoryYear(
                year=year,
                count=len(payments),
                total_clp=sum(p.amount_clp for p in payments),
                payments=payments,
            )
            for year, payments in sorted(years.items(), reverse=True)
        ],
    )


@router.get("/{person_id}/history/payments")
async def history_payments(person_id: uuid.UUID, session: LedgerReadSession) -> HistoryPaymentsRead:
    """The Historial card's payments, by year, newest first."""
    if (
        await session.scalar(
            text("SELECT 1 FROM gym_person WHERE person_id = :id"), {"id": person_id}
        )
        is None
    ):
        raise NOT_FOUND
    return await read_history_payments(session, person_id)


@router.post("/{person_id}/history/payments", status_code=status.HTTP_201_CREATED)
async def add_history_payments(
    person_id: uuid.UUID,
    body: HistoryPayments,
    tenant: Annotated[Tenant, Depends(current_tenant)],
    session: LedgerSession,
) -> HistoryPaymentsRead:
    """ "Pagos anteriores": every payment of the form, in one transaction or none. A
    payment equal to one already there is written too: the form warns, and a gym may
    have been paid twice. Under the person's lock, so their first plan is read once."""
    if (await session.execute(LOCK_PERSON, {"id": person_id})).one_or_none() is None:
        raise NOT_FOUND
    today = await _today(session, tenant)
    for payment in body.payments:
        refuse_outside_history("paid_on", payment.paid_on, today)
        if payment.covers_month is not None:
            refuse_outside_history("covers_month", payment.covers_month, today)
    refuse_covers_plan(body.payments, await session.scalar(PLAN_FROM, {"id": person_id}))
    await session.execute(
        INSERT_PAYMENT,
        [{**p.model_dump(), "person": person_id} for p in body.payments],
    )
    return await read_history_payments(session, person_id)


@router.post("/{person_id}/history/payments/{payment_id}/remove")
async def remove_history_payment(
    person_id: uuid.UUID,
    payment_id: uuid.UUID,
    body: HistoryRemoval,
    session: LedgerSession,
) -> HistoryPaymentsRead:
    """Eliminar, for a typo: the payment goes, and a `history_removed` row keeps the
    whole of it and the reason, in the same transaction."""
    row = (
        await session.execute(DELETE_PAYMENT, {"payment": payment_id, "person": person_id})
    ).one_or_none()
    if row is None:
        raise NOT_FOUND
    removed = {
        k: str(v) if isinstance(v, uuid.UUID) else _shown(v) for k, v in row._asdict().items()
    }
    result = await session.execute(
        INSERT_HISTORY_REMOVED,
        {
            "person": person_id,
            "action": HISTORY_REMOVED,
            "reason": body.reason,
            "detail": json.dumps({"payment": removed}),
        },
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise RuntimeError(f"no audit row for the removal of history payment {payment_id}")
    return await read_history_payments(session, person_id)
