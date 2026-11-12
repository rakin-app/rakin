import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { StaffRole } from '../api/me'
import { changePlan, planChangeQuery, startMembership, type Membership, type Person } from '../api/member'
import { welcomeQuery } from '../api/people'
import { plansQuery } from '../api/plans'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Select } from '../components/Field'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { useRefresh } from './PersonData'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'

const copy = t.admin.member

// The kinds that change plan, to each other: a pack or a trial ends instead (`plan_change_starts`).
const RECURRING = new Set(['monthly', 'prepaid'])

/** A membership the member is on now: what "Cambiar plan" changes, and what keeps "Asignar plan" away. */
export function isLive(membership: Membership | undefined): membership is Membership {
  return membership !== undefined && ['trial', 'active', 'frozen'].includes(membership.status)
}

/** Whether "Cambiar plan" is offered on `membership`: a monthly or prepaid one, active or frozen. */
export function changesPlan(membership: Membership): boolean {
  return RECURRING.has(membership.plan_kind) && (membership.status === 'active' || membership.status === 'frozen')
}

/**
 * "Asignar plan" (#249), in the plan column, for someone on the roster with no plan running:
 * never had one, or it lapsed or was cancelled. A plan and its first day, as "Nuevo
 * alumno" asks them, and the welcome, ticked when there is an email to send it to. For
 * the owner and admins; someone dado de baja comes back by "Reactivar" instead.
 *
 * `done` and `setDone` are the ficha's: once the plan starts this moves into its card,
 * a new place in the tree, and a message of its own would go with the old one.
 */
export function AssignPlan({
  person,
  membership,
  role,
  done,
  setDone,
}: {
  person: Person
  membership: Membership | undefined
  role: StaffRole | null | undefined
  done: string | null
  setDone: (message: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const manages = role === 'owner' || role === 'admin'
  if (!manages || person.left_on) return null
  // Started: the plan card has it now, and here only what was done.
  if (isLive(membership)) {
    return (
      done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )
    )
  }

  return (
    <>
      {!open && (
        <div className="member__actions">
          <Button
            variant="primary"
            aria-expanded={false}
            onClick={() => {
              setDone(null)
              setOpen(true)
            }}
          >
            {copy.assignPlan}
          </Button>
        </div>
      )}
      {done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )}
      {open && (
        <AssignForm
          person={person}
          onCancel={() => setOpen(false)}
          onDone={(message) => {
            setOpen(false)
            setDone(message)
          }}
        />
      )}
    </>
  )
}

