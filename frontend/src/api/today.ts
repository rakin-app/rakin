import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { MembershipStatus } from './people'

/** A period past due and not paid in full, of a membership in any status (backend `OverduePeriod`). */
export type OverduePeriod = {
  billing_period_id: string
  membership_id: string
  person_id: string
  person_name: string
  plan_name: string
  // A lapsed or cancelled plan still owes what it owed (#207).
  membership_status: MembershipStatus
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
