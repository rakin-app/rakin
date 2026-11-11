import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useId, useState, type FormEvent } from 'react'
import {
  personFieldsQuery,
  refusedFields,
  updatePersonFields,
  type FieldValue,
  type PersonField,
} from '../api/customFields'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'

const copy = t.admin.member.fields

/**
 * The gym's custom fields on a member, and the form that edits them. The API answers
 * only the fields the signed-in role may see, so a coach never gets a field the owner
 * kept to themselves; with none to show, the section is not drawn.
 */
export function CustomFieldsPanel({ personId }: { personId: string }) {
  const fields = useQuery(personFieldsQuery(personId))
  const [editing, setEditing] = useState(false)
  const [saved, setSaved] = useState(false)

  if (fields.isPending) return <p className="member__note">{copy.loading}</p>
  if (fields.isError) {
    return (
      <p className="member__note" role="alert">
        {copy.error}
      </p>
    )
  }
  if (fields.data.length === 0) return null

  return (
    <section className="member__section" aria-label={copy.title}>
      <h2 className="member__section-title">{copy.title}</h2>
      {editing ? (
        <FieldsForm
          personId={personId}
          fields={fields.data}
          onCancel={() => setEditing(false)}
          onDone={() => {
            setEditing(false)
            setSaved(true)
          }}
        />
      ) : (
        <div className="member__card">
          <dl className="member__fields">
            {fields.data.map((field) => (
              <div key={field.key} className="member__field">
                <dt className="member__detail">
                  {field.label}
                  {field.sensitive && <span className="member__tag">{copy.sensitive}</span>}
                </dt>
                <dd className={field.value === null ? 'member__detail' : undefined}>{shown(field)}</dd>
              </div>
            ))}
          </dl>
          {saved && (
            <p className="member__done" role="status">
              {copy.saved}
            </p>
          )}
          <div className="member__actions">
            <Button
              onClick={() => {
                setSaved(false)
                setEditing(true)
              }}
            >
              {copy.edit}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}

function shown(field: PersonField): string {
  if (field.value === null) return copy.empty
  if (field.type === 'date') return t.common.day(String(field.value))
  if (field.type === 'number') return Number(field.value).toLocaleString('es-CL')
  return String(field.value)
}

/** What an input holds, as text: a number as typed, a date as `YYYY-MM-DD`. */
function draftOf(field: PersonField): string {
  return field.value === null ? '' : String(field.value)
}

/** What a field's input sends: `null` for nothing typed, a number for a number field. */
export function valueOf(field: Pick<PersonField, 'type'>, draft: string): FieldValue {
  const text = draft.trim()
  if (!text) return null
  if (field.type !== 'number') return text
  // Not a number: sent as typed, for the API to refuse rather than to clear.
  const number = Number(text.replace(',', '.'))
  return Number.isNaN(number) ? text : number
}

function FieldsForm({
  personId,
  fields,
  onCancel,
  onDone,
}: {
  personId: string
  fields: PersonField[]
  onCancel: () => void
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const formId = useId()
  const [drafts, setDrafts] = useState(() => Object.fromEntries(fields.map((f) => [f.key, draftOf(f)])))

  const save = useMutation({
    mutationFn: (values: Record<string, FieldValue>) => updatePersonFields(personId, values),
    onSuccess: (answer) => {
      queryClient.setQueryData(personFieldsQuery(personId).queryKey, answer)
      onDone()
    },
  })
  const refused = new Set(refusedFields(save.error))

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // Only what changed, so a field someone else edited meanwhile is left as they left it.
    const changed = fields.filter((f) => drafts[f.key] !== draftOf(f))
    if (changed.length === 0) {
      onDone()
      return
    }
    save.mutate(Object.fromEntries(changed.map((f) => [f.key, valueOf(f, drafts[f.key] ?? '')])))
  }

  return (
    <form className="member__form" aria-label={copy.formTitle} onSubmit={submit}>
      {fields.map((field) => {
        const id = `${formId}-${field.key}`
        return (
          <Fragment key={field.key}>
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
          </Fragment>
        )
      })}

      {save.error && (
        <p className="member__error" role="alert">
          {refused.size > 0 ? copy.refused.invalid : copy.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? copy.working : copy.save}
        </Button>
      </div>
    </form>
  )
}

/** One custom field's input, by its type: a choice of its options, a number, a date or text. */
export function FieldInput({
  id,
  field,
  value,
  invalid,
  onChange,
}: {
  id: string
  field: Pick<PersonField, 'type' | 'options'>
  value: string
  invalid: boolean
  onChange: (value: string) => void
}) {
  const props = {
    id,
    value,
    'aria-invalid': invalid,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  }
  if (field.type === 'enum') {
    return (
      <Select {...props}>
        <option value="">{copy.choose}</option>
        {(field.options ?? []).map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </Select>
    )
  }
  if (field.type === 'number') return <Input {...props} type="text" inputMode="decimal" />
  if (field.type === 'date') return <Input {...props} type="date" />
  return <Input {...props} type="text" maxLength={1000} />
}
