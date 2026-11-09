import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

export type PersonRef = { id: string; name: string }

/** Who pays for this person, or whom they pay for: never both. */
export type Family = { guardian: PersonRef | null; dependents: PersonRef[] }

/** Someone new, added by name with no phone: kids have none. */
export type NewDependent = { name: string; rut?: string; dob?: string }

export type AddDependent = { person_id: string } | NewDependent

export type FamilyConflict = 'has_guardian' | 'one_level'

export function familyQuery(personId: string) {
  return queryOptions({
    queryKey: ['people', 'family', personId],
    queryFn: () => apiFetch<Family>(`/api/people/${personId}/family`),
  })
}

export function addDependent(guardianId: string, body: AddDependent): Promise<Family> {
  return apiFetch<Family>(`/api/people/${guardianId}/dependents`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function removeDependent(guardianId: string, dependentId: string): Promise<void> {
  return apiFetch<void>(`/api/people/${guardianId}/dependents/${dependentId}`, { method: 'DELETE' })
}

/** The 409's code, when the API refused a link for one of the family rules. */
export function familyConflict(error: unknown): FamilyConflict | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown } } | undefined)?.detail
  return detail?.code === 'has_guardian' || detail?.code === 'one_level' ? detail.code : null
}
