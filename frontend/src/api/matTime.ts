import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** The seconds one block kind ran, over the sessions the person attended. */
export type KindTime = {
  block_kind_id: string
  name: string
  is_sparring: boolean
  seconds: number
}

/** A person's time over a stretch (backend `TimeTotals`). `by_kind` holds the kinds
 * with any time, in the gym's order; `sparring_seconds` sums the sparring kinds, open
 * mats included, and `open_mat_seconds` is the open mats' time alone. */
export type TimeTotals = {
  by_kind: KindTime[]
  sparring_seconds: number
  open_mat_seconds: number
  classes: number
  open_mats: number
}

/** This month, from `month_start` on the gym's calendar, and all time. */
export type PersonTime = {
  timezone: string
  month_start: string
  this_month: TimeTotals
  all_time: TimeTotals
}

/** A member's time, for the ficha. Any staff role may read it. */
export function personTimeQuery(personId: string) {
  return queryOptions({
    queryKey: ['time', personId],
    queryFn: () => apiFetch<PersonTime>(`/api/people/${encodeURIComponent(personId)}/time`),
  })
}

/** The signed-in person's own time, for the student page. */
export function myTimeQuery() {
  return queryOptions({
    queryKey: ['me', 'time'],
    queryFn: () => apiFetch<PersonTime>('/api/me/time'),
  })
}

/** Whether any session the person attended was timed. */
export function hasTime(totals: TimeTotals): boolean {
  return totals.by_kind.length > 0 || totals.open_mats > 0
}
