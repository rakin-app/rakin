import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { activitiesQuery } from '../api/activities'
import { classTypesQuery } from '../api/classes'
import { ApiError } from '../api/client'
import { gymSettingsQuery } from '../api/gym'
import { recordPayment, type Method } from '../api/member'
import { myRoleQuery, myselfQuery, readsLedger } from '../api/me'
import { memberCountQuery, plansQuery } from '../api/people'
import { proofQueueQuery, type ProofReview } from '../api/review'
import { todaySessionsQuery, unmarkedSessionsQuery, type ClassSession } from '../api/sessions'
import { staffQuery } from '../api/staff'
import { inactiveQuery, logNudge, type InactiveMember } from '../api/inactive'
import { remindersQuery, ordinal, type PaymentReminder } from '../api/reminders'
import { overdueQuery, type OverduePeriod } from '../api/today'
import { Button, buttonClass } from '../components/Button'
import { EmptyState } from '../components/Card'
import { Select } from '../components/Field'
import { WhatsAppIcon } from '../components/icons'
import { JoinRequests } from '../components/JoinRequests'
import { Grid, PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { ReminderLink } from '../components/ReminderLink'
import { dayTime, monthName, shortDay, timeRange, toDate, weekdayDay } from '../format'
import { t } from '../i18n/es'
import { useGymName, usePageTitle } from '../pageTitle'
import './Today.css'
import { useSubmit } from '../api/submit'

const copy = t.admin.today
const clp = t.common.clp

// The overdue list shows this many until "Ver los N vencidos".
const OVERDUE_SHOWN = 3

/**
 * "Hoy": the owner's day at a glance. How many periods are overdue, how many proofs
 * wait for review, how many classes went without attendance and how many members
 * stopped coming, then each list, each a tap from acting on it: "Revisar" opens the
 * proof queue, "Pagó" records the payment in place.
 *
 * "Sin venir 14 d" and "A quién llamar" are the members who stopped coming (#50): the
 * five most recently away, each a tap from a WhatsApp nudge, and the rest in Alumnos.
 *
 * "Sin asistencia": the week's classes no one was marked at, each a tap from taking
 * its attendance, so a class taught without a list does not go unseen.
 *
 * Money, so for whoever reads the ledger only. A coach's Hoy is today's classes, each a
 * tap from its attendance, and the join link's requests a coach can act on (#178). The
 * join link's requests come first for an owner or admin (#154).
 *
 * Each overdue row has its WhatsApp reminder beside "Pagó", saying which one it is
 * ("2.º aviso") and standing out when the gym's cadence says the next is due; "Por
 * avisar" has the periods due today and the rejected proofs to follow up, when there
 * are any (#55).
 *
 * A phone stacks it all; from 1024px the counters run across the top and the lists sit
 * in a grid of two.
 *
 * A gym on its first day has none of that: "Configura tu academia" leads the owner
 * through setting it up, until it has members and classes (#166).
 */
export function Today() {
  const role = useQuery(myRoleQuery())
  const money = readsLedger(role.data)
  const gym = useGymName()
  usePageTitle(copy.title)

  return (
    <div className="today">
      <PageContainer className="today__page">
        <PageHeader eyebrow={gym} title={copy.heading(weekdayDay(new Date()))} />
        {role.isError && <Failed message={copy.roleError} retry={() => void role.refetch()} />}
        {role.data === 'coach' && <CoachToday />}
        {money && <OwnerToday />}
      </PageContainer>
    </div>
  )
}

/** A coach's Hoy: today's classes, each a tap from its attendance, then the join requests. */
function CoachToday() {
  const words = copy.classes
  const day = useQuery(todaySessionsQuery())
  return (
    <>
      <section className="today__section" aria-labelledby="clases-hoy-title">
        <SectionHead
          id="clases-hoy-title"
          title={words.title}
          aside={day.data && day.data.sessions.length > 0 ? words.count(day.data.sessions.length) : null}
        />
        {day.isPending ? (
          <p className="today__note">{copy.loading}</p>
        ) : day.isError ? (
          <Failed message={words.error} retry={() => void day.refetch()} />
        ) : day.data.sessions.length === 0 ? (
          <EmptyState
            action={
              <Link to="/admin/clases" className={buttonClass({ variant: 'primary' })}>
                {words.create}
              </Link>
            }
          >
            {words.empty}
          </EmptyState>
        ) : (
          <ul className="today__list">
            {day.data.sessions.map((session) => (
              <ClassRow key={session.id} session={session} timeZone={day.data.timezone} />
            ))}
          </ul>
        )}
      </section>
      <JoinRequests />
    </>
  )
}

function ClassRow({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  const words = copy.classes
  const name = copy.unmarked.row(timeRange(session.starts_at, session.duration_minutes, timeZone), session.class_type_name)
  const cancelled = session.cancelled_at !== null
  const detail = [session.coach_name, cancelled ? words.cancelled : words.present(session.present)].join(' · ')
  return (
    <li>
      <Link
        to="/admin/clases/$sessionId"
        params={{ sessionId: session.id }}
        className="today__row today__row--link"
        aria-label={cancelled ? words.viewLabel(name) : words.takeLabel(name)}
      >
        <span className="today__row-text">
          <span className="today__name">{name}</span>
          <span className="today__detail">{detail}</span>
        </span>
        <span className={buttonClass()} aria-hidden="true">
          {cancelled ? words.view : words.take}
        </span>
      </Link>
    </li>
  )
}

/** The owner's and an admin's Hoy: the money, who stopped coming, the unmarked classes. */
function OwnerToday() {
  const proofs = useQuery(proofQueueQuery())
  const overdue = useQuery(overdueQuery())
  const inactive = useQuery(inactiveQuery())
  const unmarked = useQuery(unmarkedSessionsQuery())
  const reminders = useQuery(remindersQuery())
  const reminderFor = new Map((reminders.data ?? []).map((r) => [r.billing_period_id, r]))
  // The overdue ones are on their "Vencidos" rows.
  const toRemind = (reminders.data ?? []).filter((r) => r.days_overdue <= 0)

  return (
    <>
      <Setup />
      <div className="today__counters" aria-label={copy.countersLabel} role="group">
        <Counter href="#vencidos" value={overdue.data?.periods.length} label={copy.overdue.title} tone="warning" />
        <Counter href="#validar" value={proofs.data?.length} label={copy.proofs.title} tone="accent" />
        <Counter
          href="#sin-asistencia"
          value={unmarked.data?.sessions.length}
          label={copy.unmarked.title}
          tone="muted"
        />
        <Counter href="#inactivos" value={inactive.data?.length} label={copy.inactive.counter} tone="muted" />
      </div>
      <Grid className="today__grid">
        <JoinRequests />
        <section id="validar" className="today__section" aria-labelledby="validar-title">
          <SectionHead
            id="validar-title"
            title={copy.proofs.title}
            aside={proofs.data && proofs.data.length > 0 ? copy.proofs.count(proofs.data.length) : null}
          />
          {proofs.isPending ? (
            <p className="today__note">{copy.loading}</p>
          ) : proofs.isError ? (
            <Failed message={copy.proofs.error} retry={() => void proofs.refetch()} />
          ) : proofs.data.length === 0 ? (
            <p className="today__note">{copy.proofs.empty}</p>
          ) : (
            <ul className="today__list">
              {proofs.data.map((proof) => (
                <ProofRow key={proof.id} proof={proof} />
              ))}
            </ul>
          )}
        </section>
        <section id="vencidos" className="today__section" aria-labelledby="vencidos-title">
          <SectionHead
            id="vencidos-title"
            title={copy.overdue.title}
            aside={overdue.data && overdue.data.total_clp > 0 ? copy.overdue.total(clp(overdue.data.total_clp)) : null}
          />
          {overdue.isPending ? (
            <p className="today__note">{copy.loading}</p>
          ) : overdue.isError ? (
            <Failed message={copy.overdue.error} retry={() => void overdue.refetch()} />
          ) : overdue.data.periods.length === 0 ? (
            <p className="today__note">{copy.overdue.empty}</p>
          ) : (
            <OverdueList periods={overdue.data.periods} reminderFor={reminderFor} />
          )}
        </section>
        {toRemind.length > 0 && (
          <section id="por-avisar" className="today__section" aria-labelledby="por-avisar-title">
            <SectionHead id="por-avisar-title" title={copy.remind.title} aside={copy.remind.count(toRemind.length)} />
            <ul className="today__list">
              {toRemind.map((reminder) => (
                <RemindRow key={reminder.billing_period_id} reminder={reminder} />
              ))}
            </ul>
          </section>
        )}
        <section id="inactivos" className="today__section" aria-labelledby="inactivos-title">
          <SectionHead
            id="inactivos-title"
            title={copy.inactive.title}
            aside={inactive.data && inactive.data.length > 0 ? copy.inactive.count(inactive.data.length) : null}
          />
          {inactive.isPending ? (
            <p className="today__note">{copy.loading}</p>
          ) : inactive.isError ? (
            <Failed message={copy.inactive.error} retry={() => void inactive.refetch()} />
          ) : inactive.data.length === 0 ? (
            <p className="today__note">{copy.inactive.empty}</p>
          ) : (
            <InactiveList members={inactive.data} />
          )}
        </section>
        <section id="sin-asistencia" className="today__section" aria-labelledby="sin-asistencia-title">
          <SectionHead
            id="sin-asistencia-title"
            title={copy.unmarked.title}
            aside={
              unmarked.data && unmarked.data.sessions.length > 0
                ? copy.unmarked.count(unmarked.data.sessions.length)
                : null
            }
          />
          {unmarked.isPending ? (
            <p className="today__note">{copy.loading}</p>
          ) : unmarked.isError ? (
            <Failed message={copy.unmarked.error} retry={() => void unmarked.refetch()} />
          ) : unmarked.data.sessions.length === 0 ? (
            <p className="today__note">{copy.unmarked.empty}</p>
          ) : (
            <ul className="today__list">
              {unmarked.data.sessions.map((session) => (
                <UnmarkedRow key={session.id} session={session} timeZone={unmarked.data.timezone} />
              ))}
            </ul>
          )}
        </section>
      </Grid>
    </>
  )
}

// The checklist's answers change only when someone sets something up, and each of those
// screens refreshes its own; Hoy need not ask again on every visit.
const SETUP_STALE_MS = 5 * 60_000

/** Where this browser remembers that a gym is set up: per host, which is per gym, and per
 * person, for a gym served on the instance's own address. */
export function setupDoneKey(personId: string): string {
  return `rakin:setup-done:${window.location.host}:${personId}`
}

// Storage can be refused (a private window); then the checklist just asks again.
function remembered(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function remember(key: string) {
  try {
    window.localStorage.setItem(key, '1')
  } catch {
    // Not remembered: the next visit asks the two questions again.
  }
}

/**
 * "Configura tu academia": a new gym's steps, each ticked once done and a link to where
 * it is done. Shown until the gym has members and classes, and never again after that in
 * this browser: a gym set up once is remembered, and its Hoy asks nothing for it.
 */
function Setup() {
  const me = useQuery(myselfQuery())
  if (!me.data) return null
  const key = setupDoneKey(me.data.person_id)
  return remembered(key) ? null : <SetupChecklist doneKey={key} />
}

function SetupChecklist({ doneKey }: { doneKey: string }) {
  // First the two answers that decide whether it shows at all; the other three only once
  // it will, so a gym that is set up costs two small requests, once.
  const members = useQuery({ ...memberCountQuery, staleTime: SETUP_STALE_MS })
  const classTypes = useQuery({ ...classTypesQuery, staleTime: SETUP_STALE_MS })
  const hasMembers = (members.data ?? 0) > 0
  const hasClasses = classTypes.data?.some((c) => c.active) ?? false
  const setUp = hasMembers && hasClasses
  const shows = members.data !== undefined && classTypes.data !== undefined && !setUp
  const gym = useQuery({ ...gymSettingsQuery(), staleTime: SETUP_STALE_MS, enabled: shows })
  const plans = useQuery({ ...plansQuery, staleTime: SETUP_STALE_MS, enabled: shows })
  const staff = useQuery({ ...staffQuery, staleTime: SETUP_STALE_MS, enabled: shows })
  const activities = useQuery({ ...activitiesQuery, staleTime: SETUP_STALE_MS, enabled: shows })

  useEffect(() => {
    if (setUp) remember(doneKey)
  }, [setUp, doneKey])

  // A failed answer says so, with a retry, rather than leaving a new gym with no checklist.
  const failed = [members, classTypes, gym, plans, staff, activities].filter((q) => q.isError)
  if (failed.length > 0) {
    return <Failed message={copy.setup.error} retry={() => failed.forEach((q) => void q.refetch())} />
  }
  // Nothing until every answer is in: drawing it on a partial answer would show a set-up
  // gym unticked steps for a moment.
  if (!shows || !gym.data || !plans.data || !staff.data || !activities.data) return null

  const steps = copy.setup.steps
  const done = {
    // First what the gym teaches (#245), which decides whether anything speaks of belts.
    activities: activities.data.length > 0,
    gym: gym.data.bank_account !== null,
    plans: plans.data.some((p) => p.active),
    classes: hasClasses,
    members: hasMembers,
    // The owner is on the staff from the start.
    staff: staff.data.length > 1,
  }
  const count = Object.values(done).filter(Boolean).length
  return (
    <section className="today__setup" aria-labelledby="setup-title">
      <div className="today__section-head">
        <h2 id="setup-title" className="today__setup-title">
          {copy.setup.title}
        </h2>
        <span className="today__aside">{copy.setup.progress(count, Object.keys(done).length)}</span>
      </div>
      <ol className="today__steps">
        <SetupStep done={done.activities} title={steps.activities.title} hint={steps.activities.hint}>
          <Link to="/admin/ajustes/gimnasio" hash="actividades" className="today__link">
            {steps.activities.link}
          </Link>
        </SetupStep>
        <SetupStep done={done.gym} title={steps.gym.title} hint={steps.gym.hint}>
          <Link to="/admin/ajustes/gimnasio" className="today__link">
            {steps.gym.link}
          </Link>
        </SetupStep>
        <SetupStep done={done.plans} title={steps.plans.title} hint={steps.plans.hint}>
          <Link to="/admin/ajustes/planes" className="today__link">
            {steps.plans.link}
          </Link>
        </SetupStep>
        <SetupStep done={done.classes} title={steps.classes.title} hint={steps.classes.hint}>
          <Link to="/admin/ajustes/programas" className="today__link">
            {steps.classes.link}
          </Link>
        </SetupStep>
        <SetupStep done={done.members} title={steps.members.title} hint={steps.members.hint}>
          <Link to="/admin/alumnos/nuevo" className="today__link">
            {steps.members.manual}
          </Link>
          <Link to="/admin/alumnos/importar" className="today__link">
            {steps.members.import}
          </Link>
          <Link to="/admin/ajustes/inscripcion" className="today__link">
            {steps.members.joinLink}
          </Link>
        </SetupStep>
        <SetupStep done={done.staff} title={steps.staff.title} hint={steps.staff.hint}>
          <Link to="/admin/ajustes/equipo" className="today__link">
            {steps.staff.link}
          </Link>
        </SetupStep>
      </ol>
    </section>
  )
}

function SetupStep({
  done,
  title,
  hint,
  children,
}: {
  done: boolean
  title: string
  hint: string
  children: ReactNode
}) {
  return (
    <li className={`today__step${done ? ' today__step--done' : ''}`}>
      <span className="today__check" aria-hidden="true">
        {done ? '✓' : ''}
      </span>
      <span className="today__row-text">
        <span className="today__name">
          {title}
          <span className="visually-hidden">{copy.setup.state(done)}</span>
        </span>
        <span className="today__detail">{hint}</span>
        <span className="today__step-links">{children}</span>
      </span>
    </li>
  )
}

function Counter({
  href,
  value,
  label,
  tone,
}: {
  href: string
  value: number | undefined
  label: string
  tone: 'warning' | 'accent' | 'muted'
}) {
  return (
    // The figure and its label are two spans, which a name would otherwise run together.
    <a href={href} className="today__counter" aria-label={value === undefined ? label : `${value} ${label}`}>
      <span className={`today__counter-value today__counter-value--${tone}`}>{value ?? '–'}</span>
      <span className="today__counter-label">{label}</span>
    </a>
  )
}

function SectionHead({ id, title, aside }: { id: string; title: string; aside: string | null }) {
  return (
    <div className="today__section-head">
      <h2 id={id} className="today__section-title">
        {title}
      </h2>
      {aside && <span className="today__aside">{aside}</span>}
    </div>
  )
}

function Failed({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="today__error" role="alert">
      <p>{message}</p>
      <Button onClick={retry}>
        {copy.retry}
      </Button>
    </div>
  )
}

function ProofRow({ proof }: { proof: ProofReview }) {
  const sender = proof.claimed_by_name
  const name =
    sender && sender !== proof.person_name ? copy.proofs.sentFor(sender, proof.person_name) : proof.person_name
  const detail = [
    copy.proofs.detail(
      clp(proof.amount_clp),
      // A cobro extra's proof names the cobro instead of a month (#195).
      proof.period ? monthName(proof.period.period_start) : (proof.extra_line?.title ?? ''),
    ),
    proof.claimed_at && ago(proof.claimed_at, new Date()),
  ]
    .filter(Boolean)
    .join(' · ')
  return (
    <li>
      <Link
        to="/admin/pagos/comprobantes"
        className="today__row today__row--link"
        aria-label={copy.proofs.reviewLabel(name)}
      >
        <span className="today__row-text">
          <span className="today__name">{name}</span>
          <span className="today__detail">{detail}</span>
        </span>
        <span className={buttonClass()} aria-hidden="true">
          {copy.proofs.review}
        </span>
      </Link>
    </li>
  )
}

function UnmarkedRow({ session, timeZone }: { session: ClassSession; timeZone: string }) {
  const name = copy.unmarked.row(dayTime(session.starts_at, timeZone), session.class_type_name)
  return (
    <li>
      <Link
        to="/admin/clases/$sessionId"
        params={{ sessionId: session.id }}
        className="today__row today__row--link"
        aria-label={copy.unmarked.takeLabel(name)}
      >
        <span className="today__row-text">
          <span className="today__name">{name}</span>
          <span className="today__detail">{copy.unmarked.detail(session.program_name, session.coach_name)}</span>
        </span>
        <span className={buttonClass()} aria-hidden="true">
          {copy.unmarked.take}
        </span>
      </Link>
    </li>
  )
}

/** `hace 2 h`, `ayer`, else the day: when a proof was sent, as of `now`. */
export function ago(iso: string, now: Date): string {
  const then = toDate(iso)
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000)
  if (minutes < 1) return copy.ago.now
  if (minutes < 60) return copy.ago.minutes(minutes)
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  if (then.toDateString() === now.toDateString()) return copy.ago.hours(Math.floor(minutes / 60))
  if (then.toDateString() === yesterday.toDateString()) return copy.ago.yesterday
  return shortDay(iso)
}

/** "2.º aviso ayer": the last reminder about the period, if one was sent. */
function remindedDetail(reminder: PaymentReminder | undefined): string | null {
  if (!reminder?.reminded_at) return null
  return t.admin.reminders.sent(ordinal(reminder.reminders_sent), ago(reminder.reminded_at, new Date()))
}

function OverdueList({
  periods,
  reminderFor,
}: {
  periods: OverduePeriod[]
  reminderFor: Map<string, PaymentReminder>
}) {
  const [all, setAll] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const shown = all ? periods : periods.slice(0, OVERDUE_SHOWN)
  return (
    <>
      {done && (
        <p className="today__done" role="status">
          {done}
        </p>
      )}
      <ul className="today__list">
        {shown.map((period) => (
          <OverdueRow
            key={period.billing_period_id}
            period={period}
            reminder={reminderFor.get(period.billing_period_id)}
            onDone={setDone}
          />
        ))}
      </ul>
      {!all && periods.length > OVERDUE_SHOWN && (
        <Button variant="ghost" onClick={() => setAll(true)}>
          {copy.overdue.showAll(periods.length)}
        </Button>
      )}
    </>
  )
}

const METHODS: readonly Method[] = ['cash', 'transfer', 'other']

/** "Por avisar": a period due today, or a rejected proof to follow up. */
function RemindRow({ reminder }: { reminder: PaymentReminder }) {
  const words = t.admin.reminders
  const detail =
    reminder.kind === 'proof_rejected_followup' && reminder.rejection_note
      ? words.rejected(reminder.rejection_note)
      : words.dueToday(clp(reminder.outstanding_clp), reminder.plan_name)
  const reminded = remindedDetail(reminder)
  return (
    <li className="today__row">
      <div className="today__row-line">
        <Link
          to="/admin/alumnos/$personId"
          params={{ personId: reminder.person_id }}
          className="today__row-text today__row-text--link"
        >
          <span className="today__name">{reminder.person_name}</span>
          <span className="today__detail">{detail}</span>
          {reminded && <span className="today__detail">{reminded}</span>}
        </Link>
        <ReminderLink reminder={reminder} />
      </div>
    </li>
  )
}

function OverdueRow({
  period,
  reminder,
  onDone,
}: {
  period: OverduePeriod
  reminder: PaymentReminder | undefined
  onDone: (message: string) => void
}) {
  const [open, setOpen] = useState(false)
  const amount = clp(period.outstanding_clp)
  const reminded = remindedDetail(reminder)
  return (
    <li className="today__row today__row--overdue">
      <div className="today__row-line">
        <Link
          to="/admin/alumnos/$personId"
          params={{ personId: period.person_id }}
          className="today__row-text today__row-text--link"
        >
          <span className="today__name">{period.person_name}</span>
          <span className="today__detail today__detail--warning">
            {[
              copy.overdue.detail(period.days_overdue, amount, period.plan_name),
              copy.overdue.membership[period.membership_status],
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
          {reminded && <span className="today__detail">{reminded}</span>}
        </Link>
        {!open && reminder && <ReminderLink reminder={reminder} />}
        {!open && (
          <Button
            aria-label={copy.overdue.paidLabel(period.person_name)}
            onClick={() => setOpen(true)}
          >
            {copy.overdue.paid}
          </Button>
        )}
      </div>
      {open && (
        <PaidForm
          period={period}
          onCancel={() => setOpen(false)}
          onDone={() => {
            setOpen(false)
            onDone(copy.overdue.recorded(period.person_name, amount))
          }}
        />
      )}
    </li>
  )
}

/** "Pagó": the period's outstanding amount, received by the method chosen. */
function PaidForm({ period, onCancel, onDone }: { period: OverduePeriod; onCancel: () => void; onDone: () => void }) {
  const queryClient = useQueryClient()
  const methodId = useId()
  const [method, setMethod] = useState<Method>('cash')
  const record = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordPayment({
        membership_id: period.membership_id,
        billing_period_id: period.billing_period_id,
        amount_clp: period.outstanding_clp,
        method,
      }),
    onSuccess: async () => {
      onDone()
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    record.mutate()
  }

  return (
    <form className="today__form" aria-label={copy.overdue.paidLabel(period.person_name)} onSubmit={submit}>
      <label htmlFor={methodId} className="today__label">
        {copy.overdue.method}
      </label>
      <Select id={methodId} value={method} onChange={(e) => setMethod(e.target.value as Method)}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {t.admin.member.form.methods[m]}
          </option>
        ))}
      </Select>
      {record.error && (
        <p className="today__error" role="alert">
          {record.error instanceof ApiError && record.error.status === 409
            ? copy.overdue.refused.paid
            : copy.overdue.refused.failed}
        </p>
      )}
      <div className="today__form-actions">
        <Button disabled={record.isPending} onClick={onCancel}>
          {copy.overdue.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={record.isPending} busy={record.isPending}>
          {record.isPending ? copy.overdue.working : copy.overdue.submit(clp(period.outstanding_clp))}
        </Button>
      </div>
    </form>
  )
}

// "A quién llamar" shows this many, the most recently away, until "Ver los N" in Alumnos.
const INACTIVE_SHOWN = 5

/** "A quién llamar": the most recently away first, as the API lists them, the rest in Alumnos. */
function InactiveList({ members }: { members: InactiveMember[] }) {
  return (
    <>
      <ul className="today__list">
        {members.slice(0, INACTIVE_SHOWN).map((member) => (
          <InactiveRow key={member.person_id} member={member} />
        ))}
      </ul>
      {members.length > INACTIVE_SHOWN && (
        <Link to="/admin/alumnos" search={{ away: true }} className={buttonClass({ variant: 'ghost' })}>
          {copy.inactive.showAll(members.length)}
        </Link>
      )}
    </>
  )
}

function InactiveRow({ member }: { member: InactiveMember }) {
  const queryClient = useQueryClient()
  // The link opens WhatsApp itself; this only records that it was opened.
  const nudge = useSubmit({
    mutationFn: () => logNudge(member.person_id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: inactiveQuery().queryKey }),
  })
  const payment =
    member.payment_status === 'overdue'
      ? copy.inactive.payment.overdue(clp(member.overdue_clp))
      : copy.inactive.payment[member.payment_status]
  const detail = [
    member.last_attended_on === null
      ? copy.inactive.never(member.days_absent)
      : copy.inactive.absent(member.days_absent),
    payment,
    member.nudged_at && copy.inactive.nudged(ago(member.nudged_at, new Date())),
  ]
    .filter(Boolean)
    .join(' · ')
  const label =
    member.contact_name === member.name
      ? copy.inactive.write(member.name)
      : copy.inactive.writeFor(member.contact_name, member.name)
  return (
    <li className="today__row">
      <div className="today__row-line">
        <Link
          to="/admin/alumnos/$personId"
          params={{ personId: member.person_id }}
          className="today__row-text today__row-text--link"
        >
          <span className="today__name">{member.name}</span>
          <span
            className={`today__detail${member.payment_status === 'overdue' ? ' today__detail--warning' : ''}`}
          >
            {detail}
          </span>
        </Link>
        {member.whatsapp_url && (
          <a
            href={member.whatsapp_url}
            target="_blank"
            rel="noopener noreferrer"
            className={buttonClass({ icon: true })}
            aria-label={label}
            onClick={() => nudge.mutate()}
            // A middle-click opens it in a new tab too.
            onAuxClick={(event) => {
              if (event.button === 1) nudge.mutate()
            }}
          >
            <WhatsAppIcon />
          </a>
        )}
      </div>
    </li>
  )
}
