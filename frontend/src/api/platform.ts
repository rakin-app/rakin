import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch, isReauth } from './client'
import type { SignedIn } from './auth'
import type { TermsState } from './terms'

/**
 * The platform's panel (#436), at `/plataforma` on the base host: the people who run
 * the gyms Rakin hosts. Its own sign-in and session (`__Host-platform`), apart from any
 * gym's: a gym's session never reaches it, and the API answers 404 on a gym's host.
 */
export const PLATFORM_PATH = '/plataforma'
export const PLATFORM_SIGN_IN_PATH = '/plataforma/ingresar'

/** Who is signed in to the panel, and until when they need no new code (ticket C). */
export type PlatformMe = { email: string; name: string; fresh_until: string }

/** A gym as the panel lists it (backend `PlatformGym`): counts and dates only. */
export type PlatformGym = {
  id: string
  slug: string
  name: string
  // Where it is served: `https://<slug>.rakin.app`.
  address: string
  timezone: string
  created_at: string
  titular_name: string | null
  titular_email: string | null
  // The Términos de encargo in force, the latest accepted, and when (#499).
  terms_version: string | null
  terms_accepted_at: string | null
  // `pending`: never accepted any, and takes no data; `outdated`: earlier versions.
  terms_state: TermsState
  members: number
  staff: number
  last_activity: string | null
  // Suspended from the panel (#439): nobody signs in there, and its jobs do not run.
  status: 'active' | 'suspended'
  // Whether the latest sign-in link to its titular did not go: the list offers it again.
  owner_link_failed: boolean
  // Since when it is suspended; `null` for an active gym.
  suspended_at: string | null
}

export const platformMeQuery = () =>
  queryOptions({
    queryKey: ['platform', 'me'],
    queryFn: () => apiFetch<PlatformMe>('/api/platform/me'),
  })

export const platformGymsQuery = () =>
  queryOptions({
    queryKey: ['platform', 'gyms'],
    queryFn: () => apiFetch<PlatformGym[]>('/api/platform/gyms'),
  })

/** Emails an operator a link and a code. 202 whether or not the address is an operator's. */
export function requestPlatformLink(email: string): Promise<void> {
  return apiFetch<void>('/api/platform/auth/link', { method: 'POST', body: JSON.stringify({ email }) })
}

/** Signs in with the code; a wrong, spent or expired one is a 400. */
export function redeemPlatformCode(email: string, code: string): Promise<SignedIn> {
  return apiFetch<SignedIn>('/api/platform/auth/code', { method: 'POST', body: JSON.stringify({ email, code }) })
}

export function platformLogout(): Promise<void> {
  return apiFetch<void>('/api/platform/auth/logout', { method: 'POST' })
}

export const PLATFORM_NEW_GYM_PATH = '/plataforma/nuevo'

/** Why a slug cannot be a new gym's (#437): not a host label, kept for Rakin, or a gym's. */
export type SlugProblem = 'format' | 'reserved' | 'taken'

/** What a slug would be: where the gym would be served, and why it cannot, if so. */
export type SlugCheck = { address: string; problem: SlugProblem | null }

/** What the new-gym form offers: grading presets and time zones. */
export type NewGymChoices = {
  grading: { key: string; label: string }[]
  timezones: string[]
}

/** A new gym as the panel creates it (backend `PanelNewGym`), pending its terms, which
 * its titular accepts in the app (#499). */
export type NewGym = {
  slug: string
  name: string
  timezone: string
  owner_email: string
  owner_name: string
  owner_rut: string | null
  owner_phone: string | null
  grading: string
}

export type CreatedGym = { id: string; slug: string; address: string }

export const slugCheckQuery = (slug: string) =>
  queryOptions({
    queryKey: ['platform', 'slug', slug],
    queryFn: () => apiFetch<SlugCheck>(`/api/platform/slug?slug=${encodeURIComponent(slug)}`),
  })

