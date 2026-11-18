import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch, isReauth } from './client'
import type { SignedIn } from './auth'

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
  // The Términos de encargo in force, and whether they are the current version.
  terms_version: string | null
  terms_signed_on: string | null
  terms_current: boolean
  members: number
  staff: number
  last_activity: string | null
  status: 'active'
  // Whether the latest sign-in link to its titular did not go: the list offers it again.
  owner_link_failed: boolean
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

/** What the new-gym form offers: grading presets, the terms' current version, time zones. */
export type NewGymChoices = {
  grading: { key: string; label: string }[]
  terms_version: string
  timezones: string[]
}

/** A new gym as the panel creates it (backend `PanelNewGym`): the terms are required. */
export type NewGym = {
  slug: string
  name: string
  timezone: string
  owner_email: string
  owner_name: string
  owner_rut: string | null
  owner_phone: string | null
  grading: string
  processor_terms: string
  signed_on: string | null
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

/** Emails the gym's titular a sign-in link on its host again; `sent` false if it did not go. */
export function resendOwnerLink(gymId: string): Promise<{ sent: boolean }> {
  return apiFetch<{ sent: boolean }>(`/api/platform/gyms/${encodeURIComponent(gymId)}/owner-link`, {
    method: 'POST',
  })
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
  // Every signature of the Términos de encargo, the latest first.
  terms: { version: string; signed_on: string }[]
  terms_version: string
  // The slugs it had that still redirect to it, and until when.
  aliases: { slug: string; address: string; until: string }[]
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

/** Records a signature of the current terms; `recorded` false if that version was signed. */
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
