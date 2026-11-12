import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { classTagsQuery, createClassTag, updateClassTag, type ClassTag } from '../api/classTags'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, refusal, SectionHead } from './settingsForm'

const copy = t.admin.settings.tags
const form = copy.form

/**
 * "Etiquetas" (#243): the gym's recurring focuses ("Pasaje de guardia", "Fuerza"), which
 * a class's coach puts on it beside its topic, and which the schedule's classes start
 * with. Each adds up the hours of its classes, for the gym and for each student. A tag
 * is archived, never deleted: it stays on the classes that have it and still counts,
 * and goes on no new one. A row opens its edit form, which archives it.
 */
export function ClassTagSettings() {
  const tags = useQuery(classTagsQuery)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (id: string | 'new') => {
    setNotice(null)
    setEditing(id)
  }

  if (tags.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (tags.isError) {
    return <LoadFailed error={tags.error} message={copy.error} retry={() => void tags.refetch()} />
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
      {editing === 'new' && <ClassTagForm onCancel={() => setEditing(null)} onDone={done} />}
      {tags.data.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <ul className="settings__card settings__card--rows settings__menu">
          {tags.data.map((tag) =>
            editing === tag.id ? (
              <li key={tag.id}>
                <ClassTagForm tag={tag} onCancel={() => setEditing(null)} onDone={done} />
              </li>
            ) : (
              <EditRow
                key={tag.id}
                inactive={tag.archived}
                title={
                  <>
                    {tag.name}
                    {tag.archived && <span className="settings__tag">{copy.archived}</span>}
                  </>
                }
                onOpen={() => open(tag.id)}
              />
            ),
          )}
        </ul>
      )}
    </section>
  )
}

function ClassTagForm({
  tag,
  onCancel,
  onDone,
}: {
  tag?: ClassTag
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(tag?.name ?? '')
  const refresh = () => queryClient.invalidateQueries({ queryKey: classTagsQuery.queryKey })

  const save = useSubmit({
    mutationFn: () => (tag ? updateClassTag(tag.id, { name: name.trim() }) : createClassTag({ name })),
    onSuccess: async (answer) => {
      onDone(tag ? copy.saved(answer.name) : copy.created(answer.name))
      await refresh()
    },
  })
  const toggle = useSubmit({
    mutationFn: () => updateClassTag(tag!.id, { archived: !tag!.archived }),
    onSuccess: async (answer) => {
      onDone(answer.archived ? copy.archivedDone(answer.name) : copy.restored(answer.name))
      await refresh()
    },
  })
  const taken = save.error instanceof ApiError && save.error.status === 409
  const errors = validationErrors(save.error)
  const nameError = taken
    ? form.taken
    : 'name' in errors
      ? refusal(errors['name']!, 'name', form, name.trim() === '')
      : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // The API trims the name, so whitespace alone changes nothing.
    if (tag && name.trim() === tag.name) {
      onCancel()
      return
    }
    save.mutate()
  }

  const label = tag ? form.edit(tag.name) : form.create
  return (
    <form className="settings__card settings__form" aria-label={label} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{label}</h2>
      <Field label={form.name} hint={form.nameHint} error={nameError}>
        {(props) => (
          <Input {...props} type="text" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        )}
      </Field>
      {save.error && (
        <p className="settings__error" role="alert">
          {taken || Object.keys(errors).length > 0 ? form.invalid : form.failed}
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
      {tag && (
        <div className="settings__danger">
          {toggle.isError && (
            <p className="settings__error" role="alert">
              {copy.toggleFailed}
            </p>
          )}
          <p className="settings__hint">{tag.archived ? copy.restoreHint : copy.archiveHint}</p>
          <Button
            variant={tag.archived ? 'secondary' : 'danger'}
            disabled={save.isPending || toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {tag.archived ? copy.restore : copy.archive}
          </Button>
        </div>
      )}
    </form>
  )
}
