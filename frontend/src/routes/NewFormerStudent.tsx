import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { addFormerStudent, duplicateOf, type FormerStudent } from '../api/people'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button, buttonClass } from '../components/Button'
import { Input } from '../components/Field'
import { t } from '../i18n/es'
import { LeftReasonField } from './LeftReason'
import { MOBILE, Needed, refusals } from './NewMember'
import { HISTORY_WINDOW_YEARS, yearsBefore } from './historyWindow'

const copy = t.admin.newMember
const form = copy.former

/**
 * "Ya no entrena aquí" in Nuevo alumno: "Agregar exalumno" (#294). Someone who trained
 * here before Rakin and already left: who they are, by RUT or email; a phone only if the
 * gym has one, since nobody will write to them; Alumno desde, the day they left and
 * why. No plan and no welcome. Saved, they are on "Dados de baja" and their ficha opens
 * with "Agregar historial" offered.
 */
export function NewFormerStudent() {
  const today = useGymToday()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [person, setPerson] = useState({ firstName: '', lastName: '', rut: '', email: '', phone: '' })
  const [since, setSince] = useState('')
  const [leftOn, setLeftOn] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const ids = {
    first: useId(),
    last: useId(),
    rut: useId(),
    rutHint: useId(),
    email: useId(),
    phone: useId(),
    phoneHint: useId(),
    since: useId(),
    leftOn: useId(),
  }

  const earliest = today ? yearsBefore(today, HISTORY_WINDOW_YEARS) : ''
  const leftOnOk = leftOn !== '' && leftOn <= today && leftOn >= earliest
  const problems = {
    firstName: person.firstName.trim() === '',
    identity: person.rut.trim() === '' && person.email.trim() === '',
    phone: person.phone.trim() !== '' && !MOBILE.test(person.phone.trim()),
    leftOn: !leftOnOk,
    since: since !== '' && (since < earliest || since > (leftOnOk ? leftOn : today)),
  }
  const ready = !Object.values(problems).some(Boolean)

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (body: FormerStudent) => addFormerStudent(body),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      void navigate({
        to: '/admin/alumnos/$personId',
        params: { personId: created.id },
        // In the form's place, as Nuevo alumno does (#250).
        replace: true,
        state: { offerHistory: true },
      })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!ready) return
    const optional = (value: string) => (value.trim() ? value.trim() : undefined)
    save.mutate({
      name: [person.firstName, person.lastName].map((part) => part.trim()).filter(Boolean).join(' '),
      rut: optional(person.rut),
      email: optional(person.email),
      phone: optional(person.phone),
      member_since: optional(since),
      left_on: leftOn,
      left_reason: optional(reason),
    })
  }

  const set = (key: keyof typeof person) => (e: { target: { value: string } }) =>
    setPerson({ ...person, [key]: e.target.value })
  const duplicate = duplicateOf(save.error)
  const refused = refusals(save.error).person

  return (
    <form className="new-member" aria-label={copy.kind.former} onSubmit={submit} noValidate>
      <div className="member__form">
        <p className="member__detail">{form.intro}</p>

        <label htmlFor={ids.first} className="member__label">
          {copy.firstName}
        </label>
        <Input
          id={ids.first}
          autoComplete="off"
          maxLength={100}
          value={person.firstName}
          aria-invalid={checked && problems.firstName}
          onChange={set('firstName')}
        />
        {checked && problems.firstName && <Needed text={copy.needed.firstName} />}

        <label htmlFor={ids.last} className="member__label">
          {copy.lastName}
        </label>
        <Input id={ids.last} autoComplete="off" maxLength={100} value={person.lastName} onChange={set('lastName')} />

        <label htmlFor={ids.rut} className="member__label">
          {copy.rut}
        </label>
        <Input
          id={ids.rut}
          autoComplete="off"
          value={person.rut}
          aria-describedby={ids.rutHint}
          aria-invalid={(checked && problems.identity) || refused.rut !== undefined}
          onChange={set('rut')}
        />
        <p id={ids.rutHint} className="member__detail">
          {copy.rutHint}
        </p>
        {refused.rut && <Needed text={refused.rut} />}

        <label htmlFor={ids.email} className="member__label">
          {copy.email}
        </label>
        <Input
          id={ids.email}
          type="email"
          autoComplete="off"
          value={person.email}
          aria-invalid={(checked && problems.identity) || refused.email !== undefined}
          onChange={set('email')}
        />
        {refused.email && <Needed text={refused.email} />}
        {checked && problems.identity && <Needed text={copy.needed.identity} />}

        <label htmlFor={ids.phone} className="member__label">
          {form.phone}
        </label>
        <Input
          id={ids.phone}
          type="tel"
          inputMode="tel"
          autoComplete="off"
          value={person.phone}
          aria-describedby={ids.phoneHint}
          aria-invalid={(checked && problems.phone) || refused.phone !== undefined}
          onChange={set('phone')}
        />
        <p id={ids.phoneHint} className="member__detail">
          {form.phoneHint}
        </p>
        {checked && problems.phone ? (
          <Needed text={copy.refused.phone} />
        ) : (
          refused.phone && <Needed text={refused.phone} />
        )}

        <label htmlFor={ids.since} className="member__label">
          {form.since}
        </label>
        <Input
          id={ids.since}
          type="date"
          min={earliest || undefined}
          max={(leftOnOk ? leftOn : today) || undefined}
          value={since}
          aria-invalid={checked && problems.since}
          onChange={(e) => setSince(e.target.value)}
        />
        {checked && problems.since && <Needed text={form.needed.since} />}

        <label htmlFor={ids.leftOn} className="member__label">
          {form.leftOn}
        </label>
        <Input
          id={ids.leftOn}
          type="date"
          min={earliest || undefined}
          max={today || undefined}
          value={leftOn}
          aria-invalid={checked && problems.leftOn}
          onChange={(e) => setLeftOn(e.target.value)}
        />
        {checked && problems.leftOn && <Needed text={form.needed.leftOn} />}

        <LeftReasonField value={reason} onChange={setReason} />
      </div>

      {save.error && (
        <div className="member__error" role="alert">
          {duplicate ? (
            <>
              {copy.duplicate[duplicate.code]}{' '}
              <Link to="/admin/alumnos/$personId" params={{ personId: duplicate.person_id }}>
                {copy.duplicate.open}
              </Link>
            </>
          ) : Object.keys(refused).length > 0 ? (
            copy.refused.fields
          ) : save.error instanceof ApiError && save.error.status === 422 ? (
            form.refused.invalid
          ) : (
            form.refused.failed
          )}
        </div>
      )}

      <div className="member__form-actions">
        <Link to="/admin/alumnos" className={buttonClass({ className: 'new-member__cancel' })}>
          {copy.cancel}
        </Link>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? copy.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
