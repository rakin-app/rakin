import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { classTypesQuery, createClassType, createProgram, updateClassType, updateProgram } from '../api/classes'
import { ApiError } from '../api/client'
import { programsQuery, type Program } from '../api/people'
import { CLASS_KINDS, type ClassKind, type ClassType } from '../api/sessions'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { ListRowContent, listRowClass } from '../components/Card'
import { Input, Select } from '../components/Field'
import { ChevronRightIcon } from '../components/icons'
import { t } from '../i18n/es'
import { EditRow, Field, integerOf, LoadFailed, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'

const copy = t.admin.settings.programs

// What is open: a create, or the edit of one program or class type.
type Editing = { kind: 'program'; id: string | 'new' } | { kind: 'classType'; id: string | 'new'; programId: string }

/** A save's refusal of `field`: a 409 is a name already taken, a 422 the field's own. */
function errorOf(error: Error | null, field: string, draft: string, taken: string): string | undefined {
  if (error instanceof ApiError && error.status === 409) return field === 'name' ? taken : undefined
  const errors = validationErrors(error)
  return field in errors ? refusal(errors[field]!, field, copy, draft.trim() === '') : undefined
}

function FormAlert({ error }: { error: Error | null }) {
  if (!error) return null
  const refused = (error instanceof ApiError && error.status === 409) || Object.keys(validationErrors(error)).length > 0
  return (
    <p className="settings__error" role="alert">
      {refused ? copy.invalid : copy.failed}
    </p>
  )
}

function FormActions({ pending, onCancel }: { pending: boolean; onCancel: () => void }) {
  return (
    <div className="settings__actions">
      <Button disabled={pending} onClick={onCancel}>
        {copy.cancel}
      </Button>
      <Button type="submit" variant="primary" disabled={pending} busy={pending}>
        {pending ? copy.working : copy.submit}
      </Button>
    </div>
  )
}

/**
 * "Programas y clases": the gym's programs, active ones first, each with its class
 * types and what an attendance of one costs a credits pack. Nothing is deleted: a
 * program or class type is deactivated, and what already points at it keeps it.
 */
export function ProgramSettings() {
  const programs = useQuery(programsQuery)
  const classTypes = useQuery(classTypesQuery)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (next: Editing) => {
    setNotice(null)
    setEditing(next)
  }
  const close = () => setEditing(null)
  const isOpen = (kind: Editing['kind'], id: string) => editing?.kind === kind && editing.id === id

  if (programs.isPending || classTypes.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (programs.isError || classTypes.isError) {
    const error = (programs.error ?? classTypes.error)!
    return (
      <LoadFailed
        error={error}
        message={copy.error}
        retry={() => void Promise.all([programs.refetch(), classTypes.refetch()])}
      />
    )
  }

  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead
        intro={t.admin.settings.descriptions.programs}
        action={
          !isOpen('program', 'new') && (
            <Button variant="primary" onClick={() => open({ kind: 'program', id: 'new' })}>
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
      {isOpen('program', 'new') && <ProgramForm onCancel={close} onDone={done} />}
      {programs.data.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <ul className="settings__list">
          {programs.data.map((program) => {
            const types = classTypes.data.filter((c) => c.program_id === program.id)
            return (
              <li
                key={program.id}
                className={
                  program.active
                    ? 'settings__card settings__card--rows'
                    : 'settings__card settings__card--rows settings__row--inactive'
                }
              >
                {isOpen('program', program.id) ? (
                  <ProgramForm program={program} onCancel={close} onDone={done} />
                ) : (
                  <h2 className="settings__row-heading">
                    <button
                      type="button"
                      className={listRowClass(true)}
                      onClick={() => open({ kind: 'program', id: program.id })}
                    >
                      <ListRowContent
                        title={
                          <>
                            {program.name}
                            {!program.active && <span className="settings__tag">{copy.inactive}</span>}
                          </>
                        }
                        trailing={<ChevronRightIcon />}
                      />
                    </button>
                  </h2>
                )}
                {types.length === 0 ? (
                  <p className="settings__detail settings__row-note">{copy.noClassTypes}</p>
                ) : (
                  <ul className="settings__menu settings__subrows" aria-label={copy.classTypesLabel(program.name)}>
                    {types.map((classType) =>
                      isOpen('classType', classType.id) ? (
                        <li key={classType.id}>
                          <ClassTypeForm
                            classType={classType}
                            programId={program.id}
                            programs={programs.data}
                            onCancel={close}
                            onDone={done}
                          />
                        </li>
                      ) : (
                        <EditRow
                          key={classType.id}
                          inactive={!classType.active}
                          title={
                            <>
                              {classType.name}
                              {!classType.active && <span className="settings__tag">{copy.inactive}</span>}
                            </>
                          }
                          detail={classTypeSummary(classType)}
                          onOpen={() => open({ kind: 'classType', id: classType.id, programId: program.id })}
                        />
                      ),
                    )}
                  </ul>
                )}
                {editing?.kind === 'classType' && editing.id === 'new' && editing.programId === program.id ? (
                  <ClassTypeForm programId={program.id} programs={programs.data} onCancel={close} onDone={done} />
                ) : (
                  // A deactivated program takes no new class types until it is reactivated.
                  program.active && (
                    <div className="settings__row-note">
                      <Button onClick={() => open({ kind: 'classType', id: 'new', programId: program.id })}>
                        {copy.addClassType}
                      </Button>
                    </div>
                  )
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

/** Deactivates or reactivates, then says so and reloads `queryKey`. */
function useToggle<T extends { name: string; active: boolean }>(
  mutationFn: () => Promise<T>,
  messages: { on: (name: string) => string; off: (name: string) => string },
  queryKey: readonly unknown[],
  onDone: (message: string) => void,
) {
  const queryClient = useQueryClient()
  return useSubmit({
    mutationFn,
    onSuccess: async (answer) => {
      onDone(answer.active ? messages.on(answer.name) : messages.off(answer.name))
      await queryClient.invalidateQueries({ queryKey })
    },
  })
}

function ProgramForm({
  program,
  onCancel,
  onDone,
}: {
  program?: Program
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(program?.name ?? '')
  const toggle = useToggle(
    () => updateProgram(program!.id, { active: !program!.active }),
    { on: copy.programReactivated, off: copy.programDeactivated },
    programsQuery.queryKey,
    onDone,
  )
  const save = useSubmit({
    mutationFn: () => (program ? updateProgram(program.id, { name }) : createProgram(name)),
    onSuccess: async (answer) => {
      onDone(program ? copy.programRenamed(answer.name) : copy.programCreated(answer.name))
      // Class types carry their program's name.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: programsQuery.queryKey }),
        queryClient.invalidateQueries({ queryKey: classTypesQuery.queryKey }),
      ])
    },
  })
  const label = program ? copy.programForm.rename(program.name) : copy.programForm.create

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (program && name === program.name) {
      onCancel()
      return
    }
    save.mutate()
  }

  return (
    <form className="settings__card settings__form" aria-label={label} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{label}</h2>
      <Field label={copy.programForm.name} error={errorOf(save.error, 'name', name, copy.programTaken)}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
      </Field>
      <FormAlert error={save.error} />
      <FormActions pending={save.isPending} onCancel={onCancel} />
      {program && (
        <ToggleActive
          active={program.active}
          pending={save.isPending || toggle.isPending}
          failed={toggle.isError}
          onToggle={() => toggle.mutate()}
        />
      )}
    </form>
  )
}

/** A class type's line: an open mat says so, then what it costs a pack, and if it does not count. */
function classTypeSummary(classType: ClassType): string {
  return [
    classType.kind === 'open_mat' && copy.openMat,
    copy.credits(classType.credit_cost),
    !classType.counts_as_class && copy.notCounted,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** Deactivating or reactivating, in an item's edit view (#177), with its own failure. */
function ToggleActive({
  active,
  pending,
  failed,
  onToggle,
}: {
  active: boolean
  pending: boolean
  failed: boolean
  onToggle: () => void
}) {
  return (
    <div className="settings__danger">
      {failed && (
        <p className="settings__error" role="alert">
          {copy.toggleFailed}
        </p>
      )}
      <Button variant={active ? 'danger' : 'secondary'} disabled={pending} onClick={onToggle}>
        {active ? copy.deactivate : copy.reactivate}
      </Button>
    </div>
  )
}

type ClassTypeDrafts = {
  name: string
  program_id: string
  credit_cost: string
  kind: ClassKind
  counts_as_class: boolean
}

const CLASS_TYPE_FIELDS = ['name', 'program_id', 'credit_cost', 'kind', 'counts_as_class'] as const

function ClassTypeForm({
  classType,
  programId,
  programs,
  onCancel,
  onDone,
}: {
  classType?: ClassType
  programId: string
  programs: Program[]
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.classTypeForm
  const toggle = useToggle(
    () => updateClassType(classType!.id, { active: !classType!.active }),
    { on: copy.classTypeReactivated, off: copy.classTypeDeactivated },
    classTypesQuery.queryKey,
    onDone,
  )
  const [initial] = useState<ClassTypeDrafts>(() => ({
    name: classType?.name ?? '',
    program_id: classType?.program_id ?? programId,
    credit_cost: String(classType?.credit_cost ?? 1),
    kind: classType?.kind ?? 'class',
    counts_as_class: classType?.counts_as_class ?? true,
  }))
  const [drafts, setDrafts] = useState(initial)
  const set = (field: keyof ClassTypeDrafts, value: string | boolean) => setDrafts({ ...drafts, [field]: value })

  // An edit sends only what changed, so a field someone else edited meanwhile is left as they left it.
  const fields = (keys: readonly (keyof ClassTypeDrafts)[]) =>
    Object.fromEntries(keys.map((key) => [key, key === 'credit_cost' ? integerOf(drafts[key]) : drafts[key]]))
  const changed = CLASS_TYPE_FIELDS.filter((k) => drafts[k] !== initial[k])

  const save = useSubmit({
    mutationFn: () =>
      classType
        ? updateClassType(classType.id, fields(changed))
        : createClassType(fields(CLASS_TYPE_FIELDS)),
    onSuccess: async (answer) => {
      onDone(classType ? copy.classTypeSaved(answer.name) : copy.classTypeCreated(answer.name))
      await queryClient.invalidateQueries({
        queryKey: classTypesQuery.queryKey,
      })
    },
  })
  const error = (field: 'name' | 'program_id' | 'credit_cost') =>
    errorOf(save.error, field, drafts[field], copy.classTypeTaken)

  // The gym's active programs, and the class type's own even if it was deactivated since.
  const choices = programs.filter((p) => p.active || p.id === initial.program_id)
  const programName = programs.find((p) => p.id === programId)?.name ?? ''
  const label = classType ? form.edit(classType.name) : form.create(programName)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (classType && changed.length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  return (
    <form className="settings__card settings__form" aria-label={label} onSubmit={submit} noValidate>
      <h3 className="settings__legend">{label}</h3>
      <Field label={form.name} error={error('name')}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            value={drafts.name}
            onChange={(e) => set('name', e.target.value)}
          />
        )}
      </Field>
      <Field label={form.program} error={error('program_id')}>
        {(props) => (
          <Select
            {...props}
            value={drafts.program_id}
            onChange={(e) => set('program_id', e.target.value)}
          >
            {choices.map((p) => (
              <option key={p.id} value={p.id}>
                {p.active ? p.name : form.inactiveProgram(p.name)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={form.creditCost} hint={form.creditCostHint} error={error('credit_cost')}>
        {(props) => (
          <Input
            {...props}
            type="text"
            inputMode="numeric"
            value={drafts.credit_cost}
            onChange={(e) => set('credit_cost', e.target.value)}
          />
        )}
      </Field>
      <Field label={form.kind} hint={form.kindHint}>
        {(props) => (
          <Select
            {...props}
            value={drafts.kind}
            // As the API does: a class counts as a class by default, an open mat does not.
            onChange={(e) => {
              const kind = e.target.value as ClassKind
              setDrafts({ ...drafts, kind, counts_as_class: kind === 'class' })
            }}
          >
            {CLASS_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {form.kinds[kind]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <div className="settings__field">
        <label className="settings__check">
          <input
            type="checkbox"
            checked={drafts.counts_as_class}
            onChange={(e) => set('counts_as_class', e.target.checked)}
          />
          {form.countsAsClass}
        </label>
        <p className="settings__hint">{form.countsAsClassHint}</p>
      </div>
      <FormAlert error={save.error} />
      <FormActions pending={save.isPending} onCancel={onCancel} />
      {classType && (
        <ToggleActive
          active={classType.active}
          pending={save.isPending || toggle.isPending}
          failed={toggle.isError}
          onToggle={() => toggle.mutate()}
        />
      )}
    </form>
  )
}
