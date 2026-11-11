import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { programsQuery, type Program } from '../api/people'
import {
  ANCHORS,
  createPlan,
  PLAN_KINDS,
  plansQuery,
  updatePlan,
  type Plan,
  type PlanFields,
  type PlanKind,
} from '../api/plans'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, integerOf, LoadFailed, refusal } from './settingsForm'

const copy = t.admin.settings.plans
const form = copy.form
const clp = t.common.clp

type Param = 'price_clp' | 'anchor' | 'period_months' | 'credits' | 'credit_expiry_days' | 'free_classes' | 'free_days'

// Each kind's own parameters, in the order the form asks for them.
const KIND_PARAMS: Record<PlanKind, readonly Param[]> = {
  monthly: ['price_clp', 'anchor'],
  prepaid: ['price_clp', 'period_months'],
  credits: ['price_clp', 'credits', 'credit_expiry_days'],
  dropin: ['price_clp'],
  trial: ['free_classes', 'free_days'],
}

const PARAM_LABELS: Record<Param, string> = {
  price_clp: form.price,
  anchor: form.anchor,
  period_months: form.periodMonths,
  credits: form.credits,
  credit_expiry_days: form.creditExpiryDays,
  free_classes: form.freeClasses,
  free_days: form.freeDays,
}

type Drafts = { name: string; program_id: string } & Record<Param, string>

function draftsOf(plan: Plan | undefined): Drafts {
  const value = (param: Param) => {
    const v = plan && param in plan ? (plan as Record<string, unknown>)[param] : undefined
    return v === null || v === undefined ? '' : String(v)
  }
  return {
    name: plan?.name ?? '',
    program_id: plan?.program_id ?? '',
    price_clp: value('price_clp'),
    anchor: plan ? value('anchor') : 'signup',
    period_months: value('period_months'),
    credits: value('credits'),
    credit_expiry_days: value('credit_expiry_days'),
    free_classes: value('free_classes'),
    free_days: value('free_days'),
  }
}

/** A draft as the API takes it: a trial's limits may be left out, everything else is sent as typed. */
function valueOf(param: Param, draft: string): PlanFields[Param] {
  if (param === 'anchor') return draft
  if ((param === 'free_classes' || param === 'free_days') && draft.trim() === '') return null
  return integerOf(draft)
}

function summary(plan: Plan): string {
  switch (plan.kind) {
    case 'monthly':
      return copy.row(copy.summary.monthly(clp(plan.price_clp)), copy.anchors[plan.anchor])
    case 'prepaid':
      return copy.summary.prepaid(clp(plan.price_clp), plan.period_months)
    case 'credits':
      return copy.summary.credits(clp(plan.price_clp), plan.credits, plan.credit_expiry_days)
    case 'dropin':
      return copy.summary.dropin(clp(plan.price_clp))
    case 'trial':
      return copy.summary.trial(plan.free_classes, plan.free_days)
  }
}

/**
 * "Planes": every plan the gym sells, active ones first, and the forms that create
 * and edit them. There is no delete: a plan is deactivated, and the members already
 * on it keep it.
 */
export function PlanSettings() {
  const plans = useQuery(plansQuery)
  // A program's name for each plan; a gym that has none offers "any program" only.
  const programs = useQuery(programsQuery)
  const [editing, setEditing] = useState<string | 'new' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const done = (message: string) => {
    setEditing(null)
    setNotice(message)
  }
  const open = (id: string | 'new') => {
    setNotice(null)
    setEditing(id)
  }

  if (plans.isPending) return <p className="settings__note">{t.admin.settings.loading}</p>
  if (plans.isError) {
    return <LoadFailed error={plans.error} message={copy.error} retry={() => void plans.refetch()} />
  }

  const programList = programs.data ?? []
  return (
    <section className="settings__section" aria-label={copy.title}>
      {notice && (
        <p className="settings__done" role="status">
          {notice}
        </p>
      )}
      {editing === 'new' ? (
        <PlanForm programs={programList} onCancel={() => setEditing(null)} onDone={done} />
      ) : (
        <Button variant="primary" onClick={() => open('new')}>
          {copy.add}
        </Button>
      )}
      {plans.data.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <ul className="settings__card settings__card--rows settings__menu">
          {plans.data.map((plan) => {
            const program = programList.find((p) => p.id === plan.program_id)
            return editing === plan.id ? (
              <li key={plan.id}>
                <PlanForm plan={plan} programs={programList} onCancel={() => setEditing(null)} onDone={done} />
              </li>
            ) : (
              <EditRow
                key={plan.id}
                inactive={!plan.active}
                title={
                  <>
                    {plan.name}
                    {!plan.active && <span className="settings__tag">{copy.inactive}</span>}
                  </>
                }
                detail={[copy.row(copy.kinds[plan.kind], summary(plan)), program?.name ?? (plan.program_id ? '' : copy.anyProgram)]
                  .filter(Boolean)
                  .join(' · ')}
                onOpen={() => open(plan.id)}
              />
            )
          })}
        </ul>
      )}
    </section>
  )
}

