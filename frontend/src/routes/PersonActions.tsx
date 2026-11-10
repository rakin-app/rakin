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
      {person.missing_phone && (
        <p className="member__error" role="status">
          {copy.missingPhone}
        </p>
      )}
      {person.missing_rut && (
        <p className="member__error" role="status">
          {copy.missingRut}
        </p>
      )}
      {person.no_whatsapp && <p className="member__detail">{copy.noWhatsapp}</p>}
      <div className="member__actions">
        <button type="button" className="member__button" aria-expanded={open === 'edit'} onClick={() => toggle('edit')}>
          {copy.editPerson}
        </button>
        {manages &&
          (person.left_on ? (
            <button
              type="button"
              className="member__button"
              aria-expanded={open === 'return'}
              onClick={() => toggle('return')}
            >
              {copy.reactivate}
            </button>
          ) : (
            <button
              type="button"
              className="member__button"
              aria-expanded={open === 'leave'}
              onClick={() => toggle('leave')}
            >
              {copy.leave}
            </button>
          ))}
        {role === 'owner' && (
          <button
            type="button"
            className="member__button"
            aria-expanded={open === 'remove'}
            onClick={() => toggle('remove')}
          >
            {copy.remove}
          </button>
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
  const ids = { name: useId(), phone: useId(), noWhatsapp: useId(), email: useId(), rut: useId(), dob: useId() }
  const initial = {
    name: person.name,
    phone: person.phone ? formatPhone(person.phone) : '',
    email: person.email ?? '',
    rut: person.rut ? formatRut(person.rut) : '',
    dob: person.dob ?? '',
  }
  const [noWhatsapp, setNoWhatsapp] = useState(person.no_whatsapp)
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
    if (draft.phone.trim() !== initial.phone) body.phone = draft.phone.trim() || null
    if (noWhatsapp !== person.no_whatsapp) body.no_whatsapp = noWhatsapp
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
      <input
        id={ids.name}
        className="member__input"
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
      <label htmlFor={ids.phone} className="member__label">
        {form.phone}
      </label>
      <input
        id={ids.phone}
        className="member__input"
        type="tel"
        inputMode="tel"
        value={draft.phone}
        onChange={set('phone')}
      />
      <label htmlFor={ids.noWhatsapp} className="new-member__check">
        <input
          id={ids.noWhatsapp}
          type="checkbox"
          checked={noWhatsapp}
          onChange={(e) => setNoWhatsapp(e.target.checked)}
        />
        {form.noWhatsapp}
      </label>
      <label htmlFor={ids.email} className="member__label">
        {form.email}
      </label>
      <input id={ids.email} className="member__input" type="email" value={draft.email} onChange={set('email')} />
      <label htmlFor={ids.rut} className="member__label">
        {form.rut}
      </label>
      <input id={ids.rut} className="member__input" value={draft.rut} onChange={set('rut')} />
      <label htmlFor={ids.dob} className="member__label">
        {form.dob}
      </label>
      <input id={ids.dob} className="member__input" type="date" value={draft.dob} onChange={set('dob')} />

      {save.error && (
        <div className="member__error" role="alert">
          {duplicate ? (
            <>
              {form.refused[duplicate.code]}{' '}
              <Link to="/admin/alumnos/$personId" params={{ personId: duplicate.person_id }}>
                {form.refused.open}
              </Link>
            </>
          ) : phoneRequired(save.error) ? (
            form.refused.phone
          ) : save.error instanceof ApiError && save.error.status === 422 ? (
            form.refused.invalid
          ) : (
            form.refused.failed
          )}
        </div>
      )}

      <div className="member__form-actions">
        <button type="button" className="member__button" disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button type="submit" className="member__button member__button--primary" disabled={save.isPending}>
          {save.isPending ? form.working : form.save}
        </button>
      </div>
    </form>
  )
}

/** The 422 a member's edit gets for leaving them with no phone and no "No tiene WhatsApp". */
function phoneRequired(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 422) return false
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  return typeof detail === 'string' && detail.startsWith('a phone is required')
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
      <input
        id={id}
        className="member__input"
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
        <button type="button" className="member__button" disabled={leave.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button type="submit" className="member__button member__button--primary" disabled={leave.isPending}>
          {leave.isPending ? form.working : form.submit}
        </button>
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
        <button type="button" className="member__button" disabled={back.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button type="submit" className="member__button member__button--primary" disabled={back.isPending}>
          {back.isPending ? form.working : form.submit}
        </button>
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
          <button type="button" className="member__button" onClick={onCancel}>
            {form.cancel}
          </button>
          {refused === 'ledger' && onLeave && (
            <button type="button" className="member__button member__button--primary" onClick={onLeave}>
              {copy.leave}
            </button>
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
      <input
        id={id}
        className="member__input"
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
        <button type="button" className="member__button" disabled={remove.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button
          type="submit"
          className="member__button member__button--primary"
          disabled={remove.isPending || !sameName(typed, person.name)}
        >
          {remove.isPending ? form.working : form.submit}
        </button>
      </div>
    </form>
  )
}
