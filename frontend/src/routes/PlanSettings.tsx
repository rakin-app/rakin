import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { programsQuery, type Program } from '../api/people'
import {
  ANCHORS,
  anchorMovesQuery,
  createPlan,
  nextPeriod,
  PLAN_KINDS,
  planMembershipsQuery,
  plansQuery,
  savedPlan,
  updatePlan,
  type Anchor,
  type AnchorMoves as Quote,
  type AnchorWithdrawal,
  type Plan,
  type PlanFields,
  type PlanKind,
} from '../api/plans'
import { nextYear, shortDate, shortDay } from '../format'
import { validationErrors } from '../api/validation'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { EditRow, Field, integerOf, LoadFailed, refusal, SectionHead } from './settingsForm'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'
import { Banner, Card, cardClass, CheckRow, SectionTitle } from '../components/Card'

const copy = t.admin.settings.plans
const form = copy.form
const clp = t.common.clp

type Param =
  | 'price_clp'
  | 'enrolment_fee_clp'
  | 'anchor'
  | 'period_months'
  | 'period_start'
  | 'period_end'
  | 'credits'
  | 'credit_expiry_days'
  | 'free_classes'
  | 'free_days'

// The parameters typed as a date, `2027-03-01`.
const DATE_PARAMS = new Set<Param>(['period_start', 'period_end'])

// Each kind's own parameters, in the order the form asks for them.
const KIND_PARAMS: Record<PlanKind, readonly Param[]> = {
  monthly: ['price_clp', 'anchor', 'enrolment_fee_clp'],
  prepaid: ['price_clp', 'period_months', 'enrolment_fee_clp'],
  fixed_period: ['price_clp', 'period_start', 'period_end', 'enrolment_fee_clp'],
  credits: ['price_clp', 'credits', 'credit_expiry_days', 'enrolment_fee_clp'],
  dropin: ['price_clp'],
  trial: ['free_classes', 'free_days'],
}

const PARAM_LABELS: Record<Param, string> = {
  price_clp: form.price,
  enrolment_fee_clp: form.enrolmentFee,
  anchor: form.anchor,
  period_months: form.periodMonths,
  period_start: form.periodStart,
  period_end: form.periodEnd,
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
    enrolment_fee_clp: value('enrolment_fee_clp'),
    anchor: plan ? value('anchor') : 'signup',
    period_months: value('period_months'),
    period_start: value('period_start'),
    period_end: value('period_end'),
    credits: value('credits'),
    credit_expiry_days: value('credit_expiry_days'),
    free_classes: value('free_classes'),
    free_days: value('free_days'),
  }
}

// The parameters that may be left empty: a trial's limits, and the matrícula (#355).
const OPTIONAL_PARAMS = new Set<Param>(['free_classes', 'free_days', 'enrolment_fee_clp'])

/** A draft as the API takes it: an optional one left out is none, everything else is sent as typed. */
function valueOf(param: Param, draft: string): PlanFields[Param] {
  if (param === 'anchor' || DATE_PARAMS.has(param)) return draft
  if (OPTIONAL_PARAMS.has(param) && draft.trim() === '') return null
  return integerOf(draft)
}

/** What the plan costs, and its matrícula when it has one: `$45.000 al mes · matrícula $30.000`. */
function summary(plan: Plan): string {
  const terms = kindSummary(plan)
  const fee = ('enrolment_fee_clp' in plan && plan.enrolment_fee_clp) || null
  return fee === null ? terms : copy.row(terms, copy.summary.enrolment(clp(fee)))
}

