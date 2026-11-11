import { Button } from '../components/Button'
/**
 * What every Ajustes section builds on: its load failure, its labelled fields and what
 * the API's 422s on them mean. A module of its own, so the sections import it without
 * importing `Settings.tsx`, which imports them.
 */

import { ApiError } from '../api/client'
import { t } from '../i18n/es'

const copy = t.admin.settings

export function AdminsOnly() {
  return <p className="settings__note">{copy.adminsOnly}</p>
}

/** A section's load failure: the role was taken away meanwhile (403), or a plain failure. */
export function LoadFailed({ error, message, retry }: { error: Error; message: string; retry: () => void }) {
  if (error instanceof ApiError && error.status === 403) return <AdminsOnly />
  return (
    <div className="settings__error" role="alert">
      <p>{message}</p>
      <Button onClick={retry}>
        {copy.retry}
      </Button>
    </div>
  )
}

/** Per field, what its range and value refusals mean; the other types read the same everywhere. */
export type Refusals = { range: Record<string, string>; value: Record<string, string> }

/**
 * What the API's 422 `type` on `field` means to the admin. `blank` says the field was
 * left empty, which the API refuses as a number it cannot read.
 */
export function refusal(code: string, field: string, refusals: Refusals, blank: boolean): string {
  const invalid = copy.invalid
  switch (code) {
    case 'missing':
    case 'string_too_short':
      return invalid.required
    case 'string_too_long':
      return invalid.tooLong
    case 'literal_error':
    case 'enum':
      return invalid.choose
    case 'int_type':
    case 'int_parsing':
    case 'int_from_float':
      return blank ? invalid.required : invalid.integer
    case 'greater_than':
    case 'greater_than_equal':
    case 'less_than':
    case 'less_than_equal':
      return refusals.range[field] ?? invalid.failed
    default:
      return refusals.value[field] ?? refusals.value[code] ?? invalid.failed
  }
}

/** A number as typed, with Chile's thousands dots dropped; text that is none goes as typed. */
export function integerOf(draft: string): number | string {
  const text = draft.trim().replace(/\./g, '')
  return /^-?\d+$/.test(text) ? Number(text) : text
}

/** A labelled control, with its hint and the API's refusal of it underneath. */
export { Field } from '../components/Field'
