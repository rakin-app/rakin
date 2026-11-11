import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Category } from './extraCharges'

/** A pending proof, with what the admin needs to decide on it (backend `ProofReview`). */
export type ProofReview = {
  id: string
  // Null, with the plan, `period` and history, on a cobro extra's proof (#195).
  membership_id: string | null
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
  plan_name: string | null
  plan_kind: string | null
  anchor_day: number | null
  period: {
    id: string
    period_start: string
    period_end: string
    due_date: string
    amount_due_clp: number
    paid_clp: number
    outstanding_clp: number
  } | null
  // The cobro extra line it pays instead (#195).
  extra_line?: {
    id: string
    extra_charge_id: string
    title: string
    category: Category
    due_date: string
    amount_due_clp: number
    paid_clp: number
    outstanding_clp: number
  } | null
  // What the membership still owes on its other periods already due.
  prior_balance_clp: number
  // Newest first, at most three.
  last_payments: { amount_clp: number; paid_at: string }[]
  // Classes the person attended in the last 30 days: today and the 29 before it.
  attendance_30d: number
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

/** What the proof's period, or its cobro line, still owes. */
export function owed(review: ProofReview): number {
  return review.period?.outstanding_clp ?? review.extra_line?.outstanding_clp ?? 0
}

export function amountMatch(review: ProofReview): AmountMatch {
  const difference = review.amount_clp - owed(review)
  if (difference === 0) return { kind: 'matches' }
  return difference > 0 ? { kind: 'over', difference } : { kind: 'short', difference: -difference }
}

export function isImage(review: ProofReview): boolean {
  return review.proof_content_type?.startsWith('image/') ?? false
}
