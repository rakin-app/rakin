import { queryOptions, useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'
import { myselfQuery } from './me'

/** One discipline the gym teaches, "BJJ" or "Ballet" (backend `Activity`, #245). Belts
 * and ranks show in the gym only while one of its activities `uses_grades`. */
export type Activity = {
  id: string
  name: string
  uses_grades: boolean
  // How many class types belong to it.
  class_types: number
  created_at: string
}

export type ActivityChanges = Partial<{ name: string; uses_grades: boolean }>

/** The ones Ajustes offers, each with whether it grades by default: on for the martial
 * arts that give belts, off for the rest. "Otra" is a name the gym writes itself. */
export const ACTIVITY_PRESETS: readonly { name: string; usesGrades: boolean }[] = [
  { name: 'BJJ', usesGrades: true },
  { name: 'Judo', usesGrades: true },
  { name: 'Karate', usesGrades: true },
  { name: 'Taekwondo', usesGrades: true },
  { name: 'Muay Thai', usesGrades: true },
  { name: 'Boxeo', usesGrades: false },
  { name: 'MMA', usesGrades: false },
  { name: 'Lucha', usesGrades: false },
  { name: 'Ballet', usesGrades: false },
  { name: 'Danza', usesGrades: false },
  { name: 'Música', usesGrades: false },
  { name: 'Piano', usesGrades: false },
  { name: 'Escalada', usesGrades: false },
  { name: 'Natación', usesGrades: false },
  { name: 'Fútbol', usesGrades: false },
  { name: 'Fuerza / CrossFit', usesGrades: false },
  { name: 'Yoga', usesGrades: false },
]

/** The gym's activities by name. Any staff role may read them. */
export const activitiesQuery = queryOptions({
  queryKey: ['activities'],
  queryFn: () => apiFetch<Activity[]>('/api/activities'),
})

export function createActivity(body: { name: string; uses_grades: boolean }): Promise<Activity> {
  return apiFetch<Activity>('/api/activities', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change. */
export function updateActivity(id: string, changes: ActivityChanges): Promise<Activity> {
  return apiFetch<Activity>(`/api/activities/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** Its class types stay, with no activity. */
export function deleteActivity(id: string): Promise<void> {
  return apiFetch<void>(`/api/activities/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/**
 * Whether the gym grades (#245): one of its activities uses grades. Every belt and rank
 * on its screens shows only then; until the answer is in, none does, so a gym that
 * does not grade never sees one flash by.
 */
export function useGrades(): boolean {
  return useQuery(myselfQuery()).data?.uses_grades === true
}
