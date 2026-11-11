import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { customFieldsQuery } from '../api/customFields'
import { familyConflict, type PersonRef } from '../api/family'
import { duplicateOf, enrol, type Enrolment, type GuardianChoice } from '../api/people'
import { useGymToday } from '../api/sessions'
import { Button, buttonClass } from '../components/Button'
import { Input } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { FieldInput, valueOf } from './CustomFieldsPanel'
import { PeopleSearch } from './FamilyPanel'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'
import './MemberDetail.css'
import './NewMember.css'
import { useSubmit } from '../api/submit'
import { validationErrors } from '../api/validation'

const copy = t.admin.newMember

// A Chilean mobile as people type one; the API normalises and is the real check.
export const MOBILE = /^(\+?56)?\s*9[\s.-]*(\d[\s.-]*){8}$/

/** Whether someone born on `dob` is under 18 on `today`, both ISO days, as the API reads it. */
export function isMinor(dob: string, today: string): boolean {
  const [year, month, day] = dob.split('-')
  // Born on 29 February, they come of age on the 28th, as `add_months` clamps it.
  const comesOfAge = `${Number(year) + 18}-${month}-${month === '02' && day === '29' ? '28' : day}`
  return comesOfAge > today
}

// The fields whose refusal the form shows under the field itself (#211).
const REFUSABLE = ['rut', 'email', 'phone', 'dob'] as const
type Refusable = (typeof REFUSABLE)[number]
type Refusals = { person: Partial<Record<Refusable, string>>; guardian: Partial<Record<Refusable, string>> }

/**
 * What a 422 says of each field, as the copy words it: the member's own, and a new
 * guardian's, which the API reports under the union branch it tried
 * (`guardian.function-after[_identified(), NewGuardian].rut`).
 */
export function refusals(error: unknown): Refusals {
  const out: Refusals = { person: {}, guardian: {} }
  for (const path of Object.keys(validationErrors(error))) {
    const parts = path.split('.')
    const field = parts.at(-1) as Refusable
    if (!REFUSABLE.includes(field)) continue
    if (parts.length === 1) out.person[field] ??= copy.refused[field]
    else if (parts[0] === 'guardian' && parts.length === 3 && parts[1]!.includes('NewGuardian'))
      out.guardian[field] ??= copy.refused[field]
  }
  return out
}

// A guardian picked from the gym: whether the gym can reach them, by phone or because
// they have no WhatsApp, is the API's check too.
type Picked = PersonRef & { reachable: boolean }

type Guardian =
  | { kind: 'none' }
  | { kind: 'existing'; picked: Picked | null }
  | { kind: 'new'; name: string; rut: string; email: string; phone: string; noWhatsapp: boolean }

/**
 * "Nuevo alumno" (#157): a member added by hand, as the import adds one. Their record,
 * a guardian when they are a minor, the gym's custom fields and, if picked, a plan from
 * a day, with the welcome if asked. Saved all at once; then their ficha opens.
 *
 * Someone is their RUT, or their email when they have none (#165); a kid with a guardian
 * may have neither. The phone is how the gym reaches them on WhatsApp: required, unless
 * "No tiene WhatsApp" is ticked. With a guardian, it is the guardian's that is required.
 */
