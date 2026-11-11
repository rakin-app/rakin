import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  personFieldsQuery,
  refusedFields,
  updatePersonFields,
  type FieldValue,
  type PersonField,
} from '../api/customFields'
import type { Person } from '../api/member'
import { duplicateOf, updatePerson, type PersonEdit } from '../api/people'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { FieldInput, valueOf } from './CustomFieldsPanel'
import { formatPhone, formatRut } from './Students'

const copy = t.admin.member
const words = copy.fields

/**
 * "Datos": the member's record (phone, email, RUT, birthday) and, below it, the gym's
 * custom fields the signed-in role may see (#20), with one "Editar datos" for all of
 * them. The API answers only the fields the role may see, so a coach never gets a field
 * the owner kept to themselves.
 */
export function PersonData({ person }: { person: Person }) {
  const fields = useQuery(personFieldsQuery(person.id))
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)

  return (
    <section className="member__section" aria-label={words.title}>
      <h2 className="member__section-title">{words.title}</h2>
      {person.missing_phone && (
        <p className="member__error" role="status">
          {copy.missingPhone}
        </p>
      )}
      {person.missing_rut && (
        <p className="member__error" role="status">
          {copy.missingRut}
        </p>
      )}
      {editing ? (
        <DataForm
          person={person}
          fields={fields.data ?? []}
          onCancel={() => setEditing(false)}
          onDone={() => {
            setEditing(false)
            setSaved(true)
          }}
        />
      ) : (
        <div className="member__card">
          <dl className="member__fields">
            <Datum label={words.phone} value={person.phone && formatPhone(person.phone)} />
            <Datum label={words.email} value={person.email} />
            <Datum label={words.rut} value={person.rut && formatRut(person.rut)} />
            <Datum label={words.dob} value={person.dob && t.common.day(person.dob)} />
            {fields.data?.map((field) => (
              <Datum key={field.key} label={field.label} sensitive={field.sensitive} value={shown(field)} />
            ))}
          </dl>
          {person.no_whatsapp && <p className="member__detail">{copy.noWhatsapp}</p>}
          {fields.isPending && <p className="member__note">{words.loading}</p>}
          {fields.isError && (
            <p className="member__note" role="alert">
              {words.error}
            </p>
          )}
          {saved && (
            <p className="member__done" role="status">
              {words.saved}
            </p>
          )}
          <div className="member__actions">
            <Button
              // Until the custom fields are read, so the form has them to edit; the note above says so.
              disabled={fields.isPending}
              onClick={() => {
                setSaved(false)
                setEditing(true)
              }}
            >
              {copy.editPerson}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}

function Datum({ label, value, sensitive }: { label: string; value: string | null; sensitive?: boolean }) {
  return (
    <div className="member__field">
      <dt className="member__detail">
        {label}
        {sensitive && <span className="member__tag">{words.sensitive}</span>}
      </dt>
      <dd className={value === null || value === '' ? 'member__detail' : undefined}>{value || words.empty}</dd>
    </div>
  )
}

function shown(field: PersonField): string | null {
  if (field.value === null) return null
  if (field.type === 'date') return t.common.day(String(field.value))
  if (field.type === 'number') return Number(field.value).toLocaleString('es-CL')
  return String(field.value)
}

/** What a custom field's input holds, as text: a number as typed, a date as `YYYY-MM-DD`. */
function draftOf(field: PersonField): string {
  return field.value === null ? '' : String(field.value)
}

/** After a change to who someone is in the gym: the lists, their ficha and their money. */
export function useRefresh() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['people'] }),
      queryClient.invalidateQueries({ queryKey: ['memberships'] }),
      queryClient.invalidateQueries({ queryKey: ['ledger'] }),
    ])
}

/**
 * The record and the custom fields in one form. Each is sent only if something in it
 * changed, the record first; a refusal of either keeps the form open on what was typed.
 */
