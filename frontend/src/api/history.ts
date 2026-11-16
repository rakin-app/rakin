import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

// "Historial de pagos" (#295): what a student paid before Rakin, kept beside billing and
// never in it. Owner and admin only.

export type HistoryMethod = 'cash' | 'transfer' | 'other'

export type HistoryPayment = {
  id: string
  paid_on: string
  amount_clp: number
  method: HistoryMethod | null
  // The month it paid for, as its first day; null when not known.
  covers_month: string | null
  plan_name: string | null
  note: string | null
  source: 'manual' | 'import'
  // The file an import read (#297); null when typed.
  import_name: string | null
  created_by_name: string | null
  created_at: string
}

/** A year, collapsed to its count and total: the year of the month each paid for. */
export type HistoryYear = { year: number; count: number; total_clp: number; payments: HistoryPayment[] }

/** By year, newest first. `plan_from` is their first plan's start: a month on or after it
 * is the plan's, for "Pagado hasta" (#286), never history. */
export type HistoryPayments = { plan_from: string | null; years: HistoryYear[] }

export type HistoryPaymentIn = {
  paid_on: string
  amount_clp: number
  method: HistoryMethod | null
  covers_month: string | null
  plan_name: string | null
}

const paymentsPath = (personId: string) => `/api/people/${encodeURIComponent(personId)}/history/payments`

export function historyPaymentsQuery(personId: string) {
  return queryOptions({
    queryKey: ['ledger', 'history', personId],
    queryFn: () => apiFetch<HistoryPayments>(paymentsPath(personId)),
  })
}

/** "Pagos anteriores": every month of the form, saved together or not at all. */
export function addHistoryPayments(personId: string, payments: HistoryPaymentIn[]): Promise<HistoryPayments> {
  return apiFetch<HistoryPayments>(paymentsPath(personId), { method: 'POST', body: JSON.stringify({ payments }) })
}

/** Eliminar, for a typo, with the reason the audit row keeps. */
export function removeHistoryPayment(personId: string, paymentId: string, reason: string): Promise<HistoryPayments> {
  return apiFetch<HistoryPayments>(`${paymentsPath(personId)}/${encodeURIComponent(paymentId)}/remove`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

/** Their first plan's start, when the API refused months it covers (`covers_plan`). */
export function coversPlan(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null
  const detail = (error.body as { detail?: { code?: unknown; plan_from?: unknown } } | undefined)?.detail
  return detail?.code === 'covers_plan' && typeof detail.plan_from === 'string' ? detail.plan_from : null
}
