import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
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
