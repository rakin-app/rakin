import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** A kind of class in one of the gym's programs (backend `ClassType`). */
export type ClassType = {
  id: string
  name: string
  program_id: string
  program_name: string
  credit_cost: number
  active: boolean
  created_at: string
}

/** One class actually held (backend `Session`). */
export type ClassSession = {
  id: string
  class_type_id: string
  class_type_name: string
  program_id: string
  program_name: string
  starts_at: string
  coach_id: string
  coach_name: string
  topic: string | null
  notes: string | null
  created_at: string
  updated_at: string
  /** How many are marked at it; 0 is a class whose attendance was never taken. */
  present: number
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

/** What a class covered; an empty string clears it. */
export function updateSession(id: string, body: { topic: string; notes: string }): Promise<ClassSession> {
  return apiFetch<ClassSession>(`/api/sessions/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
