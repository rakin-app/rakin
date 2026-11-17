import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { managesGym, type Access } from '../api/me'
import {
  changePlan,
  discountQuery,
  planChangeQuery,
  setDiscount,
  startMembership,
  startQuery,
  type ConvertedTrial,
  type Discount,
  type Membership,
  type Person,
} from '../api/member'
import { welcomeQuery } from '../api/people'
import { plansQuery } from '../api/plans'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Chip } from '../components/Chip'
import { Input, Select } from '../components/Field'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { useRefresh } from './PersonData'
import { membershipOf, PlanStart, type PlanChoice } from './PlanStart'
import { Banner, Card, cardClass, CheckRow } from '../components/Card'

const copy = t.admin.member
const clp = t.common.clp

// The kinds that change plan, to each other: a pack or a trial ends instead (`plan_change_starts`).
const RECURRING = new Set(['monthly', 'prepaid', 'fixed_period'])

/** A membership the member is on now: what "Cambiar plan" changes, and what keeps "Asignar plan" away. */
export function isLive(membership: Membership | undefined): membership is Membership {
  return membership !== undefined && ['trial', 'active', 'frozen'].includes(membership.status)
}

/** Whether "Cambiar plan" is offered on `membership`: a monthly, prepaid or fixed-period one, active or frozen. */
export function changesPlan(membership: Membership): boolean {
  return RECURRING.has(membership.plan_kind) && (membership.status === 'active' || membership.status === 'frozen')
}

/** Whether `membership` keeps "Asignar plan" away: a plan running, but for a trial, which
 * a plan assigned converts (#27). */
function holdsPlan(membership: Membership | undefined): boolean {
  return isLive(membership) && membership.plan_kind !== 'trial'
}

/** Whether "Asignar plan" is offered: by the owner or an admin, to someone on the roster
 * with no plan running, or on a trial. */
export function assignsPlan(person: Person, membership: Membership | undefined, access: Access | null | undefined): boolean {
  return managesGym(access) && !person.left_on && !holdsPlan(membership)
}

/**
 * "Asignar plan" (#249), in the plan column, for someone on the roster with no plan running:
 * never had one, or it lapsed or was cancelled. A plan and its first day, as "Nuevo
 * alumno" asks them, and the welcome, ticked when there is an email to send it to. For
 * the owner and admins; someone dado de baja comes back by "Reactivar" instead.
 *
 * `done` and `setDone` are the ficha's: once the plan starts this moves into its card,
 * a new place in the tree, and the card says what was done.
 */