function AssignForm({
  person,
  onCancel,
  onDone,
}: {
  person: Person
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.assignForm
  const today = useGymToday()
  const refresh = useRefresh()
  const navigate = useNavigate()
  const ids = { welcome: useId(), hint: useId() }
  const [plan, setPlan] = useState<PlanChoice>({ plan_id: '', started_on: '' })
  const [checked, setChecked] = useState(false)
  const [welcome, setWelcome] = useState(true)
  // Theirs or their guardian's address, as the welcome goes.
  const access = useQuery(welcomeQuery(person.id))
  const canWelcome = Boolean(access.data?.to)
  const plans = useQuery(plansQuery)

  const start = useSubmit({
    offline: 'refuse',
    mutationFn: ({ sendWelcome }: { sendWelcome: boolean }) =>
      startMembership(person.id, membershipOf(plan, today)!, sendWelcome),
    onSuccess: async (started, { sendWelcome }) => {
      onDone(form.done(started.plan_name))
      // "Acceso" waits for the welcome to be recorded, as it does after "Nuevo alumno".
      if (sendWelcome) {
        void navigate({
          to: '/admin/alumnos/$personId',
          params: { personId: person.id },
          state: { welcomeSince: Date.now() },
          replace: true,
        })
      }
      await refresh()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (plan.plan_id) start.mutate({ sendWelcome: canWelcome && welcome })
  }

  const missing = checked && !plan.plan_id
  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <PlanStart choice={plan} today={today} labels={form} onChange={setPlan} />
      {missing && (
        <p className="member__error" role="alert">
          {form.planNeeded}
        </p>
      )}
      <label htmlFor={ids.welcome} className="new-member__check">
        <input
          id={ids.welcome}
          type="checkbox"
          checked={welcome && canWelcome}
          disabled={!canWelcome}
          aria-describedby={ids.hint}
          onChange={(e) => setWelcome(e.target.checked)}
        />
        {form.welcome}
      </label>
      {!access.isPending && (
        <p id={ids.hint} className="member__detail">
          {canWelcome ? form.welcomeHint : form.noEmail}
        </p>
      )}
      {start.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={start.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={start.isPending || plans.isPending}
          busy={start.isPending}
        >
          {start.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

// The day before `day`, both as `2026-11-10`.
function dayBefore(day: string): string {
  const previous = new Date(`${day}T00:00:00Z`)
  previous.setUTCDate(previous.getUTCDate() - 1)
  return previous.toISOString().slice(0, 10)
}

function changeRefusal(error: unknown): string {
  const form = copy.changeForm
  if (error instanceof ApiError && error.status === 409) return form.refused.conflict
  if (error instanceof ApiError && error.status === 422) return form.refused.plan
  return form.refused.failed
}

/**
 * "Cambiar plan" (#249): the plan a monthly or prepaid membership moves to, from the
 * first day not yet billed, which the API sets; there is no proration. Before saving
 * it says, from the API's quote, until when the current plan runs and what the first
 * charge on the new one is. With a change pending, the plan it is on withdraws it.
 */
export function ChangePlanForm({
  membership,
  onCancel,
  onDone,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.changeForm
  const queryClient = useQueryClient()
  const id = useId()
  const plans = useQuery(plansQuery)
  const pending = membership.next_plan
  const [planId, setPlanId] = useState('')
  const [checked, setChecked] = useState(false)
  const withdraws = planId !== '' && planId === membership.plan_id
  const quote = useQuery({ ...planChangeQuery(membership.id, planId), enabled: planId !== '' && !withdraws })

  const offered = (plans.data ?? []).filter(
    (plan) => plan.active && RECURRING.has(plan.kind) && plan.id !== membership.plan_id && plan.id !== pending?.plan_id,
  )
  const picked = plans.data?.find((plan) => plan.id === planId)

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (to: string) => changePlan(membership.id, to),
    onSuccess: async (changed: Membership) => {
      const next = changed.next_plan
      onDone(next ? form.done(next.plan_name, shortDay(next.starts_on)) : form.withdrawn)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
      ])
    },
  })

  const ready = withdraws || quote.isSuccess
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (planId && ready) save.mutate(planId)
  }

  if (plans.isSuccess && offered.length === 0 && !pending) {
    return (
      <div className="member__form" role="status">
        <p className="member__detail">{form.none}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>{form.cancel}</Button>
        </div>
      </div>
    )
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit} noValidate>
      <label htmlFor={id} className="member__label">
        {form.plan}
      </label>
      <Select id={id} value={planId} aria-invalid={checked && !planId} onChange={(e) => setPlanId(e.target.value)}>
        <option value="">{form.noPlan}</option>
        {pending && <option value={membership.plan_id}>{form.stay(membership.plan_name)}</option>}
        {offered.map((plan) => (
          <option key={plan.id} value={plan.id}>
            {plan.name}
          </option>
        ))}
      </Select>
      {checked && !planId && (
        <p className="member__error" role="alert">
          {form.planNeeded}
        </p>
      )}
      {withdraws && pending && (
        <p className="member__detail" role="status">
          {form.withdraw(pending.plan_name, membership.plan_name)}
        </p>
      )}
      {quote.isPending && planId !== '' && !withdraws && <p className="member__note">{form.checking}</p>}
      {quote.data && picked && (
        <div className="member__quote" role="status">
          <p className="member__detail">
            {form.current(membership.plan_name, shortDay(dayBefore(quote.data.starts_on)))}
          </p>
          <p className="member__detail">
            {form.next(
              picked.name,
              shortDay(quote.data.starts_on),
              t.common.clp(quote.data.amount_due_clp),
              shortDay(quote.data.period_end),
            )}
          </p>
          {membership.status === 'frozen' && <p className="member__detail">{form.frozen}</p>}
        </div>
      )}
      {(quote.error || save.error) && (
        <p className="member__error" role="alert">
          {changeRefusal(save.error ?? quote.error)}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={save.isPending || (planId !== '' && !ready)}
          busy={save.isPending}
        >
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}
