import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { StaffRole } from '../api/me'
import type { Person } from '../api/member'
import {
  deletePerson,
  deletionQuery,
  deletionRefused,
  duplicateOf,
  leaveGym,
  returnToGym,
  updatePerson,
  type PersonEdit,
} from '../api/people'
import { useGymToday } from '../api/sessions'
import { Button } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { formatPhone, formatRut } from './Students'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'

const copy = t.admin.member

type Open = 'edit' | 'leave' | 'return' | 'remove' | null

/**
 * A member's record and the ways out of the gym (#157): "Editar datos" for every staff
 * role, as the API allows; "Dar de baja" and "Reactivar" for the owner and admins,
 * since they end or start what a member is charged; "Eliminar" for the owner alone.
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

  return (
    <section className="member__section" aria-label={copy.editForm.title}>
      {person.left_on && (
        <p className="member__error" role="status">
          {copy.leftBanner(t.common.day(person.left_on))}
        </p>
      )}
      <div className="member__actions">
        <Button aria-expanded={open === 'edit'} onClick={() => toggle('edit')}>
          {copy.editPerson}
        </Button>
        {manages &&
          (person.left_on ? (
            <Button
              aria-expanded={open === 'return'}
              onClick={() => toggle('return')}
            >
              {copy.reactivate}
            </Button>
          ) : (
            <Button
              variant="danger"
              aria-expanded={open === 'leave'}
              onClick={() => toggle('leave')}
            >
              {copy.leave}
            </Button>
          ))}
        {role === 'owner' && (
          <Button
            variant="danger"
            aria-expanded={open === 'remove'}
            onClick={() => toggle('remove')}
          >
            {copy.remove}
          </Button>
        )}
      </div>
      {done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )}
      {open === 'edit' && <EditForm person={person} onCancel={() => setOpen(null)} onDone={finish} />}
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

/** After a change to who someone is in the gym: the lists, their ficha and their money. */
function useRefresh() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['people'] }),
      queryClient.invalidateQueries({ queryKey: ['memberships'] }),
      queryClient.invalidateQueries({ queryKey: ['ledger'] }),
    ])
}

function EditForm({
  person,
  onCancel,
  onDone,
}: {
  person: Person
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.editForm
  const refresh = useRefresh()
  const ids = { name: useId(), phone: useId(), email: useId(), rut: useId(), dob: useId() }
  const initial = {
    name: person.name,
    email: person.email ?? '',
    rut: person.rut ? formatRut(person.rut) : '',
    dob: person.dob ?? '',
  }
  const [draft, setDraft] = useState(initial)
  const [checked, setChecked] = useState(false)
  const nameOk = draft.name.trim() !== ''

  const save = useMutation({
    mutationFn: (body: PersonEdit) => updatePerson(person.id, body),
    onSuccess: async () => {
      onDone(form.saved)
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!nameOk) return
    // Only what changed; an optional field emptied is cleared.
    const body: PersonEdit = {}
    if (draft.name.trim() !== initial.name) body.name = draft.name.trim()
    if (draft.email.trim() !== initial.email) body.email = draft.email.trim() || null
    if (draft.rut.trim() !== initial.rut) body.rut = draft.rut.trim() || null
    if (draft.dob !== initial.dob) body.dob = draft.dob || null
    if (Object.keys(body).length === 0) {
      onCancel()
      return
    }
    save.mutate(body)
  }

  const set = (key: keyof typeof draft) => (e: { target: { value: string } }) =>
    setDraft({ ...draft, [key]: e.target.value })
  const duplicate = duplicateOf(save.error)

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit} noValidate>
      <label htmlFor={ids.name} className="member__label">
        {form.name}
      </label>
      <Input
        id={ids.name}
        maxLength={200}
        value={draft.name}
        aria-invalid={checked && !nameOk}
        onChange={set('name')}
      />
      {checked && !nameOk && (
        <p className="member__error" role="alert">
          {form.nameNeeded}
        </p>
      )}
      {person.phone && (
        <>
          <label htmlFor={ids.phone} className="member__label">
            {form.phone}
          </label>
          <Input id={ids.phone} value={formatPhone(person.phone)} readOnly disabled />
          <p className="member__detail">{form.phoneFixed}</p>
        </>
      )}
      <label htmlFor={ids.email} className="member__label">
        {form.email}
      </label>
      <Input id={ids.email} type="email" value={draft.email} onChange={set('email')} />
      <label htmlFor={ids.rut} className="member__label">
        {form.rut}
      </label>
      <Input id={ids.rut} value={draft.rut} onChange={set('rut')} />
      <label htmlFor={ids.dob} className="member__label">
        {form.dob}
      </label>
      <Input id={ids.dob} type="date" value={draft.dob} onChange={set('dob')} />

      {save.error && (
        <div className="member__error" role="alert">
          {duplicate ? (
            <>
              {form.refused[duplicate.code]}{' '}
              <Link to="/admin/alumnos/$personId" params={{ personId: duplicate.person_id }}>
                {form.refused.open}
              </Link>
            </>
          ) : save.error instanceof ApiError && save.error.status === 422 ? (
            form.refused.invalid
          ) : (
            form.refused.failed
          )}
        </div>
      )}

      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? form.working : form.save}
        </Button>
      </div>
    </form>
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

  const leave = useMutation({
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
        <Button type="submit" variant="danger" disabled={leave.isPending}>
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

  const back = useMutation({
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
        <Button type="submit" variant="primary" disabled={back.isPending}>
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

  const remove = useMutation({
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
          disabled={remove.isPending || !sameName(typed, person.name)}
        >
          {remove.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