export function AssignPlan({
  person,
  membership,
  access,
  done,
  setDone,
}: {
  person: Person
  membership: Membership | undefined
  access: Access | null | undefined
  done: string | null
  setDone: (message: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  if (!managesGym(access) || person.left_on) return null
  // Started: the plan card has it now, and what was done.
  if (holdsPlan(membership)) return null

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
        <Banner tone="done">
          {done}
        </Banner>
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

/**
 * "Agregar otro plan" (#354), under the plan cards, for someone on a plan already: a
 * second one beside it, a course of credits beside a monthly plan say, with the form
 * "Asignar plan" opens. Each plan then has its own card, bills and lapses on its own,
 * and the roster marks the one a class's program admits. For the owner and admins.
 */
export function AddPlan({
  person,
  access,
  membership,
}: {
  person: Person
  access: Access | null | undefined
  membership: Membership | undefined
}) {
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  // A trial's card has "Asignar plan", which converts it (#27).
  if (!holdsPlan(membership) || !managesGym(access) || person.left_on) return null
  return (
    <>
      {!open && (
        <div className="member__actions">
          <Button
            aria-expanded={false}
            onClick={() => {
              setDone(null)
              setOpen(true)
            }}
          >
            {copy.addPlan}
          </Button>
        </div>
      )}
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {open && (
        <AssignForm
          person={person}
          // They were welcomed with their first plan.
          welcomed={false}
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

/** A plan and its first day, and the welcome: what "Asignar plan" opens. `welcomed`:
 * whether the welcome starts ticked, when there is an address to send it to. */
export function AssignForm({
  person,
  welcomed = true,
  onCancel,
  onDone,
}: {
  person: Person
  welcomed?: boolean
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.assignForm
  const today = useGymToday()
  const refresh = useRefresh()
  const navigate = useNavigate()
  const ids = { welcome: useId(), hint: useId(), discount: useId() }
  const [plan, setPlan] = useState<PlanChoice>({ plan_id: '', started_on: '' })
  const [checked, setChecked] = useState(false)
  const [welcome, setWelcome] = useState(welcomed)
  // Off every period from the first (#25), when ticked.
  const [discounted, setDiscounted] = useState(false)
  const [discount, setDiscountDraft] = useState<DiscountDraft>(NO_DISCOUNT)
  // Theirs or their guardian's address, as the welcome goes.
  const access = useQuery(welcomeQuery(person.id))
  const canWelcome = Boolean(access.data?.to)
  const plans = useQuery(plansQuery)
  // What a lapsed plan still owes, and the day the plan starts after what it billed (#271).
  const quote = useQuery({
    ...startQuery(person.id, plan.plan_id, plan.started_on || today),
    enabled: plan.plan_id !== '',
  })

  const start = useSubmit({
    offline: 'refuse',
    mutationFn: ({ sendWelcome }: { sendWelcome: boolean }) =>
      startMembership(person.id, membershipOf(plan, today)!, sendWelcome, discounted ? discountOf(discount) : undefined),
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
    if (plan.plan_id && (!discounted || discountOf(discount))) start.mutate({ sendWelcome: canWelcome && welcome })
  }

  const missing = checked && !plan.plan_id
  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <PlanStart choice={plan} today={today} labels={form} onChange={setPlan} />
      {plan.plan_id && quote.data && (quote.data.debt_clp > 0 || quote.data.billed_through) && (
        <Banner tone="warning" as="div" className="member__warning">
          {quote.data.debt_clp > 0 && <p>{form.debt(clp(quote.data.debt_clp))}</p>}
          {quote.data.billed_through && (
            <p>
              {form.moved(shortDay(quote.data.billed_through), shortDay(quote.data.starts_on))}
            </p>
          )}
        </Banner>
      )}
      {plan.plan_id && quote.data?.converts && (
        <ConvertsTrial trial={quote.data.converts} />
      )}
      {missing && (
        <Banner tone="error">
          {form.planNeeded}
        </Banner>
      )}
      <CheckRow htmlFor={ids.discount}>
        <input id={ids.discount} type="checkbox" checked={discounted} onChange={(e) => setDiscounted(e.target.checked)} />
        {form.discount}
      </CheckRow>
      {discounted && <DiscountFields draft={discount} checked={checked} onChange={setDiscountDraft} />}
      <CheckRow htmlFor={ids.welcome}>
        <input
          id={ids.welcome}
          type="checkbox"
          checked={welcome && canWelcome}
          disabled={!canWelcome}
          aria-describedby={ids.hint}
          onChange={(e) => setWelcome(e.target.checked)}
        />
        {form.welcome}
      </CheckRow>
      {!access.isPending && (
        <p id={ids.hint} className="member__detail">
          {canWelcome ? form.welcomeHint : form.noEmail}
        </p>
      )}
      {start.error && (
        <Banner tone="error">
          {form.failed}
        </Banner>
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

/** The trial the plan converts (#27): a warning while it runs, since saving ends it. */
function ConvertsTrial({ trial }: { trial: ConvertedTrial }) {
  const line = copy.assignForm.converts(trial.plan_name, shortDay(trial.started_on), trial.running)
  return trial.running ? (
    <Banner tone="warning" as="div" className="member__warning">
      <p>{line}</p>
    </Banner>
  ) : (
    <p className="member__detail">{line}</p>
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
      <Card as="div" className="member__form" role="status">
        <p className="member__detail">{form.none}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>{form.cancel}</Button>
        </div>
      </Card>
    )
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit} noValidate>
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
        <Banner tone="error">
          {form.planNeeded}
        </Banner>
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
        <Banner tone="error">
          {changeRefusal(save.error ?? quote.error)}
        </Banner>
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

/** A discount as its fields hold it: the percentage as typed, and the reason. */
type DiscountDraft = { pct: string; reason: string }

const NO_DISCOUNT: DiscountDraft = { pct: '', reason: '' }

/** The percentage `draft` holds, 1 to 100; `null` for anything else. */
function pctOf(draft: DiscountDraft): number | null {
  const digits = draft.pct.trim()
  if (!/^\d{1,3}$/.test(digits)) return null
  const pct = Number(digits)
  return pct >= 1 && pct <= 100 ? pct : null
}

/** What `draft` sends: `undefined` until it has a percentage and a reason. */
function discountOf(draft: DiscountDraft): Discount | undefined {
  const pct = pctOf(draft)
  const reason = draft.reason.trim()
  return pct !== null && reason ? { pct, reason } : undefined
}

/** A discount's percentage and reason, the usual reasons a tap away (#25). */
function DiscountFields({
  draft,
  checked,
  onChange,
}: {
  draft: DiscountDraft
  checked: boolean
  onChange: (draft: DiscountDraft) => void
}) {
  const form = copy.discountForm
  const ids = { pct: useId(), reason: useId() }
  const pctBad = checked && pctOf(draft) === null
  const reasonBad = checked && draft.reason.trim() === ''
  return (
    <>
      <label htmlFor={ids.pct} className="member__label">
        {form.pct}
      </label>
      <Input
        id={ids.pct}
        inputMode="numeric"
        value={draft.pct}
        aria-invalid={pctBad}
        onChange={(e) => onChange({ ...draft, pct: e.target.value.replace(/\D/g, '') })}
      />
      {pctBad && (
        <Banner tone="error">
          {form.pctNeeded}
        </Banner>
      )}
      <label htmlFor={ids.reason} className="member__label">
        {form.reason}
      </label>
      <Input
        id={ids.reason}
        type="text"
        maxLength={500}
        value={draft.reason}
        aria-invalid={reasonBad}
        onChange={(e) => onChange({ ...draft, reason: e.target.value })}
      />
      <div className="member__fix-choices" role="group" aria-label={form.reasonsLabel}>
        {form.reasons.map((reason) => (
          <Chip key={reason} pressed={draft.reason.trim() === reason} onClick={() => onChange({ ...draft, reason })}>
            {reason}
          </Chip>
        ))}
      </div>
      {reasonBad && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
    </>
  )
}

/** Whether "Descuento" is offered on `membership`: one that bills again, as "Cambiar plan" is. */
export function takesDiscount(membership: Membership): boolean {
  return changesPlan(membership)
}

/**
 * "Descuento" (#25): a percentage off every period the plan bills, with why, from the
 * next period not yet billed, which the API quotes before it is saved; the periods
 * billed already keep theirs. With one set, "Quitar descuento" takes it off.
 */
export function DiscountForm({
  membership,
  onCancel,
  onDone,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.discountForm
  const queryClient = useQueryClient()
  const current = membership.discount_pct ?? 0
  const [draft, setDraft] = useState<DiscountDraft>(
    current > 0 ? { pct: String(current), reason: membership.discount_reason ?? '' } : NO_DISCOUNT,
  )
  const [checked, setChecked] = useState(false)
  const pct = pctOf(draft)
  const quote = useQuery({ ...discountQuery(membership.id, pct ?? 0), enabled: pct !== null })
  const full = useQuery({ ...discountQuery(membership.id, 0), enabled: current > 0 })

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (discount: Discount | null) => setDiscount(membership.id, discount),
    onSuccess: async (_saved: Membership, discount: Discount | null) => {
      onDone(discount ? form.done(discount.pct, discount.reason) : form.removed)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    const discount = discountOf(draft)
    if (discount) save.mutate(discount)
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <DiscountFields draft={draft} checked={checked} onChange={setDraft} />
      {quote.isPending && pct !== null && <p className="member__note">{form.checking}</p>}
      {quote.data && (
        <div className="member__quote" role="status">
          <p className="member__detail">
            {form.next(shortDay(quote.data.starts_on), clp(quote.data.amount_due_clp), shortDay(quote.data.period_end))}
          </p>
          <p className="member__detail">{form.billed}</p>
        </div>
      )}
      {(quote.error || save.error) && (
        <Banner tone="error">
          {discountRefusal(save.error ?? quote.error)}
        </Banner>
      )}
      {current > 0 && full.data && (
        <p className="member__detail">{form.full(shortDay(full.data.starts_on), clp(full.data.amount_due_clp))}</p>
      )}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        {current > 0 && (
          <Button disabled={save.isPending} onClick={() => save.mutate(null)}>
            {form.remove}
          </Button>
        )}
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

function discountRefusal(error: unknown): string {
  const form = copy.discountForm
  if (error instanceof ApiError && error.status === 409) return form.refused.conflict
  return form.refused.failed
}
