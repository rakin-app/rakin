import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { holdsAccount, managesGym, type Access } from '../api/me'
import type { Person } from '../api/member'
import {
  anonymisationQuery,
  anonymisePerson,
  anonymiseRefused,
  deletePerson,
  deletionQuery,
  deletionRefused,
  leaveGym,
  returnToGym,
} from '../api/people'
import { useGymToday } from '../api/sessions'
import { Button } from '../components/Button'
import { useLeaveTo } from '../components/BackLink'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { LeftReasonField } from './LeftReason'
import { HISTORY_WINDOW_YEARS, yearsBefore } from './historyWindow'
import { useRefresh } from './PersonData'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'
import { useSubmit } from '../api/submit'
import { Banner, Card, cardClass } from '../components/Card'

const copy = t.admin.member

type Open = 'leave' | 'return' | 'undoLeave' | 'remove' | null

/**
 * The ways out of the gym (#157), set apart at the foot of the ficha: "Dar de baja" and
 * "Reactivar" for the owner and admins, since they end or start what a member is
 * charged; "Eliminar" for the owner alone. A coach gets none of them. The record is
 * edited in "Datos" (`PersonData`).
 *
 * Beside "Reactivar", "Deshacer la baja" when their Dar de baja ended a plan it can bring
 * back (#549): `undoLeave`, the ficha's form for it, which closes with what it did. It is
 * the way back from a mistake, the person and that plan as before; "Reactivar" is for
 * coming back later, on a new plan if any.
 *
 * "Eliminar" offers "Anonimizar" instead when what stands in the way is money the gym
 * kept (#372). An anonymous record has no ways out left: the ficha says so.
 */
