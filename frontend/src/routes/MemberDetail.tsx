import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactElement, type ReactNode } from 'react'
import { useGrades } from '../api/activities'
import { personAttendanceQuery } from '../api/attendance'
import { personTagHoursQuery, type Stretch } from '../api/classTags'
import { familyQuery } from '../api/family'
import { freezeRequestsQuery } from '../api/freezeRequests'
import { ApiError } from '../api/client'
import {
  goalProgress,
  gradesQuery,
  gradingSchemeQuery,
  rankLabel,
  type GradeEvent,
  type GradingScheme,
  type Rank,
} from '../api/grading'
import {
  aheadQuery,
  correctionsQuery,
  editFreeze,
  endFreeze,
  freezeMembership,
  membershipLedgerQuery,
  membershipsQuery,
  personQuery,
  reactivateMembership,
  reactivationQuery,
  reactivationRefused,
  recordAdjustment,
  recordPayment,
  recordPaymentAhead,
  recordRefund,
  recordRestore,
  recordVoid,
  shownMembership,
  restoreRefused,
  voidMembership,
  voidRefused,
  type BillFrom,
  type Correction,
  type Freeze,
  type FreezeLine,
  type LedgerPeriod,
  type Membership,
  type MembershipLedger,
  type Method,
  type OpenPeriod,
  type Person,
  type RecordedAdjustment,
  type RecordedAhead,
  type RecordedPayment,
  type RecordedRefund,
  type RefundablePayment,
  type TimelineEntry,
} from '../api/member'
import { myRoleQuery, readsLedger, type StaffRole } from '../api/me'
import { remindersQuery } from '../api/reminders'
import { useGymToday } from '../api/sessions'
import { RankBelt } from '../components/Belt'
import { Button, buttonClass } from '../components/Button'
import { Chip } from '../components/Chip'
import { BackLink } from '../components/BackLink'
import { Input, Select } from '../components/Field'
import { ChevronRightIcon, WhatsAppIcon } from '../components/icons'
import { Grid, PageContainer } from '../components/Layout'
import { MemberMatTime } from '../components/MatTime'
import { TagHoursCard } from '../components/TagHours'
import { EmailReminder } from '../components/EmailReminder'
import { FreezeRequestRow } from '../components/FreezeRequests'
import { ReminderLink } from '../components/ReminderLink'
import { StatusPill } from '../components/StatusPill'
import { addDays, isoDay, monthName, monthYear, shortDay } from '../format'
import { Banner, Card, cardClass, CheckRow, PlainList, SectionHeader } from '../components/Card'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { FamilyPanel } from './FamilyPanel'
import { PersonActions } from './PersonActions'
import { GradeForm } from './GradeForm'
import { PersonExtraLines } from './PersonExtraLines'
import { PersonHistory } from './PersonHistory'
import { PersonData } from './PersonData'
import { AssignForm, AssignPlan, assignsPlan, ChangePlanForm, changesPlan, isLive } from './PersonPlan'
import { PersonWelcome } from './PersonWelcome'
import './MemberDetail.css'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'
import { PageTitle } from '../components/PageHeader'

const copy = t.admin.member
const clp = t.common.clp

const route = getRouteApi('/admin/alumnos/$personId')

/**
 * "Ficha de alumno": who the member is and their rank, the plan they are on and how it
 * stands, their graduación and family, and, for whoever reads the ledger, what they
 * owe, their ledger with its freezes, "Registrar pago", "Congelar" (#26), "Devolver"
 * (#38), "Cambiar plan" and "Corregir plan"; each Libro line with something to fix opens
 * its fixes under it (#279); with no plan running, "Asignar plan", and
 * what an earlier plan still owes as "Deuda anterior" (#249). A freeze the member asked
 * for from their page waits on the plan card, with "Aprobar" and "Rechazar" (#270).
 * A coach sees the member, their plan and rank, whether it is frozen, and promotes
 * them; never money.
 *
 * Their attendance, in the last 30 days and in all, and in Graduación the classes since
 * their last promotion; their time on the mat by block kind (#141).
 *
 * Below them, "Datos": their record and the gym's custom fields the signed-in role may
 * see (#20), edited together; "Acceso", their sign-in link and how the welcome went
 * (#246); then "Dar de baja" or "Reactivar", and "Eliminar" (#157).
 * On a desktop, the money and its ledger on the left and the rest on the right (#179).
 *
 * In the header, WhatsApp: for whoever reads the ledger, the reminder about what they
 * owe, the longest overdue first, when there is one to send (#55); else a plain chat.
 * On the money card, "Enviar recordatorio" emails it now, and says when the last one
 * went out (#260).
 */
export function MemberDetail() {
  const { personId } = route.useParams()
  const person = useQuery(personQuery(personId))
  usePageTitle(person.data?.name)
  const memberships = useQuery(membershipsQuery(personId))
  // No rank by the name in a gym none of whose activities grades (#245).
  const graded = useGrades()
  const grades = useQuery({ ...gradesQuery(personId), enabled: graded })
  const role = useQuery(myRoleQuery())
  // "Asignar plan"'s confirmation, kept here as the form moves into the new plan's card.
  const [assigned, setAssigned] = useState<string | null>(null)

  if (person.isPending || memberships.isPending) {
    return (
      <Shell>
        <Loading className="member__note">{copy.loading}</Loading>
      </Shell>
    )
  }
  if (person.isError || memberships.isError) {
    const missing = person.error instanceof ApiError && person.error.status === 404
    return (
      <Shell>
        <div className="member__note" role="alert">
          <p>{missing ? copy.notFound : copy.error}</p>
          {!missing && (
            <Button
              onClick={() => {
                void person.refetch()
                void memberships.refetch()
              }}
            >
              {copy.retry}
            </Button>
          )}
        </div>
      </Shell>
    )
  }

  const membership = shownMembership(memberships.data)
  // A member since the day they first trained here (#293) or their first plan here,
  // whichever is earlier: the current plan comes first in the list, not the earliest.
  const firstStart = [person.data.member_since, ...memberships.data.map((m) => m.started_on)]
    .filter((day): day is string => day !== null)
    .sort()[0]
  const since = monthYear(firstStart ?? person.data.created_at)
  const rank = graded ? grades.data?.current : undefined
  const money = readsLedger(role.data)

  return (
    <Shell
      title={person.data.name}
      subtitle={rank ? copy.rankSince(rankLabel(rank), since) : copy.since(since)}
      action={<HeaderWhatsApp person={person.data} money={money} />}
    >
      {person.data.left_on && (
        <Banner tone="error" role="status">
          {copy.leftBanner(t.common.day(person.data.left_on))}
          {/* Only the owner and admins are ever sent it (#294). */}
          {person.data.left_reason && (
            <>
              <br />
              {copy.leftBannerReason(person.data.left_reason)}
            </>
          )}
        </Banner>
      )}
      {/* On a desktop the money on the left, everything else beside it. */}
      <Grid className="member__columns">
        <div className="member__column">
          {membership ? (
            <Standing
              personId={personId}
              membership={membership}
              money={money}
              earlier={money ? <EarlierDebt memberships={memberships.data} shown={membership} /> : null}
              assign={{ person: person.data, role: role.data, done: assigned, setDone: setAssigned }}
            />
          ) : (
            <>
              <p className="member__note">{copy.noPlan}</p>
              <AssignPlan person={person.data} membership={membership} role={role.data} done={assigned} setDone={setAssigned} />
            </>
          )}
          {money && <PersonExtraLines personId={personId} />}
          {money && <PersonHistory person={person.data} />}
        </div>
        <div className="member__column">
          <Attendance personId={personId} />
          <MemberMatTime personId={personId} />
          <MemberTagHours personId={personId} />
          <Graduation personId={personId} canAward={membership !== undefined && membership.status !== 'cancelled'} />
          <section className="member__section" aria-label={t.admin.family.toggle}>
            <SectionHeader title={t.admin.family.toggle} />
            <Card as="div" className="member__card member__family">
              <FamilyPanel person={person.data} />
            </Card>
          </section>
          <PersonData person={person.data} />
          <PersonWelcome person={person.data} role={role.data} />
          <PersonActions person={person.data} role={role.data} />
        </div>
      </Grid>
    </Shell>
  )
}

function Shell({
  title,
  subtitle,
  action,
  children,
}: {
  title?: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <PageContainer className="member">
      <header className="member__header">
        <BackLink to="/admin/alumnos" label={copy.back} />
        {title && (
          <div className="member__heading">
            <PageTitle tight>{title}</PageTitle>
            {subtitle && <span className="member__subtitle">{subtitle}</span>}
          </div>
        )}
        {action}
      </header>
      <div className="member__body">{children}</div>
    </PageContainer>
  )
}

/**
 * The header's WhatsApp: the reminder about what the member owes when there is one
 * (#55), which is counted and logged; else a chat with them. One button, never two.
 */
function HeaderWhatsApp({ person, money }: { person: Person; money: boolean }) {
  const reminders = useQuery({ ...remindersQuery(person.id), enabled: money })
  if (money && reminders.isPending) return null
  const first = reminders.data?.find((r) => r.whatsapp_url)
  return first ? <ReminderLink reminder={first} /> : <WhatsAppButton person={person} />
}

