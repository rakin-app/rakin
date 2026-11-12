import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** One of the gym's recurring focuses, "Pasaje de guardia" or "Fuerza" (backend
 * `ClassTag`, #243). An archived one stays on the classes that have it, and still
 * counts in their hours, but goes on no class from then on. */
export type ClassTag = {
  id: string
  name: string
  archived: boolean
  created_at: string
}

/** A tag as a class or a slot carries it (backend `TagOn`). */
export type TagOn = { id: string; name: string; archived: boolean }

export type ClassTagChanges = Partial<{ name: string; archived: boolean }>

/** The gym's tags by name, archived ones last. Any staff role may read them. */
export const classTagsQuery = queryOptions({
  queryKey: ['class-tags'],
  queryFn: () => apiFetch<ClassTag[]>('/api/class-tags'),
})

export function createClassTag(body: { name: string }): Promise<ClassTag> {
  return apiFetch<ClassTag>('/api/class-tags', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change. */
export function updateClassTag(id: string, changes: ClassTagChanges): Promise<ClassTag> {
  return apiFetch<ClassTag>(`/api/class-tags/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** One tag's classes over a stretch and the minutes they lasted (backend `TagHoursRow`). */
export type TagHoursRow = {
  tag_id: string
  name: string
  archived: boolean
  classes: number
  minutes: number
}

/** Hours per tag from `first_day` to `last_day` on the gym's calendar, most first
 * (backend `TagHours`). A class adds its whole duration to every tag it carries. */
export type TagHours = {
  first_day: string
  last_day: string
  tags: TagHoursRow[]
  untagged_minutes: number
}

/** A gym month, `month` from 1, or with `month` null the whole year. */
export type Stretch = { year: number; month: number | null }

function stretchParams({ year, month }: Stretch): string {
  return month === null ? `year=${year}` : `year=${year}&month=${month}`
}

/** The gym's classes held in the stretch, hours per tag: Clases'. Any staff role. */
export function gymTagHoursQuery(stretch: Stretch) {
  return queryOptions({
    queryKey: ['class-tags', 'hours', stretch.year, stretch.month],
    queryFn: () => apiFetch<TagHours>(`/api/class-tags/hours?${stretchParams(stretch)}`),
  })
}

/** The classes a member attended in the stretch, hours per tag: the ficha's. */
export function personTagHoursQuery(personId: string, stretch: Stretch) {
  return queryOptions({
    queryKey: ['class-tags', 'hours', personId, stretch.year, stretch.month],
    queryFn: () =>
      apiFetch<TagHours>(`/api/people/${encodeURIComponent(personId)}/tag-hours?${stretchParams(stretch)}`),
  })
}

/** A class attended, as the student page reads it (backend `MyClass`): no notes, which
 * are the coach's alone. */
export type MyClass = {
  session_id: string
  starts_at: string
  duration_minutes: number | null
  class_type_name: string
  program_name: string
  topic: string | null
  tags: TagOn[]
}

/** One person's latest classes, newest first, and their hours per tag this month and
 * this year (backend `PersonClasses`). */
export type PersonClasses = {
  person_id: string
  name: string
  classes: MyClass[]
  this_month: TagHours
  this_year: TagHours
}

/** The signed-in person's own, when they train, then each dependent's (backend `MyClasses`). */
export type MyClasses = { timezone: string; people: PersonClasses[] }

export function myClassesQuery() {
  return queryOptions({ queryKey: ['me', 'classes'], queryFn: () => apiFetch<MyClasses>('/api/me/classes') })
}

/** The tags a class may take: the gym's active ones, and any archived one it already
 * carries, which may stay but not be put back once taken off. */
export function pickableTags(all: readonly ClassTag[], carried: readonly TagOn[]): TagOn[] {
  const kept = new Set(carried.map((tag) => tag.id))
  return all.filter((tag) => !tag.archived || kept.has(tag.id))
}
