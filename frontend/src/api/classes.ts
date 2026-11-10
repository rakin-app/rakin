import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Program } from './people'
import type { ClassType } from './sessions'

/** Every class type, active ones first, then by program and name. Any staff role may read them. */
export const classTypesQuery = queryOptions({
  queryKey: ['class-types'],
  queryFn: () => apiFetch<ClassType[]>('/api/class-types'),
})

export function createProgram(name: string): Promise<Program> {
  return apiFetch<Program>('/api/programs', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

/** Only the fields sent change; there is no delete, `active: false` deactivates. */
export function updateProgram(programId: string, changes: { name?: string; active?: boolean }): Promise<Program> {
  return apiFetch<Program>(`/api/programs/${encodeURIComponent(programId)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** A class type's fields as sent: the credit cost as a number, or text as typed for the API to refuse. */
export type ClassTypeFields = Partial<{
  name: string
  program_id: string
  credit_cost: number | string
}>

export function createClassType(body: ClassTypeFields): Promise<ClassType> {
  return apiFetch<ClassType>('/api/class-types', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Only the fields sent change; a class type may move to another program. */
export function updateClassType(
  classTypeId: string,
  changes: ClassTypeFields & { active?: boolean },
): Promise<ClassType> {
  return apiFetch<ClassType>(`/api/class-types/${encodeURIComponent(classTypeId)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}