/**
 * WhatsApp to whoever the gym writes to about the member: them, or their guardian, as
 * the reminders go (`app/contacts.py`). Not drawn without a phone, or with "No tiene
 * WhatsApp".
 */
function WhatsAppButton({ person }: { person: Person }) {
  const family = useQuery(familyQuery(person.id))
  const guardianId = family.data?.guardian?.id
  const guardian = useQuery({ ...personQuery(guardianId ?? ''), enabled: guardianId !== undefined })
  if (family.isPending) return null
  const contact = guardianId ? guardian.data : person
  const href = contact && whatsappUrl(contact)
  if (!contact || !href) return null
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={buttonClass({ icon: true })}
      aria-label={guardianId ? copy.whatsappGuardian(contact.name) : copy.whatsapp(contact.name)}
    >
      <WhatsAppIcon />
    </a>
  )
}

/** The `wa.me` chat with `person`; null with no phone or "No tiene WhatsApp". */
export function whatsappUrl(person: Pick<Person, 'phone' | 'no_whatsapp'>): string | null {
  const digits = person.phone?.replace(/\D/g, '')
  return digits && !person.no_whatsapp ? `https://wa.me/${digits}` : null
}

/** "Asignar plan"'s part on the plan card: who to, by whom, and what it did. */
type Assigning = {
  person: Person
  role: StaffRole | null | undefined
  /** What "Asignar plan" did, kept by the ficha as the new plan takes this card's place. */
  done: string | null
  setDone: (message: string | null) => void
}

/** The plan and how it stands; with `money`, what is owed, the actions and the ledger.
 * `assign` is "Asignar plan", which offers itself once this plan has ended, and
 * `earlier` what other plans still owe, under the card (#249). */
function Standing({
  personId,
  membership,
  money,
  earlier,
  assign,
}: {
  personId: string
  membership: Membership
  money: boolean
  earlier: ReactNode
  assign: Assigning
}) {
  const ledger = useQuery({ ...membershipLedgerQuery(membership.id), enabled: money })
  const data = money ? ledger.data : undefined
  // The header's WhatsApp reads the same list. Longest overdue first: the email is about
  // the oldest period this plan owes (#260).
  const reminders = useQuery({ ...remindersQuery(personId), enabled: money })
  const overdue = money
    ? reminders.data?.find((r) => r.membership_id === membership.id && r.days_overdue >= 0)
    : undefined

  return (
    <>
      <Card className="member__card" aria-label={copy.paymentLabel}>
        <div className="member__card-head">
          <span className="member__eyebrow">{planLine(membership)}</span>
          <Badge membership={membership} ledger={data} />
        </div>
        {membership.freeze && !membership.freeze.started && (
          <p className="member__detail">
            {copy.freezeBooked(shortDay(membership.freeze.from_date), shortDay(membership.freeze.to_date))}
          </p>
        )}
        {money && <PlanFreezeRequest membershipId={membership.id} />}
        {membership.voided_at && membership.void_reason && (
          <p className="member__detail">{copy.voidedBanner(membership.void_reason, shortDay(isoDay(membership.voided_at)))}</p>
        )}
        {membership.next_plan && membership.status !== 'cancelled' && (
          <p className="member__detail">
            {copy.planChangeBooked(membership.next_plan.plan_name, shortDay(membership.next_plan.starts_on))}
          </p>
        )}
        {data && <Owed ledger={data} />}
        {data && overdue && <EmailReminder reminder={overdue} />}
        {money && ledger.isError && (
          <Banner tone="error">
            {copy.ledgerError}
          </Banner>
        )}
        {data ? (
          <Actions
            personId={personId}
            membership={membership}
            ledger={data}
            assign={assignsPlan(assign.person, membership, assign.role) ? assign : undefined}
          />
        ) : ledger.isError ? (
          // With no ledger to choose by, "Asignar plan" on its own.
          <AssignPlan membership={membership} {...assign} />
        ) : (
          // While the ledger loads, the actions' first row holds its place, so they do not pop in.
          money && <div className="member__actions-placeholder" aria-hidden="true" />
        )}
        {/* One place whether the new plan's ledger is in yet or not. */}
        {isLive(membership) && assign.done && (
          <Banner tone="done">
            {assign.done}
          </Banner>
        )}
      </Card>
      {earlier}
      {data && <Ledger membership={membership} ledger={data} />}
      {money && <Corrections personId={personId} />}
    </>
  )
}

/** The freeze the member asked for from their page (#270), waiting on this plan, with the
 * same "Aprobar" and "Rechazar" as on Hoy; then what was done. */
function PlanFreezeRequest({ membershipId }: { membershipId: string }) {
  const requests = useQuery(freezeRequestsQuery)
  const [done, setDone] = useState<string | null>(null)
  const request = requests.data?.find((r) => r.membership_id === membershipId)
  if (!request) {
    return (
      done && (
        <Banner tone="done">
          {done}
        </Banner>
      )
    )
  }
  return (
    <div className="member__freeze-request">
      <FreezeRequestRow request={request} onDone={setDone} />
    </div>
  )
}

/**
 * "Deuda anterior": what the member's other memberships still owe, a lapsed plan's
 * unpaid charges once "Asignar plan" started a new one (#249). The card shows one
 * membership; the debt stays in view here, as #206 keeps it on Hoy and in Pagos. Under
 * it, each of those plans' charges that owes or was voided, labelled with its plan
 * (#271), opens its fixes as a Libro line does (#279); "Otros planes" when only a void
 * is left to restore.
 */
function EarlierDebt({ memberships, shown }: { memberships: readonly Membership[]; shown: Membership }) {
  const [fixing, setFixing] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const others = useOtherLedgers(memberships, shown, true)
  const owing = others.filter(({ ledger }) => ledger.owed_clp > 0)
  const charges = others.flatMap(({ membership, ledger }) =>
    ledger.periods
      .filter((period) => period.outstanding_clp > 0 || period.void_id)
      .map((period) => ({ membership, period, balance: ledger.balance_clp }))
      .filter((charge) => chargeFixes(charge).length > 0),
  )
  if (owing.length === 0 && charges.length === 0 && !done) return null
  const title = owing.length > 0 ? copy.earlierDebt : copy.fix.otherPlans
  const finish = (message: string) => {
    setFixing(null)
    setDone(message)
  }
  return (
    <Card className="member__card" aria-label={title}>
      <span className="member__eyebrow">{title}</span>
      {owing.map(({ membership, ledger }) => {
        const due = ledger.open_periods.filter((p) => p.due)
        return (
          <div key={membership.id} className="member__owed">
            <span className="member__amount">{clp(ledger.owed_clp)}</span>
            <span className="member__detail">
              {copy.earlierDebtLine(
                membership.plan_name,
                due.length > 1 ? copy.pendingPeriods(due.length) : copy.pendingMonth(monthName(due[0]!.period_start)),
              )}
            </span>
          </div>
        )
      })}
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {charges.length > 0 && (
        <Card as="ul" flush className="member__ledger" aria-label={title}>
          {charges.map((charge) => {
            const { period } = charge
            const [first, ...rest] = chargeFixes(charge)
            const voided = period.void_id !== null
            return (
              <Line
                key={period.id}
                className={`member__entry member__entry--${voided ? 'muted member__entry--voided' : 'owed'}`}
                title={copy.ledger.charge(monthName(period.period_start))}
                detail={`${planOf(charge.membership)} · ${voided ? copy.fix.voided(clp(period.voided_clp)) : copy.ledger.unpaid}`}
                amount={clp(voided ? period.voided_clp : period.outstanding_clp)}
                fix={{
                  open: fixing === period.id,
                  toggle: () => {
                    setDone(null)
                    setFixing(fixing === period.id ? null : period.id)
                  },
                  panel: first && (
                    <ChargeFixes
                      charge={charge}
                      fixes={[first, ...rest]}
                      plans
                      onCancel={() => setFixing(null)}
                      onDone={finish}
                    />
                  ),
                }}
              />
            )
          })}
        </Card>
      )}
    </Card>
  )
}

type Held = { membership: Membership; ledger: MembershipLedger }

/** The ledgers of the member's memberships other than `shown`, those loaded so far. */
function useOtherLedgers(memberships: readonly Membership[], shown: Membership, enabled: boolean): Held[] {
  const others = memberships.filter((m) => m.id !== shown.id)
  const ledgers = useQueries({ queries: others.map((m) => ({ ...membershipLedgerQuery(m.id), enabled })) })
  return others.flatMap((m, i) => {
    const ledger = ledgers[i]?.data
    return ledger ? [{ membership: m, ledger }] : []
  })
}

/** A period of one of the member's plans, with that plan's balance: what a charge
 * line's fixes go to (#279). */
type Charge = { membership: Membership; period: LedgerPeriod; balance: number }

type ChargeFix = 'changeAmount' | 'voidCharge' | 'restoreCharge'

/** What can be done to `charge`, as a Libro line offers it (#279): a charge voided stands
 * restored, one owing is voided, and any is changed. Nothing on a plan voided by mistake,
 * which is assigned again. */
