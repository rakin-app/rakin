import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { customFieldsQuery } from '../api/customFields'
import { familyConflict, type PersonRef } from '../api/family'
import { duplicateOf, enrol, type Enrolment, type GuardianChoice } from '../api/people'
import { useGymToday } from '../api/sessions'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { FieldInput, valueOf } from './CustomFieldsPanel'
import { PeopleSearch } from './FamilyPanel'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'
import './MemberDetail.css'
import './NewMember.css'

const copy = t.admin.newMember

// A Chilean mobile as people type one; the API normalises and is the real check.
const MOBILE = /^(\+?56)?\s*9[\s.-]*(\d[\s.-]*){8}$/

/** Whether someone born on `dob` is under 18 on `today`, both ISO days, as the API reads it. */
export function isMinor(dob: string, today: string): boolean {
  const [year, month, day] = dob.split('-')
  // Born on 29 February, they come of age on the 28th, as `add_months` clamps it.
  const comesOfAge = `${Number(year) + 18}-${month}-${month === '02' && day === '29' ? '28' : day}`
  return comesOfAge > today
}

type Guardian =
  | { kind: 'none' }
  | { kind: 'existing'; picked: PersonRef | null }
  | { kind: 'new'; name: string; phone: string; email: string }

/**
 * "Nuevo alumno" (#157): a member added by hand, as the import adds one. Their record,
 * a guardian when they are a minor, the gym's custom fields and, if picked, a plan from
 * a day, with the welcome if asked. Saved all at once; then their ficha opens.
 */
