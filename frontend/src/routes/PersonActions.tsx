import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import type { StaffRole } from '../api/me'
import type { Person } from '../api/member'
import { deletePerson, deletionQuery, deletionRefused, leaveGym, returnToGym } from '../api/people'
import { useGymToday } from '../api/sessions'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { useRefresh } from './PersonData'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'
import { useSubmit } from '../api/submit'

const copy = t.admin.member

type Open = 'leave' | 'return' | 'remove' | null

/**
 * The ways out of the gym (#157), set apart at the foot of the ficha: "Dar de baja" and
 * "Reactivar" for the owner and admins, since they end or start what a member is
 * charged; "Eliminar" for the owner alone. A coach gets none of them. The record is
 * edited in "Datos" (`PersonData`).
 */
export function PersonActions({ person, role }: { person: Person; role: StaffRole | null | undefined }) {
  const [open, setOpen] = useState<Open>(null)
  const [done, setDone] = useState<string | null>(null)
  const manages = role === 'owner' || role === 'admin'
  const toggle = (form: Open) => {
    setDone(null)
    setOpen(open === form ? null : form)
  }
  const finish = (message: string | null) => {
    setOpen(null)
    setDone(message)
  }

  if (!manages) return null

  return (
    <section className="member__section member__exit" aria-label={copy.exitLabel}>
      <div className="member__actions">
        {person.left_on ? (
          <Button aria-expanded={open === 'return'} onClick={() => toggle('return')}>
            {copy.reactivate}
          </Button>
        ) : (
          <Button variant="danger" aria-expanded={open === 'leave'} onClick={() => toggle('leave')}>
            {copy.leave}
          </Button>
        )}
        {role === 'owner' && (
          <Button variant="danger" aria-expanded={open === 'remove'} onClick={() => toggle('remove')}>
            {copy.remove}
          </Button>
        )}
      </div>
      {done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )}
      {open === 'leave' && <LeaveForm person={person} onCancel={() => setOpen(null)} onDone={finish} />}
      {open === 'return' && <ReturnForm person={person} onCancel={() => setOpen(null)} onDone={finish} />}
      {open === 'remove' && (
        <RemoveForm
          person={person}
          onCancel={() => setOpen(null)}
          onLeave={person.left_on ? undefined : () => toggle('leave')}
        />
      )}
    </section>
  )
}

function LeaveForm({
  person,
  onCancel,
  onDone,
}: {
  person: Person
  onCancel: () => void
  onDone: (message: string | null) => void
}) {
  const form = copy.leaveForm
  const today = useGymToday()
  const refresh = useRefresh()
  const id = useId()
  // Today until a day is picked: the gym's timezone may arrive after the form opens.
  const [picked, setPicked] = useState<string | null>(null)
  const on = picked ?? today
  const [checked, setChecked] = useState(false)
  const onOk = on !== '' && on <= today

  const leave = useSubmit({
    offline: 'refuse',
    // Today is left to the server, which knows the gym's today.
    mutationFn: () => leaveGym(person.id, on < today ? on : undefined),
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.on}
      </label>
      <Input
        id={id}
        type="date"
        max={today}
        value={on}
        aria-invalid={checked && !onOk}
        onChange={(e) => setPicked(e.target.value)}
      />
      {checked && !onOk && (
        <p className="member__error" role="alert">
          {form.onNeeded}
        </p>
      )}
      {leave.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <PlanStart choice={plan} today={today} labels={form} onChange={setPlan} />
      {back.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
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
  // Offered when accounting keeps them, and they have not left yet.
  onLeave: (() => void) | undefined
}) {
  const form = copy.removeForm
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const id = useId()
  const deletion = useQuery({ ...deletionQuery(person.id), staleTime: 0 })
  const [typed, setTyped] = useState('')

  const remove = useSubmit({
    offline: 'refuse',
    mutationFn: () => deletePerson(person.id),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: ['people', 'detail', person.id] })
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      void navigate({ to: '/admin/alumnos' })
    },
  })
  // Refused at the last moment, say a payment recorded meanwhile.
  const refused = deletion.data?.refused ?? deletionRefused(remove.error)

  if (deletion.isPending) return <p className="member__note">{form.checking}</p>

  if (refused) {
    return (
      <div className="member__form" role="alert">
        <p className="member__detail">{form.refused[refused]}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>
            {form.cancel}
          </Button>
          {refused === 'ledger' && onLeave && (
            <Button variant="danger" onClick={onLeave}>
              {copy.leave}
            </Button>
          )}
        </div>
      </div>
    )
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (sameName(typed, person.name)) remove.mutate()
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
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
        <p className="member__error" role="alert">
          {form.failed}
        </p>
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
