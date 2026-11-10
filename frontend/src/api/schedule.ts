import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** One class of the gym's weekly timetable (backend `Slot`). Weekdays are ISO: 1 is
 * Monday. `start_time` is the gym's wall clock, `19:00:00`. */
export type ScheduleSlot = {
  id: string
  class_type_id: string
  class_type_name: string
  program_id: string
  program_name: string
  /** A deactivated class type's slot makes no classes. */
  class_type_active: boolean
  weekdays: number[]
  start_time: string
  duration_minutes: number
  coach_id: string
  coach_name: string
  topic: string | null
  valid_from: string
  valid_to: string | null
  created_at: string
  updated_at: string
}

/** A new slot (backend `SlotCreate`); it is valid from today unless told otherwise. */
export type SlotFields = {
  class_type_id: string
  weekdays: number[]
  start_time: string
  duration_minutes: number
  coach_id: string
  topic?: string | null
  valid_from?: string
  valid_to?: string | null
}

/** A change from `from_date` on, today by default (backend `SlotUpdate`): "esta y las
 * siguientes". Only the fields sent change. */
export type SlotChanges = Partial<Omit<SlotFields, 'valid_from'>> & { from_date?: string }

/** A date with no classes (backend `ClosedDay`). */
export type ClosedDay = { day: string; label: string | null }

/** Every slot, ended ones included. Owner and admin only. */
export const scheduleQuery = queryOptions({
  queryKey: ['schedule'],
  queryFn: () => apiFetch<ScheduleSlot[]>('/api/schedule'),
})

/** The closed days from today on. Owner and admin only. */
export const closedDaysQuery = queryOptions({
  queryKey: ['schedule', 'closed'],
  queryFn: () => apiFetch<ClosedDay[]>('/api/closed-days'),
})

const slotPath = (id: string) => `/api/schedule/${encodeURIComponent(id)}`
const closedPath = (day: string) => `/api/closed-days/${encodeURIComponent(day)}`

/** A new slot; its classes for the next two weeks are made at once. */
export function createSlot(body: SlotFields): Promise<ScheduleSlot> {
  return apiFetch<ScheduleSlot>('/api/schedule', { method: 'POST', body: JSON.stringify(body) })
}

/** The slot in effect from `from_date`: a new one when that is after the slot's first date. */
export function updateSlot(id: string, body: SlotChanges): Promise<ScheduleSlot> {
  return apiFetch<ScheduleSlot>(slotPath(id), { method: 'PATCH', body: JSON.stringify(body) })
}

/** The slot, and its classes yet to happen that nobody is marked at. */
export function deleteSlot(id: string): Promise<void> {
  return apiFetch<void>(slotPath(id), { method: 'DELETE' })
}

/** Close a day, or relabel it: its scheduled classes yet to happen go. */
export function closeDay(day: string, label: string): Promise<ClosedDay> {
  return apiFetch<ClosedDay>(closedPath(day), { method: 'PUT', body: JSON.stringify({ label }) })
}

/** Reopen a day: the schedule makes its classes again. */
export function reopenDay(day: string): Promise<void> {
  return apiFetch<void>(closedPath(day), { method: 'DELETE' })
}
