import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'
import type { PersonRef } from './join'
import { TEMPLATE_UPDATED_ON, type PrivacyNotice } from './privacy'

/**
 * The privacy notice as someone read it (backend `NoticeVersion`, #370): the template's
 * date and the gym's details'. One older than the gym's notice is a 409 `stale_notice`.
 */
export type NoticeVersion = { template_on: string; details_on: string }

/** The version of the notice this build shows, with the gym's details of `updatedOn`. */
export function noticeVersion(updatedOn: string): NoticeVersion {
  return { template_on: TEMPLATE_UPDATED_ON, details_on: updatedOn }
}

/** A 409 `stale_notice`: the notice changed since the page was opened. */
export function isStaleNotice(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    (error.body as { detail?: unknown } | undefined)?.detail === 'stale_notice'
  )
}

// An adult's data rest on the membership contract; a minor's on their guardian's consent.
export type Basis = 'contract' | 'guardian_consent'

export type ConsentState = 'given' | 'withdrawn' | 'missing'

/** One act of the register (backend `ConsentEvent`). */
export type ConsentEvent = {
  action: 'notice_accepted' | 'consent_given' | 'consent_withdrawn'
  at: string
  // The person, or their guardian; `null` once they are no longer in the gym.
  by: PersonRef | null
  source: 'join' | 'page'
  template_on: string | null
  details_on: string | null
}

/** What the ficha shows (backend `PersonConsent`). */
export type PersonConsent = {
  basis: Basis
  // `null` when the basis is the contract.
  consent: ConsentState | null
  // Newest first.
  events: ConsentEvent[]
}

/** One of the signed-in guardian's dependents whose data rest on their consent. */
export type DependentConsent = { id: string; name: string; consent: ConsentState; at: string | null }

/** The notice's "last updated" for an act that names a version: the later date. */
export function eventNoticeOn(event: ConsentEvent): string | null {
  if (event.template_on === null || event.details_on === null) return null
  return event.details_on > event.template_on ? event.details_on : event.template_on
}

export function personConsentQuery(personId: string) {
  return queryOptions({
    queryKey: ['people', 'consent', personId],
    queryFn: () => apiFetch<PersonConsent>(`/api/people/${encodeURIComponent(personId)}/consent`),
  })
}

export function myConsentsQuery() {
  return queryOptions({
    queryKey: ['me', 'consents'],
    queryFn: () => apiFetch<DependentConsent[]>('/api/me/consents'),
  })
}

/** The guardian consents for `dependentId`, under the notice as `notice` has it now. */
export function giveConsent(dependentId: string, notice: Pick<PrivacyNotice, 'updated_on'>): Promise<DependentConsent> {
  return apiFetch<DependentConsent>(`/api/me/consents/${encodeURIComponent(dependentId)}`, {
    method: 'POST',
    body: JSON.stringify(noticeVersion(notice.updated_on)),
  })
}

export function withdrawConsent(dependentId: string): Promise<DependentConsent> {
  return apiFetch<DependentConsent>(`/api/me/consents/${encodeURIComponent(dependentId)}`, { method: 'DELETE' })
}
