import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  createField,
  customFieldsQuery,
  optionsInUse,
  reorderFields,
  updateField,
  VISIBLE_TO,
  type FieldChanges,
  type FieldDefinition,
  type FieldType,
  type VisibleTo,
} from '../api/customFields'
import { myRoleQuery } from '../api/me'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input, Select, Textarea } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, MoveButtons, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'

const copy = t.admin.settings.fields
const form = copy.form

const FIELD_TYPES: readonly FieldType[] = ['text', 'number', 'date', 'enum']

/** The definitions changed: the list, and every member's Datos, which show them. */
async function refresh(queryClient: QueryClient) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: customFieldsQuery.queryKey }),
    queryClient.invalidateQueries({ queryKey: ['people', 'fields'] }),
  ])
}

function summary(field: FieldDefinition, owner: boolean): string {
  const type = field.type === 'enum' ? copy.row(copy.types.enum, (field.options ?? []).join(', ')) : copy.types[field.type]
  // Who sees it is the owner's to set, and theirs to read.
  return owner ? copy.row(type, copy.visibleTo[field.visible_to]) : type
}

/**
 * "Campos": the gym's custom fields on a member, in the order the member's Datos shows
 * them, and the forms that define, reorder and deactivate them. There is no delete: a
 * deactivated (archived) field keeps its values but is not shown. A row opens its form,
 * which deactivates it; the row keeps its ↑ ↓. Only the owner sees and sets
 * whether a field is sensitive and who sees it; an admin is answered only the fields
 * they may see, and the form leaves both out, as the API refuses them from an admin.
 */
export function FieldSettings() {
  const queryClient = useQueryClient()
  const fields = useQuery(customFieldsQuery)
  const owner = useQuery(myRoleQuery()).data === 'owner'
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reorder = useSubmit({
    mutationFn: reorderFields,
    onSuccess: async (answer) => {
      queryClient.setQueryData(customFieldsQuery.queryKey, answer)
      await queryClient.invalidateQueries({ queryKey: ['people', 'fields'] })
    },
    // Most likely someone added or archived a field meanwhile: show the list as it is.
    onError: () => refresh(queryClient),
  })

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (key: string | 'new') => {
    setNotice(null)
    setEditing(key)
  }

  if (fields.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (fields.isError) {
    return <LoadFailed error={fields.error} message={copy.error} retry={() => void fields.refetch()} />
  }

  const list = fields.data
  const move = (index: number, by: -1 | 1) => {
    const keys = list.map((f) => f.key)
    ;[keys[index], keys[index + by]] = [keys[index + by]!, keys[index]!]
    setNotice(null)
    reorder.mutate(keys)
  }

  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead
        intro={copy.intro}
        action={
          editing !== 'new' && (
            <Button variant="primary" onClick={() => open('new')}>
              {copy.add}
            </Button>
          )
        }
      />
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {editing === 'new' && <FieldForm owner={owner} onCancel={() => setEditing(null)} onDone={done} />}
      {reorder.isError && (
        <p className="settings__error" role="alert">
          {copy.reorderFailed}
        </p>
      )}
      {list.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <ul className="settings__card settings__card--rows settings__menu">
          {list.map((field, index) =>
            editing === field.key ? (
              <li key={field.key}>
                <FieldForm field={field} owner={owner} onCancel={() => setEditing(null)} onDone={done} />
              </li>
            ) : (
              <EditRow
                key={field.key}
                inactive={field.archived}
                title={
                  <>
                    {field.label}
                    {field.sensitive && <span className="settings__tag">{copy.sensitive}</span>}
                    {field.archived && <span className="settings__tag">{copy.archived}</span>}
                  </>
                }
                detail={summary(field, owner)}
                onOpen={() => open(field.key)}
                controls={
                  <MoveButtons
                    up={copy.up(field.label)}
                    down={copy.down(field.label)}
                    first={index === 0}
                    last={index === list.length - 1}
                    disabled={reorder.isPending}
                    onMove={(by) => move(index, by)}
                  />
                }
              />
            ),
          )}
        </ul>
      )}
    </section>
  )
}

type Drafts = { label: string; type: FieldType; options: string; sensitive: boolean; visible_to: VisibleTo }

function draftsOf(field: FieldDefinition | undefined): Drafts {
  return {
    label: field?.label ?? '',
    type: field?.type ?? 'text',
    options: (field?.options ?? []).join('\n'),
    sensitive: field?.sensitive ?? false,
    visible_to: field?.visible_to ?? 'staff',
  }
}