function PlanForm({
  plan,
  programs,
  onCancel,
  onDone,
}: {
  plan?: Plan
  programs: Program[]
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  // Deactivating is here, not on the row (#177): the members already on it keep it.
  const toggle = useMutation({
    mutationFn: () => updatePlan(plan!.id, { active: !plan!.active }),
    onSuccess: async (answer) => {
      onDone(answer.active ? copy.reactivated(answer.name) : copy.deactivated(answer.name))
      await queryClient.invalidateQueries({ queryKey: plansQuery.queryKey })
    },
  })
  const [kind, setKind] = useState<PlanKind>(plan?.kind ?? 'monthly')
  const [initial] = useState(() => draftsOf(plan))
  const [drafts, setDrafts] = useState(initial)
  const params = KIND_PARAMS[kind]

  const fields = (keys: readonly (keyof Drafts)[]): PlanFields =>
    Object.fromEntries(
      keys.map((key) => [
        key,
        key === 'name' ? drafts.name : key === 'program_id' ? drafts.program_id || null : valueOf(key, drafts[key]),
      ]),
    )
  // An edit sends only what changed, so a field someone else edited meanwhile is left as they left it.
  const changed = (['name', 'program_id', ...params] as const).filter((k) => drafts[k] !== initial[k])

  const save = useMutation({
    mutationFn: () =>
      plan ? updatePlan(plan.id, fields(changed)) : createPlan({ kind, ...fields(['name', 'program_id', ...params]) }),
    onSuccess: async (answer) => {
      onDone(plan ? copy.saved(answer.name) : copy.created(answer.name))
      await queryClient.invalidateQueries({ queryKey: plansQuery.queryKey })
    },
  })
  // A create's refusals name the kind first (`monthly.price_clp`); an edit's do not.
  const errors = validationErrors(save.error, PLAN_KINDS)
  const errorOf = (field: keyof Drafts) =>
    field in errors ? refusal(errors[field]!, field, form, drafts[field].trim() === '') : undefined
  const set = (field: keyof Drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  // The gym's active programs, and the plan's own even if it was deactivated since.
  const choices = programs.filter((p) => p.active || p.id === plan?.program_id)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    // An edit that changed nothing has nothing to send: the form just closes.
    if (plan && changed.length === 0) {
      onCancel()
      return
    }
    save.mutate()
  }

  return (
    <form className="settings__card settings__form" aria-label={plan ? form.edit(plan.name) : form.create} onSubmit={submit} noValidate>
      <h2 className="settings__legend">{plan ? form.edit(plan.name) : form.create}</h2>
      <Field label={form.kind}>
        {(props) => (
          <Select
            {...props}
            value={kind}
            // The kind is set on create: an edit changes the kind's parameters, not the kind.
            disabled={plan !== undefined}
            onChange={(e) => {
              setKind(e.target.value as PlanKind)
              // The refusals were of the other kind's fields.
              save.reset()
            }}
          >
            {PLAN_KINDS.map((k) => (
              <option key={k} value={k}>
                {copy.kinds[k]}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={form.name} error={errorOf('name')}>
        {(props) => (
          <Input
            {...props}
            type="text"
            maxLength={200}
            value={drafts.name}
            onChange={(e) => set('name', e.target.value)}
          />
        )}
      </Field>
      <Field label={form.program} error={errorOf('program_id')}>
        {(props) => (
          <Select
            {...props}
            value={drafts.program_id}
            onChange={(e) => set('program_id', e.target.value)}
          >
            <option value="">{copy.anyProgram}</option>
            {choices.map((p) => (
              <option key={p.id} value={p.id}>
                {p.active ? p.name : form.inactiveProgram(p.name)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {params.map((param) => (
        <Field
          key={param}
          label={PARAM_LABELS[param]}
          hint={param === 'free_days' ? form.trialHint : undefined}
          error={errorOf(param)}
        >
          {(props) =>
            param === 'anchor' ? (
              <Select
                {...props}
                value={drafts.anchor}
                onChange={(e) => set('anchor', e.target.value)}
              >
                {ANCHORS.map((anchor) => (
                  <option key={anchor} value={anchor}>
                    {copy.anchors[anchor]}
                  </option>
                ))}
              </Select>
            ) : (
              <Input
                {...props}
                type="text"
                inputMode="numeric"
                value={drafts[param]}
                onChange={(e) => set(param, e.target.value)}
              />
            )
          }
        </Field>
      ))}

      {save.error && (
        <p className="settings__error" role="alert">
          {'' in errors && kind === 'trial'
            ? form.trialLimit
            : Object.keys(errors).length > 0
              ? form.invalid
              : form.failed}
        </p>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {plan && (
        <div className="settings__danger">
          {toggle.isError && (
            <p className="settings__error" role="alert">
              {copy.toggleFailed}
            </p>
          )}
          <Button
            variant={plan.active ? 'danger' : 'secondary'}
            disabled={save.isPending || toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {plan.active ? copy.deactivate : copy.reactivate}
          </Button>
        </div>
      )}
    </form>
  )
}
