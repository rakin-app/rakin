/**
 * What every Ajustes section builds on: its load failure, its labelled fields, its rows
 * and what the API's 422s on them mean. A module of its own, so the sections import it
 * without importing `Settings.tsx`, which imports them.
 */

import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { Button } from '../components/Button'
import { ListRowContent, listRowClass } from '../components/Card'
import { cx } from '../components/classNames'
import { ChevronDownIcon, ChevronRightIcon, ChevronUpIcon } from '../components/icons'
import { t } from '../i18n/es'

const copy = t.admin.settings

export function AdminsOnly() {
  return <p className="settings__note">{copy.adminsOnly}</p>
}

/**
 * What every section opens with (#241): one line on what it holds and, for a section
 * that lists things, the one button that adds one. Side by side from 1024px, the
 * button at the end; stacked on a phone.
 */
export function SectionHead({ intro, action }: { intro: ReactNode; action?: ReactNode }) {
  return (
    <div className="settings__head">
      <p className="settings__intro">{intro}</p>
      {action}
    </div>
  )
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

/**
 * A list's item (#177): the whole row is the button that opens it to edit, and what
 * deactivates or deletes it is in there, not beside an Editar on every row. `controls`,
 * the move buttons, stay at the row's end.
 */
export function EditRow({
  title,
  detail,
  inactive = false,
  onOpen,
  controls,
}: {
  title: ReactNode
  detail?: ReactNode
  inactive?: boolean
  onOpen: () => void
  controls?: ReactNode
}) {
  return (
    <li className={cx('settings__row', inactive && 'settings__row--inactive')}>
      <button type="button" className={listRowClass(true)} onClick={onOpen}>
        <ListRowContent title={title} detail={detail} trailing={<ChevronRightIcon />} />
      </button>
      {controls && <div className="settings__row-controls">{controls}</div>}
    </li>
  )
}

/** An item's ↑ and ↓, on its row: `up` and `down` name what they move. */
export function MoveButtons({
  up,
  down,
  first,
  last,
  disabled = false,
  onMove,
}: {
  up: string
  down: string
  first: boolean
  last: boolean
  disabled?: boolean
  onMove: (by: -1 | 1) => void
}) {
  return (
    <>
      <Button variant="ghost" icon aria-label={up} disabled={first || disabled} onClick={() => onMove(-1)}>
        <ChevronUpIcon />
      </Button>
      <Button variant="ghost" icon aria-label={down} disabled={last || disabled} onClick={() => onMove(1)}>
        <ChevronDownIcon />
      </Button>
    </>
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
