import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  blockKindsQuery,
  blocksInUse,
  createBlockKind,
  deleteBlockKind,
  reorderBlockKinds,
  updateBlockKind,
  type BlockKind,
  type BlockKindChanges,
} from '../api/blockKinds'
import { ApiError } from '../api/client'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, MoveButtons, refusal } from './settingsForm'

const copy = t.admin.settings.blocks
const form = copy.form

/**
 * "Bloques": the parts the coach's timer runs a class in (Calentamiento, Técnica,
 * Sparring…), in the order the timer offers them, and whether each one's time counts
 * as sparring. A kind no class has used yet can be deleted; one in use is deactivated
 * (archived, to the API), which keeps the time already recorded, and whether it is
 * sparring is then fixed. A row opens its edit form, which deactivates and deletes; the
 * row keeps its ↑ ↓.
 */
export function BlockKindSettings() {
  const queryClient = useQueryClient()
  const kinds = useQuery(blockKindsQuery)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reorder = useMutation({
    mutationFn: reorderBlockKinds,
    onSuccess: (answer) => queryClient.setQueryData(blockKindsQuery.queryKey, answer),
    // Most likely someone added or removed a kind meanwhile: show the list as it is.
    onError: () => queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey }),
  })

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (id: string | 'new') => {
    setNotice(null)
    setEditing(id)
  }

  if (kinds.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (kinds.isError) {
    return <LoadFailed error={kinds.error} message={copy.error} retry={() => void kinds.refetch()} />
  }

  // The API lists archived kinds last, whatever their position: only the others move.
  const list = kinds.data
  const active = list.filter((k) => !k.archived)
  const move = (index: number, by: -1 | 1) => {
    const ids = active.map((k) => k.id)
    ;[ids[index], ids[index + by]] = [ids[index + by]!, ids[index]!]
    setNotice(null)
    reorder.mutate([...ids, ...list.filter((k) => k.archived).map((k) => k.id)])
  }

  return (
    <section className="settings__section" aria-label={copy.title}>
      <p className="settings__note">{copy.intro}</p>
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {editing === 'new' ? (
        <BlockKindForm onCancel={() => setEditing(null)} onDone={done} />
      ) : (
        <Button variant="primary" onClick={() => open('new')}>
          {copy.add}
        </Button>
      )}
      {reorder.isError && (
        <p className="settings__error" role="alert">
          {copy.reorderFailed}
        </p>
      )}
      {list.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <ul className="settings__card settings__card--rows settings__menu">
          {list.map((kind) => {
            const index = active.indexOf(kind)
            return editing === kind.id ? (
              <li key={kind.id}>
                <BlockKindForm kind={kind} onCancel={() => setEditing(null)} onDone={done} />
              </li>
            ) : (
              <EditRow
                key={kind.id}
                inactive={kind.archived}
                title={
                  <>
                    {kind.name}
                    {kind.is_sparring && <span className="settings__tag">{copy.sparring}</span>}
                    {kind.archived && <span className="settings__tag">{copy.archived}</span>}
                  </>
                }
                onOpen={() => open(kind.id)}
                controls={
                  // Archived kinds sit last, out of the timer's order: only the others move.
                  !kind.archived && (
                    <MoveButtons
                      up={copy.up(kind.name)}
                      down={copy.down(kind.name)}
                      first={index === 0}
                      last={index === active.length - 1}
                      disabled={reorder.isPending}
                      onMove={(by) => move(index, by)}
                    />
                  )
                }
              />
            )
          })}
        </ul>
      )}
    </section>
  )
}

function BlockKindForm({
  kind,
  onCancel,
  onDone,
}: {
  kind?: BlockKind
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(kind?.name ?? '')
  const [sparring, setSparring] = useState(kind?.is_sparring ?? false)

  // An edit sends only what changed; the API trims the name, so whitespace alone changes nothing.
  const changes = (): BlockKindChanges => {
    const out: BlockKindChanges = {}
    if (name.trim() !== kind?.name) out.name = name.trim()
    if (sparring !== kind?.is_sparring) out.is_sparring = sparring
    return out
  }

  const save = useMutation({
    mutationFn: () => (kind ? updateBlockKind(kind.id, changes()) : createBlockKind({ name, is_sparring: sparring })),
    onSuccess: async (answer) => {
      onDone(kind ? copy.saved(answer.name) : copy.created(answer.name))
      await queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey })
    },
  })
  // Deactivating and deleting are in the form, not on the row (#177): the row keeps its moves.
  const toggle = useMutation({
    mutationFn: () => updateBlockKind(kind!.id, { archived: !kind!.archived }),
    onSuccess: async (answer) => {
      onDone(answer.archived ? copy.archivedDone(answer.name) : copy.restored(answer.name))
      await queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey })
    },
  })
  const remove = useMutation({
    mutationFn: () => deleteBlockKind(kind!.id),
    onSuccess: async () => {
      onDone(copy.deleted(kind!.name))
      await queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey })
    },
  })
  const removedInUse = blocksInUse(remove.error)
  const inUse = blocksInUse(save.error)
  const taken = save.error instanceof ApiError && save.error.status === 409 && inUse === null
  const errors = validationErrors(save.error)
  const nameError = taken
    ? form.taken
    : 'name' in errors
      ? refusal(errors['name']!, 'name', form, name.trim() === '')
      : undefined

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (kind && Object.keys(changes()).length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  const label = kind ? form.edit(kind.name) : form.create
  return (
    <form className="settings__card settings__form" aria-label={label} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{label}</h2>
      <Field label={form.name} error={nameError}>
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
      <div className="settings__field">
        <label className="settings__check">
          <input type="checkbox" checked={sparring} onChange={(e) => setSparring(e.target.checked)} />
          {form.sparring}
        </label>
        <p className="settings__hint">{form.sparringHint}</p>
      </div>
      {save.error && (
        <p className="settings__error" role="alert">
          {inUse !== null ? form.sparringInUse(inUse) : taken || Object.keys(errors).length > 0 ? form.invalid : form.failed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {kind && (
        <div className="settings__danger">
          {remove.error && (
            <p className="settings__error" role="alert">
              {removedInUse !== null ? copy.inUse(removedInUse) : form.failed}
            </p>
          )}
          {toggle.isError && (
            <p className="settings__error" role="alert">
              {copy.toggleFailed}
            </p>
          )}
          <Button
            variant={kind.archived ? 'secondary' : 'danger'}
            disabled={save.isPending || toggle.isPending || remove.isPending}
            onClick={() => toggle.mutate()}
          >
            {kind.archived ? copy.restore : copy.archive}
          </Button>
          <Button
            variant="danger"
            disabled={save.isPending || toggle.isPending || remove.isPending}
            onClick={() => remove.mutate()}
          >
            {copy.delete}
          </Button>
        </div>
      )}
    </form>
  )
}
