import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

/**
 * The terms a gym accepts in the app (#499, backend `app.api.terms`): the Términos de
 * servicio and the Términos de encargo. Until the gym accepts the current versions,
 * its titular sees only the acceptance page (`TermsAcceptance`); while it has never
 * accepted any, the rest of its team sees `TermsPending`, and its API takes no data.
 */

/** `pending`: never accepted any; `outdated`: an earlier version; `current`: both now. */
export type TermsState = 'pending' | 'outdated' | 'current'

export type TermsKey = 'service' | 'processor'

/** One text as the page shows it: the server's HTML, for this gym. */
export type TermsDocument = {
  key: TermsKey
  title: string
  version: string
  // Built by the server from `docs/legal/`, every value in it escaped. Its blanks are
  // `<span data-blank="<field>">`, which the page fills as the titular types.
  html: string
  // What changed in each version since the gym's last acceptance, the latest first.
  changes: { version: string; html: string }[]
}

export type BreachContact = { name_and_role: string; email: string; phone: string }

/** What the titular fills in (backend `TermsFilled`). */
export type TermsFilled = {
  legal_name: string
  rut: string
  address: string
  representative: string
  breach_contacts: BreachContact[]
}

export type TermsPage = {
  state: TermsState
  gym_name: string
  documents: TermsDocument[]
  prefill: Partial<TermsFilled>
  // Each checkbox's words, `{legal_name}` standing for the razón social.
  declarations: Record<TermsKey, string>
  subprocessors: string[]
}

export type TermsRecord = {
  id: string
  accepted_at: string
  channel: 'in_app' | 'outside'
  service_version: string | null
  processor_version: string
  accepted_by_name: string | null
  signed_on: string | null
  has_copy: boolean
}

export const termsPageQuery = () =>
  queryOptions({
    queryKey: ['terms', 'page'],
    queryFn: () => apiFetch<TermsPage>('/api/terms'),
  })

export const termsRecordsQuery = () =>
  queryOptions({
    queryKey: ['terms', 'acceptances'],
    queryFn: () => apiFetch<TermsRecord[]>('/api/terms/acceptances'),
  })

/** Where one acceptance's copy downloads from: both texts, as accepted. */
export function termsCopyUrl(id: string): string {
  return `/api/terms/acceptances/${encodeURIComponent(id)}/copy`
}

export type Acceptance = {
  service_version: string
  processor_version: string
  filled: TermsFilled
  accept_service: true
  accept_processor: true
}

export function acceptTerms(acceptance: Acceptance): Promise<{ id: string; accepted_at: string }> {
  return apiFetch('/api/terms/accept', { method: 'POST', body: JSON.stringify(acceptance) })
}

/** The code a 409 carries, as the gate and the acceptance answer it. */
export function conflictCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown } } | null)?.detail
  return typeof detail?.code === 'string' ? detail.code : null
}

/** Whether `error` is the gate refusing a write while the terms wait (`app.tenancy`). */
export function isTermsGate(error: unknown): boolean {
  const code = conflictCode(error)
  return code === 'terms_pending' || code === 'terms_outdated'
}

/** The second contact's line as the server writes it, or "ninguno" (`TermsFilled.values`). */
export function contactLine(contact: BreachContact | undefined): string {
  return contact ? `${contact.name_and_role}, ${contact.email}, ${contact.phone}` : 'ninguno'
}
