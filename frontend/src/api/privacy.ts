import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** What the gym's privacy notice says of it (backend `PrivacyNotice`, #168). */
export type PrivacyNotice = {
  gym: string
  // Where the gym's logo is (`logo.ts`); `null` with none (#223).
  gym_logo: string | null
  // The controller of the members' data: the gym, by its legal name and RUT.
  legal_name: string
  rut: string
  // Where people send requests about their data.
  email: string
  address: string | null
  // The gym's today when it last saved these details.
  updated_on: string
  // Whether the join form checks for humans, a provider the notice names only then.
  human_check: boolean
}

/** The privacy details as Ajustes edits them (backend `Privacy`). */
export type Privacy = Omit<PrivacyNotice, 'gym' | 'gym_logo' | 'updated_on' | 'human_check'>

// The day the notice's text (`t.privacy`) last changed; the notice is as new as this
// or the gym's details, whichever is later. Change it with the text.
export const TEMPLATE_UPDATED_ON = '2026-11-11'

/** The notice's "last updated": its text's date or the gym's details', the later. */
export function lastUpdated(notice: PrivacyNotice): string {
  return notice.updated_on > TEMPLATE_UPDATED_ON ? notice.updated_on : TEMPLATE_UPDATED_ON
}

/**
 * The notice of the gym this host is, else the session's, else the one whose join link
 * `link` is (the join form on the shared host). A 404 is a gym that has not filled in
 * its details, or no gym at all. No session needed.
 */
export function privacyNoticeQuery(link?: string) {
  return queryOptions({
    queryKey: ['privacy', link ?? null],
    queryFn: () => apiFetch<PrivacyNotice>(`/api/privacy${link ? `?link=${encodeURIComponent(link)}` : ''}`),
    retry: false,
  })
}

/** Where the notice is: `/privacidad`, naming the join link when there is one. */
export function privacyPath(link?: string): string {
  return link ? `/privacidad?enlace=${encodeURIComponent(link)}` : '/privacidad'
}