function chargeFixes({ membership, period }: Charge): ChargeFix[] {
  if (membership.voided_at) return []
  if (period.void_id) return ['restoreCharge']
  return period.outstanding_clp > 0 ? ['changeAmount', 'voidCharge'] : ['changeAmount']
}

/** "Mensual · Caducado": which plan another plan's charge is on, as #271 labels it. */
function planOf(membership: Membership): string {
  return `${membership.plan_name} · ${t.admin.students.status[membership.status]}`
}

function planLine(membership: Membership): string {
  if (membership.anchor_day !== null) return copy.dueDay(membership.plan_name, membership.anchor_day)
  if (membership.current_period_end) return copy.until(membership.plan_name, t.common.day(membership.current_period_end))
  return membership.plan_name
}

/** `Congelado · vuelve el 24 nov` while frozen; `Vencido 9 d` while the oldest open period
 * is past due; else the membership's status. A freeze booked ahead is a line of its own. */
function Badge({ membership, ledger }: { membership: Membership; ledger: MembershipLedger | undefined }) {
  if (membership.voided_at) return <StatusPill status="cancelled">{copy.voidedBadge}</StatusPill>
  if (membership.freeze?.started) {
    return <StatusPill status="frozen">{copy.frozenUntil(shortDay(membership.freeze.to_date))}</StatusPill>
  }
  const late = ledger?.open_periods[0]?.days_overdue ?? 0
  if (late > 0) return <StatusPill status="overdue">{copy.overdue(late)}</StatusPill>
  return <StatusPill status={membership.status}>{t.admin.students.status[membership.status]}</StatusPill>
}

function Owed({ ledger }: { ledger: MembershipLedger }) {
  const due = ledger.open_periods.filter((p) => p.due)
  const next = ledger.open_periods[0]
  let amount = 0
  let detail: string = copy.upToDate
  if (due[0]) {
    amount = ledger.owed_clp
    detail = due.length > 1 ? copy.pendingPeriods(due.length) : copy.pendingMonth(monthName(due[0].period_start))
  } else if (next) {
    amount = next.outstanding_clp
    detail = copy.upToDateNext(shortDay(next.due_date))
  } else if (ledger.paid_through) {
    detail = copy.paidThrough(shortDay(ledger.paid_through))
  }
  return (
    <div className="member__owed">
      <span className="member__amount">{clp(amount)}</span>
      <span className="member__detail">{detail}</span>
    </div>
  )
}

type Open =
  | 'payment'
  | 'refund'
  | 'freeze'
  | 'editFreeze'
  | 'endFreeze'
  | 'changePlan'
  | 'fixPlan'
  | 'voidPlan'
  | 'reactivate'
  | 'assign'
  | null

/** What the plan's periods still owe: what "Anular plan" voids. */
function unpaid(ledger: MembershipLedger): number {
  return ledger.periods.reduce((sum, p) => sum + p.outstanding_clp, 0)
}

/** What the plan card offers, in the order it reaches for its secondary and its menu. */
type Action = 'payment' | 'reactivate' | 'assign' | 'endFreeze' | 'editFreeze' | 'freeze' | 'changePlan' | 'refund' | 'fixPlan'

/**
 * The plan card's actions (#360): one primary, chosen by how the plan stands ("Registrar
 * pago" when something is owed, "Reactivar plan" when it lapsed, "Asignar plan" when
 * none runs), one secondary beside it, and the rest under "Más acciones". What cannot be
 * done here is not offered, rather than greyed out with no reason. A charge's fixes are
 * on its Libro line (#279); a refund is there and here.
 */
