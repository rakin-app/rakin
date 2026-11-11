import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** Which message a reminder is: on the due date, while overdue, or after a rejected proof. */
export type ReminderKind = 'payment_due_today' | 'payment_overdue' | 'proof_rejected_followup'

/** A period due by today, or whose proof was rejected, not paid and with no proof waiting (backend `PaymentReminder`). */
export type PaymentReminder = {
  billing_period_id: string
  membership_id: string
  person_id: string
  person_name: string
  plan_name: string
  period_start: string
  due_date: string
  outstanding_clp: number
  // 0 on the due date; negative for a rejected proof sent early.
  days_overdue: number
  kind: ReminderKind
  rejection_note: string | null
  // Whom it goes to: the guardian, for a dependent.
  contact_name: string
  // The wa.me link with the reminder prefilled; null with WhatsApp off or no phone.
  whatsapp_url: string | null
  // Reminders about the period opened so far, and the last one.
  reminders_sent: number
  reminded_at: string | null
  // The gym's cadence says to send the next one now.
  reminder_due: boolean
}

/** Every period to remind about, longest overdue first; with `personId`, only theirs. Owner and admin only. */
export function remindersQuery(personId?: string) {
  return queryOptions({
    queryKey: personId ? ['ledger', 'reminders', personId] : ['ledger', 'reminders'],
    queryFn: () =>
      apiFetch<PaymentReminder[]>(
        personId ? `/api/reminders?person_id=${encodeURIComponent(personId)}` : '/api/reminders',
      ),
  })
}

/** Records in `message_log` that the reminder about the period was opened. */
export function logReminder(billingPeriodId: string) {
  return apiFetch<{ message_id: string; sent_at: string; kind: ReminderKind; ordinal: number }>(
    `/api/reminders/${encodeURIComponent(billingPeriodId)}`,
    { method: 'POST' },
  )
}

/** "1.er", "2.º", "3.er", "4.º": the Spanish ordinal abbreviation. */
export function ordinal(n: number): string {
  return n === 1 || n === 3 ? `${n}.er` : `${n}.º`
}
