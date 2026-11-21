"""Finanzas (#316): money in and money out side by side, a month and a year at a time.

Entradas is Pagos' Cobrado (`v_monthly_income`), Salidas the month's expenses that
count, by category, and Resultado the one less the other
(docs/design/expenses-and-officers.md, section 13). Every income figure is `None` for
someone who sees expenses and not payments: the answer carries no income at all.
"""

import uuid
from datetime import date

from pydantic import BaseModel


class Income(BaseModel):
    """A month's Entradas: Cobrado as Pagos shows it, split into the plans' and what the
    cobros extra brought in."""

    total_clp: int
    plans_clp: int
    extra_clp: int


class CategoryAmount(BaseModel):
    """What the month's expenses that count add up to under one category."""

    category_id: uuid.UUID
    name: str
    amount_clp: int
    count: int


class FinanceMonth(BaseModel):
    month: date
    # The gym's current month: Finanzas goes no later.
    current_month: date
    income: Income | None
    expenses_clp: int
    result_clp: int | None
    # Only the categories with an expense that counts this month, in the gym's order.
    categories: list[CategoryAmount]


class MonthFigures(BaseModel):
    """One month of the year. A month after the current one has nothing yet."""

    month: date
    income_clp: int | None
    expenses_clp: int
    result_clp: int | None


class CategoryYear(BaseModel):
    """One category's year: its total, and what it was each month, January first."""

    category_id: uuid.UUID
    name: str
    amount_clp: int
    months: list[int]


class FinanceYear(BaseModel):
    year: int
    current_month: date
    # Twelve, January first.
    months: list[MonthFigures]
    income_clp: int | None
    expenses_clp: int
    result_clp: int | None
    # Only the categories with an expense that counts this year, in the gym's order.
    categories: list[CategoryYear]
