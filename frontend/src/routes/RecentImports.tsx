import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { myRoleQuery } from '../api/me'
import {
  alreadyUndone,
  recentImportsQuery,
  undoCountsQuery,
  undoImport,
  type RecentImport,
} from '../api/memberImport'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { Banner, PlainList } from '../components/Card'

const copy = t.admin.import

/**
 * Importar's recent imports (#300), newest first: the file, who and when, and what each
 * wrote. The owner can undo one, with a reason: its history payments and grades go, and
 * the fields it set go back to what it found, unless changed since. The people and plans
 * it created stay. Nothing shows until the gym has imported.
 */
export function RecentImports() {
  const recent = useQuery(recentImportsQuery())
  const role = useQuery(myRoleQuery())
  const [open, setOpen] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  if (!recent.data || recent.data.length === 0) return null
  return (
    <section className="import__card" aria-labelledby="import-recent-title">
      <h2 id="import-recent-title" className="import__title">
        {copy.recentTitle}
      </h2>
      <p className="import__note">{copy.recentHint}</p>
      {done && (
        <p className="import__summary" role="status">
          {copy.undoDone}
        </p>
      )}
      <PlainList className="import__recent" aria-label={copy.recentTitle}>
        {recent.data.map((item) => (
          <li key={item.id} className="import__recent-row">
            <ImportLine item={item} />
            {role.data === 'owner' && !item.undone && open !== item.id && (
              <Button
                variant="danger"
                onClick={() => {
                  setDone(false)
                  setOpen(item.id)
                }}
              >
                {copy.undo}
              </Button>
            )}
            {open === item.id && (
              <UndoForm
                item={item}
                onCancel={() => setOpen(null)}
                onDone={() => {
                  setOpen(null)
                  setDone(true)
                }}
              />
            )}
          </li>
        ))}
      </PlainList>
    </section>
  )
}

function ImportLine({ item }: { item: RecentImport }) {
  const { alumnos, pagos, grados } = item.counts
  return (
    <>
      <span className="import__error-who">{item.file_name ?? copy.unnamedFile}</span>
      <span className="import__note">{copy.recentWho(item.by, shortDay(item.at))}</span>
      <span className="import__note">
        {copy.recentCounts(
          alumnos?.people_created ?? 0,
          alumnos?.history_set ?? 0,
          pagos?.payments_created ?? 0,
          grados?.grades_created ?? 0,
        )}
      </span>
      {item.undone && (
        <span className="import__kept-what">
          {copy.undone(shortDay(item.undone.at), item.undone.by, item.undone.reason)}
        </span>
      )}
    </>
  )
}

function UndoForm({ item, onCancel, onDone }: { item: RecentImport; onCancel: () => void; onDone: () => void }) {
  const form = copy.undoForm
  const queryClient = useQueryClient()
  const reasonId = useId()
  const counts = useQuery({ ...undoCountsQuery(item.id), staleTime: 0 })
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const undo = useSubmit({
    offline: 'refuse',
    mutationFn: () => undoImport(item.id, reason.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['import'] })
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      onDone()
    },
  })
  const undoneMeanwhile = alreadyUndone(undo.error)

  if (counts.isPending) return <p className="import__note">{form.checking}</p>

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk) undo.mutate()
  }

  return (
    <form className="import__undo" aria-label={form.title} onSubmit={submit}>
      {counts.data && (
        <>
          <p className="import__note">
            {form.removes(counts.data.payments, counts.data.grades, counts.data.people)}
          </p>
          {counts.data.kept > 0 && <p className="import__note">{form.kept(counts.data.kept)}</p>}
        </>
      )}
      <p className="import__note">{form.stays}</p>
      <label htmlFor={reasonId} className="import__label">
        {form.reason}
      </label>
      <Input
        id={reasonId}
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      {(counts.isError || undo.error) && (
        <Banner tone="error">
          {undoneMeanwhile ? form.alreadyUndone : form.failed}
        </Banner>
      )}
      <div className="import__actions">
        <Button disabled={undo.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={undo.isPending || counts.isError} busy={undo.isPending}>
          {undo.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
