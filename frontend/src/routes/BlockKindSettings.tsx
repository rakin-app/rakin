import { useQuery, useQueryClient } from '@tanstack/react-query'
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
import { useSparring } from '../api/activities'
import { ApiError } from '../api/client'
import { gymSettingsQuery, updateGymSettings } from '../api/gym'
import { myselfQuery } from '../api/me'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, LoadFailed, MoveButtons, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'
import { Banner, Card, cardClass, CheckRow, SectionTitle } from '../components/Card'

const copy = t.admin.settings.blocks
const form = copy.form

/**
 * "Bloques": the parts the coach's timer runs a class in (Calentamiento, Técnica,
 * Sparring…), in the order the timer offers them, and whether each one's time counts
 * as sparring. A kind no class has used yet can be deleted; one in use is deactivated
 * (archived, to the API), which keeps the time already recorded, and whether it is
 * sparring is then fixed. A row opens its edit form, which deactivates and deletes; the
 * row keeps its ↑ ↓.
 *
 * Above them, whether the gym spars at all (#346): off, the API archives Sparring and
 * Drilling, and the archived sparring kinds and every mention of sparring leave the
 * screen; on, they come back.
 */
export function BlockKindSettings() {
  const queryClient = useQueryClient()
  const kinds = useQuery(blockKindsQuery)
  const sparring = useSparring()
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reorder = useSubmit({
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

  if (kinds.isPending) return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  if (kinds.isError) {
    return <LoadFailed error={kinds.error} message={copy.error} retry={() => void kinds.refetch()} />
  }

  // The API lists archived kinds last, whatever their position: only the others move.
  const list = kinds.data
  const active = list.filter((k) => !k.archived)
  const shown = sparring ? list : list.filter((k) => !(k.archived && k.is_sparring))
  const move = (index: number, by: -1 | 1) => {
    const ids = active.map((k) => k.id)
    ;[ids[index], ids[index + by]] = [ids[index + by]!, ids[index]!]
    setNotice(null)
    reorder.mutate([...ids, ...list.filter((k) => k.archived).map((k) => k.id)])
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
      <SparringSwitch
        on={sparring}
        onDone={(message) => {
          setEditing(null)
          setNotice(message)
        }}
      />
      {notice && (
        <Banner tone="done">
          {notice}
        </Banner>
      )}
      {editing === 'new' && <BlockKindForm onCancel={() => setEditing(null)} onDone={done} />}
      {reorder.isError && (
        <Banner tone="error">
          {copy.reorderFailed}
        </Banner>
      )}
      {shown.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <Card as="ul" flush className="settings__card settings__card--rows settings__menu">
          {shown.map((kind) => {
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
                    {sparring && kind.is_sparring && <span className="settings__tag">{copy.sparring}</span>}
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
        </Card>
      )}
    </section>
  )
}

/** "El dojo hace randori": saved as soon as it changes, with what it did said below. */
function SparringSwitch({ on, onDone }: { on: boolean; onDone: (message: string) => void }) {
  const queryClient = useQueryClient()
  const save = useSubmit({
    mutationFn: (next: boolean) => updateGymSettings({ sparring: next }),
    onSuccess: async (answer) => {
      onDone(answer.sparring ? copy.sparringOn : copy.sparringOff)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: myselfQuery().queryKey }),
        queryClient.invalidateQueries({ queryKey: gymSettingsQuery().queryKey }),
        queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey }),
      ])
    },
  })
  return (
    <Card className="settings__card settings__field">
      <CheckRow start>
        <input
          type="checkbox"
          checked={save.isPending ? save.variables : on}
          disabled={save.isPending}
          onChange={(e) => save.mutate(e.target.checked)}
        />
        {copy.sparringSwitch}
      </CheckRow>
      <p className="settings__hint">{copy.sparringSwitchHint}</p>
      {save.isError && <Banner tone="error">{copy.toggleFailed}</Banner>}
    </Card>
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
  const spars = useSparring()
  const [name, setName] = useState(kind?.name ?? '')
  const [sparring, setSparring] = useState(kind?.is_sparring ?? false)

  // An edit sends only what changed; the API trims the name, so whitespace alone changes nothing.
  const changes = (): BlockKindChanges => {
    const out: BlockKindChanges = {}
    if (name.trim() !== kind?.name) out.name = name.trim()
    if (sparring !== kind?.is_sparring) out.is_sparring = sparring
    return out
  }

  const save = useSubmit({
    mutationFn: () => (kind ? updateBlockKind(kind.id, changes()) : createBlockKind({ name, is_sparring: sparring })),
    onSuccess: async (answer) => {
      onDone(kind ? copy.saved(answer.name) : copy.created(answer.name))
      await queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey })
    },
  })
  // Deactivating and deleting are in the form, not on the row (#177): the row keeps its moves.
  const toggle = useSubmit({
    mutationFn: () => updateBlockKind(kind!.id, { archived: !kind!.archived }),
    onSuccess: async (answer) => {
      onDone(answer.archived ? copy.archivedDone(answer.name) : copy.restored(answer.name))
      await queryClient.invalidateQueries({ queryKey: blockKindsQuery.queryKey })
    },
  })
  const remove = useSubmit({
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
    <form className={cardClass({}, 'settings__card settings__form')} aria-label={label} onSubmit={submit} noValidate>
      <SectionTitle className="settings__legend">{label}</SectionTitle>
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
      {spars && (
        <div className="settings__field">
          <CheckRow>
            <input type="checkbox" checked={sparring} onChange={(e) => setSparring(e.target.checked)} />
            {form.sparring}
          </CheckRow>
          <p className="settings__hint">{form.sparringHint}</p>
        </div>
      )}
      {save.error && (
        <Banner tone="error">
          {inUse !== null ? form.sparringInUse(inUse) : taken || Object.keys(errors).length > 0 ? form.invalid : form.failed}
        </Banner>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {kind && (
        <div className="settings__danger">
          {remove.error && (
            <Banner tone="error">
              {removedInUse !== null ? copy.inUse(removedInUse) : form.failed}
            </Banner>
          )}
          {toggle.isError && (
            <Banner tone="error">
              {copy.toggleFailed}
            </Banner>
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
