import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'
import type { Rank } from './grading'
import type { MembershipStatus } from './people'

export type PlanKind = 'monthly' | 'prepaid' | 'credits' | 'dropin' | 'trial'

/** One person on a session's roster (backend `RosterMember`). */
export type RosterMember = {
  membership_id: string
  person_id: string
  name: string
  plan_name: string
  plan_kind: PlanKind
  status: MembershipStatus
  // Credits left on a pack, free classes left on a trial; null on other plans.
  credits_remaining: number | null
  // A period past due and unpaid: they can still train, the coach nudges.
  overdue: boolean
  // Days since their last class before this one; null for a first.
  days_absent: number | null
  rank: Rank | null
  present: boolean
}

/** Who may be marked at a session, by name, and how many are (backend `Roster`). */
export type Roster = {
  session_id: string
  present: number
  members: RosterMember[]
}

/** What to mark and unmark, by membership. */
export type AttendanceChange = { mark: string[]; unmark: string[] }

/** A person's classes here (backend `PersonAttendance`). */
export type PersonAttendance = {
  last_30_days: number
  total: number
  // Since their current rank's day; null until they have a rank.
  since_promotion: number | null
}

type TrialPlan = { id: string; name: string; kind: PlanKind; active: boolean }

export function rosterQuery(sessionId: string) {
  return queryOptions({
    queryKey: ['sessions', 'roster', sessionId],
    queryFn: () => apiFetch<Roster>(`/api/sessions/${encodeURIComponent(sessionId)}/roster`),
  })
}

export function changeAttendance(sessionId: string, change: AttendanceChange): Promise<Roster> {
  return apiFetch<Roster>(`/api/sessions/${encodeURIComponent(sessionId)}/attendance`, {
    method: 'PATCH',
    body: JSON.stringify(change),
  })
}

/** The plans a guest can try the gym on: the active trial plans. */
export function trialPlansQuery() {
  return queryOptions({
    queryKey: ['plans', 'active'],
    queryFn: () => apiFetch<TrialPlan[]>('/api/plans?active=true'),
    select: (plans) => plans.filter((p) => p.kind === 'trial'),
  })
}

/**
 * Add someone by phone and start them on `planId`, present at the session: the roster
 * then. A phone already in the gym is that person, and one who is already a member is
 * their membership instead, for the screen to mark as any other tap.
 */
export async function addTrialGuest(
  sessionId: string,
  guest: { name: string; phone: string; planId: string },
): Promise<{ roster: Roster } | { member: string }> {
  const personId = await addPerson(guest.name, guest.phone)
  try {
    const roster = await apiFetch<Roster>(`/api/sessions/${encodeURIComponent(sessionId)}/trials`, {
      method: 'POST',
      body: JSON.stringify({ person_id: personId, plan_id: guest.planId }),
    })
    return { roster }
  } catch (error) {
    const membership = conflict(error, 'already_member', 'membership_id')
    if (membership === null) throw error
    return { member: membership }
  }
}

async function addPerson(name: string, phone: string): Promise<string> {
  try {
    const person = await apiFetch<{ id: string }>('/api/people', {
      method: 'POST',
      body: JSON.stringify({ name, phone }),
    })
    return person.id
  } catch (error) {
    const existing = conflict(error, 'phone_in_gym', 'person_id')
    if (existing === null) throw error
    return existing
  }
}

/** The id a 409 of `code` names under `field`, else null. */
function conflict(error: unknown, code: string, field: string): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: Record<string, unknown> } | undefined)?.detail
  const id = detail?.code === code ? detail[field] : undefined
  return typeof id === 'string' ? id : null
}

export function personAttendanceQuery(personId: string) {
  return queryOptions({
    queryKey: ['attendance', personId],
    queryFn: () => apiFetch<PersonAttendance>(`/api/people/${encodeURIComponent(personId)}/attendance`),
  })
}

/**
 * A request that never reached the API for lack of signal: `fetch` rejects with a
 * `TypeError` on a network failure, or the browser knows it is offline. Any other
 * failure, an answer from the API or a bug, is not something resending will fix.
 */
export function isOffline(error: unknown): boolean {
  if (error instanceof ApiError) return false
  return error instanceof TypeError || (typeof navigator !== 'undefined' && navigator.onLine === false)
}

// The API's answers to a change that sending it again would get again: an invalid mark,
// a conflict, a session gone. A 5xx, 401 or 429 may pass on a later try.
const REFUSALS = new Set([404, 409, 422])

/** The API refused the change itself, so resending it is pointless. */
export function isRefusal(error: unknown): boolean {
  return error instanceof ApiError && REFUSALS.has(error.status)
}

// Marks a coach saved without signal, per session, until they reach the API. Kept in the
// phone's storage so a closed tab does not lose them; an unusable storage keeps none.
const QUEUE_PREFIX = 'rakin:attendance:'

export function queuedChange(sessionId: string): AttendanceChange | null {
  try {
    const raw = localStorage.getItem(QUEUE_PREFIX + sessionId)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<AttendanceChange>
    if (!Array.isArray(parsed.mark) || !Array.isArray(parsed.unmark)) return null
    return { mark: parsed.mark.map(String), unmark: parsed.unmark.map(String) }
  } catch {
    return null
  }
}

export function queueChange(sessionId: string, change: AttendanceChange): void {
  try {
    localStorage.setItem(QUEUE_PREFIX + sessionId, JSON.stringify(change))
  } catch {
    // Still pending on screen; it goes when the signal comes back while the page is open.
  }
}

export function clearQueuedChange(sessionId: string): void {
  try {
    localStorage.removeItem(QUEUE_PREFIX + sessionId)
  } catch {
    // Nothing to clear.
  }
}
