import { queryOptions, useQuery } from '@tanstack/react-query'
import { apiFetch } from './client'
import { myselfQuery } from './me'
import type { Vocabulary } from '../i18n/vocabulary'

/** One discipline the gym teaches, "BJJ" or "Ballet" (backend `Activity`, #245). Belts
 * and ranks show in the gym only while one of its activities `uses_grades`. */
export type Activity = {
  id: string
  name: string
  uses_grades: boolean
  // The preset it came from (#344), kept through a rename; `null` for a name the gym wrote.
  preset?: ActivityPreset | null
  // What a gym of that sport calls itself, its members and its coach; `null` with no preset.
  words?: Vocabulary | null
  // How many class types belong to it.
  class_types: number
  created_at: string
}

export type ActivityChanges = Partial<{ name: string; uses_grades: boolean }>

/** The ones Ajustes offers, each by the key the API stores (backend
 * `app.domain.vocabulary.PRESETS`, which holds the words each brings, #344) and with
 * whether it grades by default: on for the martial arts that give belts, off for the
 * rest. "Otra" is a name the gym writes itself. */
export const ACTIVITY_PRESETS = [
  { key: 'bjj', name: 'BJJ', usesGrades: true },
  { key: 'judo', name: 'Judo', usesGrades: true },
  { key: 'karate', name: 'Karate', usesGrades: true },
  { key: 'taekwondo', name: 'Taekwondo', usesGrades: true },
  { key: 'kenpo', name: 'Kenpo', usesGrades: true },
  { key: 'aikido', name: 'Aikido', usesGrades: true },
  { key: 'muay_thai', name: 'Muay Thai', usesGrades: true },
  { key: 'boxeo', name: 'Boxeo', usesGrades: false },
  { key: 'mma', name: 'MMA', usesGrades: false },
  { key: 'lucha', name: 'Lucha', usesGrades: false },
  { key: 'ballet', name: 'Ballet', usesGrades: false },
  { key: 'danza', name: 'Danza', usesGrades: false },
  { key: 'musica', name: 'Música', usesGrades: false },
  { key: 'piano', name: 'Piano', usesGrades: false },
  { key: 'escalada', name: 'Escalada', usesGrades: false },
  { key: 'remo', name: 'Remo', usesGrades: false },
  { key: 'natacion', name: 'Natación', usesGrades: false },
  { key: 'futbol', name: 'Fútbol', usesGrades: false },
  { key: 'crossfit', name: 'Fuerza / CrossFit', usesGrades: false },
  { key: 'yoga', name: 'Yoga', usesGrades: false },
] as const satisfies readonly { key: string; name: string; usesGrades: boolean }[]

export type ActivityPreset = (typeof ACTIVITY_PRESETS)[number]['key']

/** The gym's activities by name. Any staff role may read them. */
export const activitiesQuery = queryOptions({
  queryKey: ['activities'],
  queryFn: () => apiFetch<Activity[]>('/api/activities'),
})

export function createActivity(body: {
  name: string
  uses_grades: boolean
  preset?: ActivityPreset
}): Promise<Activity> {
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
