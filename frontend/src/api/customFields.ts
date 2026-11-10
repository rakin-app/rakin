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

// --- definitions -------------------------------------------------------------------

/** Who sees a field: the owner alone, owner and admins, or every staff role. */
export const VISIBLE_TO = ['owner', 'admin', 'staff'] as const
export type VisibleTo = (typeof VISIBLE_TO)[number]

/** One of the gym's custom fields as defined (backend `FieldDefinition`). */
export type FieldDefinition = {
  key: string
  label: string
  type: FieldType
  options: string[] | null
  sensitive: boolean
  visible_to: VisibleTo
  archived: boolean
}

/** A field's definition as sent. `sensitive` and `visible_to` are the owner's alone. */
export type FieldChanges = Partial<{
  label: string
  options: string[]
  archived: boolean
  sensitive: boolean
  visible_to: VisibleTo
}>

/** The fields the signed-in role sees, in the gym's order, archived ones included. */
export const customFieldsQuery = queryOptions({
  queryKey: ['custom-fields'],
  queryFn: () => apiFetch<FieldDefinition[]>('/api/custom-fields'),
})

/** The key is made by the API from the label. */
export function createField(body: FieldChanges & { label: string; type: FieldType }): Promise<FieldDefinition> {
  return apiFetch<FieldDefinition>('/api/custom-fields', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change; the type and key are fixed, and there is no delete. */
export function updateField(key: string, changes: FieldChanges): Promise<FieldDefinition> {
  return apiFetch<FieldDefinition>(`/api/custom-fields/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** `keys` must name every field the caller sees, once. */
export function reorderFields(keys: string[]): Promise<FieldDefinition[]> {
  return apiFetch<FieldDefinition[]>('/api/custom-fields/order', { method: 'PUT', body: JSON.stringify({ keys }) })
}

/** The 409 `option_in_use`: each option an edit would remove that people still hold, and how many. */
export function optionsInUse(error: unknown): Record<string, number> | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown; options?: unknown } } | undefined)?.detail
  if (detail?.code !== 'option_in_use' || !detail.options || typeof detail.options !== 'object') return null
  return detail.options as Record<string, number>
}
