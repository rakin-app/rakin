import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'

export type FieldType = 'text' | 'number' | 'date' | 'enum'

/** A number, a text, an ISO date or one of an enum's options; `null` when unset. */
export type FieldValue = string | number | null

/** One of the gym's custom fields on a person, with its value (backend `PersonField`).
 * The API only answers the fields the signed-in role may see. */
export type PersonField = {
  key: string
  label: string
  type: FieldType
  options: string[] | null
  sensitive: boolean
  value: FieldValue
}

export function personFieldsQuery(personId: string) {
  return queryOptions({
    queryKey: ['people', 'fields', personId],
    queryFn: () => apiFetch<PersonField[]>(`/api/people/${encodeURIComponent(personId)}/fields`),
  })
}

export function updatePersonFields(personId: string, values: Record<string, FieldValue>): Promise<PersonField[]> {
  return apiFetch<PersonField[]>(`/api/people/${encodeURIComponent(personId)}/fields`, {
    method: 'PATCH',
    body: JSON.stringify({ values }),
  })
}

/** The keys of the fields a 422 refused, when the API refused some values. */
export function refusedFields(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 422) return []
  const detail = (error.body as { detail?: { fields?: unknown } } | undefined)?.detail
  const fields = detail?.fields
  return fields && typeof fields === 'object' ? Object.keys(fields) : []
}