function kindSummary(plan: Plan): string {
  switch (plan.kind) {
    case 'monthly':
      return copy.row(copy.summary.monthly(clp(plan.price_clp)), copy.anchors[plan.anchor])
    case 'prepaid':
      return copy.summary.prepaid(clp(plan.price_clp), plan.period_months)
    case 'fixed_period':
      return copy.summary.fixed_period(clp(plan.price_clp), shortDate(plan.period_start), shortDate(plan.period_end))
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

  if (plans.isPending) return <Loading className="settings__note">{t.admin.settings.loading}</Loading>
  if (plans.isError) {
    return <LoadFailed error={plans.error} message={copy.error} retry={() => void plans.refetch()} />
  }

  const programList = programs.data ?? []
  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead
        intro={t.admin.settings.descriptions.plans}
        action={
          editing !== 'new' && (
            <Button variant="primary" onClick={() => open('new')}>
              {copy.add}
            </Button>
          )
        }
      />
      {notice && (
        <Banner tone="done">
          {notice}
        </Banner>
      )}
      {editing === 'new' && <PlanForm programs={programList} onCancel={() => setEditing(null)} onDone={done} />}
      {plans.data.length === 0 ? (
        <p className="settings__note">{copy.empty}</p>
      ) : (
        <Card as="ul" flush className="settings__card settings__card--rows settings__menu">
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
        </Card>
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
  const toggle = useSubmit({
    offline: 'refuse',
    mutationFn: () => updatePlan(plan!.id, { active: !plan!.active }),
    onSuccess: async (answer) => {
      const saved = savedPlan(queryClient, answer)
      onDone(answer.active ? copy.reactivated(answer.name) : copy.deactivated(answer.name))
      await saved
    },
  })
  // "Duplicar para el próximo período" open in place of the form (#351).
  const [duplicating, setDuplicating] = useState(false)
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

  // A monthly plan's anchor changed reaches the members already on it only if the owner
  // says so (#547): the moves are quoted first, each member's, and sent with the edit.
  const anchorChanged = plan?.kind === 'monthly' && drafts.anchor !== initial.anchor
  const [moveMembers, setMoveMembers] = useState(false)
  const moves = useQuery({ ...anchorMovesQuery(plan?.id ?? '', drafts.anchor as Anchor), enabled: anchorChanged })
  const moving = anchorChanged && moveMembers && moves.isSuccess ? moves.data.moves.length : 0

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      plan
        ? updatePlan(plan.id, moving ? { ...fields(changed), move_members: true } : fields(changed))
        : createPlan({ kind, ...fields(['name', 'program_id', ...params]) }),
    onSuccess: async (answer) => {
      const saved = savedPlan(queryClient, answer)
      onDone(plan ? (moving ? copy.savedMoved(answer.name, moving) : copy.saved(answer.name)) : copy.created(answer.name))
      await saved
      // The members' fichas say the day they move to.
      if (moving) await queryClient.invalidateQueries({ queryKey: ['people'] })
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

  if (duplicating && plan?.kind === 'fixed_period') {
    return <NextPeriodForm plan={plan} onCancel={() => setDuplicating(false)} onDone={onDone} />
  }

  return (
    <form className={cardClass({}, 'settings__card settings__form')} aria-label={plan ? form.edit(plan.name) : form.create} onSubmit={submit} noValidate>
      <SectionTitle className="settings__legend">{plan ? form.edit(plan.name) : form.create}</SectionTitle>
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
          hint={
            param === 'free_days'
              ? form.trialHint
              : param === 'period_end'
                ? form.periodHint
                : param === 'enrolment_fee_clp'
                  ? form.enrolmentHint
                  : undefined
          }
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
            ) : DATE_PARAMS.has(param) ? (
              <Input {...props} type="date" value={drafts[param]} onChange={(e) => set(param, e.target.value)} />
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
      {anchorChanged && (
        <AnchorMoves
          anchor={drafts.anchor as Anchor}
          moves={moves.data}
          pending={moves.isPending}
          failed={moves.isError}
          checked={moveMembers}
          onChange={setMoveMembers}
        />
      )}

      {save.error && (
        <Banner tone="error">
          {'' in errors && kind === 'trial'
            ? form.trialLimit
            : Object.keys(errors).length > 0
              ? form.invalid
              : form.failed}
        </Banner>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
      {plan?.kind === 'fixed_period' && (
        <Button disabled={save.isPending} onClick={() => setDuplicating(true)}>
          {copy.nextPeriod.open}
        </Button>
      )}
      {plan && (
        <div className="settings__danger">
          {toggle.isError && (
            <Banner tone="error">
              {copy.toggleFailed}
            </Banner>
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

/**
 * "¿Aplicar también a los N alumnos con este plan?" (#547): a monthly plan's anchor
 * changed, offered to the members already on it, each with what moving them bills: the
 * transition to their new day, prorated, then the whole month. Unticked, the form says
 * they keep their day before it is saved.
 */
function AnchorMoves({
  anchor,
  moves: quote,
  pending,
  failed,
  checked,
  onChange,
}: {
  anchor: Anchor
  moves: Quote | undefined
  pending: boolean
  failed: boolean
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  const words = form.anchorMove
  if (pending) {
    return (
      <fieldset className="settings__moves">
        <legend className="settings__label">{words.legend}</legend>
        <Loading className="settings__note">{words.loading}</Loading>
      </fieldset>
    )
  }
  if (failed || quote === undefined) {
    return (
      <fieldset className="settings__moves">
        <legend className="settings__label">{words.legend}</legend>
        <Banner tone="error">{words.error}</Banner>
      </fieldset>
    )
  }
  const { moves } = quote
  // A pending move withdrawn: always without the offer ticked; ticked, only one that does not move again.
  const moving = new Set(checked ? moves.map((m) => m.membership_id) : [])
  const withdrawn = quote.withdrawn.filter((w) => !moving.has(w.membership_id))
  return (
    <fieldset className="settings__moves">
      <legend className="settings__label">{words.legend}</legend>
      {moves.length === 0 ? (
        withdrawn.length === 0 && <p className="settings__note">{words.none}</p>
      ) : (
        <>
          <CheckRow>
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
            {words.offer(moves.length, anchor)}
          </CheckRow>
          {checked ? (
            <>
              <p className="settings__note">{words.proration}</p>
              <ul className="settings__note" aria-label={words.legend}>
                {moves.map((move) => (
                  <li key={move.membership_id}>
                    {[
                      move.name,
                      words.line(
                        shortDay(move.starts_on),
                        shortDay(move.ends_on),
                        clp(move.amount_due_clp),
                        shortDay(move.next_starts_on),
                        clp(move.next_amount_clp),
                      ),
                      move.status === 'frozen' ? words.frozen : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="settings__note">{words.declined(anchor)}</p>
          )}
        </>
      )}
      {withdrawn.length > 0 && <Withdrawn withdrawn={withdrawn} />}
    </fieldset>
  )
}

/** "Ana Rojas · se cancela el cambio al día 12: sigue pagando el día 1" (#547). */
function Withdrawn({ withdrawn }: { withdrawn: AnchorWithdrawal[] }) {
  const words = form.anchorMove
  return (
    <ul className="settings__note">
      {withdrawn.map((w) => (
        <li key={w.membership_id}>{[w.name, words.withdrawn(w.pending_day, w.stays_on)].join(' · ')}</li>
      ))}
    </ul>
  )
}

/** A plan's name for its next period: each year in it one on, `Temporada 2027` to `Temporada 2028`. */
function nextName(name: string): string {
  return name.replace(/\b(19|20)\d{2}\b/g, (year) => String(Number(year) + 1))
}

/**
 * "Duplicar para el próximo período" (#351): a fixed-period plan does not renew itself.
 * The owner copies it with the dates a year on, as they can change, and moves the
 * members on its list across, every one ticked to begin with: each moves when what
 * they paid for runs out.
 */
function NextPeriodForm({
  plan,
  onCancel,
  onDone,
}: {
  plan: Extract<Plan, { kind: 'fixed_period' }>
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const words = copy.nextPeriod
  const queryClient = useQueryClient()
  const members = useQuery(planMembershipsQuery(plan.id))
  const [drafts, setDrafts] = useState({
    name: nextName(plan.name),
    price_clp: String(plan.price_clp),
    period_start: nextYear(plan.period_start),
    period_end: nextYear(plan.period_end),
  })
  // Who does not move: everyone on the list moves unless unticked.
  const [staying, setStaying] = useState<ReadonlySet<string>>(new Set())
  const set = (field: keyof typeof drafts, value: string) => setDrafts({ ...drafts, [field]: value })

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      nextPeriod(plan.id, {
        name: drafts.name,
        price_clp: integerOf(drafts.price_clp),
        period_start: drafts.period_start,
        period_end: drafts.period_end,
        membership_ids: (members.data ?? []).map((m) => m.membership_id).filter((id) => !staying.has(id)),
      }),
    onSuccess: async (answer) => {
      const saved = savedPlan(queryClient, answer.plan)
      onDone(words.done(answer.plan.name, answer.moved))
      await saved
    },
  })
  const errors = validationErrors(save.error)
  const errorOf = (field: keyof typeof drafts) => {
    if (!(field in errors)) return undefined
    if (errors[field] === 'after_period') return words.afterPeriod(shortDate(plan.period_end))
    return refusal(errors[field]!, field, form, drafts[field].trim() === '')
  }
  const notOnPlan =
    save.error instanceof ApiError &&
    save.error.status === 409 &&
    (save.error.body as { detail?: { code?: string } } | undefined)?.detail?.code === 'not_on_plan'

  const toggle = (id: string) => {
    const next = new Set(staying)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setStaying(next)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    save.mutate()
  }

  return (
    <form className={cardClass({}, 'settings__card settings__form')} aria-label={words.title(plan.name)} onSubmit={submit} noValidate>
      <SectionTitle className="settings__legend">{words.title(plan.name)}</SectionTitle>
      <p className="settings__note">{words.intro}</p>
      <Field label={form.name} error={errorOf('name')}>
        {(props) => (
          <Input {...props} type="text" maxLength={200} value={drafts.name} onChange={(e) => set('name', e.target.value)} />
        )}
      </Field>
      <Field label={form.price} error={errorOf('price_clp')}>
        {(props) => (
          <Input {...props} type="text" inputMode="numeric" value={drafts.price_clp} onChange={(e) => set('price_clp', e.target.value)} />
        )}
      </Field>
      <Field label={form.periodStart} error={errorOf('period_start')}>
        {(props) => <Input {...props} type="date" value={drafts.period_start} onChange={(e) => set('period_start', e.target.value)} />}
      </Field>
      <Field label={form.periodEnd} error={errorOf('period_end')}>
        {(props) => <Input {...props} type="date" value={drafts.period_end} onChange={(e) => set('period_end', e.target.value)} />}
      </Field>
      <fieldset className="settings__moves">
        <legend className="settings__label">{words.members}</legend>
        {members.isPending ? (
          <Loading className="settings__note">{words.loading}</Loading>
        ) : members.isError ? (
          <Banner tone="error">{words.error}</Banner>
        ) : members.data.length === 0 ? (
          <p className="settings__note">{words.none}</p>
        ) : (
          members.data.map((member) => (
            <CheckRow key={member.membership_id}>
              <input
                type="checkbox"
                checked={!staying.has(member.membership_id)}
                onChange={() => toggle(member.membership_id)}
              />
              {[
                member.name,
                member.status === 'frozen' ? words.frozen : null,
                member.next_plan_name ? words.pending(member.next_plan_name) : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </CheckRow>
          ))
        )}
      </fieldset>
      {save.error && (
        <Banner tone="error">
          {notOnPlan ? words.notOnPlan : Object.keys(errors).length > 0 ? form.invalid : words.failed}
        </Banner>
      )}
      <div className="settings__actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={save.isPending || !members.isSuccess}
          busy={save.isPending}
        >
          {save.isPending ? words.working : words.submit}
        </Button>
      </div>
    </form>
  )
}
