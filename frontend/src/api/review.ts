import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** A pending proof, with what the admin needs to decide on it (backend `ProofReview`). */
export type ProofReview = {
  id: string
  membership_id: string
  person_id: string
  person_name: string
  amount_clp: number
  method: 'cash' | 'transfer' | 'other' | null
  claimed_at: string | null
  // The student, or the guardian who sent it for them.
  claimed_by_name: string | null
  // Null when the file is missing from storage.
  proof_url: string | null
  proof_content_type: string | null
  plan_name: string
  plan_kind: string
  anchor_day: number | null
  period: {
    id: string
    period_start: string
    period_end: string
    due_date: string
    amount_due_clp: number
    paid_clp: number
    outstanding_clp: number
  }
  // What the membership still owes on its other periods already due.
  prior_balance_clp: number
  // Newest first, at most three.
  last_payments: { amount_clp: number; paid_at: string }[]
  // Null until attendance is recorded (#44).
  attendance_30d: number | null
}

export type Validated = {
  credit: { amount_clp: number; note: string | null } | null
  period: { outstanding_clp: number; closed: boolean }
}

/** The proofs waiting for review, oldest first. */
export function proofQueueQuery() {
  return queryOptions({
    queryKey: ['ledger', 'proofs'],
    queryFn: () => apiFetch<ProofReview[]>('/api/ledger/proofs'),
  })
}

export function validateProof(id: string): Promise<Validated> {
  return apiFetch<Validated>(`/api/ledger/proofs/${encodeURIComponent(id)}/validate`, { method: 'POST' })
}

export function rejectProof(id: string, note: string): Promise<unknown> {
  return apiFetch(`/api/ledger/proofs/${encodeURIComponent(id)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  })
}

/** How the claimed amount compares with what the period still owes. */
export type AmountMatch = { kind: 'matches' } | { kind: 'over' | 'short'; difference: number }

export function amountMatch(review: ProofReview): AmountMatch {
  const difference = review.amount_clp - review.period.outstanding_clp
  if (difference === 0) return { kind: 'matches' }
  return difference > 0 ? { kind: 'over', difference } : { kind: 'short', difference: -difference }
}

export function isImage(review: ProofReview): boolean {
  return review.proof_content_type?.startsWith('image/') ?? false
}
