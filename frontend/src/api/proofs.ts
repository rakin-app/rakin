import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

/** A billing period the signed-in person can pay: theirs or a dependent's. */
export type OpenPeriod = {
  id: string
  membership_id: string
  person_id: string
  person_name: string
  plan_name: string
  period_start: string
  period_end: string
  due_date: string
  amount_due_clp: number
  paid_clp: number
  outstanding_clp: number
  pending_clp: number
}

type ProofUpload = {
  key: string
  url: string
  headers: Record<string, string>
  expires_in_seconds: number
}

// What the API takes (backend `ALLOWED_CONTENT_TYPES`, `MAX_UPLOAD_BYTES`); checked here
// first so a wrong file is refused before anything is sent.
export const PROOF_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'application/pdf'] as const
export const MAX_PROOF_BYTES = 10 * 1024 * 1024

export type ProofType = (typeof PROOF_TYPES)[number]

// Some pickers leave `file.type` empty for a type the browser has no name for: a
// desktop Chrome picking an iPhone's `.heic` is the common one. The extension decides
// then, still within `PROOF_TYPES`.
const BY_EXTENSION: Record<string, ProofType> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heic',
  pdf: 'application/pdf',
}

/** The proof type to upload `file` as, or null if it is not one. */
export function proofContentType(file: File): ProofType | null {
  if (file.type) return (PROOF_TYPES as readonly string[]).includes(file.type) ? (file.type as ProofType) : null
  const extension = /\.([^.]+)$/.exec(file.name)?.[1]?.toLowerCase()
  return (extension && BY_EXTENSION[extension]) || null
}

export type ProofProblem = 'type' | 'size' | 'empty'

export function proofProblem(file: File): ProofProblem | null {
  if (file.size === 0) return 'empty'
  if (proofContentType(file) === null) return 'type'
  if (file.size > MAX_PROOF_BYTES) return 'size'
  return null
}

export function openPeriodsQuery() {
  return queryOptions({
    queryKey: ['me', 'periods'],
    queryFn: () => apiFetch<OpenPeriod[]>('/api/me/periods'),
  })
}

/** Proofs waiting for review: the admin's badge. A coach is refused, and sees none. */
export function pendingCountQuery() {
  return queryOptions({
    queryKey: ['ledger', 'pending'],
    queryFn: () => apiFetch<{ count: number }>('/api/ledger/pending'),
    select: (data) => data.count,
    refetchInterval: 60_000,
  })
}

/** The storage refused the file, so nothing was claimed. */
export class UploadFailed extends Error {
  constructor(readonly status: number) {
    super(`proof upload failed with status ${status}`)
    this.name = 'UploadFailed'
  }
}

/**
 * Upload `file` and claim the payment it proves. The file goes straight to
 * storage on the presigned URL, never through the API; only then is the
 * pending payment recorded against its key.
 */
export async function submitProof(file: File, periodId: string, amountClp: number): Promise<void> {
  const contentType = proofContentType(file)
  if (contentType === null) throw new Error(`not a proof type: ${file.name}`)
  const upload = await apiFetch<ProofUpload>('/api/me/proofs', {
    method: 'POST',
    body: JSON.stringify({ content_type: contentType, size_bytes: file.size }),
  })
  // Not `apiFetch`: the URL may be the storage's own origin. The browser sends
  // the file's size as Content-Length, which the signature covers.
  const put = await fetch(upload.url, { method: 'PUT', headers: upload.headers, body: file })
  if (!put.ok) throw new UploadFailed(put.status)
  await apiFetch('/api/me/payments', {
    method: 'POST',
    body: JSON.stringify({ billing_period_id: periodId, amount_clp: amountClp, proof_key: upload.key }),
  })
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409
}
