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
  'guardian_rut',
  'guardian_email',
  'guardian_phone',
  // History from before Rakin (#297): only where the gym has none yet.
  'member_since',
  'left_on',
  'left_reason',
  'prior_classes',
] as const
export type ImportField = (typeof IMPORT_FIELDS)[number]

export type Mapping = Partial<Record<ImportField, number>>

export type SheetRow = { number: number; cells: string[] }

// The file the sheet was read from, sent back so the import's record names it.
export type SheetFile = { name: string | null; sha256: string }

export type Sheet = { headers: string[]; rows: SheetRow[]; mapping: Mapping; file: SheetFile }

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
  // Two of the name in the gym, and nothing else tells them apart (#165).
  | 'ambiguous_name'
  // The RUT or email the row would give someone is another person's in this gym.
  | 'rut_in_gym'
  | 'email_in_gym'
  // "Fecha de baja" before "Alumno desde".
  | 'left_before_start'
  // "Clases antes de Rakin" is not a whole number.
  | 'invalid_number'
  // "Motivo de baja" over 200 characters.
  | 'too_long'

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
  // Whom the gym messages about them (their guardian, for a kid) has no phone:
  // imported, and flagged "Falta teléfono" until one is filled in.
  missing_phone: boolean
  // Neither a RUT nor an email: imported, and found again by their name in this gym.
  missing_identity: boolean
  // It wrote some of their history from before Rakin, where the gym had none.
  history: boolean
  // A former student's row: one with a "Fecha de baja", imported with no plan.
  former: boolean
}

export type ImportReport = {
  dry_run: boolean
  // The import's record in the gym's log; never on a dry run, nor when nothing was written.
  import_id: string | null
  summary: {
    rows: number
    imported: number
    refused: number
    people_created: number
    links_created: number
    memberships_created: number
    // Rows imported with "Falta teléfono".
    missing_phone: number
    missing_identity: number
    // People whose history it wrote, and the former students it created.
    history_set: number
    former_created: number
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
  return apiFetch<Sheet>(`/api/import/sheet?${new URLSearchParams({ name: file.name })}`, {
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
  file?: SheetFile
}

/** Rakin's sheet to fill in (#297): a file the browser downloads, not JSON. */
export const TEMPLATE_PATH = '/api/import/template.xlsx'

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
