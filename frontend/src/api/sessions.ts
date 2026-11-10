import { queryOptions, useQuery } from '@tanstack/react-query'
import { isoDay } from '../format'
import { apiFetch } from './client'

/** A class, or an open mat: rounds of sparring only (backend `ClassKind`). */
export const CLASS_KINDS = ['class', 'open_mat'] as const
export type ClassKind = (typeof CLASS_KINDS)[number]

/** A kind of class in one of the gym's programs (backend `ClassType`). */
export type ClassType = {
  id: string
  name: string
  program_id: string
  program_name: string
  credit_cost: number
  /** An open mat is rounds of sparring only, and by default is not counted as a class. */
  kind: ClassKind
  counts_as_class: boolean
  active: boolean
  created_at: string
}

/** One class (backend `Session`): held, or made ahead by the weekly schedule. */
export type ClassSession = {
  id: string
  class_type_id: string
  class_type_name: string
  program_id: string
  program_name: string
  starts_at: string
  /** How long it lasts; null when nobody set it. */
  duration_minutes: number | null
  coach_id: string
  coach_name: string
  topic: string | null
  notes: string | null
  /** When it was cancelled; null for a class that stands. A cancelled class takes no
   * attendance and counts for nothing. */
  cancelled_at: string | null
  created_at: string
  updated_at: string
  /** How many are marked at it; 0 is a class whose attendance was never taken. */
  present: number
  /** The schedule's slot it was made from, and the gym-local date it was made for;
   * null for a one-off class. */
  slot_id: string | null
  slot_date: string | null
}

/** A day's sessions in the gym's timezone, earliest first (backend `Day`). */
export type SessionDay = {
  date: string
  timezone: string
  sessions: ClassSession[]
}

/** The class types a session can be started of: the active ones, by program and name. */
export function activeClassTypesQuery() {
  return queryOptions({
    queryKey: ['class-types', 'active'],
    queryFn: () => apiFetch<ClassType[]>('/api/class-types?active=true'),
  })
}

/** Today's sessions, today being the gym's. */
export function todaySessionsQuery() {
  return queryOptions({ queryKey: ['sessions', 'today'], queryFn: () => apiFetch<SessionDay>('/api/sessions') })
}

/** A day's sessions, `2026-11-10` in the gym's timezone. */
export function daySessionsQuery(day: string) {
  return queryOptions({
    queryKey: ['sessions', 'day', day],
    queryFn: () => apiFetch<SessionDay>(`/api/sessions?date=${encodeURIComponent(day)}`),
  })
}

/** The gym's timezone, from today's sessions, which every staff role reads; this
 * device's until they arrive. */
export function useGymTimeZone(): string {
  const today = useQuery(todaySessionsQuery())
  return today.data?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** Today in the gym's timezone, `2026-11-10`: past 21:00 in Santiago it is still today
 * there, though tomorrow in UTC, and on a device set to another zone. */
export function useGymToday(): string {
  return isoDay(new Date().toISOString(), useGymTimeZone())
}

/** The last week's classes, already started, that no one is marked at (backend `Unmarked`). */
export type UnmarkedSessions = {
  since: string
  timezone: string
  sessions: ClassSession[]
}

/** The classes nobody took attendance at, latest first. Owner and admin only. */
export function unmarkedSessionsQuery() {
  return queryOptions({
    queryKey: ['sessions', 'unmarked'],
    queryFn: () => apiFetch<UnmarkedSessions>('/api/sessions/unmarked'),
  })
}

export function sessionQuery(id: string) {
  return queryOptions({
    queryKey: ['sessions', 'detail', id],
    queryFn: () => apiFetch<ClassSession>(`/api/sessions/${encodeURIComponent(id)}`),
  })
}

/** Start a class of `class_type_id` now, taught by whoever starts it. */
export function startSession(body: { class_type_id: string }): Promise<ClassSession> {
  return apiFetch<ClassSession>('/api/sessions', { method: 'POST', body: JSON.stringify(body) })
}

/** What may change of a class (backend `SessionUpdate`): its own coach the topic and
 * notes, an owner or admin all of it. An empty topic or notes clears it. For a class
 * of the schedule this is "solo esta clase". */
export type SessionChanges = Partial<{
  topic: string
  notes: string
  starts_at: string
  class_type_id: string
  coach_id: string
  /** Null clears it. */
  duration_minutes: number | null
}>

const sessionPath = (id: string) => `/api/sessions/${encodeURIComponent(id)}`

/** Only the fields sent change. */
export function updateSession(id: string, body: SessionChanges): Promise<ClassSession> {
  return apiFetch<ClassSession>(sessionPath(id), { method: 'PATCH', body: JSON.stringify(body) })
}

/** A class that won't happen; a 409 once attendance was taken. Owner and admin only. */
export function cancelSession(id: string): Promise<ClassSession> {
  return apiFetch<ClassSession>(`${sessionPath(id)}/cancel`, { method: 'POST' })
}

/** Undo a cancel. Owner and admin only. */
export function reactivateSession(id: string): Promise<ClassSession> {
  return apiFetch<ClassSession>(`${sessionPath(id)}/reactivate`, { method: 'POST' })
}

/** A class made by mistake, gone with its attendance (credits given back) and its timer
 * record. Owner and admin only. */
export function deleteSession(id: string): Promise<void> {
  return apiFetch<void>(sessionPath(id), { method: 'DELETE' })
}