/** The options as typed, one per line, blank lines dropped. */
function optionsOf(draft: string): string[] {
  return draft
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

/** What the API's 422 on the options means: the list's own refusal, else its first option's. */
function optionsRefusal(errors: Record<string, string>): string | undefined {
  const list = errors['options']
  if (list === 'too_short') return form.optionsRequired
  if (list === 'too_long') return form.optionsTooMany
  if (list !== undefined) return refusal(list, 'options', form, false)
  const option = Object.keys(errors).find((key) => key.startsWith('options.'))
  if (option === undefined) return undefined
  return errors[option] === 'string_too_long' ? form.optionTooLong : refusal(errors[option]!, 'options', form, false)
}

function FieldForm({
  field,
  owner,
  onCancel,
  onDone,
}: {
  field?: FieldDefinition
  owner: boolean
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  // Deactivating is here, not on the row (#177): the row keeps its moves.
  const toggle = useSubmit({
    mutationFn: () => updateField(field!.key, { archived: !field!.archived }),
    onSuccess: async (answer) => {
      onDone(answer.archived ? copy.archivedDone(answer.label) : copy.restored(answer.label))
      await refresh(queryClient)
    },
  })
  const [initial] = useState(() => draftsOf(field))
  const [drafts, setDrafts] = useState(initial)
  const enumField = drafts.type === 'enum'

  // An edit sends only what changed; an admin never sends what is the owner's to set.
  const changes = (): FieldChanges => {
    const out: FieldChanges = {}
    // The API trims the label, so whitespace alone changes nothing.
    if (drafts.label.trim() !== initial.label.trim()) out.label = drafts.label.trim()
    if (enumField && optionsOf(drafts.options).join('\n') !== optionsOf(initial.options).join('\n')) {
      out.options = optionsOf(drafts.options)
    }
    if (owner && drafts.sensitive !== initial.sensitive) out.sensitive = drafts.sensitive
    if (owner && drafts.visible_to !== initial.visible_to) out.visible_to = drafts.visible_to
    return out
  }

  const save = useSubmit({
    mutationFn: () =>
      field
        ? updateField(field.key, changes())
        : createField({
            label: drafts.label,
            type: drafts.type,
            ...(enumField && { options: optionsOf(drafts.options) }),
            ...(owner && { sensitive: drafts.sensitive, visible_to: drafts.visible_to }),
          }),
    onSuccess: async (answer) => {
      onDone(field ? copy.saved(answer.label) : copy.created(answer.label))
      await refresh(queryClient)
    },
  })
  const errors = validationErrors(save.error)
  const inUse = optionsInUse(save.error)
  const labelError = 'label' in errors ? refusal(errors['label']!, 'label', form, drafts.label.trim() === '') : undefined
  const optionsError = optionsRefusal(errors)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // An edit that changed nothing has nothing to send: the form just closes.
    if (field && Object.keys(changes()).length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  return (
    <form className="settings__card settings__form" aria-label={field ? form.edit(field.label) : form.create} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{field ? form.edit(field.label) : form.create}</h2>
      <Field label={form.label} error={labelError}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={80}
            value={drafts.label}
            onChange={(e) => setDrafts({ ...drafts, label: e.target.value })}
          />
        )}
      </Field>
      <Field label={form.type} hint={field ? undefined : form.typeHint}>
        {(props) => (
          <Select
            {...props}
            value={drafts.type}
            // The type is set on create, as the API has it.
            disabled={field !== undefined}
            onChange={(e) => {
              setDrafts({ ...drafts, type: e.target.value as FieldType })
              save.reset()
            }}
          >
            {FIELD_TYPES.map((type) => (
              <option key={type} value={type}>
                {copy.types[type]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {enumField && (
        <Field label={form.options} hint={form.optionsHint} error={optionsError}>
          {(props) => (
            <Textarea
              {...props}
              rows={4}
              value={drafts.options}
              onChange={(e) => setDrafts({ ...drafts, options: e.target.value })}
            />
          )}
        </Field>
      )}
      {owner && (
        <>
          <div className="settings__field">
            <label className="settings__check">
              <input
                type="checkbox"
                checked={drafts.sensitive}
                onChange={(e) =>
                  setDrafts({
                    ...drafts,
                    sensitive: e.target.checked,
                    // As the API does: a field marked sensitive is narrowed to the owner unless told otherwise.
                    visible_to: e.target.checked && !drafts.sensitive ? 'owner' : drafts.visible_to,
                  })
                }
              />
              {form.sensitive}
            </label>
            <p className="settings__hint">{form.sensitiveHint}</p>
          </div>
          <Field label={form.visibleTo}>
            {(props) => (
              <Select
                {...props}
                value={drafts.visible_to}
                onChange={(e) => setDrafts({ ...drafts, visible_to: e.target.value as VisibleTo })}
              >
                {VISIBLE_TO.map((v) => (
                  <option key={v} value={v}>
                    {copy.visibleTo[v]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </>
      )}

      {save.error && (
        <p className="settings__error" role="alert">
          {inUse ? form.inUse(inUse) : Object.keys(errors).length > 0 ? form.invalid : form.failed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {field && (
        <div className="settings__danger">
          {toggle.isError && (
            <p className="settings__error" role="alert">
              {copy.toggleFailed}
            </p>
          )}
          <Button
            variant={field.archived ? 'secondary' : 'danger'}
            disabled={save.isPending || toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {field.archived ? copy.restore : copy.archive}
          </Button>
        </div>
      )}
    </form>
  )
}
