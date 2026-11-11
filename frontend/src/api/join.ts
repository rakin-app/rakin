import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

/** The gym's join link (backend `JoinLink`), owner and admin only (#154). */
export type JoinLink = {
  url: string
  token: string
  program_id: string | null
  program_name: string | null
  // The last day it works, in the gym's timezone.
  expires_on: string | null
  // Past `expires_on`: the form answers as for an invalid link.
  expired: boolean
  created_at: string
}

export type JoinLinkOptions = { program_id?: string | null; expires_on?: string | null }

/** The gym's link; a 404 is a gym with none yet. */
export const joinLinkQuery = queryOptions({
  queryKey: ['join-link'],
  queryFn: () => apiFetch<JoinLink>('/api/join-link'),
  retry: false,
})

/** A 409 on generating a link: the gym's privacy details are not set yet (#168). */
export function isPrivacyIncomplete(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    (error.body as { detail?: unknown } | undefined)?.detail === 'privacy_incomplete'
  )
}

/** A new link with these options; any link the gym had stops working. A gym without its
 * privacy details gets a 409 `privacy_incomplete` (`isPrivacyIncomplete`). */
export function generateJoinLink(options: JoinLinkOptions): Promise<JoinLink> {
  return apiFetch<JoinLink>('/api/join-link', { method: 'POST', body: JSON.stringify(options) })
}

/** Changes what the link says, keeping its token: only the fields sent change. */
export function changeJoinLink(options: JoinLinkOptions): Promise<JoinLink> {
  return apiFetch<JoinLink>('/api/join-link', { method: 'PATCH', body: JSON.stringify(options) })
}

export function revokeJoinLink(): Promise<void> {
  return apiFetch<void>('/api/join-link', { method: 'DELETE' })
}

/** A `wa.me` link that opens WhatsApp with the join link and a short text, for any chat. */
export function whatsappShareUrl(text: string): string {
  return `https://wa.me/?text=${encodeURIComponent(text)}`
}

/** What the public form shows (backend `JoinForm`). */
export type JoinForm = {
  gym: string
  // Where the gym's logo is (`logo.ts`); `null` with none (#223).
  gym_logo: string | null
  program: string | null
  // The gym's today, which says who is a minor.
  today: string
  human_check_site_key: string | null
}

/** The form for `token`; a 404 is a link that no longer works. No session needed. */
export function joinFormQuery(token: string) {
  return queryOptions({
    queryKey: ['join', token],
    queryFn: () => apiFetch<JoinForm>(`/api/join/${encodeURIComponent(token)}`),
    retry: false,
  })
}

export type JoinSubmission = {
  first_name: string
  last_name: string
  // Who they are when they give one; with none, their email is.
  rut: string | null
  // An adult's is required, unless `no_whatsapp`; a minor's guardian's instead.
  phone: string | null
  email: string | null
  dob: string
  guardian_name: string | null
  guardian_phone: string | null
  guardian_email: string | null
  // "No tiene WhatsApp", for the adult, or for a minor's guardian.
  no_whatsapp: boolean
  consent: boolean
  // The honeypot: never shown, so only a script fills it in.
  website: string
  human_check_token: string | null
}

/** Leaves a request for the gym's staff; the answer is the same whoever it is for. */
export function submitJoinRequest(token: string, body: JoinSubmission): Promise<void> {
  return apiFetch<void>(`/api/join/${encodeURIComponent(token)}`, { method: 'POST', body: JSON.stringify(body) })
}

// Under this age on the gym's today, the form asks for a guardian (backend `ADULT_AGE`).
export const ADULT_AGE = 18

/** Whole years from `dob` to `today`, both `YYYY-MM-DD`; `null` while `dob` is not a date. */
export function ageOn(dob: string, today: string): number | null {
  const born = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dob)
  const now = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today)
  if (!born || !now) return null
  const [by, bm, bd] = born.slice(1).map(Number) as [number, number, number]
  const [ny, nm, nd] = now.slice(1).map(Number) as [number, number, number]
  return ny - by - (nm < bm || (nm === bm && nd < bd) ? 1 : 0)
}

export type PersonRef = { id: string; name: string }

/** A request in the queue (backend `JoinRequest`), with whoever here it may already be. */
export type JoinRequest = {
  id: string
  first_name: string
  last_name: string
  rut: string | null
  phone: string | null
  email: string | null
  dob: string
  no_whatsapp: boolean
  guardian: { name: string; phone: string | null; email: string } | null
  program_id: string | null
  program_name: string | null
  created_at: string
  // Someone in this gym with the request's RUT, or, for a request with none, its email.
  rut_in_gym: PersonRef | null
  email_in_gym: PersonRef | null
  // The request's email, when approving leaves it unused: whoever here has the RUT keeps theirs.
  ignored_email: string | null
}

/** A page of the queue, and how many wait in all (backend `JoinRequestPage`). */
export type JoinRequestPage = { items: JoinRequest[]; total: number }

// The queue shows the oldest this many; the count is of them all.
export const JOIN_REQUESTS_SHOWN = 50

/** The queue, oldest first. Every staff role. */
export const joinRequestsQuery = queryOptions({
  queryKey: ['join-requests'],
  queryFn: () => apiFetch<JoinRequestPage>(`/api/join-requests?limit=${JOIN_REQUESTS_SHOWN}`),
})

export type JoinApproved = { person_id: string; membership_id: string | null }

/**
 * Adds the person, with a membership on `planId` when given (owner and admin only). A
 * 409 `has_membership` is someone already a member here: approved with no plan, they
 * are linked as they are.
 */
export function approveJoinRequest(requestId: string, planId: string | null): Promise<JoinApproved> {
  return apiFetch<JoinApproved>(`/api/join-requests/${encodeURIComponent(requestId)}/approve`, {
    method: 'POST',
    body: JSON.stringify(planId ? { plan_id: planId } : {}),
  })
}

/** Rejects it: its data is deleted. */
export function rejectJoinRequest(requestId: string): Promise<void> {
  return apiFetch<void>(`/api/join-requests/${encodeURIComponent(requestId)}`, { method: 'DELETE' })
}
