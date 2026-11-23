import { useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { activitiesQuery } from '../api/activities'
import { classTypesQuery } from '../api/classes'
import { ApiError } from '../api/client'
import { gymSettingsQuery } from '../api/gym'
import { METHODS, recordPayment, trialConversionsQuery, type Method } from '../api/member'
import { myAccessQuery, myselfQuery, readsLedger } from '../api/me'
import { memberCountQuery, missingGuardianQuery, plansQuery, type MemberRow } from '../api/people'
import { proofQueueQuery, type ProofReview } from '../api/review'
import { requirementsDueQuery, type RequirementsDue } from '../api/requirements'
import { scheduleQuery } from '../api/schedule'
import { isClass, todaySessionsQuery, unmarkedSessionsQuery, type ClassSession, type SessionDay } from '../api/sessions'
import { staffQuery } from '../api/staff'
import { inactiveQuery, logNudge, type InactiveMember } from '../api/inactive'
import { remindersQuery, ordinal, type PaymentReminder } from '../api/reminders'
import { overdueQuery, type OverduePeriod } from '../api/today'
import { Button, buttonClass } from '../components/Button'
import { cx } from '../components/classNames'
import { Banner, Card, cardClass, EmptyState, PlainList, SectionTitle } from '../components/Card'
import { Select } from '../components/Field'
import { WhatsAppIcon } from '../components/icons'
import { EntradaCard, useHasEntrada } from '../components/EntradaCard'
import { FreezeRequests } from '../components/FreezeRequests'
import { JoinRequests } from '../components/JoinRequests'
import { Grid, PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { EmailReminder } from '../components/EmailReminder'
import { ReminderLink } from '../components/ReminderLink'
import { dayTime, isoDay, monthName, shortDay, timeRange, toDate, weekdayDay } from '../format'
import { t } from '../i18n/es'
import { useGymName, usePageTitle } from '../pageTitle'
import './Today.css'
import { setupDoneKey, useSetupMemory, type SetupMemory } from './setupMemory'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'

const copy = t.admin.today
const clp = t.common.clp

// The overdue list shows this many until "Ver los N vencidos".
const OVERDUE_SHOWN = 3

// "Requisitos" shows this many until "Ver los N".
const REQUIREMENTS_SHOWN = 5

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
 * tap from its attendance, and the join link's requests a coach can act on (#178). In a
 * gym with open access (#348) it leads with "Entrada", the door, which stands in for the
 * class list on a day with no class; an owner's and an admin's has it too. The
 * join link's requests come first for an owner or admin (#154), then the freezes students
 * asked for from their page (#270).
 *
 * Each overdue row has its WhatsApp reminder beside "Pagó", saying which one it is
 * ("Aviso 2") and standing out when the gym's cadence says the next is due; "Por
 * avisar" has the periods due today and the rejected proofs to follow up, when there
 * are any (#55). In the same group, the mail button emails it now (#260). Only the
 * overdue fact is in the warning colour (#358).
 *
 * "Falta apoderado", when there is anyone: the minors with no guardian, to whom Rakin
 * sends nothing until the gym adds one (#368), each a tap from their ficha.
 *
 * "Requisitos", when there is anyone (#350): people with a live membership who lack one
 * of the gym's requirements or whose one expired, then those whose one expires within 30
 * days, each a tap from their ficha. A coach's Hoy has it too, with the requirements a
 * coach sees.
 *
 * A phone stacks it all; from 1024px the counters run across the top and the lists sit
 * in a grid of two.
 *
 * A gym on its first day has none of that: "Configura tu academia" leads the owner
 * through setting it up, until it has members and classes (#166). Until it has a first
 * student, Hoy is that checklist alone: no counters at zero, no "all good" cards (#358).
 */
export function Today() {
  const access = useQuery(myAccessQuery())
  const money = readsLedger(access.data)
  const gym = useGymName()
  usePageTitle(copy.title)

  return (
    <div className="today">
      <PageContainer className="today__page">
        <PageHeader eyebrow={gym} title={copy.heading(weekdayDay(new Date()))} />
        {access.isError && <Failed message={copy.roleError} retry={() => void access.refetch()} />}
        {access.data && !money && <CoachToday />}
        {money && <OwnerToday />}
      </PageContainer>
    </div>
  )
}

/** A coach's Hoy: Entrada if the gym has open access, today's classes, each a tap from its
 * attendance, then the join requests. On a day with no class, Entrada alone. */
function CoachToday() {
  const entrada = useHasEntrada()
  // The open-access day is Entrada's, not a class.
  const day = useQuery({
    ...todaySessionsQuery(),
    select: (today) => ({ ...today, sessions: today.sessions.filter((s) => isClass(s.class_type_kind)) }),
  })
  const noClass = day.data !== undefined && day.data.sessions.length === 0
  return (
    <>
      <EntradaCard />
      {!(entrada && noClass) && <CoachClasses day={day} />}
      <JoinRequests />
      <RequirementsDueCard />
    </>
  )
}

/** "Clases de hoy", each a tap from its attendance. */
function CoachClasses({ day }: { day: UseQueryResult<SessionDay> }) {
  const words = copy.classes
  return (
    <Card className="today__section" aria-labelledby="clases-hoy-title">
      <SectionHead
        id="clases-hoy-title"
        title={words.title}
        aside={day.data && day.data.sessions.length > 0 ? words.count(day.data.sessions.length) : null}
      />
      {day.isPending ? (
        <Loading className="today__note">{copy.loading}</Loading>
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
        <PlainList className="today__list">
          {day.data.sessions.map((session) => (
            <ClassRow key={session.id} session={session} timeZone={day.data.timezone} />
          ))}
        </PlainList>
      )}
    </Card>
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

/** A gym with no students yet: what it can act on, and how to set it up. */
function NoMembersYet({ setup }: { setup: SetupProps }) {
  return (
    <>
      <JoinRequests />
      <SetupChecklist {...setup} />
    </>
  )
}

/** The owner's and an admin's Hoy: the money, who stopped coming, the unmarked classes;
 * for a gym with no students yet, its setup instead. */
function OwnerToday() {
  const members = useQuery(setupMembersQuery)
  const me = useQuery(myselfQuery())
  const key = me.data ? setupDoneKey(me.data.person_id) : null
  const [memory, remember] = useSetupMemory(key)
  const setup: SetupProps = { memory, remember, canHide: key !== null }
  // Asked for alongside the count, not after it, so a gym with students waits no longer.
  const proofs = useQuery(proofQueueQuery())
  const overdue = useQuery(overdueQuery())
  const inactive = useQuery(inactiveQuery())
  const unmarked = useQuery(unmarkedSessionsQuery())
  const reminders = useQuery(remindersQuery())
  const reminderFor = new Map((reminders.data ?? []).map((r) => [r.billing_period_id, r]))
  // The overdue ones are on their "Vencidos" rows.
  const toRemind = (reminders.data ?? []).filter((r) => r.days_overdue <= 0)

  // Nothing before the count is in, so a new gym never sees zeros flash; a failed count
  // shows Hoy as usual.
  if (members.isPending || me.isPending) return null
  // Until a first student the checklist is all of Hoy, whatever this browser remembers as
  // done, unless the owner hid it.
  if (members.data === 0 && memory !== 'hidden') return <NoMembersYet setup={setup} />

  return (
    <>
      {memory !== 'hidden' && memory !== 'done' && <SetupChecklist {...setup} />}
      <div className="today__counters" aria-label={copy.countersLabel} role="group">
        <Counter
          href="#vencidos"
          value={overdue.data && byMember(overdue.data.periods).length}
          label={copy.overdue.title}
          tone="warning"
        />
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
        <EntradaCard />
        <JoinRequests />
        <FreezeRequests />
        <MissingGuardians />
        <RequirementsDueCard />
        <Card id="validar" className="today__section" aria-labelledby="validar-title">
          <SectionHead
            id="validar-title"
            title={copy.proofs.title}
            aside={proofs.data && proofs.data.length > 0 ? copy.proofs.count(proofs.data.length) : null}
          />
          {proofs.isPending ? (
            <Loading className="today__note">{copy.loading}</Loading>
          ) : proofs.isError ? (
            <Failed message={copy.proofs.error} retry={() => void proofs.refetch()} />
          ) : proofs.data.length === 0 ? (
            <p className="today__note">{copy.proofs.empty}</p>
          ) : (
            <PlainList className="today__list">
              {proofs.data.map((proof) => (
                <ProofRow key={proof.id} proof={proof} />
              ))}
            </PlainList>
          )}
        </Card>
        <Card id="vencidos" className="today__section" aria-labelledby="vencidos-title">
          <SectionHead
            id="vencidos-title"
            title={copy.overdue.title}
            aside={overdue.data && overdue.data.total_clp > 0 ? copy.overdue.total(clp(overdue.data.total_clp)) : null}
          />
          {overdue.isPending ? (
            <Loading className="today__note">{copy.loading}</Loading>
          ) : overdue.isError ? (
            <Failed message={copy.overdue.error} retry={() => void overdue.refetch()} />
          ) : overdue.data.periods.length === 0 ? (
            <p className="today__note">{copy.overdue.empty}</p>
          ) : (
            <OverdueList periods={overdue.data.periods} reminderFor={reminderFor} />
          )}
        </Card>
        {toRemind.length > 0 && (
          <Card id="por-avisar" className="today__section" aria-labelledby="por-avisar-title">
            <SectionHead id="por-avisar-title" title={copy.remind.title} aside={copy.remind.count(toRemind.length)} />
            <PlainList className="today__list">
              {toRemind.map((reminder) => (
                <RemindRow key={reminder.billing_period_id} reminder={reminder} />
              ))}
            </PlainList>
          </Card>
        )}
        <Card id="inactivos" className="today__section" aria-labelledby="inactivos-title">
          <SectionHead
            id="inactivos-title"
            title={copy.inactive.title}
            aside={inactive.data && inactive.data.length > 0 ? copy.inactive.count(inactive.data.length) : null}
          />
          {inactive.isPending ? (
            <Loading className="today__note">{copy.loading}</Loading>
          ) : inactive.isError ? (
            <Failed message={copy.inactive.error} retry={() => void inactive.refetch()} />
          ) : inactive.data.length === 0 ? (
            <p className="today__note">{copy.inactive.empty}</p>
          ) : (
            <InactiveList members={inactive.data} />
          )}
        </Card>
        <TrialsCard />
        <Card id="sin-asistencia" className="today__section" aria-labelledby="sin-asistencia-title">
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
            <Loading className="today__note">{copy.loading}</Loading>
          ) : unmarked.isError ? (
            <Failed message={copy.unmarked.error} retry={() => void unmarked.refetch()} />
          ) : unmarked.data.sessions.length === 0 ? (
            <p className="today__note">{copy.unmarked.empty}</p>
          ) : (
            <PlainList className="today__list">
              {unmarked.data.sessions.map((session) => (
                <UnmarkedRow key={session.id} session={session} timeZone={unmarked.data.timezone} />
              ))}
            </PlainList>
          )}
        </Card>
      </Grid>
    </>
  )
}

// The checklist's answers change only when someone sets something up, and each of those
// screens refreshes its own; Hoy need not ask again on every visit.
const SETUP_STALE_MS = 5 * 60_000

// How many students the gym has: whether Hoy is the checklist alone (#358), and one of
// the checklist's steps. A failed count is not asked again as the checklist mounts: Hoy
// hides while it is pending, which would unmount the checklist and ask again, forever.
// The checklist's "Reintentar" still does.
const setupMembersQuery = { ...memberCountQuery, staleTime: SETUP_STALE_MS, retryOnMount: false }

/** What the checklist knows of this browser's memory of it, and how to change it. */
type SetupProps = {
  memory: SetupMemory
  remember: (memory: 'done' | 'hidden') => void
  // Who is signed in is known, so "Ocultar" has somewhere to remember it.
  canHide: boolean
}

type StepId = 'activities' | 'gym' | 'classes' | 'staff' | 'schedule' | 'plans' | 'members'

/**
 * "Configura tu academia": a new gym's steps, in an order that works (#573), each ticked
 * once done, with what comes next, and a link to where it is done. The next step to do
 * says "Siguiente" and has its links as buttons; on a phone the done ones fold to a row.
 *
 * Shown until the gym has programs, plans and members, then never again in this
 * browser: a gym set up once is remembered, and its Hoy asks nothing for it. "Ocultar"
 * hides it sooner, and Ajustes › Cuenta's "Ver primeros pasos" brings it back.
 */
function SetupChecklist({ memory, remember, canHide }: SetupProps) {
  // First the answers that decide whether it shows at all; the others only once it will,
  // so a gym that is set up costs three small requests, once.
  const members = useQuery(setupMembersQuery)
  const classTypes = useQuery({ ...classTypesQuery, staleTime: SETUP_STALE_MS })
  const plans = useQuery({ ...plansQuery, staleTime: SETUP_STALE_MS })
  const hasMembers = (members.data ?? 0) > 0
  const activeTypes = classTypes.data?.filter((c) => c.active) ?? []
  const hasClasses = activeTypes.length > 0
  const hasPlans = plans.data?.some((p) => p.active) ?? false
  const setUp = hasMembers && hasClasses && hasPlans
  const answered = members.data !== undefined && classTypes.data !== undefined && plans.data !== undefined
  // Asked for again from Ajustes, it shows set up or not.
  const shows = answered && (!setUp || memory === 'asked')
  const gym = useQuery({ ...gymSettingsQuery(), staleTime: SETUP_STALE_MS, enabled: shows })
  const staff = useQuery({ ...staffQuery, staleTime: SETUP_STALE_MS, enabled: shows })
  const activities = useQuery({ ...activitiesQuery, staleTime: SETUP_STALE_MS, enabled: shows })
  const schedule = useQuery({ ...scheduleQuery, staleTime: SETUP_STALE_MS, enabled: shows })

  useEffect(() => {
    if (setUp && memory === null && canHide) remember('done')
  }, [setUp, memory, canHide, remember])

  // A failed answer says so, with a retry, rather than leaving a new gym with no checklist.
  const failed = [members, classTypes, plans, gym, staff, activities, schedule].filter((q) => q.isError)
  if (failed.length > 0) {
    return <Failed message={copy.setup.error} retry={() => failed.forEach((q) => void q.refetch())} />
  }
  // Nothing until every answer is in: drawing it on a partial answer would show a set-up
  // gym unticked steps for a moment.
  if (!shows || !gym.data || !staff.data || !activities.data || !schedule.data) return null

  const steps = copy.setup.steps
  // A class type is not a class: Clases stays empty until a weekly class exists. Open
  // access needs none, as Entrada makes the day's class at the first check-in (#348).
  const today = isoDay(new Date().toISOString())
  const weekly = schedule.data.some((s) => s.class_type_active && (s.valid_to === null || s.valid_to >= today))
  const openAccessOnly = hasClasses && activeTypes.every((c) => c.kind === 'open_access')
  const done: Record<StepId, boolean> = {
    // First what the gym teaches (#245), which decides whether anything speaks of belts.
    activities: activities.data.length > 0,
    gym: gym.data.bank_account !== null,
    classes: hasClasses,
    // The owner is on the staff from the start.
    staff: staff.data.length > 1,
    schedule: weekly || openAccessOnly,
    plans: hasPlans,
    members: hasMembers,
  }
  const order: StepId[] = ['activities', 'gym', 'classes', 'staff', 'schedule', 'plans', 'members']
  // The team is optional: it counts only once done, "4 de 6 listos" without it.
  const optional = (id: StepId) => id === 'staff'
  const counted = order.filter((id) => !optional(id) || done[id])
  const count = counted.filter((id) => done[id]).length
  // The next is the first required step to do; the optional one only once it is all that is left.
  const next = order.find((id) => !done[id] && !optional(id)) ?? order.find((id) => !done[id])
  const step = (id: StepId) => ({ id, done: done[id], next: next === id })
  const linkClass = (id: StepId) => (next === id ? buttonClass({ variant: 'primary' }) : 'tap-link today__link')

  const hide = () => {
    if (window.confirm(copy.setup.hideConfirm)) remember('hidden')
  }

  return (
    <Card aria-labelledby="setup-title" className="today__setup">
      <div className="today__section-head">
        <SectionTitle id="setup-title">
          {copy.setup.title}
        </SectionTitle>
        <span className="today__aside">{copy.setup.progress(count, counted.length)}</span>
      </div>
      <PlainList ordered className="today__steps">
        <SetupStep {...step('activities')} title={steps.activities.title} hint={steps.activities.hint} doneLine={steps.activities.doneLine}>
          <Link to="/admin/ajustes/gimnasio" hash="actividades" className={linkClass('activities')}>
            {steps.activities.link}
          </Link>
        </SetupStep>
        <SetupStep {...step('gym')} title={steps.gym.title} hint={steps.gym.hint} doneLine={steps.gym.doneLine}>
          <Link to="/admin/ajustes/gimnasio" className={linkClass('gym')}>
            {steps.gym.link}
          </Link>
        </SetupStep>
        <SetupStep {...step('classes')} title={steps.classes.title} hint={steps.classes.hint} doneLine={steps.classes.doneLine}>
          <Link to="/admin/ajustes/programas" className={linkClass('classes')}>
            {steps.classes.link}
          </Link>
        </SetupStep>
        <SetupStep
          {...step('staff')}
          title={steps.staff.title}
          optional
          hint={steps.staff.hint}
          doneLine={steps.staff.doneLine}
        >
          <Link to="/admin/ajustes/equipo" className={linkClass('staff')}>
            {steps.staff.link}
          </Link>
        </SetupStep>
        <SetupStep
          {...step('schedule')}
          title={steps.schedule.title}
          hint={steps.schedule.hint}
          doneLine={weekly ? steps.schedule.doneLine : steps.schedule.openAccess}
        >
          <Link to="/admin/ajustes/horario" className={linkClass('schedule')}>
            {steps.schedule.link}
          </Link>
        </SetupStep>
        <SetupStep {...step('plans')} title={steps.plans.title} hint={steps.plans.hint} doneLine={steps.plans.doneLine}>
          <Link to="/admin/ajustes/planes" className={linkClass('plans')}>
            {steps.plans.link}
          </Link>
        </SetupStep>
        <SetupStep {...step('members')} title={steps.members.title} hint={steps.members.hint} doneLine={steps.members.doneLine}>
          <Link to="/admin/alumnos/nuevo" className={linkClass('members')}>
            {steps.members.manual}
          </Link>
          <Link to="/admin/alumnos/importar" className={linkClass('members')}>
            {steps.members.import}
          </Link>
          <Link to="/admin/ajustes/inscripcion" className={linkClass('members')}>
            {steps.members.joinLink}
          </Link>
        </SetupStep>
      </PlainList>
      {canHide && (
        <div className="today__setup-actions">
          <Button variant="ghost" onClick={hide}>
            {copy.setup.hide}
          </Button>
        </div>
      )}
    </Card>
  )
}

function SetupStep({
  done,
  next,
  optional = false,
  title,
  hint,
  doneLine,
  children,
}: {
  id: StepId
  done: boolean
  next: boolean
  optional?: boolean
  title: string
  hint: string
  doneLine: string
  children: ReactNode
}) {
  return (
    <li className={cx('today__step', done && 'today__step--done', next && 'today__step--next')}>
      <span className="today__check" aria-hidden="true">
        {done ? '✓' : ''}
      </span>
      <span className="today__row-text">
        <span className="today__name">
          {title}
          {optional && <span className="today__step-optional"> {copy.setup.optional}</span>}
          <span className="visually-hidden">{copy.setup.state(done)}</span>
          {next && <span className="today__step-next">{copy.setup.next}</span>}
        </span>
        <span className="today__detail">{done ? doneLine : hint}</span>
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
    <a href={href} className={cardClass({}, 'today__counter')} aria-label={value === undefined ? label : `${value} ${label}`}>
      {/* Zero is nothing to worry about: never in the warning colour (#358). */}
      <span className={`today__counter-value today__counter-value--${value === 0 ? 'muted' : tone}`}>
        {value ?? '–'}
      </span>
      <span className="today__counter-label">{label}</span>
    </a>
  )
}

function SectionHead({ id, title, aside }: { id: string; title: string; aside: string | null }) {
  return (
    <div className="today__section-head">
      <SectionTitle id={id}>
        {title}
      </SectionTitle>
      {aside && <span className="today__aside">{aside}</span>}
    </div>
  )
}

function Failed({ message, retry }: { message: string; retry: () => void }) {
  return (
    <Banner tone="error" as="div">
      <p>{message}</p>
      <Button onClick={retry}>
        {copy.retry}
      </Button>
    </Banner>
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

/** "Falta apoderado" (#368): shown only when someone has none, as a request is. */
function MissingGuardians() {
  const minors = useQuery(missingGuardianQuery)
  const items = minors.data?.items ?? []
  if (items.length === 0) return null
  return (
    <Card id="falta-apoderado" className="today__section" aria-labelledby="falta-apoderado-title">
      <SectionHead
        id="falta-apoderado-title"
        title={copy.missingGuardian.title}
        aside={copy.missingGuardian.count(minors.data?.total ?? items.length)}
      />
      <p className="today__note">{copy.missingGuardian.hint}</p>
      <PlainList className="today__list">
        {items.map((member) => (
          <MissingGuardianRow key={member.id} member={member} />
        ))}
      </PlainList>
    </Card>
  )
}

function MissingGuardianRow({ member }: { member: MemberRow }) {
  return (
    <li>
      <Link
        to="/admin/alumnos/$personId"
        params={{ personId: member.id }}
        className="today__row today__row--link"
        aria-label={copy.missingGuardian.openLabel(member.name)}
      >
        <span className="today__row-text">
          <span className="today__name">{member.name}</span>
        </span>
        <span className={buttonClass()} aria-hidden="true">
          {copy.missingGuardian.open}
        </span>
      </Link>
    </li>
  )
}

/** "Pruebas" (#27): how many of the last days' trials went on to a plan, and how many are
 * still running. Shown once the gym has had one; a count that fails shows nothing, so it
 * never puts an error card on a gym that has had no trial. */
function TrialsCard() {
  const trials = useQuery(trialConversionsQuery)
  const words = copy.trials
  if (!trials.data || trials.data.started === 0) return null
  return (
    <Card id="pruebas" className="today__section" aria-labelledby="pruebas-title">
      <SectionHead id="pruebas-title" title={words.title} aside={words.aside(trials.data.days)} />
      <p className="today__note">
        {words.converted(trials.data.converted, trials.data.started)}
        {trials.data.running > 0 && ` · ${words.running(trials.data.running)}`}
      </p>
    </Card>
  )
}

/** "Requisitos" (#350): shown only when someone is short on one, as a request is. */
function RequirementsDueCard() {
  const due = useQuery(requirementsDueQuery)
  const [all, setAll] = useState(false)
  const people = due.data ?? []
  if (people.length === 0) return null
  const words = copy.requirements
  const shown = all ? people : people.slice(0, REQUIREMENTS_SHOWN)
  return (
    <Card id="requisitos" className="today__section" aria-labelledby="requisitos-title">
      <SectionHead id="requisitos-title" title={words.title} aside={words.count(people.length)} />
      <p className="today__note">{words.hint}</p>
      <PlainList className="today__list">
        {shown.map((person) => (
          <RequirementsDueRow key={person.person_id} person={person} />
        ))}
      </PlainList>
      {!all && people.length > REQUIREMENTS_SHOWN && (
        <Button variant="ghost" onClick={() => setAll(true)}>
          {words.showAll(people.length)}
        </Button>
      )}
    </Card>
  )
}

function RequirementsDueRow({ person }: { person: RequirementsDue }) {
  const words = copy.requirements
  return (
    <li>
      <Link
        to="/admin/alumnos/$personId"
        params={{ personId: person.person_id }}
        className="today__row today__row--link"
        aria-label={words.openLabel(person.name)}
      >
        <span className="today__row-text">
          <span className="today__name">{person.name}</span>
          <span className="today__detail">{person.requirements.map(words.flag).join(' · ')}</span>
        </span>
        <span className={buttonClass()} aria-hidden="true">
          {words.open}
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

/** The periods grouped by member (#271), in the order the API lists them, so each member
 * comes where their longest overdue period does: one row per member, however many of
 * their plans owe. */
export function byMember(periods: readonly OverduePeriod[]): OverduePeriod[][] {
  const members = new Map<string, OverduePeriod[]>()
  for (const period of periods) {
    const owed = members.get(period.person_id)
    if (owed) owed.push(period)
    else members.set(period.person_id, [period])
  }
  return [...members.values()]
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
  const members = byMember(periods)
  const shown = all ? members : members.slice(0, OVERDUE_SHOWN)
  return (
    <>
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      <PlainList className="today__list">
        {shown.map((owed) => (
          <OverdueRow key={owed[0]!.person_id} periods={owed} reminderFor={reminderFor} onDone={setDone} />
        ))}
      </PlainList>
      {!all && members.length > OVERDUE_SHOWN && (
        <Button variant="ghost" onClick={() => setAll(true)}>
          {copy.overdue.showAll(members.length)}
        </Button>
      )}
    </>
  )
}


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

/** A member's row: their one overdue period, or with several, the total and each period
 * under it, a lapsed plan's beside the active one's, each with its own "Pagó" (#271). */
function OverdueRow({
  periods,
  reminderFor,
  onDone,
}: {
  periods: OverduePeriod[]
  reminderFor: Map<string, PaymentReminder>
  onDone: (message: string) => void
}) {
  const [first] = periods
  if (periods.length === 1) {
    return (
      <li className="today__row today__row--overdue">
        <OverdueLine period={first!} reminder={reminderFor.get(first!.billing_period_id)} named onDone={onDone} />
      </li>
    )
  }
  const total = periods.reduce((sum, p) => sum + p.outstanding_clp, 0)
  return (
    <li className="today__row today__row--overdue">
      <Link
        to="/admin/alumnos/$personId"
        params={{ personId: first!.person_id }}
        className="today__row-text today__row-text--link"
      >
        <span className="today__name">{first!.person_name}</span>
        <span className="today__detail">
          <span className="today__warning">{copy.overdue.periods(periods.length)}</span>
          {copy.after([clp(total)])}
        </span>
      </Link>
      {periods.map((period) => (
        <OverdueLine
          key={period.billing_period_id}
          period={period}
          reminder={reminderFor.get(period.billing_period_id)}
          named={false}
          onDone={onDone}
        />
      ))}
    </li>
  )
}

/** One overdue period: what it owes, its reminders and "Pagó"; `named` leads with whose. */
function OverdueLine({
  period,
  reminder,
  named,
  onDone,
}: {
  period: OverduePeriod
  reminder: PaymentReminder | undefined
  named: boolean
  onDone: (message: string) => void
}) {
  const [open, setOpen] = useState(false)
  const amount = clp(period.outstanding_clp)
  const reminded = remindedDetail(reminder)
  // Under the member's name, each "Pagó" says which period it is.
  const label = copy.overdue.paidLabel(
    named ? period.person_name : copy.overdue.periodOf(period.person_name, period.plan_name, monthName(period.period_start)),
  )
  const rest = [amount, period.plan_name, copy.overdue.membership[period.membership_status]].filter(
    (part): part is string => Boolean(part),
  )
  return (
    <>
      <div className="today__row-line today__row-line--actions">
        <Link
          to="/admin/alumnos/$personId"
          params={{ personId: period.person_id }}
          className="today__row-text today__row-text--link"
        >
          {named && <span className="today__name">{period.person_name}</span>}
          {/* "Venció hace 9 días" in the warning colour; what and which plan, not. */}
          <span className="today__detail">
            <span className="today__warning">{copy.overdue.since(period.days_overdue)}</span>
            {copy.after(rest)}
          </span>
          {reminded && <span className="today__detail">{reminded}</span>}
        </Link>
        {!open && (
          <div className="today__actions">
            {reminder && <ReminderLink reminder={reminder} />}
            {reminder && <EmailReminder reminder={reminder} compact />}
            <Button aria-label={label} onClick={() => setOpen(true)}>
              {copy.overdue.paid}
            </Button>
          </div>
        )}
      </div>
      {open && (
        <PaidForm
          period={period}
          label={label}
          onCancel={() => setOpen(false)}
          onDone={() => {
            setOpen(false)
            onDone(copy.overdue.recorded(period.person_name, amount))
          }}
        />
      )}
    </>
  )
}

/** "Pagó": the period's outstanding amount, received by the method chosen. */
function PaidForm({
  period,
  label,
  onCancel,
  onDone,
}: {
  period: OverduePeriod
  label: string
  onCancel: () => void
  onDone: () => void
}) {
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
    <form className="today__form" aria-label={label} onSubmit={submit}>
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
        <Banner tone="error">
          {record.error instanceof ApiError && record.error.status === 409
            ? copy.overdue.refused.paid
            : copy.overdue.refused.failed}
        </Banner>
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
      <PlainList className="today__list">
        {members.slice(0, INACTIVE_SHOWN).map((member) => (
          <InactiveRow key={member.person_id} member={member} />
        ))}
      </PlainList>
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
  const absent =
    member.last_attended_on === null ? copy.inactive.never(member.days_absent) : copy.inactive.absent(member.days_absent)
  const nudged = member.nudged_at && copy.inactive.nudged(ago(member.nudged_at, new Date()))
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
          {/* Only what they owe in the warning colour (#358). */}
          <span className="today__detail">
            {absent}
            {copy.separator}
            {member.payment_status === 'overdue' ? <span className="today__warning">{payment}</span> : payment}
            {nudged && copy.after([nudged])}
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
