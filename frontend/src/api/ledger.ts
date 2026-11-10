import { infiniteQueryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { FreezeLine, Method, TimelineEntry } from './member'

export const BOOK_FILTERS = ['all', 'pending', 'overdue', 'kids'] as const
/** `all` and `kids` are the month's entries; `pending` and `overdue` how the gym stands today. */
export type BookFilter = (typeof BOOK_FILTERS)[number]

export type PersonRef = { id: string; name: string }

/** An entry's billing period, settled as the member detail settles it. */
export type BookPeriod = {
  period_start: string
  period_end: string
  due_date: string
  outstanding_clp: number
  // 0 on or before the due date, and once paid.
  days_overdue: number
}

/** One ledger entry as the book lists it (backend `BookEntry`). */
export type BookEntry = {
  id: string
  created_at: string
  kind: TimelineEntry['kind']
  status: TimelineEntry['status']
  // Signed on an adjustment: positive in the member's favour, negative owed.
  amount_clp: number
  method: Method | null
  note: string | null
  // The payment a refund gives back; null on every other kind.
  refund_of: string | null
  membership_id: string
  plan_name: string
  person: PersonRef
  // Who pays for them, when they are a dependent.
  guardian: PersonRef | null
  // Null for a credit carried to a later period.
  period: BookPeriod | null
  validated_by_name: string | null
}

/** A freeze line in the book (backend `BookFreeze`): no money, listed among the entries. */
export type BookFreeze = FreezeLine & {
  membership_id: string
  plan_name: string
  person: PersonRef
  guardian: PersonRef | null
}

export type BookKpis = {
  // The month's.
  collected_clp: number
  collected_payments: number
  expected_clp: number
  // Today's, whichever month is shown.
  pending_clp: number
  pending_payments: number
  overdue_clp: number
  overdue_members: number
  overdue_avg_days: number
  active_memberships: number
  frozen_memberships: number
}

/** The gym's ledger for a month (backend `LedgerBook`). Owner and admin only. */
export type LedgerBook = {
  // First days of months, `2026-11-01`.
  month: string
  months: string[]
  timezone: string
  kpis: BookKpis
  items: BookEntry[]
  total: number
  // The month's freeze lines, newest first; none on `pending` and `overdue`. Not paged.
  freezes: BookFreeze[]
}

export const BOOK_PAGE_SIZE = 50

export function bookPath(month: string | undefined, filter: BookFilter, offset: number): string {
  const params = new URLSearchParams()
  if (month) params.set('month', month)
  params.set('filter', filter)
  params.set('limit', String(BOOK_PAGE_SIZE))
  params.set('offset', String(offset))
  return `/api/ledger/book?${params}`
}

// One query per month and filter; "Cargar más" fetches the next page into it.
export function ledgerBookQuery(month: string | undefined, filter: BookFilter) {
  return infiniteQueryOptions({
    queryKey: ['ledger', 'book', { month: month ?? null, filter }],
    queryFn: ({ pageParam }) => apiFetch<LedgerBook>(bookPath(month, filter, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}