function DataForm({
  person,
  fields,
  onCancel,
  onDone,
}: {
  person: Person
  fields: PersonField[]
  onCancel: () => void
  onDone: () => void
}) {
  const form = copy.editForm
  const queryClient = useQueryClient()
  const refresh = useRefresh()
  const formId = useId()
  const ids = { name: useId(), phone: useId(), noWhatsapp: useId(), email: useId(), rut: useId(), dob: useId() }
  const initial = {
    name: person.name,
    phone: person.phone ? formatPhone(person.phone) : '',
    email: person.email ?? '',
    rut: person.rut ? formatRut(person.rut) : '',
    dob: person.dob ?? '',
  }
  const [noWhatsapp, setNoWhatsapp] = useState(person.no_whatsapp)
  const [draft, setDraft] = useState(initial)
  const [drafts, setDrafts] = useState(() => Object.fromEntries(fields.map((f) => [f.key, draftOf(f)])))
  const [checked, setChecked] = useState(false)
  const nameOk = draft.name.trim() !== ''

  const save = useMutation({
    mutationFn: (body: PersonEdit) => updatePerson(person.id, body),
    onSuccess: refresh,
  })
  const saveFields = useMutation({
    mutationFn: (values: Record<string, FieldValue>) => updatePersonFields(person.id, values),
    onSuccess: (answer) => queryClient.setQueryData(personFieldsQuery(person.id).queryKey, answer),
  })
  const refused = new Set(refusedFields(saveFields.error))
  const busy = save.isPending || saveFields.isPending

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!nameOk) return
    save.reset()
    saveFields.reset()
    // Only what changed; an optional field emptied is cleared.
    const body: PersonEdit = {}
    if (draft.name.trim() !== initial.name) body.name = draft.name.trim()
    if (draft.phone.trim() !== initial.phone) body.phone = draft.phone.trim() || null
    if (noWhatsapp !== person.no_whatsapp) body.no_whatsapp = noWhatsapp
    if (draft.email.trim() !== initial.email) body.email = draft.email.trim() || null
    if (draft.rut.trim() !== initial.rut) body.rut = draft.rut.trim() || null
    if (draft.dob !== initial.dob) body.dob = draft.dob || null
    // Only the fields that changed, so one someone else edited meanwhile is left as they left it.
    const changed = fields.filter((f) => drafts[f.key] !== draftOf(f))
    try {
      if (Object.keys(body).length > 0) await save.mutateAsync(body)
      if (changed.length > 0) {
        await saveFields.mutateAsync(Object.fromEntries(changed.map((f) => [f.key, valueOf(f, drafts[f.key] ?? '')])))
      }
    } catch {
      // The refusal is drawn from the mutation's error.
      return
    }
    if (Object.keys(body).length === 0 && changed.length === 0) onCancel()
    else onDone()
  }

  const set = (key: keyof typeof draft) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value })
  const duplicate = duplicateOf(save.error)

  return (
    <form className="member__form" aria-label={form.title} onSubmit={(e) => void submit(e)} noValidate>
      <div className="member__form-grid">
        <div className="member__form-field member__form-field--wide">
          <label htmlFor={ids.name} className="member__label">
            {form.name}
          </label>
          <Input
            id={ids.name}
            maxLength={200}
            value={draft.name}
            aria-invalid={checked && !nameOk}
            onChange={set('name')}
          />
          {checked && !nameOk && (
            <p className="member__error" role="alert">
              {form.nameNeeded}
            </p>
          )}
        </div>
        <div className="member__form-field">
          <label htmlFor={ids.phone} className="member__label">
            {form.phone}
          </label>
          <Input id={ids.phone} type="tel" inputMode="tel" value={draft.phone} onChange={set('phone')} />
          <label htmlFor={ids.noWhatsapp} className="new-member__check">
            <input
              id={ids.noWhatsapp}
              type="checkbox"
              checked={noWhatsapp}
              onChange={(e) => setNoWhatsapp(e.target.checked)}
            />
            {form.noWhatsapp}
          </label>
        </div>
        <div className="member__form-field">
          <label htmlFor={ids.email} className="member__label">
            {form.email}
          </label>
          <Input id={ids.email} type="email" value={draft.email} onChange={set('email')} />
        </div>
        <div className="member__form-field">
          <label htmlFor={ids.rut} className="member__label">
            {form.rut}
          </label>
          <Input id={ids.rut} value={draft.rut} onChange={set('rut')} />
        </div>
        <div className="member__form-field">
          <label htmlFor={ids.dob} className="member__label">
            {form.dob}
          </label>
          <Input id={ids.dob} type="date" value={draft.dob} onChange={set('dob')} />
        </div>
        {fields.map((field) => {
          const id = `${formId}-${field.key}`
          return (
            <div key={field.key} className="member__form-field">
              <label htmlFor={id} className="member__label">
                {field.label}
              </label>
              <FieldInput
                id={id}
                field={field}
                value={drafts[field.key] ?? ''}
                invalid={refused.has(field.key)}
                onChange={(value) => setDrafts({ ...drafts, [field.key]: value })}
              />
            </div>
          )
        })}
      </div>

      {save.error && (
        <div className="member__error" role="alert">
          {duplicate ? (
            <>
              {form.refused[duplicate.code]}{' '}
              <Link to="/admin/alumnos/$personId" params={{ personId: duplicate.person_id }}>
                {form.refused.open}
              </Link>
            </>
          ) : refusedFor(save.error, 'a RUT or an email') ? (
            form.refused.identity
          ) : refusedFor(save.error, 'a phone is required') ? (
            form.refused.phone
          ) : save.error instanceof ApiError && save.error.status === 422 ? (
            form.refused.invalid
          ) : (
            form.refused.failed
          )}
        </div>
      )}
      {saveFields.error && (
        <p className="member__error" role="alert">
          {refused.size > 0 ? words.refused.invalid : words.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={busy} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? form.working : form.save}
        </Button>
      </div>
    </form>
  )
}

/** Whether the API refused an edit with the 422 whose detail starts with `reason`. */
function refusedFor(error: unknown, reason: string): boolean {
  if (!(error instanceof ApiError) || error.status !== 422) return false
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  return typeof detail === 'string' && detail.startsWith(reason)
}
