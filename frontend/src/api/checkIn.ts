import { queryOptions } from '@tanstack/react-query'
import type { PlanKind } from './attendance'
import { apiFetch } from './client'
import type { MembershipStatus } from './people'

/** Someone at the door, by the membership a check-in marks (backend `Visitor`). */
export type Visitor = {
  membership_id: string
  person_id: string
  name: string
  rut: string | null
  plan_name: string
  plan_kind: PlanKind
  status: MembershipStatus
  // Credits left on a pack, free classes left on a trial; null on other plans.
  credits_remaining: number | null
  // A period past due and unpaid: they still come in.
  overdue: boolean
}

/** A search result: when they came in today, null if they have not (backend `Candidate`). */
export type Candidate = Visitor & { checked_in_at: string | null }

/** A visit today (backend `Arrival`). */
export type Arrival = Visitor & { marked_at: string; credits_consumed: number }

/**
 * One open-access class type and its day so far (backend `Door`, #348): its session,
 * null until the first check-in makes it, and the arrivals, newest first.
 */
export type Door = {
  class_type_id: string
  name: string
  program_id: string
  program_name: string
  credit_cost: number
  date: string
  timezone: string
  session_id: string | null
  // An admin cancelled the day: check-ins are refused until it is reactivated.
  cancelled: boolean
  arrivals: Arrival[]
}

/** The gym's active open-access class types, each with today; none is a gym with no Entrada. */
export function doorsQuery() {
  return queryOptions({ queryKey: ['check-in'], queryFn: () => apiFetch<Door[]>('/api/check-in') })
}

const doorPath = (classTypeId: string) => `/api/check-in/${encodeURIComponent(classTypeId)}`

/** Who `q` finds, by name or RUT, that may be checked in at `classTypeId`. */
export function candidatesQuery(classTypeId: string, q: string) {
  return queryOptions({
    queryKey: ['check-in', 'search', classTypeId, q],
    queryFn: () => apiFetch<Candidate[]>(`${doorPath(classTypeId)}/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim() !== '',
  })
}

/** Check the membership in today, making the day's session on the first: the day then. */
export function checkIn(classTypeId: string, membershipId: string): Promise<Door> {
  return apiFetch<Door>(doorPath(classTypeId), {
    method: 'POST',
    body: JSON.stringify({ membership_id: membershipId }),
  })
}

/** Undo today's check-in of the membership, its credits given back: the day then. */
export function undoCheckIn(classTypeId: string, membershipId: string): Promise<Door> {
  return apiFetch<Door>(`${doorPath(classTypeId)}/${encodeURIComponent(membershipId)}`, { method: 'DELETE' })
}

/**
 * What to warn of before letting someone in, never a reason to refuse: a lapsed or
 * frozen plan, or a pack without the credits the visit costs. Null when nothing is wrong.
 */
export function warning(visitor: Visitor, creditCost: number): 'lapsed' | 'frozen' | 'noCredits' | null {
  if (visitor.status === 'lapsed' || visitor.status === 'frozen') return visitor.status
  const spends = visitor.plan_kind === 'credits' ? creditCost : visitor.plan_kind === 'trial' ? 1 : 0
  if (visitor.credits_remaining !== null && spends > 0 && visitor.credits_remaining < spends) return 'noCredits'
  return null
}