export const newGymChoicesQuery = () =>
  queryOptions({
    queryKey: ['platform', 'presets'],
    queryFn: () => apiFetch<NewGymChoices>('/api/platform/presets'),
    staleTime: Infinity,
  })

/** Creates the gym; a 422 names each field refused, the slug `slug_taken` when a gym has it. */
export function createGym(gym: NewGym): Promise<CreatedGym> {
  return apiFetch<CreatedGym>('/api/platform/gyms', { method: 'POST', body: JSON.stringify(gym) })
}

/** Emails the gym's titular again: the invitation to accept the terms while the gym has
 * not accepted the current ones (`invite`), else a sign-in link; `sent` false if it did not go. */
export function resendOwnerLink(gymId: string): Promise<{ sent: boolean; invite: boolean }> {
  return apiFetch<{ sent: boolean; invite: boolean }>(`/api/platform/gyms/${encodeURIComponent(gymId)}/owner-link`, {
    method: 'POST',
  })
}

/** One acceptance of the terms (#499): in the app, by whom, or signed outside it. */
export type TermsSignature = {
  accepted_at: string
  channel: 'in_app' | 'outside'
  // `null` for a signature from before #499, of the Términos de encargo alone.
  service_version: string | null
  processor_version: string
  accepted_by_name: string | null
  signed_on: string | null
}

/** Where one gym is edited (#438): `/plataforma/<gym id>`. */
export const PLATFORM_GYM_PATH = '/plataforma/$gymId'

/** A gym as its edit screen shows it (backend `PlatformGymDetail`). */
export type PlatformGymDetail = {
  id: string
  slug: string
  name: string
  address: string
  titular_name: string | null
  titular_email: string | null
  titular_phone: string | null
  // Once the titular signed in there, their email changes only through a handover (#321).
  titular_signed_in: boolean
  // Every acceptance, the latest first, the versions current today and the state.
  terms: TermsSignature[]
  terms_version: string
  service_terms_version: string
  terms_state: TermsState
  // Exempt from the terms (0081): an instance the company does not host, current with
  // no acceptance at all (#559).
  terms_exempt: boolean
  // The slugs it had that still redirect to it, and until when.
  aliases: { slug: string; address: string; until: string }[]
  // Since when it is suspended (#439), and why; both `null` for an active gym.
  suspended_at: string | null
  suspended_reason: string | null
  // For a suspended gym, the dates its removal keeps, or one started today would;
  // `null` for an active gym.
  removal: RemovalDates | null
}

/**
 * The end of service of the Términos de encargo, clause 14 (backend `app.platform.removal`):
 * the days each step takes, and the dates of the removal started on `started_on`, or of one
 * started today while `started_on` is `null`.
 */
export type RemovalDates = {
  export_days: number
  deletion_days: number
  backup_days: number
  started_on: string | null
  // The day the gym asked in writing for its deletion before its window ended.
  early_deletion_on: string | null
  export_until: string
  // The first day its rows and files may be deleted, on the host's shell.
  deletion_from: string
  deleted_by: string
  backups_gone_by: string
}

/** What changes; a field left out stays as it is. */
export type GymEdit = {
  name?: string
  owner_name?: string
  owner_phone?: string
  owner_email?: string
}

export type Renamed = { slug: string; address: string; old_slug: string; until: string | null }

export const platformGymQuery = (gymId: string) =>
  queryOptions({
    queryKey: ['platform', 'gyms', gymId],
    queryFn: () => apiFetch<PlatformGymDetail>(`/api/platform/gyms/${encodeURIComponent(gymId)}`),
  })

/** A slug's check for a gym's rename: one it had itself is not taken. */
export const renameCheckQuery = (gymId: string, slug: string) =>
  queryOptions({
    queryKey: ['platform', 'slug', slug, gymId],
    queryFn: () =>
      apiFetch<SlugCheck>(
        `/api/platform/slug?slug=${encodeURIComponent(slug)}&gym=${encodeURIComponent(gymId)}`,
      ),
  })

