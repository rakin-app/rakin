import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { useId, type ComponentType, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { managesGym, myRoleQuery } from '../api/me'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { GymSettings } from './GymSettings'
import { PlanSettings } from './PlanSettings'
import './Settings.css'

const copy = t.admin.settings

/**
 * The sections, in tab order: the router makes a route of each under `/admin/ajustes`,
 * and the first is where it opens. A new section is its component and an entry here.
 */
export const SETTINGS_SECTIONS = [
  { path: 'gimnasio', label: copy.sections.gym, component: GymSettings },
  { path: 'planes', label: copy.sections.plans, component: PlanSettings },
] as const satisfies readonly { path: string; label: string; component: ComponentType }[]

/**
 * "Ajustes": the gym's configuration, one section per route under it. Owner and admin
 * only, as the API is; a coach is told so and nothing is asked of the API. The
 * sections are a row of tabs that scrolls sideways on a phone once there are more
 * than fit (#57's other config screens hang off it).
 */
export function Settings() {
  const role = useQuery(myRoleQuery())

  return (
    <div className="settings">
      <PageHeader title={copy.title} />
      {managesGym(role.data) ? (
        <>
          <nav className="settings__sections" aria-label={copy.sectionsLabel}>
            {SETTINGS_SECTIONS.map((section) => (
              <Link key={section.path} to={`/admin/ajustes/${section.path}`} className="settings__section-link">
                {section.label}
              </Link>
            ))}
          </nav>
          <div className="settings__body">
            <Outlet />
          </div>
        </>
      ) : role.isError ? (
        <p className="settings__note" role="alert">
          {copy.roleError}
        </p>
      ) : (
        role.isSuccess && <AdminsOnly />
      )}
    </div>
  )
}

function AdminsOnly() {
  return <p className="settings__note">{copy.adminsOnly}</p>
}

/** A section's load failure: the role was taken away meanwhile (403), or a plain failure. */
export function LoadFailed({ error, message, retry }: { error: Error; message: string; retry: () => void }) {
  if (error instanceof ApiError && error.status === 403) return <AdminsOnly />
  return (
    <div className="settings__error" role="alert">
      <p>{message}</p>
      <button type="button" className="settings__button" onClick={retry}>
        {copy.retry}
      </button>
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

type ControlProps = { id: string; 'aria-invalid': boolean; 'aria-describedby': string | undefined }

/** A labelled control, with its hint and the API's refusal of it underneath. */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string
  children: (props: ControlProps) => ReactNode
}) {
  const id = useId()
  const described = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(' ')
  return (
    <div className="settings__field">
      <label htmlFor={id} className="settings__label">
        {label}
      </label>
      {children({ id, 'aria-invalid': error !== undefined, 'aria-describedby': described || undefined })}
      {hint && (
        <p id={`${id}-hint`} className="settings__hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="settings__field-error">
          {error}
        </p>
      )}
    </div>
  )
}
