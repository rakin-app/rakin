import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** Late payments that came after a reminder: how many, and how much. */
export type Paid = { payments: number; amount_clp: number }

/** `GET /api/summary` (backend `MonthSummary`, #505): the gym's month, counts only. */
export type MonthSummary = {
  // Its first day, `2026-11-01`.
  month: string
  // Every month there is one of, newest first.
  months: string[]
  // The gym's first day, when it is in this month.
  since: string | null
  whatsapp: boolean
  // The month's "Cobrado", and the validated payments behind it.
  income_clp: number
  income_payments: number
  // Overdue emails sent, and WhatsApp reminders opened.
  reminder_emails: number
  reminder_whatsapps: number
  after_reminders: {
    total: Paid
    emails_only: Paid
    after_whatsapp: Paid
    // Of the month's income; null with fewer than 5 payments.
    income_percent: number | null
  }
  nudges: { nudged: number; back: number; percent: number | null }
  emails_sent: number
  own_payments: { by_members: number; payments: number; percent: number | null }
  proofs: { reviewed: number; median_minutes: number | null }
  reactivated: number
  trials_converted: number
  // Owed on overdue periods of Active memberships as the month closed; null for the
  // current month and for a closed month that was not kept (#506).
  overdue_clp: number | null
  // How a closed month was kept on the 1st; null when it was counted for this request.
  kept: { computed_at: string; rules_version: number; older_rules: boolean } | null
}

/** The month starting `month` (`2026-11-01`), or the current one. Owner and admin only: it is money. */
export function summaryQuery(month?: string) {
  const query = month ? `?month=${month.slice(0, 7)}` : ''
  return queryOptions({
    queryKey: ['ledger', 'summary', month ?? 'current'],
    queryFn: () => apiFetch<MonthSummary>(`/api/summary${query}`),
  })
}
