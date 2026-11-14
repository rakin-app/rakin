import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'
import type { Membership } from './member'

/** Why a student asks (backend `FreezeReason`): a short list, with a note for the rest. */
export type FreezeReason = 'lesion' | 'viaje' | 'salud' | 'otro'

export const FREEZE_REASONS: readonly FreezeReason[] = ['lesion', 'viaje', 'salud', 'otro']

export type FreezeRequestStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn'

/** A freeze asked for from /me (#270), and its answer (backend `FreezeRequest`). */
export type FreezeRequest = {
  id: string
  membership_id: string
  // The member whose plan it is, and who asked: themselves, or their guardian.
  person_id: string
  person_name: string
  requested_by: string
  requested_by_name: string
  plan_name: string
  // Its first day, and the day the plan is Active again, as a freeze's.
  from_date: string
  to_date: string
  reason: FreezeReason
  note: string | null
  status: FreezeRequestStatus
  // A rejection's note, written for the member.
  decision_note: string | null
  decided_at: string | null
  created_at: string
}

export type FreezeRequestCreate = {
  membership_id: string
  from_date: string
  to_date: string
  reason: FreezeReason
  note?: string
}

/** Asks for a freeze of their membership, or a dependent's. */
export function requestFreeze(body: FreezeRequestCreate): Promise<FreezeRequest> {
  return apiFetch<FreezeRequest>('/api/me/freeze-requests', { method: 'POST', body: JSON.stringify(body) })
}

/** Withdraws a request still waiting, by whoever made it. */
export function withdrawFreezeRequest(requestId: string): Promise<void> {
  return apiFetch<void>(`/api/me/freeze-requests/${encodeURIComponent(requestId)}`, { method: 'DELETE' })
}

/** Why a request was refused: not Active, a freeze running or booked, or one waiting already. */
export type FreezeRefusal = 'not_active' | 'has_freeze' | 'has_pending'

export function freezeRefusal(error: unknown): FreezeRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'not_active' || code === 'has_freeze' || code === 'has_pending' ? code : null
}

/** The requests waiting for an answer, oldest first: the owner and admins only. */
export const freezeRequestsQuery = queryOptions({
  queryKey: ['freeze-requests'],
  queryFn: () => apiFetch<FreezeRequest[]>('/api/freeze-requests'),
})

/** Freezes the membership as asked, or on the dates given, as "Congelar" would. */
export function approveFreezeRequest(
  requestId: string,
  dates: { from_date?: string; to_date?: string },
): Promise<Membership> {
  return apiFetch<Membership>(`/api/freeze-requests/${encodeURIComponent(requestId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(dates),
  })
}

/** Rejects it, with a note for the member when one is written. */
export function rejectFreezeRequest(requestId: string, note: string): Promise<FreezeRequest> {
  return apiFetch<FreezeRequest>(`/api/freeze-requests/${encodeURIComponent(requestId)}/reject`, {
    method: 'POST',
    body: JSON.stringify(note.trim() ? { note: note.trim() } : {}),
  })
}
