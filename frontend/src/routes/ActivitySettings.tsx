import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type KeyboardEvent } from 'react'
import {
  ACTIVITY_PRESETS,
  activitiesQuery,
  createActivity,
  deleteActivity,
  updateActivity,
  type Activity,
} from '../api/activities'
import { ApiError } from '../api/client'
import { myselfQuery } from '../api/me'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { Field } from './settingsForm'

const copy = t.admin.settings.gym.activities

// The select's value for a name the gym writes itself.
const OTHER = '__other__'

type Change =
  | { kind: 'grades'; activity: Activity; usesGrades: boolean }
  | { kind: 'rename'; activity: Activity; name: string }
  | { kind: 'remove'; activity: Activity }

function messageOf(change: Change, answer: Activity | void): string {
  switch (change.kind) {
    case 'grades':
      return change.usesGrades ? copy.gradesOn(change.activity.name) : copy.gradesOff(change.activity.name)
    case 'rename':
      return copy.renamed(answer ? answer.name : change.name)
    case 'remove':
      return copy.removed(change.activity.name)
  }
}

function run(change: Change): Promise<Activity | void> {
  switch (change.kind) {
    case 'grades':
      return updateActivity(change.activity.id, { uses_grades: change.usesGrades })
    case 'rename':
      return updateActivity(change.activity.id, { name: change.name })
    case 'remove':
      return deleteActivity(change.activity.id)
  }
}

const taken = (error: unknown) => error instanceof ApiError && error.status === 409

/**
 * "Actividades" in Ajustes › Gimnasio (#245): what the gym teaches, one or more, from
 * the presets or named by the gym, each with whether it grades. While one does, the
 * belts and ranks show everywhere (`useGrades`); with none, nowhere. Each change is
 * saved on its own, not with the form's "Guardar", as the logo is (#241).
 */
export function ActivitySettings() {
  const activities = useQuery(activitiesQuery)
  const [notice, setNotice] = useState<string | null>(null)

  return (
    <fieldset className="settings__card" id="actividades">
      <legend className="settings__legend">{copy.title}</legend>
      <p className="settings__hint">{copy.hint}</p>
      {activities.isPending ? (
        <p className="settings__note">{t.admin.settings.loading}</p>
      ) : activities.isError ? (
        <div className="settings__preview">
          <p className="settings__error" role="alert">
            {copy.error}
          </p>
          <Button onClick={() => void activities.refetch()}>{t.admin.settings.retry}</Button>
        </div>
      ) : (
        <ActivityList activities={activities.data} onDone={setNotice} />
      )}
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
    </fieldset>
  )
}

function useRefresh() {
  const queryClient = useQueryClient()
  // `uses_grades` rides on who is signed in, which every screen reads.
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: activitiesQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: myselfQuery().queryKey }),
      queryClient.invalidateQueries({ queryKey: ['class-types'] }),
    ])
}

