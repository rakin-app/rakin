import { useQueryClient } from '@tanstack/react-query'
import { useLocation } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import type { Person } from '../api/member'
import { setHistory } from '../api/people'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'

const copy = t.admin.member.history

// How far back a day of someone's history may go (backend `HISTORY_WINDOW_YEARS`): a
// typo guard. "Alumno desde", and the day they left (#294).
export const HISTORY_WINDOW_YEARS = 60
// Backend `MAX_PRIOR_CLASSES`.
const MAX_PRIOR_CLASSES = 20_000

type Open = 'menu' | 'start' | null

/**
 * "Historial" (#293): what the gym knew of the member before Rakin, beside billing and
 * never in it. For now the day they first trained here and their classes before Rakin,
 * added with "Agregar historial" › "Fecha de inicio y clases"; the payments and grades
 * of later tickets join this card (docs/design/historical-data.md, section 4). Owner
 * and admin only: the ficha draws it with the Libro. Just after "Agregar exalumno" its
 * choices are open, offered (#294).
 */
export function PersonHistory({ person }: { person: Person }) {
  const offered = useLocation({ select: (location) => location.state.offerHistory === true })
  const [open, setOpen] = useState<Open>(offered ? 'menu' : null)
  const [done, setDone] = useState<string | null>(null)
  const lines = [
    person.member_since ? copy.memberSince(t.common.dayYear(person.member_since)) : null,
    person.prior_classes > 0 ? copy.priorClasses(person.prior_classes) : null,
  ].filter((line): line is string => line !== null)

  return (
    <section className="member__section" aria-labelledby="member-history">
      <h2 id="member-history" className="member__section-title">
        {copy.title}
      </h2>
      <div className="member__card member__history">
        {lines.length > 0 ? (
          lines.map((line) => (
            <span key={line} className="member__detail">
              {line}
            </span>
          ))
        ) : (
          <span className="member__detail">{copy.empty}</span>
        )}
        {done && (
          <p className="member__done" role="status">
            {done}
          </p>
        )}
        {open === 'start' ? (
          <StartForm
            person={person}
            onCancel={() => setOpen(null)}
            onDone={() => {
              setOpen(null)
              setDone(copy.saved)
            }}
          />
        ) : (
          <>
            <div className="member__actions">
              <Button
                aria-expanded={open === 'menu'}
                onClick={() => {
                  setDone(null)
                  setOpen(open === 'menu' ? null : 'menu')
                }}
              >
                {copy.add}
              </Button>
            </div>
            {open === 'menu' && (
              <div className="member__actions" role="group" aria-label={copy.add}>
                <Button onClick={() => setOpen('start')}>{copy.start}</Button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** The `YYYY-MM-DD` `years` before `iso`. */
export function yearsBefore(iso: string, years: number): string {
  return `${String(Number(iso.slice(0, 4)) - years).padStart(4, '0')}${iso.slice(4)}`
}

function StartForm({ person, onCancel, onDone }: { person: Person; onCancel: () => void; onDone: () => void }) {
  const form = copy.form
  const today = useGymToday()
  const queryClient = useQueryClient()
  const sinceId = useId()
  const classesId = useId()
  const [since, setSince] = useState(person.member_since ?? '')
  const [classes, setClasses] = useState(String(person.prior_classes))
  const [checked, setChecked] = useState(false)
  const earliest = today ? yearsBefore(today, HISTORY_WINDOW_YEARS) : ''
  const sinceOk = since === '' || (since <= today && since >= earliest)
  const count = Number(classes)
  const classesOk = classes.trim() !== '' && Number.isInteger(count) && count >= 0 && count <= MAX_PRIOR_CLASSES

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: () => setHistory(person.id, { member_since: since || null, prior_classes: count }),
    onSuccess: async () => {
      onDone()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['people'] }),
        queryClient.invalidateQueries({ queryKey: ['attendance', person.id] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (sinceOk && classesOk) save.mutate()
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={sinceId} className="member__label">
        {form.since}
      </label>
      <Input
        id={sinceId}
        type="date"
        min={earliest || undefined}
        max={today || undefined}
        value={since}
        aria-invalid={checked && !sinceOk}
        onChange={(e) => setSince(e.target.value)}
      />
      {checked && !sinceOk && (
        <p className="member__error" role="alert">
          {form.sinceNeeded}
        </p>
      )}
      <label htmlFor={classesId} className="member__label">
        {form.classes}
      </label>
      <Input
        id={classesId}
        type="number"
        inputMode="numeric"
        min={0}
        max={MAX_PRIOR_CLASSES}
        step={1}
        value={classes}
        aria-invalid={checked && !classesOk}
        onChange={(e) => setClasses(e.target.value)}
      />
      {checked && !classesOk && (
        <p className="member__error" role="alert">
          {form.classesNeeded}
        </p>
      )}
      {save.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
