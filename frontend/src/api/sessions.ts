import { queryOptions } from '@tanstack/react-query'
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