function ActivityList({ activities, onDone }: { activities: Activity[]; onDone: (message: string | null) => void }) {
  const refresh = useRefresh()
  const [renaming, setRenaming] = useState<string | null>(null)
  const change = useSubmit({
    mutationFn: run,
    onSuccess: async (answer, variables) => {
      setRenaming(null)
      onDone(messageOf(variables, answer))
      await refresh()
    },
  })
  const pending = change.isPending ? change.variables : undefined
  const busy = (activity: Activity) => pending?.activity.id === activity.id

  return (
    <>
      {activities.length === 0 ? (
        <p className="settings__note">{copy.none}</p>
      ) : (
        <ul className="activities">
          {activities.map((activity) => (
            <li key={activity.id} className="activities__item">
              {renaming === activity.id ? (
                <RenameForm
                  activity={activity}
                  busy={busy(activity)}
                  error={change.error && change.variables?.activity.id === activity.id ? change.error : null}
                  onCancel={() => {
                    change.reset()
                    setRenaming(null)
                  }}
                  onSave={(name) => change.mutate({ kind: 'rename', activity, name })}
                />
              ) : (
                <>
                  <span className="activities__name">
                    {activity.name}
                    {activity.class_types > 0 && (
                      <span className="activities__detail">{copy.classTypes(activity.class_types)}</span>
                    )}
                  </span>
                  <label className="settings__check activities__grades">
                    <input
                      type="checkbox"
                      checked={pending?.kind === 'grades' && busy(activity) ? pending.usesGrades : activity.uses_grades}
                      disabled={busy(activity)}
                      onChange={(e) => change.mutate({ kind: 'grades', activity, usesGrades: e.target.checked })}
                    />
                    <span>{copy.usesGrades}</span>
                  </label>
                  <span className="activities__actions">
                    <Button
                      disabled={busy(activity)}
                      onClick={() => {
                        change.reset()
                        onDone(null)
                        setRenaming(activity.id)
                      }}
                    >
                      {copy.rename}
                    </Button>
                    <Button
                      variant="danger"
                      aria-label={copy.removeLabel(activity.name)}
                      disabled={busy(activity)}
                      busy={pending?.kind === 'remove' && busy(activity)}
                      onClick={() => {
                        if (window.confirm(copy.removeConfirm(activity.name, activity.class_types))) {
                          change.mutate({ kind: 'remove', activity })
                        }
                      }}
                    >
                      {copy.remove}
                    </Button>
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {change.isError && change.variables?.kind !== 'rename' && (
        <p className="settings__error" role="alert">
          {copy.failed}
        </p>
      )}
      <AddActivity activities={activities} onDone={onDone} />
    </>
  )
}

function RenameForm({
  activity,
  busy,
  error,
  onCancel,
  onSave,
}: {
  activity: Activity
  busy: boolean
  error: Error | null
  onCancel: () => void
  onSave: (name: string) => void
}) {
  const [name, setName] = useState(activity.name)
  const save = () => {
    if (name.trim() === activity.name) onCancel()
    else onSave(name.trim())
  }
  const fieldError = name.trim() === '' && error ? copy.required : taken(error) ? copy.taken : undefined
  return (
    <div className="activities__rename">
      <Field label={copy.renameLabel(activity.name)} error={fieldError}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={onEnter(save)}
          />
        )}
      </Field>
      {error && !fieldError && (
        <p className="settings__error" role="alert">
          {copy.failed}
        </p>
      )}
      <span className="activities__actions">
        <Button disabled={busy} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button variant="primary" disabled={busy} busy={busy} onClick={save}>
          {copy.save}
        </Button>
      </span>
    </div>
  )
}

/** Enter in a field here does its own action, not the Gimnasio form's "Guardar". */
function onEnter(action: () => void) {
  return (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter') return
    event.preventDefault()
    action()
  }
}

/** A preset not yet added, or "Otra" with a name; its "Usa grados" starts at the preset's. */
function AddActivity({ activities, onDone }: { activities: Activity[]; onDone: (message: string | null) => void }) {
  const refresh = useRefresh()
  const gradesId = useId()
  const have = new Set(activities.map((a) => a.name.toLowerCase()))
  const presets = ACTIVITY_PRESETS.filter((p) => !have.has(p.name.toLowerCase()))
  const [choice, setChoice] = useState('')
  const [name, setName] = useState('')
  const [usesGrades, setUsesGrades] = useState(false)

  const add = useSubmit({
    mutationFn: createActivity,
    onSuccess: async (answer) => {
      setChoice('')
      setName('')
      setUsesGrades(false)
      onDone(copy.added(answer.name))
      await refresh()
    },
  })
  const other = choice === OTHER
  const chosenName = other ? name.trim() : choice
  const pick = (value: string) => {
    add.reset()
    onDone(null)
    setChoice(value)
    setUsesGrades(ACTIVITY_PRESETS.find((p) => p.name === value)?.usesGrades ?? false)
  }
  const submit = () => {
    if (chosenName === '') return
    add.mutate({ name: chosenName, uses_grades: usesGrades })
  }
  const nameError = taken(add.error) ? copy.taken : undefined

  return (
    <div className="activities__add" role="group" aria-label={copy.add}>
      <Field label={copy.add}>
        {(props) => (
          <Select {...props} value={choice} onChange={(e) => pick(e.target.value)}>
            <option value="">{copy.pick}</option>
            {presets.map((preset) => (
              <option key={preset.name} value={preset.name}>
                {preset.name}
              </option>
            ))}
            <option value={OTHER}>{copy.other}</option>
          </Select>
        )}
      </Field>
      {other && (
        <Field label={copy.name} error={nameError}>
          {(props) => (
            <Input
              {...props}
              type="text"
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={onEnter(submit)}
            />
          )}
        </Field>
      )}
      {choice !== '' && (
        <>
          <label className="settings__check" htmlFor={gradesId}>
            <input
              id={gradesId}
              type="checkbox"
              checked={usesGrades}
              onChange={(e) => setUsesGrades(e.target.checked)}
            />
            <span>{copy.usesGrades}</span>
          </label>
          {/* A name taken shows under the name written; a preset's, here. */}
          {add.isError && !(other && nameError) && (
            <p className="settings__error" role="alert">
              {nameError ?? copy.failed}
            </p>
          )}
          <span className="activities__actions">
            <Button
              variant="primary"
              disabled={add.isPending || chosenName === ''}
              busy={add.isPending}
              onClick={submit}
            >
              {add.isPending ? copy.adding : copy.addSubmit}
            </Button>
          </span>
        </>
      )}
    </div>
  )
}