export function NewMember() {
  usePageTitle(copy.title)
  const today = useGymToday()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const definitions = useQuery(customFieldsQuery)
  const fields = (definitions.data ?? []).filter((field) => !field.archived)

  const [person, setPerson] = useState({ firstName: '', lastName: '', phone: '', email: '', rut: '', dob: '' })
  const [noWhatsapp, setNoWhatsapp] = useState(false)
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
    noWhatsapp: useId(),
    email: useId(),
    rut: useId(),
    rutHint: useId(),
    dob: useId(),
    gName: useId(),
    gRut: useId(),
    gPhone: useId(),
    gNoWhatsapp: useId(),
    gEmail: useId(),
    welcome: useId(),
    fields: useId(),
  }

  const minor = person.dob !== '' && isMinor(person.dob, today)
  const hasGuardian = guardian.kind !== 'none'
  const problems = {
    firstName: person.firstName.trim() === '',
    // Who they are; a guardian's dependent may have neither.
    identity: !hasGuardian && person.rut.trim() === '' && person.email.trim() === '',
    phone: person.phone.trim() === '' ? !hasGuardian && !noWhatsapp : !MOBILE.test(person.phone.trim()),
    guardian: minor && !hasGuardian,
    guardianPicked: guardian.kind === 'existing' && guardian.picked === null,
    guardianUnreachable: guardian.kind === 'existing' && guardian.picked !== null && !guardian.picked.reachable,
    guardianName: guardian.kind === 'new' && guardian.name.trim() === '',
    guardianIdentity: guardian.kind === 'new' && guardian.rut.trim() === '' && guardian.email.trim() === '',
    guardianPhone:
      guardian.kind === 'new' &&
      (guardian.phone.trim() === '' ? !guardian.noWhatsapp : !MOBILE.test(guardian.phone.trim())),
  }
  const ready = !Object.values(problems).some(Boolean)

  const save = useSubmit({
    offline: 'refuse',
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
      chosen = {
        name: guardian.name.trim(),
        rut: optional(guardian.rut),
        email: optional(guardian.email),
        phone: optional(guardian.phone),
        no_whatsapp: guardian.noWhatsapp || undefined,
      }
    }
    const values = Object.fromEntries(
      fields.filter((f) => (drafts[f.key] ?? '').trim() !== '').map((f) => [f.key, valueOf(f, drafts[f.key] ?? '')]),
    )
    const membership = membershipOf(plan, today)
    save.mutate({
      name: [person.firstName, person.lastName].map((part) => part.trim()).filter(Boolean).join(' '),
      rut: optional(person.rut),
      email: optional(person.email),
      phone: optional(person.phone),
      // Theirs only without a guardian: with one, the guardian is who the gym messages.
      no_whatsapp: (!hasGuardian && noWhatsapp) || undefined,
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
  const refused = refusals(save.error)
  const marked = Object.keys(refused.person).length + Object.keys(refused.guardian).length > 0

  return (
    <>
      <PageHeader title={copy.title} eyebrow={copy.eyebrow} />
      <form className="new-member" aria-label={copy.title} onSubmit={submit} noValidate>
        <div className="member__form">
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
          <Input
            id={ids.last}
            autoComplete="off"
            maxLength={100}
            value={person.lastName}
            onChange={set('lastName')}
          />

          <label htmlFor={ids.rut} className="member__label">
            {copy.rut}
          </label>
          <Input
            id={ids.rut}
            autoComplete="off"
            value={person.rut}
            aria-describedby={ids.rutHint}
            aria-invalid={(checked && problems.identity) || refused.person.rut !== undefined}
            onChange={set('rut')}
          />
          <p id={ids.rutHint} className="member__detail">
            {copy.rutHint}
          </p>
          {refused.person.rut && <Needed text={refused.person.rut} />}

          <label htmlFor={ids.email} className="member__label">
            {copy.email}
          </label>
          <Input
            id={ids.email}
            type="email"
            autoComplete="off"
            value={person.email}
            aria-invalid={(checked && problems.identity) || refused.person.email !== undefined}
            onChange={set('email')}
          />
          {refused.person.email && <Needed text={refused.person.email} />}
          {checked && problems.identity && <Needed text={copy.needed.identity} />}

          <label htmlFor={ids.phone} className="member__label">
            {hasGuardian || noWhatsapp ? copy.phoneOptional : copy.phone}
          </label>
          <Input
            id={ids.phone}
            type="tel"
            inputMode="tel"
            autoComplete="off"
            value={person.phone}
            aria-describedby={ids.phoneHint}
            aria-invalid={(checked && problems.phone) || refused.person.phone !== undefined}
            onChange={set('phone')}
          />
          <p id={ids.phoneHint} className="member__detail">
            {hasGuardian ? copy.phoneHintMinor : copy.phoneHint}
          </p>
          {!hasGuardian && (
            <label htmlFor={ids.noWhatsapp} className="new-member__check">
              <input
                id={ids.noWhatsapp}
                type="checkbox"
                checked={noWhatsapp}
                onChange={(e) => setNoWhatsapp(e.target.checked)}
              />
              {copy.noWhatsapp}
            </label>
          )}
          {checked && problems.phone ? (
            <Needed text={copy.needed.phone} />
          ) : (
            refused.person.phone && <Needed text={refused.person.phone} />
          )}

          <label htmlFor={ids.dob} className="member__label">
            {copy.dob}
          </label>
          <Input
            id={ids.dob}
            type="date"
            max={today}
            value={person.dob}
            aria-invalid={refused.person.dob !== undefined}
            onChange={set('dob')}
          />
          {refused.person.dob && <Needed text={refused.person.dob} />}
        </div>

        <section className="member__form" aria-label={copy.guardianTitle}>
          <h2 className="member__section-title">{copy.guardianTitle}</h2>
          <p className="member__detail">{minor ? copy.guardianMinor : copy.guardianOptional}</p>
          {checked && problems.guardian && <Needed text={copy.needed.guardian} />}
          {guardian.kind === 'none' ? (
            <div className="member__actions">
              <Button
                onClick={() => setGuardian({ kind: 'existing', picked: null })}
              >
                {copy.guardianExisting}
              </Button>
              <Button
                onClick={() =>
                  setGuardian({ kind: 'new', name: '', rut: '', email: '', phone: '', noWhatsapp: false })
                }
              >
                {copy.guardianNew}
              </Button>
            </div>
          ) : (
            <>
              {guardian.kind === 'existing' &&
                (guardian.picked ? (
                  <div className="new-member__picked">
                    <span>{copy.guardianPicked(guardian.picked.name)}</span>
                    <Button onClick={() => setGuardian({ kind: 'existing', picked: null })}>
                      {copy.guardianChange}
                    </Button>
                    {checked && problems.guardianUnreachable && <Needed text={copy.needed.guardianUnreachable} />}
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
                      onPick={(row) =>
                        setGuardian({
                          kind: 'existing',
                          picked: { id: row.id, name: row.name, reachable: row.phone !== null || row.no_whatsapp },
                        })
                      }
                    />
                    {checked && problems.guardianPicked && <Needed text={copy.needed.guardianPicked} />}
                  </>
                ))}
              {guardian.kind === 'new' && (
                <>
                  <label htmlFor={ids.gName} className="member__label">
                    {copy.guardianName}
                  </label>
                  <Input
                    id={ids.gName}
                    autoComplete="off"
                    maxLength={200}
                    value={guardian.name}
                    aria-invalid={checked && problems.guardianName}
                    onChange={(e) => setGuardian({ ...guardian, name: e.target.value })}
                  />
                  {checked && problems.guardianName && <Needed text={copy.needed.guardianName} />}
                  <label htmlFor={ids.gRut} className="member__label">
                    {copy.guardianRut}
                  </label>
                  <Input
                    id={ids.gRut}
                    autoComplete="off"
                    value={guardian.rut}
                    aria-invalid={(checked && problems.guardianIdentity) || refused.guardian.rut !== undefined}
                    onChange={(e) => setGuardian({ ...guardian, rut: e.target.value })}
                  />
                  {refused.guardian.rut && <Needed text={refused.guardian.rut} />}
                  <label htmlFor={ids.gEmail} className="member__label">
                    {copy.guardianEmail}
                  </label>
                  <Input
                    id={ids.gEmail}
                    type="email"
                    autoComplete="off"
                    value={guardian.email}
                    aria-invalid={(checked && problems.guardianIdentity) || refused.guardian.email !== undefined}
                    onChange={(e) => setGuardian({ ...guardian, email: e.target.value })}
                  />
                  {refused.guardian.email && <Needed text={refused.guardian.email} />}
                  {checked && problems.guardianIdentity && <Needed text={copy.needed.guardianIdentity} />}
                  <label htmlFor={ids.gPhone} className="member__label">
                    {guardian.noWhatsapp ? copy.guardianPhoneOptional : copy.guardianPhone}
                  </label>
                  <Input
                    id={ids.gPhone}
                    type="tel"
                    inputMode="tel"
                    autoComplete="off"
                    value={guardian.phone}
                    aria-invalid={(checked && problems.guardianPhone) || refused.guardian.phone !== undefined}
                    onChange={(e) => setGuardian({ ...guardian, phone: e.target.value })}
                  />
                  <label htmlFor={ids.gNoWhatsapp} className="new-member__check">
                    <input
                      id={ids.gNoWhatsapp}
                      type="checkbox"
                      checked={guardian.noWhatsapp}
                      onChange={(e) => setGuardian({ ...guardian, noWhatsapp: e.target.checked })}
                    />
                    {copy.noWhatsapp}
                  </label>
                  {checked && problems.guardianPhone ? (
                    <Needed text={copy.needed.guardianPhone} />
                  ) : (
                    refused.guardian.phone && <Needed text={refused.guardian.phone} />
                  )}
                </>
              )}
              <Button onClick={() => setGuardian({ kind: 'none' })}>
                {copy.guardianRemove}
              </Button>
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
            ) : marked ? (
              copy.refused.fields
            ) : save.error instanceof ApiError && save.error.status === 422 ? (
              copy.refused.invalid
            ) : (
              copy.refused.failed
            )}
          </div>
        )}

        <div className="member__form-actions">
          <Link to="/admin/alumnos" className={buttonClass({ className: 'new-member__cancel' })}>
            {copy.cancel}
          </Link>
          <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
            {save.isPending ? copy.working : copy.submit}
          </Button>
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
