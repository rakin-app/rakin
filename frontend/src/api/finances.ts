import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

// Finanzas (#316): money in and money out side by side, a month and a year at a time.
// Read with `expenses_read`; every income figure is null without `money_read`
// (backend `app.api.finances`). Keyed under `expenses`, so recording, correcting or
// voiding one refreshes it.

/** Entradas: Cobrado as Pagos shows it, split into plans and cobros extra. */
export type Income = { total_clp: number; plans_clp: number; extra_clp: number }

export type CategoryAmount = { category_id: string; name: string; amount_clp: number; count: number }

export type FinanceMonth = {
  month: string
  current_month: string
  income: Income | null
  expenses_clp: number
  result_clp: number | null
  categories: CategoryAmount[]
}

export type MonthFigures = {
  month: string
  income_clp: number | null
  expenses_clp: number
  result_clp: number | null
}

/** A category's year: its total, and its twelve months, January first. */
export type CategoryYear = { category_id: string; name: string; amount_clp: number; months: number[] }

export type FinanceYear = {
  year: number
  current_month: string
  months: MonthFigures[]
  income_clp: number | null
  expenses_clp: number
  result_clp: number | null
  categories: CategoryYear[]
}

const FINANCES = '/api/finances'

export function financeMonthQuery(month: string | undefined) {
  return queryOptions({
    queryKey: ['expenses', 'finances', 'month', month ?? null],
    queryFn: () => apiFetch<FinanceMonth>(month ? `${FINANCES}?month=${month}` : FINANCES),
  })
}

export function financeYearQuery(year: number | undefined) {
  return queryOptions({
    queryKey: ['expenses', 'finances', 'year', year ?? null],
    queryFn: () => apiFetch<FinanceYear>(year ? `${FINANCES}/year?year=${year}` : `${FINANCES}/year`),
  })
}
