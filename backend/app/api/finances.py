"""Finanzas (`/api/finances`): money in and money out side by side (#316).

The owner sees the month whole: what came in, what went out and what is left, and the
year month by month (docs/design/expenses-and-officers.md, section 13).

- **Entradas** is Cobrado as Pagos shows it: `v_monthly_income`, net of refunds, each
  payment in the month it was validated in, read by the same query Pagos' KPIs use, so
  the two never disagree. It is split into the plans' and the cobros extra's
  (`extra_income_clp`).
- **Salidas** is the month's expenses that count (not voided), by `spent_on`, by
  category in the gym's order. A voided expense leaves the month.
- **Resultado** is Entradas less Salidas.

`GET` answers a month, `GET /year` the twelve months of a year, with each category's
months, so a category opens to them. Reading needs `expenses_read` ("Ver gastos"):
whoever holds it and not `money_read` sees Salidas only, and the answer carries no
income figure at all, not even a zero. Nothing here is written.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.dates import add_months, gym_today
from app.permissions import ExpensesReadSession, SeesMoney
from app.schemas.finances import (
    CategoryAmount,
    CategoryYear,
    FinanceMonth,
    FinanceYear,
    Income,
    MonthFigures,
)
from app.tenancy import Tenant, current_tenant

router = APIRouter(prefix="/api/finances", tags=["finances"])

Acting = Annotated[Tenant, Depends(current_tenant)]

TIMEZONE = text("SELECT timezone FROM gym WHERE id = :id")

# Cobrado and its cobros extra per month, as `app.api.ledger.BOOK_KPIS` sums them.
INCOME = text(
    """
    SELECT month, coalesce(sum(income_clp), 0)::bigint AS income_clp,
           coalesce(sum(extra_income_clp), 0)::bigint AS extra_clp
    FROM v_monthly_income
    WHERE month >= :start AND month < :end
    GROUP BY month
    """
)

# The expenses that count, per category and month, in the gym's order of categories.
EXPENSES = text(
    """
    SELECT c.id AS category_id, c.name, c.sort,
           date_trunc('month', e.spent_on)::date AS month,
           sum(e.amount_clp)::bigint AS amount_clp, count(*) AS count
    FROM expense e
    JOIN expense_category c ON c.id = e.category_id
    WHERE e.voided_at IS NULL AND e.spent_on >= :start AND e.spent_on < :end
    GROUP BY c.id, c.name, c.sort, month
    ORDER BY c.sort, c.name, c.id, month
    """
)


def unprocessable(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": code, "message": message})


async def _current_month(session: AsyncSession, tenant: Tenant) -> date:
    return gym_today(await session.scalar(TIMEZONE, {"id": tenant.gym_id})).replace(day=1)


async def _income(session: AsyncSession, start: date, end: date) -> dict[date, Any]:
    return {row.month: row for row in await session.execute(INCOME, {"start": start, "end": end})}


async def _expenses(session: AsyncSession, start: date, end: date) -> list[Any]:
    return list(await session.execute(EXPENSES, {"start": start, "end": end}))


@router.get("")
async def finance_month(
    tenant: Acting,
    session: ExpensesReadSession,
    sees_money: SeesMoney,
    month: Annotated[date | None, Query()] = None,
) -> FinanceMonth:
    """A month (the current one by default): Entradas, Salidas by category, Resultado.
    Without `money_read`, Salidas only."""
    current = await _current_month(session, tenant)
    shown = current if month is None else month
    if shown.day != 1:
        raise unprocessable("not_a_month", "month is the first day of a month")
    if shown > current:
        raise unprocessable("future", "Finanzas goes no later than the current month")
    end = add_months(shown, 1)

    categories = [
        CategoryAmount(
            category_id=row.category_id, name=row.name, amount_clp=row.amount_clp, count=row.count
        )
        for row in await _expenses(session, shown, end)
    ]
    expenses_clp = sum(c.amount_clp for c in categories)
    income = None
    if sees_money:
        row = (await _income(session, shown, end)).get(shown)
        total, extra = (0, 0) if row is None else (row.income_clp, row.extra_clp)
        income = Income(total_clp=total, plans_clp=total - extra, extra_clp=extra)
    return FinanceMonth(
        month=shown,
        current_month=current,
        income=income,
        expenses_clp=expenses_clp,
        result_clp=None if income is None else income.total_clp - expenses_clp,
        categories=categories,
    )


@router.get("/year")
async def finance_year(
    tenant: Acting,
    session: ExpensesReadSession,
    sees_money: SeesMoney,
    year: Annotated[int | None, Query(ge=2000, le=9999)] = None,
) -> FinanceYear:
    """A year (the current one by default), month by month, with its totals and each
    category's months. Without `money_read`, Salidas only."""
    current = await _current_month(session, tenant)
    shown = current.year if year is None else year
    if shown > current.year:
        raise unprocessable("future", "Finanzas goes no later than the current year")
    start = date(shown, 1, 1)
    months = [add_months(start, i) for i in range(12)]
    end = add_months(start, 12)

    spent: dict[date, int] = dict.fromkeys(months, 0)
    by_category: dict[Any, CategoryYear] = {}
    for row in await _expenses(session, start, end):
        spent[row.month] += row.amount_clp
        found = by_category.setdefault(
            row.category_id,
            CategoryYear(category_id=row.category_id, name=row.name, amount_clp=0, months=[0] * 12),
        )
        found.amount_clp += row.amount_clp
        found.months[row.month.month - 1] += row.amount_clp

    income = await _income(session, start, end) if sees_money else {}

    def figures(month: date) -> MonthFigures:
        came_in = None
        if sees_money:
            row = income.get(month)
            came_in = 0 if row is None else int(row.income_clp)
        return MonthFigures(
            month=month,
            income_clp=came_in,
            expenses_clp=spent[month],
            result_clp=None if came_in is None else came_in - spent[month],
        )

    rows = [figures(m) for m in months]
    expenses_clp = sum(spent.values())
    income_clp = sum(r.income_clp or 0 for r in rows) if sees_money else None
    return FinanceYear(
        year=shown,
        current_month=current,
        months=rows,
        income_clp=income_clp,
        expenses_clp=expenses_clp,
        result_clp=None if income_clp is None else income_clp - expenses_clp,
        categories=list(by_category.values()),
    )
