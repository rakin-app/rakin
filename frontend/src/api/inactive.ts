import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** Someone with a trial or Active membership and no class for 14 days or more (backend `InactiveMember`). */
export type InactiveMember = {
  person_id: string
  name: string
  // Their last class; null if they have not come to one yet.
  last_attended_on: string | null
  // Since `last_attended_on`, or since they joined if null.
  days_absent: number
  // 14 to 29 days away, or 30 and more.
  bucket: 14 | 30
  payment_status: 'up_to_date' | 'overdue' | 'trial'
  overdue_clp: number
  // Whom the nudge goes to: the guardian, for a dependent.
  contact_name: string
  // The wa.me link with the nudge prefilled; null with WhatsApp off or no phone.
  whatsapp_url: string | null
  // When a nudge about them was last opened.
  nudged_at: string | null
}

/** Everyone away 14 days or more, nearest the line first. Owner and admin only: it says who owes. */
export function inactiveQuery() {
  return queryOptions({
    queryKey: ['ledger', 'inactive'],
    queryFn: () => apiFetch<InactiveMember[]>('/api/inactive'),
  })
}

/** Records in `message_log` that the nudge to `personId` (or their guardian) was opened. */
export function logNudge(personId: string) {
  return apiFetch<{ message_id: string; sent_at: string }>(`/api/inactive/${personId}/nudge`, { method: 'POST' })
}
