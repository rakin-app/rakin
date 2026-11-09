import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** A period of an Active membership past due and not paid in full (backend `OverduePeriod`). */
export type OverduePeriod = {
  billing_period_id: string
  membership_id: string
  person_id: string
  person_name: string
  plan_name: string
  period_start: string
  due_date: string
  outstanding_clp: number
  // At least 1.
  days_overdue: number
}

/** The gym's overdue periods (backend `Overdue`). Owner and admin only. */
export type Overdue = {
  total_clp: number
  // Longest overdue first.
  periods: OverduePeriod[]
}

export function overdueQuery() {
  return queryOptions({ queryKey: ['ledger', 'overdue'], queryFn: () => apiFetch<Overdue>('/api/ledger/overdue') })
}