export function PersonActions({
  person,
  access,
  undoLeave,
}: {
  person: Person
  access: Access | null | undefined
  undoLeave?: (close: (message: string | null) => void) => ReactNode
}) {
  const [open, setOpen] = useState<Open>(null)
  const [done, setDone] = useState<string | null>(null)
  // "Dar de baja" asked for from Eliminar's alert, which the form takes the place of.
  const [revealLeave, setRevealLeave] = useState(false)
  const manages = managesGym(access)
  const toggle = (form: Open) => {
    setDone(null)
    setRevealLeave(false)
    setOpen(open === form ? null : form)
  }
  const finish = (message: string | null) => {
    setOpen(null)
    setDone(message)
  }

  if (!manages) return null
  if (person.anonymised) {
    return (
      <section className="member__section member__exit" aria-label={copy.exitLabel}>
        <p className="member__note">{copy.anonymised}</p>
      </section>
    )
  }

  return (
    <section className="member__section member__exit" aria-label={copy.exitLabel}>
      <div className="member__actions">
        {person.left_on ? (
          <>
            {undoLeave && (
              <Button variant="primary" aria-expanded={open === 'undoLeave'} onClick={() => toggle('undoLeave')}>
                {copy.undoLeave}
              </Button>
            )}
            <Button aria-expanded={open === 'return'} onClick={() => toggle('return')}>
              {copy.reactivate}
            </Button>
          </>
        ) : (
          <Button variant="danger" aria-expanded={open === 'leave'} onClick={() => toggle('leave')}>
            {copy.leave}
          </Button>
        )}
        {holdsAccount(access) && (
          <Button variant="danger" aria-expanded={open === 'remove'} onClick={() => toggle('remove')}>
            {copy.remove}
          </Button>
        )}
      </div>
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {open === 'leave' && (
        <LeaveForm person={person} reveal={revealLeave} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'return' && <ReturnForm person={person} onCancel={() => setOpen(null)} onDone={finish} />}
      {open === 'undoLeave' && person.left_on && undoLeave?.(finish)}
      {open === 'remove' && (
        <RemoveForm
          person={person}
          onCancel={() => setOpen(null)}
          onLeave={
            person.left_on
              ? undefined
              : () => {
                  toggle('leave')
                  setRevealLeave(true)
                }
          }
        />
      )}
    </section>
  )
}

function LeaveForm({
  person,
  reveal = false,
  onCancel,
  onDone,
}: {
  person: Person
  // Opened from Eliminar's alert (#581): its "Cancelar" and "Dar de baja" sit where the
  // alert's did, so it looks as if nothing happened. Brought into view, its first field
  // focused, so it is seen to open.
  reveal?: boolean
  onCancel: () => void
  onDone: (message: string | null) => void
}) {
  const form = copy.leaveForm
  const formRef = useRef<HTMLFormElement>(null)
  const dayRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (!reveal) return
    formRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
    dayRef.current?.focus({ preventScroll: true })
  }, [reveal])
  const today = useGymToday()
  const refresh = useRefresh()
  const id = useId()
  // Today until a day is picked: the gym's timezone may arrive after the form opens.
  const [picked, setPicked] = useState<string | null>(null)
  const on = picked ?? today
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  // As far back as history goes (#294), not a plan's five years.
  const earliest = today ? yearsBefore(today, HISTORY_WINDOW_YEARS) : ''
  const onOk = on !== '' && on <= today && on >= earliest

  const leave = useSubmit({
    offline: 'refuse',
    // Today is left to the server, which knows the gym's today.
    mutationFn: () =>
      leaveGym(person.id, { left_on: on < today ? on : undefined, left_reason: reason.trim() || undefined }),
    onSuccess: async () => {
      // The banner says it; nothing more to add.
      onDone(null)
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (onOk) leave.mutate()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.on}
      </label>
      <Input
        ref={dayRef}
        id={id}
        type="date"
        min={earliest || undefined}
        max={today}
        value={on}
        aria-invalid={checked && !onOk}
        onChange={(e) => setPicked(e.target.value)}
      />
      {checked && !onOk && (
        <Banner tone="error">
          {form.onNeeded}
        </Banner>
      )}
      <LeftReasonField value={reason} onChange={setReason} />
      {leave.error && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button disabled={leave.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={leave.isPending} busy={leave.isPending}>
          {leave.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

function ReturnForm({
  person,
  onCancel,
  onDone,
}: {
  person: Person
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.returnForm
  const today = useGymToday()
  const refresh = useRefresh()
  const [plan, setPlan] = useState<PlanChoice>({ plan_id: '', started_on: '' })

  const back = useSubmit({
    offline: 'refuse',
    mutationFn: () => returnToGym(person.id, membershipOf(plan, today)),
    onSuccess: async () => {
      onDone(form.done)
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    back.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <PlanStart choice={plan} today={today} labels={form} onChange={setPlan} />
      {back.error && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button disabled={back.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={back.isPending} busy={back.isPending}>
          {back.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

// Typed names compared as people type them: case and spacing aside.
function sameName(typed: string, name: string): boolean {
  const fold = (value: string) => value.trim().replace(/\s+/g, ' ').toLocaleLowerCase('es-CL')
  return fold(typed) === fold(name)
}

function RemoveForm({
  person,
  onCancel,
  onLeave,
}: {
  person: Person
  onCancel: () => void
  // Offered when money stands in the way, and they have not left yet.
  onLeave: (() => void) | undefined
}) {
  const form = copy.removeForm
  // To Alumnos, and not back to the gone ficha (#250).
  const leave = useLeaveTo('/admin/alumnos')
  const queryClient = useQueryClient()
  const id = useId()
  const reasonId = useId()
  const deletion = useQuery({ ...deletionQuery(person.id), staleTime: 0 })
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const remove = useSubmit({
    offline: 'refuse',
    mutationFn: () => deletePerson(person.id, reason.trim()),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['people', 'detail', person.id] })
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      leave()
    },
  })
  // Refused at the last moment, say a payment recorded meanwhile.
  const refusal = deletion.data?.refused ? deletion.data : deletionRefused(remove.error)
  const refused = refusal?.refused

  if (deletion.isPending) return <p className="member__note">{form.checking}</p>

  // Money the gym kept, its own or moved to a sibling, stays in the books: anonymise.
  if (refused === 'payment' || refused === 'moved') {
    return <AnonymiseForm person={person} onCancel={onCancel} onLeave={onLeave} />
  }

  if (refused) {
    return (
      <Card as="div" className="member__form" role="alert">
        <p className="member__detail">{form.refused[refused](t.common.clp(refusal?.amount_clp ?? 0))}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>
            {form.cancel}
          </Button>
          {refused === 'owes' && onLeave && (
            <Button variant="danger" onClick={onLeave}>
              {copy.leave}
            </Button>
          )}
        </div>
      </Card>
    )
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (sameName(typed, person.name) && reasonOk) remove.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={reasonId} className="member__label">
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
      <label htmlFor={id} className="member__label">
        {form.confirm(person.name)}
      </label>
      <Input
        id={id}
        autoComplete="off"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />
      {(deletion.isError || remove.error) && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button disabled={remove.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button
          type="submit"
          variant="danger"
          disabled={remove.isPending || !sameName(typed, person.name)} busy={remove.isPending}
        >
          {remove.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

function AnonymiseForm({
  person,
  onCancel,
  onLeave,
}: {
  person: Person
  onCancel: () => void
  // Offered while they have not left yet, which anonymising needs first.
  onLeave: (() => void) | undefined
}) {
  const form = copy.anonymiseForm
  const words = copy.removeForm
  // To Alumnos: the ficha that stays is the anonymous record's, under another id.
  const leave = useLeaveTo('/admin/alumnos')
  const queryClient = useQueryClient()
  const id = useId()
  const reasonId = useId()
  const anonymisation = useQuery({ ...anonymisationQuery(person.id), staleTime: 0 })
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const anonymise = useSubmit({
    offline: 'refuse',
    mutationFn: () => anonymisePerson(person.id, reason.trim()),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['people', 'detail', person.id] })
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      leave()
    },
  })
  // Refused at the last moment, say a proof sent meanwhile.
  const refusal = anonymisation.data?.refused ? anonymisation.data : anonymiseRefused(anonymise.error)
  const refused = refusal?.refused

  if (anonymisation.isPending) return <p className="member__note">{words.checking}</p>

  if (refused) {
    return (
      <Card as="div" className="member__form" role="alert">
        <p className="member__detail">{form.refused[refused](t.common.clp(refusal?.amount_clp ?? 0))}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>
            {words.cancel}
          </Button>
          {refused === 'running' && onLeave && (
            <Button variant="danger" onClick={onLeave}>
              {copy.leave}
            </Button>
          )}
        </div>
      </Card>
    )
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (sameName(typed, person.name) && reasonOk) anonymise.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={reasonId} className="member__label">
        {words.reason}
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
      <label htmlFor={id} className="member__label">
        {words.confirm(person.name)}
      </label>
      <Input
        id={id}
        autoComplete="off"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
      />
      {(anonymisation.isError || anonymise.error) && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button disabled={anonymise.isPending} onClick={onCancel}>
          {words.cancel}
        </Button>
        <Button
          type="submit"
          variant="danger"
          disabled={anonymise.isPending || !sameName(typed, person.name)} busy={anonymise.isPending}
        >
          {anonymise.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