export function NewMember() {
  const today = useGymToday()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const definitions = useQuery(customFieldsQuery)
  const fields = (definitions.data ?? []).filter((field) => !field.archived)

  const [person, setPerson] = useState({ firstName: '', lastName: '', phone: '', email: '', rut: '', dob: '' })
  const [guardian, setGuardian] = useState<Guardian>({ kind: 'none' })
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [plan, setPlan] = useState<PlanChoice>({ plan_id: '', started_on: '' })
  const [welcome, setWelcome] = useState(false)
  const [checked, setChecked] = useState(false)
  const ids = {
    first: useId(),
    last: useId(),
    phone: useId(),
    phoneHint: useId(),
    email: useId(),
    rut: useId(),
    dob: useId(),
    gName: useId(),
    gPhone: useId(),
    gEmail: useId(),
    welcome: useId(),
    fields: useId(),
  }

  const minor = person.dob !== '' && isMinor(person.dob, today)
  const hasGuardian = guardian.kind !== 'none'
  const problems = {
    firstName: person.firstName.trim() === '',
    phone: person.phone.trim() === '' ? !hasGuardian : !MOBILE.test(person.phone.trim()),
    guardian: minor && !hasGuardian,
    guardianPicked: guardian.kind === 'existing' && guardian.picked === null,
    guardianName: guardian.kind === 'new' && guardian.name.trim() === '',
    guardianPhone: guardian.kind === 'new' && !MOBILE.test(guardian.phone.trim()),
  }
  const ready = !Object.values(problems).some(Boolean)

  const save = useMutation({
    mutationFn: (body: Enrolment) => enrol(body),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['people'] })
      void navigate({ to: '/admin/alumnos/$personId', params: { personId: created.id } })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!ready) return
    const optional = (value: string) => (value.trim() ? value.trim() : undefined)
    let chosen: GuardianChoice | undefined
    if (guardian.kind === 'existing' && guardian.picked) chosen = { person_id: guardian.picked.id }
    if (guardian.kind === 'new') {
      chosen = { name: guardian.name.trim(), phone: guardian.phone.trim(), email: optional(guardian.email) }
    }
    const values = Object.fromEntries(
      fields.filter((f) => (drafts[f.key] ?? '').trim() !== '').map((f) => [f.key, valueOf(f, drafts[f.key] ?? '')]),
    )
    const membership = membershipOf(plan, today)
    save.mutate({
      name: [person.firstName, person.lastName].map((part) => part.trim()).filter(Boolean).join(' '),
      phone: optional(person.phone),
      email: optional(person.email),
      rut: optional(person.rut),
      dob: optional(person.dob),
      guardian: chosen,
      fields: Object.keys(values).length > 0 ? values : undefined,
      membership,
      send_welcome: membership !== undefined && welcome,
    })
  }

  const set = (key: keyof typeof person) => (e: { target: { value: string } }) =>
    setPerson({ ...person, [key]: e.target.value })
  const duplicate = duplicateOf(save.error)

  return (
    <>
      <PageHeader title={copy.title} eyebrow={copy.eyebrow} />
      <form className="new-member" aria-label={copy.title} onSubmit={submit} noValidate>
        <div className="member__form">
          <label htmlFor={ids.first} className="member__label">
            {copy.firstName}
          </label>
          <input
            id={ids.first}
            className="member__input"
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
          <input
            id={ids.last}
            className="member__input"
            autoComplete="off"
            maxLength={100}
            value={person.lastName}
            onChange={set('lastName')}
          />

          <label htmlFor={ids.phone} className="member__label">
            {hasGuardian ? copy.phoneOptional : copy.phone}
          </label>
          <input
            id={ids.phone}
            className="member__input"
            type="tel"
            inputMode="tel"
            autoComplete="off"
            value={person.phone}
            aria-describedby={ids.phoneHint}
            aria-invalid={checked && problems.phone}
            onChange={set('phone')}
          />
          <p id={ids.phoneHint} className="member__detail">
            {copy.phoneHint}
          </p>
          {checked && problems.phone && <Needed text={copy.needed.phone} />}

          <label htmlFor={ids.email} className="member__label">
            {copy.email}
          </label>
          <input
            id={ids.email}
            className="member__input"
            type="email"
            autoComplete="off"
            value={person.email}
            onChange={set('email')}
          />

          <label htmlFor={ids.rut} className="member__label">
            {copy.rut}
          </label>
          <input id={ids.rut} className="member__input" autoComplete="off" value={person.rut} onChange={set('rut')} />

          <label htmlFor={ids.dob} className="member__label">
            {copy.dob}
          </label>
          <input
            id={ids.dob}
            className="member__input"
            type="date"
            max={today}
            value={person.dob}
            onChange={set('dob')}
          />
        </div>

        <section className="member__form" aria-label={copy.guardianTitle}>
          <h2 className="member__section-title">{copy.guardianTitle}</h2>
          <p className="member__detail">{minor ? copy.guardianMinor : copy.guardianOptional}</p>
          {checked && problems.guardian && <Needed text={copy.needed.guardian} />}
          {guardian.kind === 'none' ? (
            <div className="member__actions">
              <button
                type="button"
                className="member__button"
                onClick={() => setGuardian({ kind: 'existing', picked: null })}
              >
                {copy.guardianExisting}
              </button>
              <button
                type="button"
                className="member__button"
                onClick={() => setGuardian({ kind: 'new', name: '', phone: '', email: '' })}
              >
                {copy.guardianNew}
              </button>
            </div>
          ) : (
            <>
              {guardian.kind === 'existing' &&
                (guardian.picked ? (
                  <div className="new-member__picked">
                    <span>{copy.guardianPicked(guardian.picked.name)}</span>
                    <button
                      type="button"
                      className="family__action"
                      onClick={() => setGuardian({ kind: 'existing', picked: null })}
                    >
                      {copy.guardianChange}
                    </button>
                  </div>
                ) : (
                  <>
                    <PeopleSearch
                      label={copy.guardianSearch}
                      action={copy.guardianPick}
                      actionLabel={copy.guardianPickLabel}
                      noMatches={copy.noMatches}
                      // A guardian is never someone's dependent (one level, 0010).
                      offered={(row) => !row.guardian}
                      busy={false}
                      onPick={(row) => setGuardian({ kind: 'existing', picked: { id: row.id, name: row.name } })}
                    />
                    {checked && problems.guardianPicked && <Needed text={copy.needed.guardianPicked} />}
                  </>
                ))}
              {guardian.kind === 'new' && (
                <>
                  <label htmlFor={ids.gName} className="member__label">
                    {copy.guardianName}
                  </label>
                  <input
                    id={ids.gName}
                    className="member__input"
                    autoComplete="off"
                    maxLength={200}
                    value={guardian.name}
                    aria-invalid={checked && problems.guardianName}
                    onChange={(e) => setGuardian({ ...guardian, name: e.target.value })}
                  />
                  {checked && problems.guardianName && <Needed text={copy.needed.guardianName} />}
                  <label htmlFor={ids.gPhone} className="member__label">
                    {copy.guardianPhone}
                  </label>
                  <input
                    id={ids.gPhone}
                    className="member__input"
                    type="tel"
                    inputMode="tel"
                    autoComplete="off"
                    value={guardian.phone}
                    aria-invalid={checked && problems.guardianPhone}
                    onChange={(e) => setGuardian({ ...guardian, phone: e.target.value })}
                  />
                  {checked && problems.guardianPhone && <Needed text={copy.needed.guardianPhone} />}
                  <label htmlFor={ids.gEmail} className="member__label">
                    {copy.guardianEmail}
                  </label>
                  <input
                    id={ids.gEmail}
                    className="member__input"
                    type="email"
                    autoComplete="off"
                    value={guardian.email}
                    onChange={(e) => setGuardian({ ...guardian, email: e.target.value })}
                  />
                </>
              )}
              <button type="button" className="member__button" onClick={() => setGuardian({ kind: 'none' })}>
                {copy.guardianRemove}
              </button>
            </>
          )}
        </section>

        {fields.length > 0 && (
          <section className="member__form" aria-label={copy.fieldsTitle}>
            <h2 className="member__section-title">{copy.fieldsTitle}</h2>
            {fields.map((field) => {
              const id = `${ids.fields}-${field.key}`
              return (
                <div key={field.key} className="new-member__field">
                  <label htmlFor={id} className="member__label">
                    {field.label}
                  </label>
                  <FieldInput
                    id={id}
                    field={field}
                    value={drafts[field.key] ?? ''}
                    invalid={false}
                    onChange={(value) => setDrafts({ ...drafts, [field.key]: value })}
                  />
                </div>
              )
            })}
          </section>
        )}

        <section className="member__form" aria-label={copy.planTitle}>
          <h2 className="member__section-title">{copy.planTitle}</h2>
          <PlanStart choice={plan} today={today} labels={copy} onChange={setPlan} />
          <label htmlFor={ids.welcome} className="new-member__check">
            <input
              id={ids.welcome}
              type="checkbox"
              checked={welcome && plan.plan_id !== ''}
              disabled={plan.plan_id === ''}
              onChange={(e) => setWelcome(e.target.checked)}
            />
            {copy.welcome}
          </label>
          <p className="member__detail">{copy.welcomeHint}</p>
        </section>

        {save.error && (
          <div className="member__error" role="alert">
            {duplicate ? (
              <>
                {copy.duplicate[duplicate.code]}{' '}
                <Link to="/admin/alumnos/$personId" params={{ personId: duplicate.person_id }}>
                  {copy.duplicate.open}
                </Link>
              </>
            ) : familyConflict(save.error) ? (
              copy.refused.one_level
            ) : save.error instanceof ApiError && save.error.status === 422 ? (
              copy.refused.invalid
            ) : (
              copy.refused.failed
            )}
          </div>
        )}

        <div className="member__form-actions">
          <Link to="/admin/alumnos" className="member__button new-member__cancel">
            {copy.cancel}
          </Link>
          <button type="submit" className="member__button member__button--primary" disabled={save.isPending}>
            {save.isPending ? copy.working : copy.submit}
          </button>
        </div>
      </form>
    </>
  )
}

function Needed({ text }: { text: string }) {
  return (
    <p className="member__error" role="alert">
      {text}
    </p>
  )
}
