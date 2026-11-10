import { apiFetch, ApiError } from './client'

/** What a sheet column can be, in the order the mapping offers them. */
export const IMPORT_FIELDS = [
  'name',
  'last_name',
  'phone',
  'email',
  'rut',
  'dob',
  'plan',
  'due_on',
  'started_on',
  'guardian_name',
  'guardian_phone',
] as const
export type ImportField = (typeof IMPORT_FIELDS)[number]

export type Mapping = Partial<Record<ImportField, number>>

export type SheetRow = { number: number; cells: string[] }

export type Sheet = { headers: string[]; rows: SheetRow[]; mapping: Mapping }

export type RowErrorCode =
  | 'required'
  | 'repeated'
  | 'invalid_phone'
  | 'invalid_email'
  | 'invalid_rut'
  | 'invalid_date'
  | 'own_guardian'
  | 'unknown_plan'
  | 'inactive_plan'
  | 'dropin_plan'
  | 'due_before_start'
  | 'has_guardian'
  | 'one_level'
  // Dado de baja: reactivated from their ficha, never by a sheet (#157).
  | 'has_left'

export type Outcome = 'created' | 'existing'

export type RowResult = {
  row: number
  name: string
  errors: { field: ImportField; code: RowErrorCode }[]
  person: Outcome | null
  guardian: Outcome | null
  link: Outcome | null
  membership: Outcome | null
  // Fields the import leaves unapplied: whoever it found keeps this gym's record.
  ignored: ImportField[]
}

export type ImportReport = {
  dry_run: boolean
  summary: {
    rows: number
    imported: number
    refused: number
    people_created: number
    links_created: number
    memberships_created: number
  }
  rows: RowResult[]
}

const SHEET_REFUSALS = ['unreadable', 'empty', 'too_many_rows', 'too_many_empty_rows', 'too_large'] as const
export type SheetRefusal = (typeof SHEET_REFUSALS)[number]

// The API's own limit is 5 MB; refusing here spares the upload.
export const MAX_SHEET_BYTES = 5 * 1024 * 1024
export const SHEET_TYPES = ['.csv', '.xlsx', 'text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']

/** Read the file into rows; nothing is stored. */
export function uploadSheet(file: File): Promise<Sheet> {
  return apiFetch<Sheet>('/api/import/sheet', {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
  })
}

export type ImportRequest = {
  rows: SheetRow[]
  mapping: Mapping
  // A plan cell's value to the plan it means; `null` for no plan, the person alone.
  plans: Record<string, string | null>
  dry_run: boolean
}

export function runImport(body: ImportRequest): Promise<ImportReport> {
  return apiFetch<ImportReport>('/api/import/members', { method: 'POST', body: JSON.stringify(body) })
}

/** Why the API refused a file, when it said. */
export function sheetRefusal(error: unknown): SheetRefusal | null {
  if (!(error instanceof ApiError)) return null
  const detail = (error.body as { detail?: { code?: unknown } } | undefined)?.detail
  const code = typeof detail === 'object' && detail !== null ? detail.code : undefined
  return SHEET_REFUSALS.find((refusal) => refusal === code) ?? null
}

/** For matching a plan cell to a plan's name, as the API does: accents, case and spacing ignored. */
export function fold(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}
