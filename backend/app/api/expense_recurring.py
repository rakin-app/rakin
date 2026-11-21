"""Gastos fijos (`/api/expenses/recurring`): rent and bills as monthly templates (#315).

Rent, internet and the power bill come every month. The gym saves each as a template
(`expense_recurring`, migration 0085), and Gastos shows, above the month's list, the
active ones with no expense from them that month and not skipped: "Gastos fijos por
registrar" (docs/design/expenses-and-officers.md, section 11).

- `GET` lists the templates, active first; `POST` adds one, `PATCH /{id}` edits or
  pauses it (`active`).
- `GET /month` is the card for a month: `due` and `skipped`, each with the day it would
  be recorded on.
- `POST /record` records fixed templates at their amounts, one (a tap on Registrar) or
  every one ("Registrar los fijos"), each dated its day of the month, or the gym's
  today if that is earlier. One recorded already that month is passed over, so a
  double tap records once. An estimated one is recorded through the form instead
  (`POST /api/expenses` with its `recurring_id`), at the bill's figure.
- `POST /{id}/skip` is "No este mes", `DELETE /{id}/skip/{month}` takes it back.

Rakin never records an expense by itself: no job, trigger or read writes one, so every
expense on the books is one a person confirmed. The same permissions as expenses:
reading with `expenses_read`, writing with `expenses_write`, and RLS holds the
database to the same (0085).
"""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.expenses import (
    TIMEZONE,
    _live_category,
    _read,
    _today,
    unprocessable,
)
from app.domain.dates import add_months
from app.permissions import ExpensesReadSession, ExpensesSession
from app.schemas.expenses import (
    MAX_RECURRING,
    AmountKind,
    DueRecurring,
    Expense,
    RecordRecurring,
    Recurring,
    RecurringChange,
    RecurringIn,
    RecurringMonth,
    SkipRecurring,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/expenses/recurring", tags=["expenses"])

Acting = Annotated[Tenant, Depends(current_tenant)]

NO_RECURRING = HTTPException(status.HTTP_404_NOT_FOUND, "no such gasto fijo in this gym")
TOO_MANY = HTTPException(
    status.HTTP_409_CONFLICT,
    {
        "code": "too_many_recurring",
        "message": f"a gym has at most {MAX_RECURRING} gastos fijos",
    },
)

COLUMNS = """
    SELECT r.id, r.category_id, c.name AS category_name,
           c.archived_at IS NOT NULL AS category_archived, r.payee, r.method, r.amount_clp,
           r.amount_kind, r.day_of_month, r.active, r.created_at
    FROM expense_recurring r
    JOIN expense_category c ON c.id = r.category_id
"""

ALL = text(COLUMNS + " ORDER BY NOT r.active, r.day_of_month, c.sort, r.created_at, r.id")
ONE = text(COLUMNS + " WHERE r.id = :id")

# The month's card: the active templates made by the end of the month, with no expense
# from them that counts in it, and whether each was skipped for it.
MONTH = text(
    COLUMNS.replace(
        "FROM expense_recurring r",
        ", EXISTS (SELECT FROM expense_skip s WHERE s.recurring_id = r.id"
        " AND s.month = :month) AS skipped\n    FROM expense_recurring r",
    )
    + """
    WHERE r.active
      AND (r.created_at AT TIME ZONE :tz)::date < :end
      AND NOT EXISTS (
          SELECT FROM expense e
          WHERE e.recurring_id = r.id AND e.voided_at IS NULL
            AND e.spent_on >= :month AND e.spent_on < :end)
    ORDER BY r.day_of_month, c.sort, r.created_at, r.id
    """
)

LOCK = text(
    "SELECT id, category_id, payee, method, amount_clp, amount_kind, day_of_month, active"
    " FROM expense_recurring WHERE id = :id FOR UPDATE"
)

INSERT = text(
    "INSERT INTO expense_recurring (gym_id, category_id, payee, method, amount_clp,"
    " amount_kind, day_of_month, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :category_id, :payee, :method,"
    " :amount_clp, :amount_kind, :day_of_month, current_setting('app.person_id')::uuid)"
    " RETURNING id"
)

# The template's expense in its month, at its amount, unless one that counts is there
# already (the partial unique index of 0085): then nothing, and no id.
RECORD = text(
    "INSERT INTO expense (gym_id, spent_on, amount_clp, category_id, payee, method,"
    " recurring_id, created_by)"
    " SELECT r.gym_id, :spent_on, r.amount_clp, r.category_id, r.payee, r.method, r.id,"
    " current_setting('app.person_id')::uuid FROM expense_recurring r WHERE r.id = :id"
    " ON CONFLICT (recurring_id, (date_trunc('month', spent_on::timestamp)))"
    " WHERE recurring_id IS NOT NULL AND voided_at IS NULL DO NOTHING"
    " RETURNING id"
)

SKIP = text(
    "INSERT INTO expense_skip (gym_id, recurring_id, month, created_by)"
    " VALUES (current_setting('app.gym_id')::uuid, :id, :month,"
    " current_setting('app.person_id')::uuid) ON CONFLICT DO NOTHING"
)
UNSKIP = text("DELETE FROM expense_skip WHERE recurring_id = :id AND month = :month")


async def _one(session: AsyncSession, recurring_id: uuid.UUID) -> Recurring:
    row = (await session.execute(ONE, {"id": recurring_id})).one_or_none()
    if row is None:
        raise NO_RECURRING
    return Recurring.model_validate(row._asdict())


def due_on(month: date, day_of_month: int, today: date) -> date:
    """The day a template is recorded on in `month`: its day, the month's last if the
    month is shorter, or `today` if that is earlier, since nothing is recorded before
    it is paid."""
    last = (add_months(month, 1) - timedelta(days=1)).day
    return min(month.replace(day=min(day_of_month, last)), today)


async def _shown_month(
    session: AsyncSession, tenant: Tenant, month: date | None
) -> tuple[date, date]:
    """`month` (the current one when None) and the gym's today, once `month` is the
    first of a month up to the current one."""
    today = await _today(session, tenant)
    if month is None:
        return today.replace(day=1), today
    if month.day != 1:
        raise unprocessable("not_a_month", "month is the first day of a month")
    if month > today.replace(day=1):
        raise unprocessable("future", "nothing is recorded for a later month")
    return month, today


@router.get("")
async def recurring_expenses(session: ExpensesReadSession) -> list[Recurring]:
    """The gym's gastos fijos: the active ones by their day of the month, then the
    paused."""
    rows = await session.execute(ALL)
    return [Recurring.model_validate(row._asdict()) for row in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_recurring(body: RecurringIn, session: ExpensesSession) -> Recurring:
    """A new gasto fijo, under a live category; a 409 past `MAX_RECURRING`."""
    await _live_category(session, body.category_id)
    # Every template locked, then counted, so two adds at once cannot both pass the cap.
    await session.execute(text("SELECT id FROM expense_recurring FOR UPDATE"))
    count = await session.scalar(text("SELECT count(*) FROM expense_recurring"))
    if (count or 0) >= MAX_RECURRING:
        raise TOO_MANY
    recurring_id = await session.scalar(INSERT, body.model_dump())
    return await _one(session, recurring_id)


# What an edit may change, as the columns hold them.
EDITABLE = ("category_id", "payee", "method", "amount_clp", "amount_kind", "day_of_month", "active")


@router.patch("/{recurring_id}")
async def change_recurring(
    recurring_id: uuid.UUID, body: RecurringChange, session: ExpensesSession
) -> Recurring:
    """Edit a gasto fijo, or pause it (`active: false`) and resume it. The expenses
    already recorded from it keep what they were recorded with."""
    row = (await session.execute(LOCK, {"id": recurring_id})).one_or_none()
    if row is None:
        raise NO_RECURRING
    sent = body.model_fields_set
    changed = {
        field: getattr(body, field)
        for field in EDITABLE
        if field in sent and getattr(row, field) != getattr(body, field)
    }
    if not changed:
        return await _one(session, recurring_id)
    if "category_id" in changed:
        await _live_category(session, changed["category_id"])
    assignments = ", ".join(f"{f} = :{f}" for f in changed)
    await session.execute(
        text(f"UPDATE expense_recurring SET {assignments}, updated_at = now() WHERE id = :id"),
        {**changed, "id": recurring_id},
    )
    return await _one(session, recurring_id)


@router.get("/month")
async def recurring_month(
    tenant: Acting,
    session: ExpensesReadSession,
    month: Annotated[date | None, Query()] = None,
) -> RecurringMonth:
    """Gastos fijos por registrar in `month` (the current one by default): `due`, the
    active templates with no expense from them that counts in it, and `skipped`, those
    of them the gym said it will not pay this month. Reading it records nothing."""
    shown, today = await _shown_month(session, tenant, month)
    rows = await session.execute(
        MONTH,
        {
            "month": shown,
            "end": add_months(shown, 1),
            "tz": await session.scalar(TIMEZONE, {"id": tenant.gym_id}),
        },
    )
    due: list[DueRecurring] = []
    skipped: list[DueRecurring] = []
    for row in rows:
        fields: dict[str, Any] = row._asdict()
        was_skipped = fields.pop("skipped")
        item = DueRecurring.model_validate(
            {**fields, "due_on": due_on(shown, row.day_of_month, today)}
        )
        (skipped if was_skipped else due).append(item)
    return RecurringMonth(
        month=shown, current_month=today.replace(day=1), today=today, due=due, skipped=skipped
    )


@router.post("/record", status_code=status.HTTP_201_CREATED)
async def record_recurring(
    body: RecordRecurring, tenant: Acting, session: ExpensesSession
) -> list[Expense]:
    """Registrar, and Registrar los fijos: each fixed template named, at its amount, in
    `month`, dated `due_on`. One that has an expense counting in the month already is
    passed over, so the answer lists only what this request recorded. An estimated or
    paused template, or one under an archived category, is refused (422): the first is
    typed through the form at the bill's figure, the others are not on the card."""
    month, today = await _shown_month(session, tenant, body.month)
    ids = list(dict.fromkeys(body.ids))
    templates = {}
    for recurring_id in ids:
        row = (await session.execute(LOCK, {"id": recurring_id})).one_or_none()
        if row is None:
            raise unprocessable("no_recurring", "no such gasto fijo in this gym")
        if row.amount_kind != AmountKind.FIXED:
            raise unprocessable("estimated", "an estimated gasto fijo is recorded through the form")
        if not row.active:
            raise unprocessable("paused", "the gasto fijo is paused")
        await _live_category(session, row.category_id)
        templates[recurring_id] = row
    recorded: list[Expense] = []
    for recurring_id, row in templates.items():
        expense_id = await session.scalar(
            RECORD, {"id": recurring_id, "spent_on": due_on(month, row.day_of_month, today)}
        )
        if expense_id is not None:
            recorded.append(await _read(session, expense_id))
    return recorded


@router.post("/{recurring_id}/skip", status_code=status.HTTP_204_NO_CONTENT)
async def skip_recurring(
    recurring_id: uuid.UUID, body: SkipRecurring, tenant: Acting, session: ExpensesSession
) -> None:
    """No este mes: the template leaves `month`'s card until it is taken back, and is
    on the next month's. Skipping one twice is the same as once."""
    month, _ = await _shown_month(session, tenant, body.month)
    if (await session.execute(LOCK, {"id": recurring_id})).one_or_none() is None:
        raise NO_RECURRING
    await session.execute(SKIP, {"id": recurring_id, "month": month})


@router.delete("/{recurring_id}/skip/{month}", status_code=status.HTTP_204_NO_CONTENT)
async def unskip_recurring(recurring_id: uuid.UUID, month: date, session: ExpensesSession) -> None:
    """Take back a No este mes: the template is on `month`'s card again."""
    if (await session.execute(LOCK, {"id": recurring_id})).one_or_none() is None:
        raise NO_RECURRING
    await session.execute(UNSKIP, {"id": recurring_id, "month": month})