/**
 * Changes the gym's name and its titular's contact; the fields that changed. A new email
 * after the titular's first sign-in is a 409 `titular_handover` (`isHandover`).
 */
export function editGym(gymId: string, edit: GymEdit): Promise<{ fields: string[] }> {
  return apiFetch<{ fields: string[] }>(`/api/platform/gyms/${encodeURIComponent(gymId)}`, {
    method: 'PATCH',
    body: JSON.stringify(edit),
  })
}

/** Records an acceptance of the current terms signed outside the app; `recorded` false if
 * those versions were signed already. */
export function recordTerms(gymId: string, signedOn: string): Promise<{ recorded: boolean }> {
  return apiFetch<{ recorded: boolean }>(`/api/platform/gyms/${encodeURIComponent(gymId)}/terms`, {
    method: 'POST',
    body: JSON.stringify({ signed_on: signedOn }),
  })
}

/** Gives the gym a new slug; a session not proved recently is a 401 `reauth` (`needsReauth`). */
export function renameGym(gymId: string, slug: string): Promise<Renamed> {
  return apiFetch<Renamed>(`/api/platform/gyms/${encodeURIComponent(gymId)}/slug`, {
    method: 'POST',
    body: JSON.stringify({ slug }),
  })
}

/**
 * Suspends the gym (#439); `changed` false if it was already. A session not proved recently
 * is a 401 `reauth` (`needsReauth`).
 */
export function suspendGym(gymId: string, reason: string): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>(`/api/platform/gyms/${encodeURIComponent(gymId)}/suspend`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

/** Resumes the gym; `changed` false if it was active. A stale session is a 401 `reauth`. */
export function resumeGym(gymId: string): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>(`/api/platform/gyms/${encodeURIComponent(gymId)}/resume`, {
    method: 'POST',
  })
}

const removalPath = (gymId: string) => `/api/platform/gyms/${encodeURIComponent(gymId)}/removal`

/**
 * Starts the suspended gym's removal (#377), its slug typed again; nothing is deleted yet.
 * A 409 `not_suspended` or `slug_mismatch` refuses it; a stale session is a 401 `reauth`.
 */
export function startRemoval(gymId: string, slug: string): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>(removalPath(gymId), { method: 'POST', body: JSON.stringify({ slug }) })
}

/** Cancels the gym's removal: it stays suspended. A stale session is a 401 `reauth`. */
export function cancelRemoval(gymId: string): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>(removalPath(gymId), { method: 'DELETE' })
}

/**
 * Records the day the gym asked in writing for its deletion before its window ends; a day
 * to come is a 422 `early_deletion_future`. A stale session is a 401 `reauth`.
 */
export function recordEarlyDeletion(gymId: string, askedOn: string): Promise<{ changed: boolean }> {
  return apiFetch<{ changed: boolean }>(`${removalPath(gymId)}/early`, {
    method: 'POST',
    body: JSON.stringify({ asked_on: askedOn }),
  })
}

/** Emails the signed-in operator a code to prove who they are again. */
export function sendReauthCode(): Promise<void> {
  return apiFetch<void>('/api/platform/reauth/send', { method: 'POST' })
}

/** Spends that code; a wrong, spent or expired one is a 400. */
export function reauth(code: string): Promise<void> {
  return apiFetch<void>('/api/platform/reauth', { method: 'POST', body: JSON.stringify({ code }) })
}

/** Whether an action was refused for want of a recent proof: ask for a code, then retry. */
export function needsReauth(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && isReauth(error.body)
}

/** Whether a new email for the titular was refused: they signed in, so it is a handover. */
export function isHandover(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 409) return false
  const detail = (error.body as { detail?: { code?: unknown } } | undefined)?.detail
  return detail?.code === 'titular_handover'
}
