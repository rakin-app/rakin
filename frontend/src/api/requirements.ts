import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { VisibleTo } from './customFields'

/** Where someone stands on a requirement (backend `RequirementState`): al día, vence
 * pronto (within 30 days), vencido or pendiente. */
export type RequirementState = 'ok' | 'expiring' | 'expired' | 'pending'

/** One of the gym's requirements (backend `Requirement`, #349). The API only answers the
 * ones the signed-in role may see. */
export type Requirement = {
  id: string
  name: string
  // How long one lasts; `null` for one done once.
  valid_months: number | null
  sensitive: boolean
  visible_to: VisibleTo
  active: boolean
}

/** A requirement as sent. `sensitive` and `visible_to` are the owner's alone. */
export type RequirementChanges = Partial<{
  name: string
  valid_months: number | null
  active: boolean
  sensitive: boolean
  visible_to: VisibleTo
}>

/** The requirements the signed-in role sees, in the gym's order, inactive ones included. */
export const requirementsQuery = queryOptions({
  queryKey: ['requirements'],
  queryFn: () => apiFetch<Requirement[]>('/api/requirements'),
})

export function createRequirement(body: RequirementChanges & { name: string }): Promise<Requirement> {
  return apiFetch<Requirement>('/api/requirements', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change; there is no delete. */
export function updateRequirement(id: string, changes: RequirementChanges): Promise<Requirement> {
  return apiFetch<Requirement>(`/api/requirements/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** `ids` must name every requirement the caller sees, once. */
export function reorderRequirements(ids: string[]): Promise<Requirement[]> {
  return apiFetch<Requirement[]>('/api/requirements/order', { method: 'PUT', body: JSON.stringify({ ids }) })
}

// --- a person's ----------------------------------------------------------------------

/** One active requirement on a person, with their current record (backend
 * `PersonRequirement`); the dates and note are `null` while there is none. */
export type PersonRequirement = {
  id: string
  name: string
  valid_months: number | null
  sensitive: boolean
  state: RequirementState
  done_on: string | null
  // The last day it is in force; `null` when done once, or never done.
  expires_on: string | null
  note: string | null
  recorded_at: string | null
}

export function personRequirementsQuery(personId: string) {
  return queryOptions({
    queryKey: ['people', 'requirements', personId],
    queryFn: () => apiFetch<PersonRequirement[]>(`/api/people/${encodeURIComponent(personId)}/requirements`),
  })
}

/** A new record, which becomes the person's current one: done on `done_on`, today at the latest. */
export function recordRequirement(
  personId: string,
  requirementId: string,
  body: { done_on: string; note: string | null },
): Promise<PersonRequirement[]> {
  return apiFetch<PersonRequirement[]>(
    `/api/people/${encodeURIComponent(personId)}/requirements/${encodeURIComponent(requirementId)}`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

// --- the student page ------------------------------------------------------------------

/** A requirement as the student page shows it (backend `MyRequirement`): no note. */
export type MyRequirement = {
  id: string
  name: string
  state: RequirementState
  done_on: string | null
  expires_on: string | null
}

/** The signed-in person's requirements, or a dependent's (backend `PersonRequirements`). */
export type PersonRequirements = { person_id: string; name: string; requirements: MyRequirement[] }

/** Empty when the gym asks for nothing. */
export const myRequirementsQuery = queryOptions({
  queryKey: ['me', 'requirements'],
  queryFn: () => apiFetch<PersonRequirements[]>('/api/me/requirements'),
})