function Actions({
  personId,
  membership,
  ledger,
  assign,
}: {
  personId: string
  membership: Membership
  ledger: MembershipLedger
  /** "Asignar plan", when it is offered. */
  assign?: Assigning
}) {
  const periods = ledger.open_periods
  const payments = ledger.refundable_payments
  const freeze = membership.freeze
  const [open, setOpen] = useState<Open>(null)
  const [more, setMore] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  // A payment settled the last debt of this lapsed plan: "Reactivar plan" is offered (#284).
  const [offer, setOffer] = useState(false)
  // A lapsed pack or trial ends: it can only be refused, so it is not offered.
  const reactivates =
    membership.status === 'lapsed' &&
    !membership.voided_at &&
    (membership.plan_kind === 'monthly' || membership.plan_kind === 'prepaid')
  // "Corregir plan" stays open while one of its fixes is.
  const fixingPlan = open === 'fixPlan' || open === 'voidPlan'

  const offered: Action[] = [
    ...(reactivates ? (['reactivate'] as const) : []),
    ...(assign ? (['assign'] as const) : []),
    'payment',
    ...(freeze ? (['endFreeze', 'editFreeze'] as const) : membership.status === 'active' ? (['freeze'] as const) : []),
    ...(changesPlan(membership) ? (['changePlan'] as const) : []),
    ...(payments.length > 0 ? (['refund'] as const) : []),
    'fixPlan',
  ]
  const primary: Action = ledger.owed_clp > 0 ? 'payment' : (offered[0] ?? 'payment')
  const [secondary, ...rest] = offered.filter((action) => action !== primary)
  const label: Record<Action, string> = {
    payment: copy.record,
    reactivate: copy.reactivatePlan,
    assign: copy.assignPlan,
    endFreeze: freeze?.started ? copy.endFreeze : copy.callOffFreeze,
    editFreeze: copy.editFreeze,
    freeze: copy.freeze,
    changePlan: copy.changePlan,
    refund: copy.refund,
    fixPlan: copy.fix.plan,
  }
  const opens = (action: Action) => (action === 'fixPlan' ? fixingPlan : open === action)

  const toggle = (form: Open) => {
    setDone(null)
    setOffer(false)
    if (form === 'assign') assign?.setDone(null)
    setOpen(open === form ? null : form)
  }
  const choose = (action: Action) => toggle(action === 'fixPlan' && fixingPlan ? open : action)
  // Closing "Más acciones" closes the form opened from it, which would be left without its button.
  const fromMenu = rest.some(opens)
  const collapse = () => {
    if (more && fromMenu) setOpen(null)
    setMore(!more)
  }
  const finish = (message: string, settledLapsed = false) => {
    setOpen(null)
    setMore(false)
    setDone(message)
    setOffer(settledLapsed)
  }
  return (
    <>
      <div className="member__actions">
        <Button variant="primary" aria-expanded={opens(primary)} onClick={() => choose(primary)}>
          {label[primary]}
        </Button>
        {secondary && (
          <Button aria-expanded={opens(secondary)} onClick={() => choose(secondary)}>
            {label[secondary]}
          </Button>
        )}
      </div>
      {rest.length > 0 && (
        <Button variant="ghost" className="member__more-actions" aria-expanded={more} onClick={collapse}>
          {copy.moreActions}
        </Button>
      )}
      {more && rest.length > 0 && (
        <div className="member__actions member__actions--wrap" role="group" aria-label={copy.moreActions}>
          {rest.map((action) => (
            <Button key={action} aria-expanded={opens(action)} onClick={() => choose(action)}>
              {label[action]}
            </Button>
          ))}
        </div>
      )}
      {/* Fixing the plan as a whole (#279): voided with a reason (#256), or a cobro extra. */}
      {fixingPlan && (
        <div className="member__fix-choices" role="group" aria-label={copy.fix.plan}>
          {!membership.voided_at && (
            <Chip pressed={open === 'voidPlan'} onClick={() => setOpen(open === 'voidPlan' ? 'fixPlan' : 'voidPlan')}>
              {copy.voidPlan}
            </Chip>
          )}
          <Link to="/admin/pagos/cobros/nuevo" search={{ person: personId }} className="chip">
            {copy.fix.extraCharge}
          </Link>
        </div>
      )}
      {done && (
        <Banner tone="done" as="div">
          <p>{done}</p>
          {offer && reactivates && (
            <>
              <p>{copy.reactivateOffer}</p>
              <Button onClick={() => toggle('reactivate')}>
                {copy.reactivatePlan}
              </Button>
            </>
          )}
        </Banner>
      )}
      {open === 'payment' &&
        (periods.length > 0 ? (
          <PaymentForm membership={membership} periods={periods} onCancel={() => setOpen(null)} onDone={finish} />
        ) : (
          <PaymentAheadForm
            membership={membership}
            onCancel={() => setOpen(null)}
            onDone={finish}
            // Al día, and nothing to pay ahead (a pack, say): a payment needs a period to go to.
            // Dado de baja, none will open (#213).
            nothing={
              <p className="member__note" role="status">
                {membership.status === 'cancelled' ? copy.nothingToRecordLeft : copy.nothingToRecord}
              </p>
            }
          />
        ))}
      {open === 'refund' && payments.length > 0 && (
        <RefundForm payments={payments} ledger={ledger} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'freeze' && membership.status === 'active' && !freeze && (
        <FreezeForm membership={membership} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'editFreeze' && freeze && (
        <EditFreezeForm membershipId={membership.id} freeze={freeze} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'endFreeze' && freeze && (
        <EndFreezeForm membershipId={membership.id} freeze={freeze} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'changePlan' && changesPlan(membership) && (
        <ChangePlanForm membership={membership} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'voidPlan' && !membership.voided_at && (
        <VoidPlanForm
          membership={membership}
          balance={ledger.balance_clp}
          owed={unpaid(ledger)}
          onCancel={() => setOpen('fixPlan')}
          onDone={finish}
        />
      )}
      {open === 'reactivate' && reactivates && (
        <ReactivateForm membership={membership} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'assign' && assign && (
        <AssignForm
          person={assign.person}
          onCancel={() => setOpen(null)}
          onDone={(message) => {
            setOpen(null)
            setMore(false)
            assign.setDone(message)
          }}
        />
      )}
    </>
  )
}

/** A line's fixes, opened in place under it (#279): one chip per fix that applies to it,
 * then the chosen one's form, the first to begin with. */
function Fixes<F extends string>({
  title,
  fixes,
  label,
  children,
}: {
  title: string
  fixes: readonly [F, ...F[]]
  label: (fix: F) => string
  children: (fix: F) => ReactNode
}) {
  const [picked, setPicked] = useState<F>(fixes[0])
  const fix = fixes.includes(picked) ? picked : fixes[0]
  return (
    <div className="member__fix" role="group" aria-label={title}>
      <span className="member__fix-title">{title}</span>
      <div className="member__fix-choices">
        {fixes.map((f) => (
          <Chip key={f} pressed={f === fix} onClick={() => setPicked(f)}>
            {label(f)}
          </Chip>
        ))}
      </div>
      {children(fix)}
    </div>
  )
}

/** What a fix does as the admin types (#279): the period's debt and the plan's balance,
 * before → after. With no period, the balance alone. */
function FixPreview({ month, owed, balance }: { month?: string; owed?: [number, number]; balance: [number, number] }) {
  return (
    <div className="member__fix-preview">
      {month && owed && <span className="member__detail">{copy.fix.owed(month, clp(owed[0]), clp(owed[1]))}</span>}
      <span className="member__detail">{copy.fix.balance(clp(balance[0]), clp(balance[1]))}</span>
    </div>
  )
}

/** A charge line's fixes (#279): "Cambiar monto", "Anular cargo" or "Restaurar cargo",
 * whichever apply; `plans` names the plan, for another plan's charge (#271). */
function ChargeFixes({
  charge,
  fixes,
  plans,
  onCancel,
  onDone,
}: {
  charge: Charge
  fixes: readonly [ChargeFix, ...ChargeFix[]]
  plans: boolean
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const month = monthName(charge.period.period_start)
  return (
    <Fixes title={copy.fix.charge(month, plans ? planOf(charge.membership) : null)} fixes={fixes} label={(f) => copy.fix[f]}>
      {(fix) =>
        fix === 'changeAmount' ? (
          <ChangeAmountForm charge={charge} onCancel={onCancel} onDone={onDone} />
        ) : fix === 'voidCharge' ? (
          <VoidChargeForm charge={charge} onCancel={onCancel} onDone={onDone} />
        ) : (
          <RestoreChargeForm charge={charge} onCancel={onCancel} onDone={onDone} />
        )
      }
    </Fixes>
  )
}

/** What a refused void says, and how to clear it (#256). */
function voidRefusal(error: Error): string {
  const refused = voidRefused(error)
  if (!refused) return copy.voidRefused.failed
  if (refused.code === 'paid') return copy.voidRefused.paid(clp(refused.amount_clp ?? 0))
  return copy.voidRefused[refused.code]
}

/** What a refused restore says (#278). */
function restoreRefusal(error: Error): string {
  return copy.restoreRefused[restoreRefused(error) ?? 'failed']
}

/** "Restaurar cargo" (#278): a charge voided by mistake is owed again, as if never voided. */
function RestoreChargeForm({
  charge,
  onCancel,
  onDone,
}: {
  charge: Charge
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.restoreForm
  const id = useId()
  const { period, balance } = charge
  const month = monthName(period.period_start)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const restored = useSubmit({
    offline: 'refuse',
    mutationFn: () => recordRestore({ void_id: period.void_id!, reason: reason.trim() }),
    onSuccess: async () => {
      onDone(form.done(month, clp(period.voided_clp)))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk && period.void_id) restored.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview
        month={month}
        owed={[period.outstanding_clp, period.outstanding_clp + period.voided_clp]}
        balance={[balance, balance + period.voided_clp]}
      />
      {restored.error && (
        <Banner tone="error">
          {restoreRefusal(restored.error)}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={restored.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={restored.isPending} busy={restored.isPending}>
          {restored.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

/** "Anular cargo" (#256): a charge made by mistake, owed nowhere once voided. */
function VoidChargeForm({
  charge,
  onCancel,
  onDone,
}: {
  charge: Charge
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.voidForm
  const id = useId()
  const { membership, period, balance } = charge
  const month = monthName(period.period_start)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const voided = useSubmit({
    offline: 'refuse',
    mutationFn: () => recordVoid({ membership_id: membership.id, billing_period_id: period.id, reason: reason.trim() }),
    onSuccess: async () => {
      onDone(form.done(month, clp(period.outstanding_clp)))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk) voided.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview month={month} owed={[period.outstanding_clp, 0]} balance={[balance, balance - period.outstanding_clp]} />
      {voided.error && (
        <Banner tone="error">
          {voidRefusal(voided.error)}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={voided.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={voided.isPending} busy={voided.isPending}>
          {voided.isPending ? form.working : form.submit(clp(period.outstanding_clp))}
        </Button>
      </div>
    </form>
  )
}

/** "Anular plan" (#256): a plan assigned by mistake ends as of its start, its unpaid
 * charges voided with one reason, and it bills no more. Not "Dar de baja", which keeps
 * what a real plan owed. */
function VoidPlanForm({
  membership,
  balance,
  owed,
  onCancel,
  onDone,
}: {
  membership: Membership
  // The plan's balance, and what its periods still owe, which the void takes off.
  balance: number
  owed: number
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.voidPlanForm
  const id = useId()
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''

  const voided = useSubmit({
    offline: 'refuse',
    mutationFn: () => voidMembership(membership.id, reason.trim()),
    onSuccess: async () => {
      onDone(form.done)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
        queryClient.invalidateQueries({ queryKey: ['people'] }),
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk) voided.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview balance={[balance, balance - owed]} />
      {voided.error && (
        <Banner tone="error">
          {voidRefusal(voided.error)}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button disabled={voided.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={voided.isPending} busy={voided.isPending}>
          {voided.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

/** What a refused reactivation says, and what to do first (#284). */
function reactivateRefusal(error: Error): string {
  const words = copy.reactivateRefused
  const refused = reactivationRefused(error)
  if (!refused) return words.failed
  if (refused.code === 'unpaid') {
    const month = refused.period_start ? monthName(refused.period_start) : ''
    return words.unpaid(clp(refused.amount_clp ?? 0), month)
  }
  if (refused.code === 'live_plan') return words.live_plan(refused.plan_name ?? '')
  return words[refused.code]
}

const BILL_FROM: readonly BillFrom[] = ['last', 'today']

/** "Reactivar plan" (#284): a lapsed plan Active again, with a reason, billing from where
 * it left off (the months since the lapse, at once) or from today. A second step lists
 * what it bills before it saves. Refused, with what to do first, while a period past grace
 * is unpaid or beside another live plan. */
function ReactivateForm({
  membership,
  onCancel,
  onDone,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.reactivateForm
  const id = useId()
  const quote = useQuery(reactivationQuery(membership.id))
  const [billFrom, setBillFrom] = useState<BillFrom>('last')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const reasonOk = reason.trim() !== ''
  const bill = quote.data?.[billFrom]

  const reactivated = useSubmit({
    offline: 'refuse',
    mutationFn: () => reactivateMembership(membership.id, reason.trim(), billFrom),
    onSuccess: async () => {
      const total = bill?.total_clp ?? 0
      onDone(total > 0 ? form.done(clp(total)) : form.doneNothing)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
        queryClient.invalidateQueries({ queryKey: ['people'] }),
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!reasonOk || !bill) return
    if (confirming) reactivated.mutate()
    else setConfirming(true)
  }

  if (!quote.data) {
    return (
      <Card as="div" className="member__form" role="group" aria-label={form.title}>
        {quote.isError ? (
          <Banner tone="error">
            {reactivateRefusal(quote.error)}
          </Banner>
        ) : (
          <Loading className="member__detail" role="status">
            {form.loading}
          </Loading>
        )}
        <div className="member__form-actions">
          <Button onClick={onCancel}>{form.cancel}</Button>
        </div>
      </Card>
    )
  }

  const { last, today } = quote.data
  // Billed past yesterday already, there is no gap to skip: one way to bill, no choice.
  const choice = today.bills_from !== last.bills_from
  const hints: Record<BillFrom, string> = {
    last: form.lastHint(last.periods.length, monthName(last.bills_from), clp(last.total_clp)),
    today: form.todayHint(shortDay(today.bills_from), clp(today.total_clp)),
  }

  if (confirming && bill) {
    return (
      <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
        <p className="member__label">{form.confirmTitle}</p>
        {bill.periods.length > 0 ? (
          <PlainList className="member__bill">
            {bill.periods.map((p) => (
              <li key={p.period_start}>{form.period(monthName(p.period_start), clp(p.amount_due_clp))}</li>
            ))}
            <li className="member__bill-total">{form.total(clp(bill.total_clp))}</li>
          </PlainList>
        ) : (
          <p className="member__detail">{form.nothing}</p>
        )}
        {reactivated.error && (
          <Banner tone="error">
            {reactivateRefusal(reactivated.error)}
          </Banner>
        )}
        <div className="member__form-actions">
          <Button disabled={reactivated.isPending} onClick={() => setConfirming(false)}>
            {form.back}
          </Button>
          <Button type="submit" variant="primary" disabled={reactivated.isPending} busy={reactivated.isPending}>
            {reactivated.isPending ? form.working : form.submit}
          </Button>
        </div>
      </form>
    )
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      {!choice && <p className="member__detail">{hints.last}</p>}
      {choice && (
        <fieldset className="member__choices">
          <legend className="member__label">{form.billFrom}</legend>
          {BILL_FROM.map((value) => (
            <CheckRow start key={value} className="member__choice">
              <input type="radio" name={`${id}-bill-from`} checked={billFrom === value} onChange={() => setBillFrom(value)} />
              <span>
                <span className="member__choice-title">{form[value]}</span>
                <span className="member__detail">{hints[value]}</span>
              </span>
            </CheckRow>
          ))}
        </fieldset>
      )}
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      <div className="member__form-actions">
        <Button onClick={onCancel}>{form.cancel}</Button>
        <Button type="submit" variant="primary">
          {form.next}
        </Button>
      </div>
    </form>
  )
}

/** A change to a freeze: the membership and its ledger are read again after it. */
function useFreezeChange(mutationFn: () => Promise<Membership>, onSuccess: (membership: Membership) => void) {
  const queryClient = useQueryClient()
  return useSubmit({
    offline: 'refuse',
    mutationFn,
    onSuccess: async (membership: Membership) => {
      onSuccess(membership)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
      ])
    },
  })
}

function FreezeForm({
  membership,
  onCancel,
  onDone,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.freezeForm
  const ids = { from: useId(), until: useId(), hint: useId(), reason: useId(), reasonHint: useId() }
  // Today, the first day a freeze can start on, in the gym's timezone.
  const first = useGymToday()
  // Today until a day is picked: the gym's timezone may arrive after the form opens.
  const [picked, setFrom] = useState<string | null>(null)
  const from = picked ?? first
  const [until, setUntil] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const fromOk = from >= first
  const untilOk = until > from
  const reasonOk = reason.trim() !== ''

  const freeze = useFreezeChange(
    () =>
      freezeMembership(membership.id, {
        // From today, it is left to the server, which knows the gym's today.
        ...(from > first ? { from_date: from } : {}),
        to_date: until,
        reason: reason.trim(),
      }),
    (frozen) => {
      const to = shortDay(frozen.freeze?.to_date ?? until)
      onDone(frozen.freeze?.started === false ? form.booked(shortDay(frozen.freeze.from_date), to) : form.done(to))
    },
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (fromOk && untilOk && reasonOk) freeze.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.from} className="member__label">
        {form.from}
      </label>
      <Input
        id={ids.from}
        type="date"
        min={first}
        value={from}
        aria-invalid={checked && !fromOk}
        onChange={(e) => setFrom(e.target.value)}
      />
      {checked && !fromOk && (
        <Banner tone="error">
          {form.fromNeeded}
        </Banner>
      )}

      <label htmlFor={ids.until} className="member__label">
        {form.until}
      </label>
      <Input
        id={ids.until}
        type="date"
        min={addDays(fromOk ? from : first, 1)}
        value={until}
        aria-describedby={ids.hint}
        aria-invalid={checked && !untilOk}
        onChange={(e) => setUntil(e.target.value)}
      />
      <p id={ids.hint} className="member__detail">
        {form.untilHint}
      </p>
      {checked && !untilOk && (
        <Banner tone="error">
          {form.untilNeeded}
        </Banner>
      )}

      <label htmlFor={ids.reason} className="member__label">
        {form.reason}
      </label>
      <Input
        id={ids.reason}
        type="text"
        maxLength={500}
        value={reason}
        aria-describedby={ids.reasonHint}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <p id={ids.reasonHint} className="member__detail">
        {form.reasonHint}
      </p>
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}

      {freeze.error && (
        <Banner tone="error">
          {freeze.error instanceof ApiError && freeze.error.status === 409 ? form.refused.notActive : form.refused.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={freeze.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={freeze.isPending} busy={freeze.isPending}>
          {freeze.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

function EditFreezeForm({
  membershipId,
  freeze,
  onCancel,
  onDone,
}: {
  membershipId: string
  freeze: Freeze
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.editFreezeForm
  const ids = { until: useId(), hint: useId(), reason: useId(), reasonHint: useId() }
  // A running freeze ends after today (ending it today is "Terminar"), a booked one after its first day.
  const today = useGymToday()
  const first = addDays(freeze.started ? today : freeze.from_date, 1)
  const [until, setUntil] = useState(freeze.to_date)
  const [reason, setReason] = useState(freeze.reason)
  const [checked, setChecked] = useState(false)
  const moved = until !== freeze.to_date
  const untilOk = !moved || until >= first
  const reasonOk = reason.trim() !== ''

  const edit = useFreezeChange(
    () => editFreeze(membershipId, { ...(moved ? { to_date: until } : {}), reason: reason.trim() }),
    (edited) => onDone(form.done(shortDay(edited.freeze?.to_date ?? until))),
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (untilOk && reasonOk) edit.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.until} className="member__label">
        {form.until}
      </label>
      <Input
        id={ids.until}
        type="date"
        min={first}
        value={until}
        aria-describedby={ids.hint}
        aria-invalid={checked && !untilOk}
        onChange={(e) => setUntil(e.target.value)}
      />
      <p id={ids.hint} className="member__detail">
        {form.untilHint}
      </p>
      {checked && !untilOk && (
        <Banner tone="error">
          {form.untilNeeded}
        </Banner>
      )}

      <label htmlFor={ids.reason} className="member__label">
        {form.reason}
      </label>
      <Input
        id={ids.reason}
        type="text"
        maxLength={500}
        value={reason}
        aria-describedby={ids.reasonHint}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <p id={ids.reasonHint} className="member__detail">
        {form.reasonHint}
      </p>
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}

      {edit.error && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={edit.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={edit.isPending} busy={edit.isPending}>
          {edit.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

/** Ends a running freeze today, or calls off a booked one, once confirmed. */
function EndFreezeForm({
  membershipId,
  freeze,
  onCancel,
  onDone,
}: {
  membershipId: string
  freeze: Freeze
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const form = copy.endFreezeForm
  const end = useFreezeChange(
    () => endFreeze(membershipId),
    () => onDone(freeze.started ? form.ended : form.calledOff),
  )

  const submit = (event: FormEvent) => {
    event.preventDefault()
    end.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">
        {freeze.started ? form.endHint : form.callOffHint(shortDay(freeze.from_date), shortDay(freeze.to_date))}
      </p>

      {end.error && (
        <Banner tone="error">
          {form.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={end.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={end.isPending} busy={end.isPending}>
          {end.isPending ? form.working : freeze.started ? form.end : form.callOff}
        </Button>
      </div>
    </form>
  )
}

const METHODS: readonly Method[] = ['cash', 'transfer', 'other']

/** "Registrar pago" for one of the membership's open periods; the book's header opens
 *  it too, once a member is picked (#107). */
export function PaymentForm({
  membership,
  periods,
  onCancel,
  onDone,
}: {
  membership: Membership
  periods: OpenPeriod[]
  onCancel: () => void
  // `settledLapsed`: the payment settled the last period a lapsed plan owed (#284).
  onDone: (message: string, settledLapsed?: boolean) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.form
  const ids = { period: useId(), amount: useId(), method: useId(), note: useId() }
  const [periodId, setPeriodId] = useState(periods[0]!.id)
  const period = periods.find((p) => p.id === periodId) ?? periods[0]!
  const [amount, setAmount] = useState(String(period.outstanding_clp))
  const [method, setMethod] = useState<Method>('cash')
  const [note, setNote] = useState('')
  const [amountNeeded, setAmountNeeded] = useState(false)
  const value = Number(amount.replace(/\D/g, ''))

  const record = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordPayment({
        membership_id: membership.id,
        billing_period_id: period.id,
        amount_clp: value,
        method,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: async (result: RecordedPayment) => {
      const credit = result.credit ? form.credit(clp(result.credit.amount_clp)) : ''
      const rest = result.period.closed ? '' : form.remainder(clp(result.period.outstanding_clp))
      const last = result.period.closed && periods.every((p) => p.id === period.id)
      onDone(form.recorded(clp(value)) + credit + rest, membership.status === 'lapsed' && last)
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!value) {
      setAmountNeeded(true)
      return
    }
    record.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.period} className="member__label">
        {form.period}
      </label>
      <Select
        id={ids.period}
        value={period.id}
        onChange={(e) => {
          setPeriodId(e.target.value)
          const chosen = periods.find((p) => p.id === e.target.value)
          if (chosen) setAmount(String(chosen.outstanding_clp))
        }}
      >
        {periods.map((p) => (
          <option key={p.id} value={p.id}>
            {form.periodOption(monthName(p.period_start), clp(p.outstanding_clp))}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <Input
        id={ids.amount}
        inputMode="numeric"
        value={amount}
        aria-invalid={amountNeeded && !value}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountNeeded && !value && (
        <Banner tone="error">
          {form.amountNeeded}
        </Banner>
      )}

      <label htmlFor={ids.method} className="member__label">
        {form.method}
      </label>
      <Select id={ids.method} value={method} onChange={(e) => setMethod(e.target.value as Method)}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {form.methods[m]}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.note} className="member__label">
        {form.note}
      </label>
      <Input
        id={ids.note}
        type="text"
        maxLength={500}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      {record.error && (
        <Banner tone="error">
          {record.error instanceof ApiError && record.error.status === 409 ? form.refused.paid : form.refused.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={record.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={record.isPending} busy={record.isPending}>
          {record.isPending ? form.working : form.submit(clp(value))}
        </Button>
      </div>
    </form>
  )
}

/** "Registrar pago" for a member al día, with no period open (#196): the next 1 to 12
 *  periods, billed and paid at once, for what the quote says they cost. `nothing` when
 *  the membership cannot pay ahead. The book's header opens it too. */
export function PaymentAheadForm({
  membership,
  onCancel,
  onDone,
  nothing,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
  nothing: ReactNode
}) {
  const queryClient = useQueryClient()
  const form = copy.form
  const words = form.ahead
  const ids = { periods: useId(), method: useId(), note: useId() }
  const quote = useQuery(aheadQuery(membership.id))
  const [count, setCount] = useState(1)
  const [method, setMethod] = useState<Method>('cash')
  const [note, setNote] = useState('')
  const periods = quote.data?.periods ?? []
  const chosen = periods.slice(0, count)
  const total = chosen.reduce((sum, p) => sum + p.amount_due_clp, 0)

  const record = useSubmit({
    mutationFn: () =>
      recordPaymentAhead({
        membership_id: membership.id,
        periods: count,
        amount_clp: total,
        method,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: async (result: RecordedAhead) => {
      onDone(words.recorded(clp(total), shortDay(result.paid_through)))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
    // A new price: read the quote again, so the total shown is the one to record. The
    // other refusals stay on screen rather than swapping the form out under them.
    onError: async (error: Error) => {
      if (refusalCode(error) === 'amount_changed') {
        await queryClient.invalidateQueries({ queryKey: aheadQuery(membership.id).queryKey })
      }
    },
  })

  if (quote.isPending) {
    return (
      <Loading className="member__note" role="status">
        {words.loading}
      </Loading>
    )
  }
  if (quote.isError) {
    return (
      <Banner tone="error">
        {words.error}
      </Banner>
    )
  }
  if (periods.length === 0) return <>{nothing}</>

  const submit = (event: FormEvent) => {
    event.preventDefault()
    record.mutate()
  }
  const monthly = membership.plan_kind === 'monthly'

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__note">{words.intro}</p>
      <label htmlFor={ids.periods} className="member__label">
        {words.periods}
      </label>
      <Select id={ids.periods} value={String(count)} onChange={(e) => setCount(Number(e.target.value))}>
        {periods.map((p, i) => (
          <option key={p.period_start} value={String(i + 1)}>
            {words.option(
              i + 1,
              monthly,
              shortDay(p.period_end),
              clp(periods.slice(0, i + 1).reduce((sum, q) => sum + q.amount_due_clp, 0)),
            )}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.method} className="member__label">
        {form.method}
      </label>
      <Select id={ids.method} value={method} onChange={(e) => setMethod(e.target.value as Method)}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {form.methods[m]}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.note} className="member__label">
        {form.note}
      </label>
      <Input id={ids.note} type="text" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />

      {record.error && (
        <Banner tone="error">
          {aheadRefusal(record.error) ?? form.refused.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={record.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={record.isPending} busy={record.isPending}>
          {record.isPending ? form.working : form.submit(clp(total))}
        </Button>
      </div>
    </form>
  )
}

/** What a 409 from paying ahead says, by its `code`; `null` for any other error. */
function aheadRefusal(error: unknown): string | null {
  const refused = copy.form.ahead.refused
  const code = refusalCode(error)
  return code !== null && code in refused ? refused[code as keyof typeof refused] : null
}

function refusalCode(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return typeof code === 'string' ? code : null
}

/** "Asistencia": classes in the last 30 days, and in all. */
function Attendance({ personId }: { personId: string }) {
  const words = copy.attendance
  const attendance = useQuery(personAttendanceQuery(personId))
  if (attendance.isPending) return null
  if (attendance.isError) {
    return (
      <Banner tone="error">
        {words.error}
      </Banner>
    )
  }
  const { last_30_days: recent, total, before_rakin: before } = attendance.data
  return (
    <section className="member__section" aria-label={words.title}>
      <SectionHeader title={words.title} />
      <Card as="div" className="member__card">
        <div className="member__rank">
          <span className="member__rank-label">{recent}</span>
          <span className="member__detail">{words.detail(recent, total, before)}</span>
        </div>
      </Card>
    </section>
  )
}

/**
 * The member's rank, "Registrar graduación" and the promotion log. Hidden in a gym none
 * of whose activities grades (#245), and in one with no ranks unless the member has
 * promotions from when it had them.
 */
function Graduation({ personId, canAward }: { personId: string; canAward: boolean }) {
  return useGrades() ? <GraduationSection personId={personId} canAward={canAward} /> : null
}

function GraduationSection({ personId, canAward }: { personId: string; canAward: boolean }) {
  const words = copy.grading
  const grades = useQuery(gradesQuery(personId))
  const scheme = useQuery(gradingSchemeQuery())
  const attendance = useQuery(personAttendanceQuery(personId))
  const sincePromotion = attendance.data?.since_promotion ?? null
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  if (grades.isPending || scheme.isPending) return null
  const ranked = scheme.data ? scheme.data.ranks.length + scheme.data.kids_ladder.length > 0 : false
  if (grades.isError) {
    return (
      <Banner tone="error">
        {words.error}
      </Banner>
    )
  }
  const { current, events } = grades.data
  if (!ranked && events.length === 0) return null

  return (
    <section className="member__section" aria-label={words.title}>
      <SectionHeader title={words.title} />
      <Card as="div" className="member__card">
        {current ? (
          <div className="member__rank">
            <RankBelt rank={current} />
            <span className="member__rank-label">{rankLabel(current)}</span>
            <span className="member__detail">{words.since(t.common.dayYear(current.awarded_on))}</span>
            {sincePromotion !== null && <span className="member__detail">{words.sincePromotion(sincePromotion)}</span>}
            {scheme.data && <GoalTile scheme={scheme.data} current={current} sincePromotion={sincePromotion} />}
          </div>
        ) : (
          <p className="member__note">{words.none}</p>
        )}
        {ranked && canAward && scheme.data && (
          <>
            <div className="member__actions">
              <Button
                aria-expanded={open}
                onClick={() => {
                  setDone(null)
                  setOpen(!open)
                }}
              >
                {words.award}
              </Button>
            </div>
            {done && (
              <Banner tone="done">
                {done}
              </Banner>
            )}
            {open && (
              <GradeForm
                personId={personId}
                scheme={scheme.data}
                current={current}
                onCancel={() => setOpen(false)}
                onDone={(grading) => {
                  setOpen(false)
                  if (grading.current) setDone(words.form.done(rankLabel(grading.current)))
                }}
              />
            )}
          </>
        )}
      </Card>
      {events.length > 0 && (
        <Card as="ul" flush className="member__ledger" aria-label={words.log}>
          {events.map((event) => (
            <GradeRow key={event.id} event={event} />
          ))}
        </Card>
      )}
    </section>
  )
}

/** "62 / 80 clases para 3 grados", with a bar; nothing when the rank has no target. */
function GoalTile({
  scheme,
  current,
  sincePromotion,
}: {
  scheme: GradingScheme
  current: Rank
  sincePromotion: number | null
}) {
  const progress = goalProgress(scheme, current, sincePromotion, useGymToday())
  if (!progress) return null
  const { metric, done, target, next } = progress
  const text = copy.grading.goal(done, target, metric, next)
  return (
    <div className="member__goal">
      <span className="member__goal-text">{text}</span>
      <div
        className="member__goal-bar"
        role="progressbar"
        aria-label={copy.grading.goalLabel}
        aria-valuemin={0}
        aria-valuemax={target}
        aria-valuenow={Math.min(done, target)}
        aria-valuetext={text}
      >
        <div className="member__goal-fill" style={{ width: `${Math.min(100, (done / target) * 100)}%` }} />
      </div>
    </div>
  )
}

function GradeRow({ event }: { event: GradeEvent }) {
  const detail = [t.common.dayYear(event.awarded_on), event.awarded_by_name && copy.grading.by(event.awarded_by_name), event.note]
    .filter(Boolean)
    .join(' · ')
  return (
    <li className="member__entry member__entry--grade">
      <RankBelt rank={event} compact fallback={<span className="member__dot" aria-hidden="true" />} />
      <div className="member__entry-text">
        <span className="member__entry-title">{rankLabel(event)}</span>
        <span className="member__detail">{detail}</span>
      </div>
    </li>
  )
}

/** "Cambiar monto" (#279): what the charge comes to now, the difference written as an
 * adjustment with its reason, in the member's favour when lower. No lower than what has
 * come in already: that is given back first. */
function ChangeAmountForm({
  charge,
  onCancel,
  onDone,
}: {
  charge: Charge
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.amountForm
  const ids = { amount: useId(), reason: useId() }
  const { membership, period, balance } = charge
  const month = monthName(period.period_start)
  const current = period.charged_clp
  const [amount, setAmount] = useState(String(current))
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const digits = amount.replace(/\D/g, '')
  const value = Number(digits)
  // Owed on top when higher, taken off when lower.
  const change = value - current
  const owedAfter = period.outstanding_clp + change
  // What came in against it. Exact while it owes; a period overpaid past its charge has
  // `outstanding_clp` clamped at 0, so this reads only up to `current` there.
  const paid = current - period.outstanding_clp
  const amountOk = digits !== '' && change !== 0 && owedAfter >= 0
  const reasonOk = reason.trim() !== ''

  const adjust = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordAdjustment({
        membership_id: membership.id,
        billing_period_id: period.id,
        // Signed as an adjustment is: positive in the member's favour.
        amount_clp: -change,
        note: reason.trim(),
      }),
    onSuccess: async (result: RecordedAdjustment) => {
      const rest = result.period.closed ? '' : copy.form.remainder(clp(result.period.outstanding_clp))
      onDone(form.done(month, clp(current), clp(value)) + rest)
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (amountOk && reasonOk) adjust.mutate()
  }

  const amountError =
    digits === '' ? (checked ? form.amountNeeded : null) : owedAfter < 0 ? form.paidMore(clp(paid)) : change === 0 && checked ? form.sameAmount : null

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.current(clp(current))}</p>
      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <Input
        id={ids.amount}
        inputMode="numeric"
        value={amount}
        aria-invalid={amountError !== null}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountError && (
        <Banner tone="error">
          {amountError}
        </Banner>
      )}

      <label htmlFor={ids.reason} className="member__label">
        {form.reason}
      </label>
      <Input
        id={ids.reason}
        type="text"
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error">
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview
        month={month}
        owed={[period.outstanding_clp, Math.max(owedAfter, 0)]}
        balance={[balance, owedAfter < 0 ? balance : balance + change]}
      />

      {adjust.error && (
        <Banner tone="error">
          {adjust.error instanceof ApiError && adjust.error.status === 409 ? form.refused.exceeds : form.refused.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={adjust.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={adjust.isPending} busy={adjust.isPending}>
          {adjust.isPending ? form.working : form.submit(clp(value))}
        </Button>
      </div>
    </form>
  )
}

/** "Devolver", from the plan card, or "Reembolsar" from a payment's Libro line (#279). */
function RefundForm({
  payments,
  ledger,
  onCancel,
  onDone,
}: {
  payments: RefundablePayment[]
  // The plan's: its periods, for what each payment's owes, and its balance.
  ledger: MembershipLedger
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.refundForm
  const ids = { payment: useId(), amount: useId(), method: useId(), note: useId() }
  const [paymentId, setPaymentId] = useState(payments[0]!.id)
  const payment = payments.find((p) => p.id === paymentId) ?? payments[0]!
  const [amount, setAmount] = useState(String(payment.refundable_clp))
  const [method, setMethod] = useState<Method>(payment.method ?? 'transfer')
  const [note, setNote] = useState('')
  const [amountNeeded, setAmountNeeded] = useState(false)
  const value = Number(amount.replace(/\D/g, ''))
  // A refund opens its payment's period again for what it gives back: no more than the
  // payment has left, which is all the server takes.
  const owed = ledger.periods.find((p) => p.id === payment.billing_period_id)?.outstanding_clp ?? 0
  const back = Math.min(value, payment.refundable_clp)

  const refund = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordRefund({
        payment_id: payment.id,
        amount_clp: value,
        method,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: async (result: RecordedRefund) => {
      const rest = result.period.closed ? '' : copy.form.remainder(clp(result.period.outstanding_clp))
      onDone(form.done(clp(value)) + rest)
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!value) {
      setAmountNeeded(true)
      return
    }
    refund.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.payment} className="member__label">
        {form.payment}
      </label>
      <Select
        id={ids.payment}
        value={payment.id}
        onChange={(e) => {
          setPaymentId(e.target.value)
          const chosen = payments.find((p) => p.id === e.target.value)
          if (chosen) setAmount(String(chosen.refundable_clp))
        }}
      >
        {payments.map((p) => (
          <option key={p.id} value={p.id}>
            {form.paymentOption(
              monthName(p.period_start),
              p.validated_at ? shortDay(p.validated_at) : '',
              clp(p.refundable_clp),
            )}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <Input
        id={ids.amount}
        inputMode="numeric"
        value={amount}
        aria-invalid={amountNeeded && !value}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountNeeded && !value && (
        <Banner tone="error">
          {form.amountNeeded}
        </Banner>
      )}

      <label htmlFor={ids.method} className="member__label">
        {form.method}
      </label>
      <Select id={ids.method} value={method} onChange={(e) => setMethod(e.target.value as Method)}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {copy.form.methods[m]}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.note} className="member__label">
        {form.note}
      </label>
      <Input
        id={ids.note}
        type="text"
        maxLength={500}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <FixPreview
        month={monthName(payment.period_start)}
        owed={[owed, owed + back]}
        balance={[ledger.balance_clp, ledger.balance_clp + back]}
      />

      {refund.error && (
        <Banner tone="error">
          {refund.error instanceof ApiError && refund.error.status === 409 ? form.refused.exceeds : form.refused.failed}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={refund.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={refund.isPending} busy={refund.isPending}>
          {refund.isPending ? form.working : form.submit(clp(value))}
        </Button>
      </div>
    </form>
  )
}

type Line = { kind: 'entry'; entry: TimelineEntry } | { kind: 'freeze'; line: FreezeLine }

/** Entries and freeze lines, newest first; a freeze line after the entries of its day. */
function timeline(ledger: MembershipLedger): Line[] {
  const lines: Line[] = []
  const freezes = [...ledger.freezes]
  for (const entry of ledger.entries) {
    const day = isoDay(entry.created_at)
    while (freezes[0] && freezes[0].day > day) lines.push({ kind: 'freeze', line: freezes.shift()! })
    lines.push({ kind: 'entry', entry })
  }
  return [...lines, ...freezes.map((line) => ({ kind: 'freeze' as const, line }))]
}

// The ledger shows its latest lines; the rest open in place.
const LEDGER_SHOWN = 4

/** The Libro: each line with something to fix a button that opens its fixes under it
 * (#279), one line at a time. */
function Ledger({ membership, ledger }: { membership: Membership; ledger: MembershipLedger }) {
  const [all, setAll] = useState(false)
  const [fixing, setFixing] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const open = new Map(ledger.open_periods.map((p) => [p.id, p.paid_clp]))
  const periods = new Map(ledger.periods.map((p) => [p.id, p]))
  const refundable = new Map(ledger.refundable_payments.map((p) => [p.id, p]))
  const lines = timeline(ledger)
  const shown = all ? lines : lines.slice(0, LEDGER_SHOWN)
  const finish = (message: string) => {
    setFixing(null)
    setDone(message)
  }
  const cancel = () => setFixing(null)

  /** The line's fixes, if it has any: a charge's, or a payment's refund. */
  const fixesOf = (entry: TimelineEntry): ReactElement | null => {
    if (entry.kind === 'charge') {
      const period = entry.billing_period_id === null ? undefined : periods.get(entry.billing_period_id)
      if (!period) return null
      const charge = { membership, period, balance: ledger.balance_clp }
      const [first, ...rest] = chargeFixes(charge)
      if (!first) return null
      return <ChargeFixes charge={charge} fixes={[first, ...rest]} plans={false} onCancel={cancel} onDone={finish} />
    }
    const payment = entry.kind === 'payment' ? refundable.get(entry.id) : undefined
    if (!payment) return null
    return (
      <Fixes title={copy.fix.payment(monthName(payment.period_start))} fixes={['refund']} label={() => copy.fix.refund}>
        {() => <RefundForm payments={[payment]} ledger={ledger} onCancel={cancel} onDone={finish} />}
      </Fixes>
    )
  }

  return (
    <section className="member__section" aria-label={copy.ledger.title}>
      <SectionHeader title={copy.ledger.title} />
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {lines.length === 0 ? (
        <p className="member__note">{copy.ledger.empty}</p>
      ) : (
        <Card as="ul" flush className="member__ledger">
          {shown.map((line) => {
            if (line.kind === 'freeze') {
              return <FreezeEntry key={`${line.line.freeze_id}-${line.line.edge}`} line={line.line} />
            }
            const { entry } = line
            const fixes = fixesOf(entry)
            return (
              <Entry
                key={entry.id}
                entry={entry}
                unpaid={entry.billing_period_id !== null && open.has(entry.billing_period_id)}
                paidClp={entry.billing_period_id === null ? 0 : (open.get(entry.billing_period_id) ?? 0)}
                fix={
                  fixes && {
                    open: fixing === entry.id,
                    toggle: () => {
                      setDone(null)
                      setFixing(fixing === entry.id ? null : entry.id)
                    },
                    panel: fixes,
                  }
                }
              />
            )
          })}
        </Card>
      )}
      {lines.length > LEDGER_SHOWN && (
        <Button variant="ghost" className="member__more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? copy.ledger.fewer : copy.ledger.all(lines.length)}
        </Button>
      )}
    </section>
  )
}

/** A line that opens its fixes in place: whether it is open, and what it opens. */
type LineFix = { open: boolean; toggle: () => void; panel: ReactNode }

/** A Libro line: a dot in its tone, what it is, its detail and amount. With `fix`, a
 * button with "›" that opens its fixes under it (#279); with none, nothing to press. */
function Line({
  className,
  title,
  detail,
  amount,
  fix,
}: {
  className: string
  title: string
  detail: string
  amount: string
  fix?: LineFix | null
}) {
  const content = (
    <>
      <span className="member__dot" aria-hidden="true" />
      <span className="member__entry-text">
        <span className="member__entry-title">{title}</span>
        <span className="member__detail">{detail}</span>
      </span>
      <span className="member__entry-amount">{amount}</span>
    </>
  )
  if (!fix) return <li className={className}>{content}</li>
  return (
    <li className={`${className} member__entry--fixable`}>
      <button type="button" className="member__entry-button" aria-expanded={fix.open} onClick={fix.toggle}>
        {content}
        <span className="member__entry-chevron" aria-hidden="true">
          <ChevronRightIcon />
        </span>
      </button>
      {fix.open && fix.panel}
    </li>
  )
}

const CORRECTIONS_SHOWN = 3

/** "Correcciones" (#277): every fix to the person's billing, newest first, the latest
 * three with "Ver todas (N)". Owner and admin only, as the Libro above it; none until a
 * first fix. */
function Corrections({ personId }: { personId: string }) {
  const [all, setAll] = useState(false)
  const corrections = useQuery(correctionsQuery(personId))
  const words = copy.corrections
  if (corrections.isError) {
    return (
      <Banner tone="error">
        {words.error}
      </Banner>
    )
  }
  const items = corrections.data?.items ?? []
  if (items.length === 0) return null
  const total = corrections.data?.total ?? items.length
  const shown = all ? items : items.slice(0, CORRECTIONS_SHOWN)
  return (
    <section className="member__section" aria-label={words.title}>
      <SectionHeader title={words.title} />
      <Card as="ul" flush className="member__ledger">
        {shown.map((c) => (
          <CorrectionLine key={c.id} correction={c} />
        ))}
      </Card>
      {total > CORRECTIONS_SHOWN && (
        <Button variant="ghost" className="member__more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? words.fewer : words.all(total)}
        </Button>
      )}
    </section>
  )
}

/** `Anuló cargo noviembre` · `$45.000 → $0` · `duplicado · Mensual · por Ana · 2 nov`. */
function CorrectionLine({ correction: c }: { correction: Correction }) {
  const words = copy.corrections
  const { before, after } = c
  const detail = [c.reason, c.plan_name, c.actor_name ? words.by(c.actor_name) : null, shortDay(c.at)]
  return (
    <li className="member__entry member__entry--correction">
      <span className="member__dot" aria-hidden="true" />
      <div className="member__entry-text">
        <span className="member__entry-title">{correctionTitle(c)}</span>
        <span className="member__detail">{detail.filter(Boolean).join(' · ')}</span>
        {before && after && (
          <span className="member__detail">{words.balance(clp(before.balance_clp), clp(after.balance_clp))}</span>
        )}
      </div>
      {before && after && (
        <span className="member__entry-amount">
          {words.owed(clp(before.outstanding_clp), clp(after.outstanding_clp))}
        </span>
      )}
    </li>
  )
}

function correctionTitle(c: Correction): string {
  const words = copy.corrections
  const month = c.period_start ? monthName(c.period_start) : ''
  switch (c.action) {
    case 'due_date_changed':
      return words.dueDate
    case 'membership_reactivated':
      return words.reactivated
    case 'cancel_undone':
      return words.cancelUndone
    case 'ledger_corrected':
      if (c.purpose === 'void') return (c.plan_void ? words.planVoid : words.void)(month)
      if (c.purpose === 'restore') return words.restore(month)
      // In the member's favour when it left the period owing less.
      return words.adjustment((c.after?.outstanding_clp ?? 0) < (c.before?.outstanding_clp ?? 0), month)
  }
}

/** `Congelación` · `Vacaciones · vuelve el 24 nov · 10 nov`, with no amount. */
function FreezeEntry({ line }: { line: FreezeLine }) {
  const words = copy.ledger
  const start = line.edge === 'start'
  const detail = [line.reason, start ? words.returns(shortDay(line.to_date)) : null, shortDay(line.day)]
  return (
    <li className="member__entry member__entry--freeze">
      <span className="member__dot" aria-hidden="true" />
      <div className="member__entry-text">
        <span className="member__entry-title">{start ? words.freezeStart : words.freezeEnd}</span>
        <span className="member__detail">{detail.filter(Boolean).join(' · ')}</span>
      </div>
      <span className="member__entry-amount" aria-hidden="true">
        {t.common.noAmount}
      </span>
    </li>
  )
}

function Entry({
  entry,
  unpaid,
  paidClp,
  fix,
}: {
  entry: TimelineEntry
  unpaid: boolean
  paidClp: number
  fix?: LineFix | null
}) {
  const { title, detail, tone } = describeEntry(entry, unpaid, paidClp)
  // A voided charge stays, struck through and labelled, not hidden (#256).
  const struck = entry.voided ? ' member__entry--voided' : ''
  return (
    <Line
      className={`member__entry member__entry--${tone}${struck}`}
      title={title}
      detail={detail}
      amount={entryAmount(entry)}
      fix={fix}
    />
  )
}

/** An adjustment by what it does to what is owed, a discount `−$5.000` and a surcharge
 * `+$5.000`, and a carried credit as held; a refund, money out, `−$10.000`. */
function entryAmount(entry: TimelineEntry): string {
  if (entry.kind === 'adjustment' && entry.period_start) return t.common.adjustmentClp(entry.amount_clp)
  if (entry.kind === 'refund') return t.common.signedClp(-entry.amount_clp)
  return clp(entry.amount_clp)
}

type Tone = 'paid' | 'owed' | 'muted' | 'rejected'

/** What a ledger row says: `Pago septiembre`, `transferencia · validó Martín · 2 sep`. */
function describeEntry(entry: TimelineEntry, unpaid: boolean, paidClp = 0): { title: string; detail: string; tone: Tone } {
  const words = copy.ledger
  const month = entry.period_start ? monthName(entry.period_start) : ''
  const method = entry.method ? words.method[entry.method] : null
  const day = shortDay(entry.validated_at ?? entry.created_at)
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(' · ')

  switch (entry.kind) {
    case 'charge':
      if (entry.voided) {
        const { reason, by_name, at } = entry.voided
        return { title: words.charge(month), detail: words.voided(reason, by_name, shortDay(at)), tone: 'muted' }
      }
      return {
        title: words.charge(month),
        detail: join(
          // Voided and restored (#278): owed again, and says what happened to it.
          entry.restored
            ? join(
                words.voided(entry.restored.void.reason, entry.restored.void.by_name, shortDay(entry.restored.void.at)),
                words.restored(entry.restored.reason, entry.restored.by_name, shortDay(entry.restored.at)),
              )
            : words.generated(shortDay(entry.created_at)),
          unpaid ? (paidClp > 0 ? words.partlyPaid(clp(paidClp)) : words.unpaid) : null,
        ),
        tone: unpaid ? 'owed' : 'muted',
      }
    case 'payment': {
      const review =
        entry.status === 'pending'
          ? words.pending
          : entry.status === 'rejected'
            ? words.rejected
            : entry.validated_by_name && words.validatedBy(entry.validated_by_name)
      const tone = entry.status === 'validated' ? 'paid' : entry.status === 'rejected' ? 'rejected' : 'muted'
      return { title: words.payment(month), detail: join(method, review, day), tone }
    }
    case 'adjustment':
      if (entry.voids || entry.purpose === 'restore') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        const title = entry.voids ? words.void(month) : words.restore(month)
        return { title, detail: join(entry.note, by, day), tone: 'muted' }
      }
      return {
        title: entry.period_start ? words.adjustment(entry.amount_clp > 0, month) : words.credit,
        detail: join(entry.note, day),
        tone: entry.status === 'rejected' ? 'rejected' : entry.amount_clp < 0 ? 'owed' : 'muted',
      }
    case 'refund':
      return { title: words.refund(month), detail: join(method, entry.note, day), tone: 'muted' }
  }
}

/** "Horas por etiqueta" (#243): the classes the member attended, hours per tag, for a month or a year. */
function MemberTagHours({ personId }: { personId: string }) {
  return (
    <TagHoursCard
      title={t.tagHours.theirs}
      headed
      today={useGymToday()}
      query={(stretch: Stretch) => personTagHoursQuery(personId, stretch)}
    />
  )
}
