import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useRef, useState, type FormEvent, type ReactElement, type ReactNode } from 'react'
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
  dueDateRefused,
  editFreeze,
  endFreeze,
  freezeMembership,
  membershipLedgerQuery,
  membershipsQuery,
  moveDueDate,
  moveRefused,
  moveTargetsQuery,
  personQuery,
  bringBack,
  bringBackQuery,
  type BringBack,
  reactivationRefused,
  recordAdjustment,
  recordMove,
  paymentVoidRefused,
  recordPayment,
  recordPaymentAhead,
  recordPaymentVoid,
  recordRefund,
  recordRestore,
  recordRevert,
  recordVoid,
  recordWriteOff,
  shownMemberships,
  restoreRefused,
  revertRefused,
  writeOffRefused,
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
  METHODS,
  type MoveTarget,
  type OpenPeriod,
  type Person,
  type RecordedAdjustment,
  type RecordedAhead,
  type RecordedPayment,
  type RecordedRefund,
  type RefundablePayment,
  type TimelineEntry,
} from '../api/member'
import { holds, myAccessQuery, readsLedger, type Access } from '../api/me'
import { refusedAnonymised, welcomeQuery } from '../api/people'
import { remindersQuery } from '../api/reminders'
import { useGymToday } from '../api/sessions'
import { RankBelt } from '../components/Belt'
import { Button, buttonClass } from '../components/Button'
import { Chip } from '../components/Chip'
import { BackLink } from '../components/BackLink'
import { Input, Select } from '../components/Field'
import { useFocusOnOpen, useRefusal } from '../components/focusInvalid'
import { cx } from '../components/classNames'
import { ChevronRightIcon, WhatsAppIcon } from '../components/icons'
import { Grid, PageContainer } from '../components/Layout'
import { MemberMatTime } from '../components/MatTime'
import { TagHoursCard } from '../components/TagHours'
import { EmailReminder } from '../components/EmailReminder'
import { FreezeRequestRow } from '../components/FreezeRequests'
import { ReminderLink } from '../components/ReminderLink'
import { StatusPill } from '../components/StatusPill'
import { addDays, isoDay, monthName, monthYear, shortDate, shortDay } from '../format'
import { Banner, Card, cardClass, CheckRow, PlainList, SectionHeader } from '../components/Card'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { failedMessage } from './anonymised'
import { FamilyPanel } from './FamilyPanel'
import { PersonActions } from './PersonActions'
import { GradeForm } from './GradeForm'
import { PersonExtraLines } from './PersonExtraLines'
import { PaidThroughForm, paysThrough } from './PaidThroughForm'
import { PersonHistory } from './PersonHistory'
import { FixActions, useConfirmStep } from './ConfirmStep'
import { PersonData } from './PersonData'
import { PersonConsent } from './PersonConsent'
import { PersonRequirements } from './PersonRequirements'
import { AddPlan, AssignForm, AssignPlan, assignsPlan, ChangePlanForm, changesPlan, DiscountForm, isLive, takesDiscount } from './PersonPlan'
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
 * what an earlier plan still owes as "Deuda anterior" (#249). On a plan, "Agregar otro
 * plan", and a card and a Libro for each plan running (#354). A freeze the member asked
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
 * An anonymous record (#372) is read-only (#581): its plans, Libro, corrections and
 * history as they are, with no action, fix, reminder or form in any section, and none
 * of the hints that ask for data it will never have.
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
  const access = useQuery(myAccessQuery())
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

  // A card for each plan running, a course beside a monthly plan say (#354).
  const shown = shownMemberships(memberships.data)
  const membership = shown[0]
  // A member since the day they first trained here (#293) or their first plan here,
  // whichever is earlier: the current plan comes first in the list, not the earliest.
  const firstStart = [person.data.member_since, ...memberships.data.map((m) => m.started_on)]
    .filter((day): day is string => day !== null)
    .sort()[0]
  const since = monthYear(firstStart ?? person.data.created_at)
  const rank = graded ? grades.data?.current : undefined
  const money = readsLedger(access.data)
  // An anonymous record (#372) is the books' alone: read, never changed (#581).
  const readOnly = person.data.anonymised === true

  return (
    <Shell
      title={person.data.name}
      subtitle={rank ? copy.rankSince(rankLabel(rank), since) : copy.since(since)}
      action={readOnly ? undefined : <HeaderWhatsApp person={person.data} money={money} />}
    >
      <LeftBanner
        person={person.data}
        // A mistaken Dar de baja undone in one step, their plan with them (#549). It writes
        // money and returns them to the list: both permissions, as the API asks.
        undoable={!readOnly && holds(access.data, 'money_write') && holds(access.data, 'members_manage')}
      />
      {/* On a desktop the money on the left, everything else beside it. */}
      <Grid className="member__columns">
        <div className="member__column">
          {membership ? (
            <>
              {shown.map((m, i) => (
                <Standing
                  key={m.id}
                  personId={personId}
                  membership={m}
                  money={money}
                  named={shown.length > 1}
                  earlier={
                    money && i === 0 && !readOnly ? <EarlierDebt memberships={memberships.data} shown={shown} /> : null
                  }
                  assign={{ person: person.data, access: access.data, done: assigned, setDone: setAssigned }}
                />
              ))}
              <AddPlan person={person.data} access={access.data} membership={membership} />
              {money && <Corrections personId={personId} />}
            </>
          ) : (
            <>
              <p className="member__note">{copy.noPlan}</p>
              <AssignPlan person={person.data} membership={membership} access={access.data} done={assigned} setDone={setAssigned} />
            </>
          )}
          {money && <PersonExtraLines personId={personId} />}
          {money && <PersonHistory person={person.data} />}
        </div>
        <div className="member__column">
          <Attendance personId={personId} />
          <MemberMatTime personId={personId} />
          <MemberTagHours personId={personId} />
          <Graduation
            personId={personId}
            canAward={!readOnly && membership !== undefined && membership.status !== 'cancelled'}
          />
          <section className="member__section" aria-label={t.admin.family.toggle}>
            <SectionHeader title={t.admin.family.toggle} />
            <Card as="div" className="member__card member__family">
              <FamilyPanel person={person.data} />
            </Card>
          </section>
          <PersonRequirements person={person.data} />
          <PersonData person={person.data} />
          <PersonConsent person={person.data} />
          <PersonWelcome person={person.data} access={access.data} />
          <PersonActions person={person.data} access={access.data} />
        </div>
      </Grid>
    </Shell>
  )
}

/**
 * "Dado de baja" at the top of a ficha (#294): since when, and why for the owner and
 * admins. Something to know, not a failure. With `undoable` and a plan their Dar de baja
 * ended, it carries "Deshacer la baja" itself (#568), the form opening under it, and one
 * line on how that differs from "Reactivar" at the foot of the ficha: on a phone the foot
 * is screens away from the banner that announces the baja.
 */
function LeftBanner({ person, undoable }: { person: Person; undoable: boolean }) {
  const [undoing, setUndoing] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const plan = person.left_with
  const canUndo = undoable && plan !== null && plan !== undefined
  return (
    <>
      {person.left_on && (
        <Banner tone="warning" as="div" role="status" className="member__left">
          <p>
            {copy.leftBanner(shortDate(person.left_on))}
            {/* Only the owner and admins are ever sent it (#294). */}
            {person.left_reason && (
              <>
                <br />
                {copy.leftBannerReason(person.left_reason)}
              </>
            )}
          </p>
          {canUndo && (
            <>
              <p>{copy.undoLeaveHint}</p>
              <div className="member__actions">
                <Button aria-expanded={undoing} onClick={() => setUndoing(!undoing)}>
                  {copy.undoLeave}
                </Button>
              </div>
            </>
          )}
        </Banner>
      )}
      {person.left_on && canUndo && undoing && (
        <ReactivateForm
          mode="uncancel"
          membership={{ id: plan }}
          onCancel={() => setUndoing(false)}
          onDone={(message) => {
            setUndoing(false)
            setDone(message)
          }}
        />
      )}
      {done && <Banner tone="done">{done}</Banner>}
    </>
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
  access: Access | null | undefined
  /** What "Asignar plan" did, kept by the ficha as the new plan takes this card's place. */
  done: string | null
  setDone: (message: string | null) => void
}

/** The plan and how it stands; with `money`, what is owed, the actions and the ledger.
 * `assign` is "Asignar plan", which offers itself once this plan has ended, and
 * `earlier` what other plans still owe, under the card (#249). `named`: the card and its
 * Libro say the plan's name, beside another plan's (#354). */
function Standing({
  personId,
  membership,
  money,
  named,
  earlier,
  assign,
}: {
  personId: string
  membership: Membership
  money: boolean
  named: boolean
  earlier: ReactNode
  assign: Assigning
}) {
  const ledger = useQuery({ ...membershipLedgerQuery(membership.id), enabled: money })
  const data = money ? ledger.data : undefined
  // An anonymous record's plan and Libro, to read: no action, no fix, no reminder (#581).
  const readOnly = assign.person.anonymised === true
  // The header's WhatsApp reads the same list. Longest overdue first: the email is about
  // the oldest period this plan owes (#260).
  const reminders = useQuery({ ...remindersQuery(personId), enabled: money })
  const overdue = money
    ? reminders.data?.find((r) => r.membership_id === membership.id && r.days_overdue >= 0)
    : undefined

  return (
    <>
      <Card
        className="member__card"
        aria-label={named ? copy.planLabel(copy.paymentLabel, membership.plan_name) : copy.paymentLabel}
      >
        <div className="member__card-head">
          <span className="member__eyebrow">{planLine(membership)}</span>
          <Badge membership={membership} ledger={data} />
        </div>
        {membership.freeze && !membership.freeze.started && (
          <p className="member__detail">
            {copy.freezeBooked(shortDay(membership.freeze.from_date), shortDay(membership.freeze.to_date))}
          </p>
        )}
        {money && !readOnly && <PlanFreezeRequest membershipId={membership.id} />}
        {membership.voided_at && membership.void_reason && (
          <p className="member__detail">{copy.voidedBanner(membership.void_reason, shortDay(isoDay(membership.voided_at)))}</p>
        )}
        {membership.converted_from && (
          <p className="member__detail">
            {copy.convertedFrom(membership.converted_from.plan_name, shortDay(membership.converted_from.started_on))}
          </p>
        )}
        {money && membership.discount_pct ? (
          <p className="member__detail">{copy.discountLine(membership.discount_pct, membership.discount_reason ?? null)}</p>
        ) : null}
        {membership.next_plan && membership.status !== 'cancelled' && (
          <p className="member__detail">
            {copy.planChangeBooked(membership.next_plan.plan_name, shortDay(membership.next_plan.starts_on))}
          </p>
        )}
        {data && <Owed ledger={data} />}
        {data && overdue && !readOnly && <EmailReminder reminder={overdue} />}
        {money && ledger.isError && (
          <Banner tone="error">
            {copy.ledgerError}
          </Banner>
        )}
        {readOnly ? null : data ? (
          <Actions
            personId={personId}
            membership={membership}
            ledger={data}
            assign={assignsPlan(assign.person, membership, assign.access) ? assign : undefined}
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
      {data && <Ledger personId={personId} membership={membership} ledger={data} named={named} readOnly={readOnly} />}
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
function EarlierDebt({ memberships, shown }: { memberships: readonly Membership[]; shown: readonly Membership[] }) {
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

/** The ledgers of the member's memberships other than those `shown`, loaded so far. */
function useOtherLedgers(memberships: readonly Membership[], shown: readonly Membership[], enabled: boolean): Held[] {
  const others = memberships.filter((m) => !shown.some((s) => s.id === m.id))
  const ledgers = useQueries({ queries: others.map((m) => ({ ...membershipLedgerQuery(m.id), enabled })) })
  return others.flatMap((m, i) => {
    const ledger = ledgers[i]?.data
    return ledger ? [{ membership: m, ledger }] : []
  })
}

/** A period of one of the member's plans, with that plan's balance: what a charge
 * line's fixes go to (#279). */
type Charge = { membership: Membership; period: LedgerPeriod; balance: number }

type ChargeFix = 'changeAmount' | 'moveDueDate' | 'voidCharge' | 'restoreCharge' | 'writeOff'

/** What can be done to `charge`, as a Libro line offers it (#279): a charge voided stands
 * restored, one owing falls due another day (#283), is voided or its debt forgiven (#282),
 * and any is changed. Nothing on a plan voided by mistake, which is assigned again. */
function chargeFixes({ membership, period }: Charge): ChargeFix[] {
  if (membership.voided_at) return []
  if (period.void_id) return ['restoreCharge']
  return period.outstanding_clp > 0 ? ['changeAmount', 'moveDueDate', 'voidCharge', 'writeOff'] : ['changeAmount']
}

/** Whether `entry`, an adjustment, is reverted by "Revertir" (#282): one on a period, of
 * no correction but a write-off, not reverted yet, on a charge not voided and a plan not
 * voided. A void is restored instead, and a carried credit follows its payment. */
function revertible(entry: TimelineEntry, period: LedgerPeriod | undefined, membership: Membership): boolean {
  if (entry.kind !== 'adjustment' || entry.status !== 'validated' || !period || membership.voided_at) return false
  if (entry.reverted || period.void_id) return false
  return entry.purpose == null || entry.purpose === 'write_off'
}

/** "Mensual · Caducado": which plan another plan's charge is on, as #271 labels it. */
function planOf(membership: Membership): string {
  return `${membership.plan_name} · ${t.admin.students.status[membership.status]}`
}

function planLine(membership: Membership): string {
  if (membership.anchor_day !== null && membership.next_anchor_day) {
    return copy.dueDayMoving(membership.plan_name, membership.anchor_day, membership.next_anchor_day)
  }
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
  | 'discount'
  | 'fixPlan'
  | 'voidPlan'
  | 'uncancelPlan'
  | 'paidThrough'
  | 'reactivate'
  | 'assign'
  | null

/** What the plan's periods still owe: what "Anular plan" voids. */
function unpaid(ledger: MembershipLedger): number {
  return ledger.periods.reduce((sum, p) => sum + p.outstanding_clp, 0)
}

/** What the plan card offers, in the order it reaches for its secondary and its menu. */
type Action =
  | 'payment'
  | 'reactivate'
  | 'assign'
  | 'endFreeze'
  | 'editFreeze'
  | 'freeze'
  | 'changePlan'
  | 'discount'
  | 'refund'
  | 'fixPlan'

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
    (membership.plan_kind === 'monthly' || membership.plan_kind === 'prepaid' || membership.plan_kind === 'fixed_period')
  // "Corregir plan" stays open while one of its fixes is.
  const fixingPlan = open === 'fixPlan' || open === 'voidPlan' || open === 'uncancelPlan' || open === 'paidThrough'
  // Dado de baja by mistake: "Deshacer baja" brings it back (#285). A voided plan stays voided.
  const uncancels = membership.status === 'cancelled' && !membership.voided_at

  const offered: Action[] = [
    ...(reactivates ? (['reactivate'] as const) : []),
    ...(assign ? (['assign'] as const) : []),
    'payment',
    ...(freeze ? (['endFreeze', 'editFreeze'] as const) : membership.status === 'active' ? (['freeze'] as const) : []),
    ...(changesPlan(membership) ? (['changePlan'] as const) : []),
    ...(takesDiscount(membership) ? (['discount'] as const) : []),
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
    discount: copy.discount,
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
          {uncancels && (
            <Chip
              pressed={open === 'uncancelPlan'}
              onClick={() => setOpen(open === 'uncancelPlan' ? 'fixPlan' : 'uncancelPlan')}
            >
              {copy.uncancelPlan}
            </Chip>
          )}
          {paysThrough(membership) && (
            <Chip
              pressed={open === 'paidThrough'}
              onClick={() => setOpen(open === 'paidThrough' ? 'fixPlan' : 'paidThrough')}
            >
              {copy.paidThroughPlan}
            </Chip>
          )}
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
      {open === 'discount' && takesDiscount(membership) && (
        <DiscountForm membership={membership} onCancel={() => setOpen(null)} onDone={finish} />
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
      {open === 'paidThrough' && paysThrough(membership) && (
        <PaidThroughForm membership={membership} onCancel={() => setOpen('fixPlan')} onDone={finish} />
      )}
      {open === 'uncancelPlan' && uncancels && (
        <ReactivateForm mode="uncancel" membership={membership} onCancel={() => setOpen('fixPlan')} onDone={finish} />
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
 * then the chosen one's form. None is chosen to begin with (#568): the first may be one
 * that cannot be used yet ("Mover" with every period's proof waiting), and a form opened
 * unasked looks like the one to use. A lone fix is no choice: it is named in the title,
 * with no chip, and its form open (#419). */
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
  const [picked, setPicked] = useState<F | null>(null)
  const fix = fixes.length === 1 ? fixes[0] : picked !== null && fixes.includes(picked) ? picked : null
  // Opened from a Libro line: focus lands in it, its first chip or its lone fix's first field (#569).
  const panel = useFocusOnOpen<HTMLDivElement>()
  return (
    <div ref={panel} className="member__fix" role="group" aria-label={title}>
      <span className="member__fix-title">{fixes.length === 1 ? copy.fix.only(title, label(fixes[0])) : title}</span>
      {fixes.length > 1 && (
        <div className="member__fix-choices">
          {fixes.map((f) => (
            <Chip key={f} pressed={f === fix} onClick={() => setPicked(f)}>
              {label(f)}
            </Chip>
          ))}
        </div>
      )}
      {fix !== null && children(fix)}
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

/** A charge line's fixes (#279): "Cambiar monto", "Mover vencimiento" (#283), "Anular
 * cargo" or "Restaurar cargo", whichever apply; `plans` names the plan, for another plan's charge (#271). */
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
        ) : fix === 'moveDueDate' ? (
          <MoveDueDateForm charge={charge} onCancel={onCancel} onDone={onDone} />
        ) : fix === 'voidCharge' ? (
          <VoidChargeForm charge={charge} onCancel={onCancel} onDone={onDone} />
        ) : fix === 'writeOff' ? (
          <WriteOffForm charge={charge} onCancel={onCancel} onDone={onDone} />
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

/** What a refused "Mover vencimiento" says (#283). */
function dueDateRefusal(error: Error): string {
  return copy.dueDateRefused[dueDateRefused(error) ?? 'failed']
}

/** A due date moves at most this many days past its period's end (`billing.due_date_bounds`). */
const DUE_DATE_DAYS_PAST_END = 60

/** "Mover vencimiento" (#283): "le doy hasta el 10". The charge falls due on another day,
 * from its period's start to its end plus 60 days; the lapse and the overdue emails follow. */
function MoveDueDateForm({
  charge,
  onCancel,
  onDone,
}: {
  charge: Charge
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.dueDateForm
  const ids = { day: useId(), hint: useId(), reason: useId() }
  const { period } = charge
  const month = monthName(period.period_start)
  const earliest = period.period_start
  const latest = addDays(period.period_end, DUE_DATE_DAYS_PAST_END)
  const [day, setDay] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
  const dayOk = day >= earliest && day <= latest && day !== period.due_date
  const reasonOk = reason.trim() !== ''

  const moved = useSubmit({
    offline: 'refuse',
    mutationFn: () => moveDueDate(period.id, { due_date: day, reason: reason.trim() }),
    onSuccess: async (result) => {
      onDone(form.done(month, shortDay(result.due_date)))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!dayOk || !reasonOk) return refuse()
    if (step.confirming) moved.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={ids.day} className="member__label">
        {form.day}
      </label>
      <Input
        id={ids.day}
        type="date"
        min={earliest}
        max={latest}
        value={day}
        readOnly={step.confirming}
        aria-describedby={cx(ids.hint, checked && !dayOk && `${ids.day}-error`)}
        aria-invalid={checked && !dayOk}
        onChange={(e) => setDay(e.target.value)}
      />
      <p id={ids.hint} className="member__detail">
        {form.hint(shortDay(period.due_date), shortDay(latest))}
      </p>
      {checked && !dayOk && (
        <Banner tone="error" id={`${ids.day}-error`}>
          {day === period.due_date ? form.unchanged : form.dayNeeded(shortDay(earliest), shortDay(latest))}
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
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${ids.reason}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${ids.reason}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      {dayOk && (
        <div className="member__fix-preview">
          <span className="member__detail">{form.preview(shortDay(period.due_date), shortDay(day))}</span>
        </div>
      )}
      {step.confirming && (
        <Banner tone="info">{form.notice(month, clp(period.outstanding_clp), shortDay(day))}</Banner>
      )}
      {moved.error && (
        <Banner tone="error">
          {dueDateRefusal(moved.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={moved.isPending}
        words={form}
        submit={form.submit}
        confirm={form.confirm(shortDay(day))}
        onCancel={onCancel}
      />
    </form>
  )
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
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
    if (!reasonOk || !period.void_id) return refuse()
    if (step.confirming) restored.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview
        month={month}
        owed={[period.outstanding_clp, period.outstanding_clp + period.voided_clp]}
        balance={[balance, balance + period.voided_clp]}
      />
      {step.confirming && <Banner tone="info">{form.notice(month, clp(period.voided_clp))}</Banner>}
      {restored.error && (
        <Banner tone="error">
          {restoreRefusal(restored.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={restored.isPending}
        words={form}
        submit={form.submit}
        confirm={form.confirm(clp(period.voided_clp))}
        onCancel={onCancel}
      />
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
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
    if (!reasonOk) return refuse()
    if (step.confirming) voided.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview month={month} owed={[period.outstanding_clp, 0]} balance={[balance, balance - period.outstanding_clp]} />
      {step.confirming && <Banner tone="info">{form.notice(month, clp(period.outstanding_clp))}</Banner>}
      {voided.error && (
        <Banner tone="error">
          {voidRefusal(voided.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={voided.isPending}
        words={form}
        submit={form.submit(clp(period.outstanding_clp))}
        confirm={form.confirm(clp(period.outstanding_clp))}
        variant="danger"
        onCancel={onCancel}
      />
    </form>
  )
}

/** What a refused write-off says (#282). */
function writeOffRefusal(error: Error): string {
  return copy.writeOffRefused[writeOffRefused(error) ?? 'failed']
}

/** "Condonar deuda" (#282): a real debt the gym will not collect. Owed nowhere once
 * forgiven, but the charge was no mistake, so "Esperado" still counts it. A second step
 * says so before it is saved. */
function WriteOffForm({
  charge,
  onCancel,
  onDone,
}: {
  charge: Charge
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.writeOffForm
  const id = useId()
  const { membership, period, balance } = charge
  const month = monthName(period.period_start)
  const owed = clp(period.outstanding_clp)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
  const reasonOk = reason.trim() !== ''

  const forgiven = useSubmit({
    offline: 'refuse',
    mutationFn: () => recordWriteOff({ membership_id: membership.id, billing_period_id: period.id, reason: reason.trim() }),
    onSuccess: async () => {
      onDone(form.done(month, owed))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!reasonOk) return refuse()
    if (step.confirming) forgiven.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview month={month} owed={[period.outstanding_clp, 0]} balance={[balance, balance - period.outstanding_clp]} />
      {step.confirming && <Banner tone="info">{form.notice}</Banner>}
      {forgiven.error && (
        <Banner tone="error">
          {writeOffRefusal(forgiven.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={forgiven.isPending}
        words={form}
        submit={form.submit(owed)}
        confirm={form.confirm(owed)}
        variant="danger"
        onCancel={onCancel}
      />
    </form>
  )
}

/** What a refused revert says (#282). */
function revertRefusal(error: Error): string {
  return copy.revertRefused[revertRefused(error) ?? 'failed']
}

/** "Revertir" (#282): an adjustment made by mistake is undone, its period as before it.
 * Reverting one in the member's favour is owed again; a Recargo's revert is in their favour. */
function RevertForm({
  entry,
  title,
  period,
  balance,
  onCancel,
  onDone,
}: {
  entry: TimelineEntry
  // The adjustment's line title, "Descuento noviembre".
  title: string
  period: LedgerPeriod
  balance: number
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.revertForm
  const id = useId()
  const month = monthName(period.period_start)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
  const reasonOk = reason.trim() !== ''
  // An adjustment in the member's favour (positive) is owed once reverted, and the other way round.
  const owedAfter = Math.max(period.outstanding_clp + entry.amount_clp, 0)

  const reverted = useSubmit({
    offline: 'refuse',
    mutationFn: () => recordRevert({ adjustment_id: entry.id, reason: reason.trim() }),
    onSuccess: async () => {
      onDone(form.done(title))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!reasonOk) return refuse()
    if (step.confirming) reverted.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview
        month={month}
        owed={[period.outstanding_clp, owedAfter]}
        balance={[balance, balance + owedAfter - period.outstanding_clp]}
      />
      {step.confirming && <Banner tone="info">{form.notice(month, clp(owedAfter))}</Banner>}
      {reverted.error && (
        <Banner tone="error">
          {revertRefusal(reverted.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={reverted.isPending}
        words={form}
        submit={form.submit}
        confirm={form.confirm(clp(Math.abs(entry.amount_clp)))}
        onCancel={onCancel}
      />
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
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
    if (!reasonOk) return refuse()
    if (step.confirming) voided.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview balance={[balance, balance - owed]} />
      {step.confirming && <Banner tone="info">{form.notice(clp(owed))}</Banner>}
      {voided.error && (
        <Banner tone="error">
          {voidRefusal(voided.error)}
        </Banner>
      )}
      <FixActions
        step={step}
        pending={voided.isPending}
        words={form}
        submit={form.submit}
        confirm={form.confirm}
        variant="danger"
        onCancel={onCancel}
      />
    </form>
  )
}

/** What a refused reactivation (#284) or undone cancel (#285) says, and what to do first. */
function reactivateRefusal(error: Error, mode: BringBack = 'reactivate'): string {
  const words = copy.reactivateRefused
  const refused = reactivationRefused(error)
  if (!refused) return mode === 'uncancel' ? copy.uncancelForm.failed : words.failed
  if (refused.code === 'unpaid') {
    const month = refused.period_start ? monthName(refused.period_start) : ''
    return words.unpaid(clp(refused.amount_clp ?? 0), month)
  }
  if (refused.code === 'live_plan') {
    // Beside another plan started since, the payments can be moved to it instead.
    return (mode === 'uncancel' ? copy.uncancelForm.live_plan : words.live_plan)(refused.plan_name ?? '')
  }
  return words[refused.code]
}

const BILL_FROM: readonly BillFrom[] = ['last', 'today']

/** "Reactivar plan" (#284): a lapsed plan Active again, with a reason, billing from where
 * it left off (the months since the lapse, at once) or from today. A second step lists
 * what it bills before it saves. Refused, with what to do first, while a period past grace
 * is unpaid or beside another live plan.
 *
 * With `mode="uncancel"`, "Deshacer baja" (#285): a plan dado de baja by mistake back as it
 * was, billing as a reactivation does; or back Lapsed, billing nothing and offering no
 * choice, when a period past grace is unpaid. */
function ReactivateForm({
  membership,
  mode = 'reactivate',
  onCancel,
  onDone,
}: {
  membership: Pick<Membership, 'id'>
  mode?: BringBack
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const uncancel = mode === 'uncancel'
  const form = uncancel ? copy.uncancelForm : copy.reactivateForm
  const id = useId()
  const quote = useQuery(bringBackQuery(membership.id, mode))
  // Back Lapsed (#285): nothing billed, so no choice of from when.
  const lapsed = quote.data?.status === 'lapsed'
  // Their Dar de baja ended it: the person comes back on the list with it (#549).
  const returns = uncancel && quote.data?.returns === true
  const [billFrom, setBillFrom] = useState<BillFrom>('last')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const [confirming, setConfirming] = useState(false)
  const reasonOk = reason.trim() !== ''
  const bill = quote.data?.[billFrom]

  const reactivated = useSubmit({
    offline: 'refuse',
    mutationFn: () => bringBack(membership.id, mode, reason.trim(), billFrom),
    onSuccess: async () => {
      const total = bill?.total_clp ?? 0
      const message = lapsed ? copy.uncancelForm.doneLapsed : total > 0 ? form.done(clp(total)) : form.doneNothing
      onDone(returns ? `${message} ${copy.uncancelForm.returned}` : message)
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
    if (!reasonOk || !bill) return refuse()
    if (confirming) reactivated.mutate()
    else setConfirming(true)
  }

  if (!quote.data) {
    return (
      <Card as="div" className="member__form" role="group" aria-label={form.title}>
        {quote.isError ? (
          <Banner tone="error">
            {reactivateRefusal(quote.error, mode)}
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
  const choice = !lapsed && today.bills_from !== last.bills_from
  const hints: Record<BillFrom, string> = {
    last: form.lastHint(last.periods.length, monthName(last.bills_from), clp(last.total_clp)),
    today: form.todayHint(shortDay(today.bills_from), clp(today.total_clp)),
  }

  if (confirming && bill) {
    return (
      <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
        {lapsed ? (
          <p className="member__detail">{copy.uncancelForm.confirmLapsed}</p>
        ) : (
          <p className="member__label">{form.confirmTitle}</p>
        )}
        {returns && <p className="member__detail">{copy.uncancelForm.returns}</p>}
        {lapsed ? null : bill.periods.length > 0 ? (
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
            {reactivateRefusal(reactivated.error, mode)}
          </Banner>
        )}
        <div className="member__form-actions">
          <Button disabled={reactivated.isPending} onClick={() => setConfirming(false)}>
            {form.back}
          </Button>
          <Button type="submit" variant="primary" disabled={reactivated.isPending} busy={reactivated.isPending}>
            {reactivated.isPending
              ? form.working
              : uncancel && !lapsed && bill.total_clp > 0
                ? copy.uncancelForm.confirm(clp(bill.total_clp))
                : form.submit}
          </Button>
        </div>
      </form>
    )
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{lapsed ? copy.uncancelForm.introLapsed : form.intro}</p>
      {returns && <p className="member__detail">{copy.uncancelForm.returns}</p>}
      {!choice && !lapsed && <p className="member__detail">{hints.last}</p>}
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
        aria-describedby={checked && !reasonOk ? `${id}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
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
    else refuse()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.from} className="member__label">
        {form.from}
      </label>
      <Input
        id={ids.from}
        type="date"
        min={first}
        value={from}
        aria-invalid={checked && !fromOk}
        aria-describedby={checked && !fromOk ? `${ids.from}-error` : undefined}
        onChange={(e) => setFrom(e.target.value)}
      />
      {checked && !fromOk && (
        <Banner tone="error" id={`${ids.from}-error`}>
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
        aria-describedby={cx(ids.hint, checked && !untilOk && `${ids.until}-error`)}
        aria-invalid={checked && !untilOk}
        onChange={(e) => setUntil(e.target.value)}
      />
      <p id={ids.hint} className="member__detail">
        {form.untilHint}
      </p>
      {checked && !untilOk && (
        <Banner tone="error" id={`${ids.until}-error`}>
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
        aria-describedby={cx(ids.reasonHint, checked && !reasonOk && `${ids.reason}-error`)}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <p id={ids.reasonHint} className="member__detail">
        {form.reasonHint}
      </p>
      {checked && !reasonOk && (
        <Banner tone="error" id={`${ids.reason}-error`}>
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
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
    else refuse()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.until} className="member__label">
        {form.until}
      </label>
      <Input
        id={ids.until}
        type="date"
        min={first}
        value={until}
        aria-describedby={cx(ids.hint, checked && !untilOk && `${ids.until}-error`)}
        aria-invalid={checked && !untilOk}
        onChange={(e) => setUntil(e.target.value)}
      />
      <p id={ids.hint} className="member__detail">
        {form.untilHint}
      </p>
      {checked && !untilOk && (
        <Banner tone="error" id={`${ids.until}-error`}>
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
        aria-describedby={cx(ids.reasonHint, checked && !reasonOk && `${ids.reason}-error`)}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <p id={ids.reasonHint} className="member__detail">
        {form.reasonHint}
      </p>
      {checked && !reasonOk && (
        <Banner tone="error" id={`${ids.reason}-error`}>
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
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
      return refuse()
    }
    record.mutate()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
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
        aria-describedby={amountNeeded && !value ? `${ids.amount}-error` : undefined}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountNeeded && !value && (
        <Banner tone="error" id={`${ids.amount}-error`}>
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
          {refusedAnonymised(record.error)
            ? copy.anonymisedRefused
            : record.error instanceof ApiError && record.error.status === 409
              ? form.refused.paid
              : form.refused.failed}
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
          {aheadRefusal(record.error) ?? failedMessage(record.error, form.refused.failed)}
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
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
    if (!amountOk || !reasonOk) return refuse()
    if (step.confirming) adjust.mutate()
    else step.ask()
  }

  const amountError =
    digits === '' ? (checked ? form.amountNeeded : null) : owedAfter < 0 ? form.paidMore(clp(paid)) : change === 0 && checked ? form.sameAmount : null

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.current(clp(current))}</p>
      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <Input
        id={ids.amount}
        inputMode="numeric"
        value={amount}
        readOnly={step.confirming}
        aria-invalid={amountError !== null}
        aria-describedby={amountError ? `${ids.amount}-error` : undefined}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountError && (
        <Banner tone="error" id={`${ids.amount}-error`}>
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
        readOnly={step.confirming}
        aria-invalid={checked && !reasonOk}
        aria-describedby={checked && !reasonOk ? `${ids.reason}-error` : undefined}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <Banner tone="error" id={`${ids.reason}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview
        month={month}
        owed={[period.outstanding_clp, Math.max(owedAfter, 0)]}
        balance={[balance, owedAfter < 0 ? balance : balance + change]}
      />

      {step.confirming && <Banner tone="info">{form.notice(month, clp(current), clp(value))}</Banner>}
      {adjust.error && (
        <Banner tone="error">
          {adjust.error instanceof ApiError && adjust.error.status === 409 ? form.refused.exceeds : form.refused.failed}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={adjust.isPending}
        words={form}
        submit={form.submit(clp(value))}
        confirm={form.confirm(clp(value))}
        // Nothing to change until the amount differs (#568).
        disabled={change === 0}
        onCancel={onCancel}
      />
    </form>
  )
}

/** A payment line's fixes, in the design's order (docs/design/billing-corrections.md, section 5). */
const PAYMENT_FIXES = ['move', 'voidPayment', 'refund'] as const

/** An adjustment line's one fix (#282). */
const REVERT_FIXES = ['revert'] as const
/** A payment moved in (#280) is a correction: moved again or refunded, never undone as a mistake. */
const MOVED_PAYMENT_FIXES = ['move', 'refund'] as const

/** What a refused "Mover pago" says (#280). */
function moveRefusal(error: Error): string {
  return copy.moveRefused[moveRefused(error) ?? 'failed']
}

/** A period a payment may move to, as the form lists it: a sibling's names them. */
function targetLabel(target: MoveTarget, personId: string): string {
  const form = copy.moveForm
  const label = form.option(
    monthName(target.period_start),
    target.plan_name,
    target.person_id === personId ? null : target.person_name,
    clp(target.outstanding_clp),
  )
  return target.pending ? form.pendingOption(label) : label
}

/** "Mover a otro mes o plan" (#280): all or part of a payment recorded on the wrong month,
 * plan or sibling, moved to a period that still owes. Neither income nor a refund, and no
 * email. A second step names where it goes from and to (#550); a payment that carried
 * credit moves only as a whole. */
function MoveForm({
  personId,
  membership,
  payment,
  ledger,
  onCancel,
  onDone,
}: {
  personId: string
  membership: Membership
  payment: RefundablePayment
  ledger: MembershipLedger
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.moveForm
  const ids = { target: useId(), amount: useId(), amountHint: useId(), reason: useId(), reasonHint: useId() }
  const offered = useQuery(moveTargetsQuery(payment.id))
  const [targetId, setTargetId] = useState<string | null>(null)
  const [amount, setAmount] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()

  const movable = offered.data?.movable_clp ?? payment.refundable_clp
  const wholeOnly = offered.data?.whole_only ?? false
  const targets = offered.data?.targets ?? []
  const target = targets.find((t) => t.billing_period_id === targetId) ?? targets.find((t) => !t.pending)
  const value = wholeOnly ? movable : Number((amount ?? String(movable)).replace(/\D/g, ''))
  const amountOk = value > 0 && value <= movable
  const reasonOk = reason.trim() !== ''
  const month = monthName(payment.period_start)
  const owed = ledger.periods.find((p) => p.id === payment.billing_period_id)?.outstanding_clp ?? 0
  // Another plan or person: this plan's balance carries it no more.
  const leaves = target !== undefined && target.membership_id !== membership.id
  const from = `${month} · ${membership.plan_name}`
  const to = target
    ? [monthName(target.period_start), target.plan_name, target.person_id === personId ? null : target.person_name]
        .filter(Boolean)
        .join(' · ')
    : ''

  const moved = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordMove({
        payment_id: payment.id,
        billing_period_id: target!.billing_period_id,
        amount_clp: value,
        reason: reason.trim(),
      }),
    onSuccess: async () => {
      onDone(form.done(clp(value), month, to))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  if (offered.isPending) return <p className="member__detail">{form.loading}</p>
  if (offered.isError) return <Banner tone="error">{form.failed}</Banner>
  // Nowhere to go: no period owing, or each with a proof waiting, reviewed first.
  if (!targets.some((t) => !t.pending)) {
    return (
      <div className={cardClass({}, 'member__form')}>
        <p className="member__detail">{targets.length === 0 ? form.none : form.allPending}</p>
        <div className="member__form-actions">
          <Button onClick={onCancel}>{form.cancel}</Button>
          {/* Where the waiting proof is reviewed, so the block is not a dead end (#568). */}
          {targets.length > 0 && (
            <Link to="/admin/pagos/comprobantes" className={buttonClass({ variant: 'primary' })}>
              {form.review}
            </Link>
          )}
        </div>
      </div>
    )
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!amountOk || !reasonOk || !target || target.pending) return refuse()
    if (step.confirming) moved.mutate()
    else step.ask()
  }

  const landing = target ? Math.max(target.outstanding_clp - value, 0) : 0
  const credit = target ? Math.max(value - target.outstanding_clp, 0) : 0

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={ids.target} className="member__label">
        {form.target}
      </label>
      <Select
        id={ids.target}
        value={target?.billing_period_id ?? ''}
        disabled={step.confirming}
        onChange={(e) => setTargetId(e.target.value)}
      >
        {targets.map((t) => (
          <option key={t.billing_period_id} value={t.billing_period_id} disabled={t.pending}>
            {targetLabel(t, personId)}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <Input
        id={ids.amount}
        inputMode="numeric"
        value={wholeOnly ? String(movable) : (amount ?? String(movable))}
        readOnly={wholeOnly || step.confirming}
        aria-describedby={cx(ids.amountHint, checked && !amountOk && `${ids.amount}-error`)}
        aria-invalid={checked && !amountOk}
        onChange={(e) => setAmount(e.target.value)}
      />
      <span id={ids.amountHint} className="member__detail">
        {wholeOnly ? form.wholeOnly(clp(movable)) : form.amountHint(clp(movable))}
      </span>
      {checked && !amountOk && (
        <Banner tone="error" id={`${ids.amount}-error`}>
          {value > movable ? form.beyond(clp(movable)) : form.amountNeeded}
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
        readOnly={step.confirming}
        aria-describedby={cx(ids.reasonHint, checked && !reasonOk && `${ids.reason}-error`)}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <span id={ids.reasonHint} className="member__detail">
        {form.reasonHint}
      </span>
      {checked && !reasonOk && (
        <Banner tone="error" id={`${ids.reason}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}

      <FixPreview
        month={month}
        owed={[owed, owed + (amountOk ? value : 0)]}
        balance={[ledger.balance_clp, ledger.balance_clp + (leaves && amountOk ? value : 0)]}
      />
      {target && amountOk && (
        <div className="member__fix-preview">
          <span className="member__detail">
            {copy.fix.owed(to, clp(target.outstanding_clp), clp(landing))}
          </span>
          {credit > 0 && <span className="member__detail">{form.credit(clp(credit))}</span>}
        </div>
      )}
      {step.confirming && <Banner tone="info">{form.notice(clp(value), from, to)}</Banner>}
      {moved.error && (
        <Banner tone="error">
          {moveRefusal(moved.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={moved.isPending}
        words={form}
        submit={form.submit(clp(value))}
        confirm={form.confirm(clp(value))}
        onCancel={onCancel}
      />
    </form>
  )
}

/** What a refused "Anular pago" says (#281). */
function paymentVoidRefusal(error: Error): string {
  return copy.voidPaymentRefused[paymentVoidRefused(error) ?? 'failed']
}

/** "Anular pago" (#281): a payment recorded by mistake (a wrong amount, the wrong member,
 * money that never arrived) is undone whole, and its period owes it again. A second step
 * says whom the notice goes to before it is sent; the reason is staff's alone. */
function VoidPaymentForm({
  personId,
  payment,
  ledger,
  onCancel,
  onDone,
}: {
  personId: string
  payment: RefundablePayment
  ledger: MembershipLedger
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.voidPaymentForm
  const id = useId()
  const hint = useId()
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
  const person = useQuery(personQuery(personId))
  const welcome = useQuery(welcomeQuery(personId))
  const reasonOk = reason.trim() !== ''
  const month = monthName(payment.period_start)
  const back = payment.refundable_clp
  const owed = ledger.periods.find((p) => p.id === payment.billing_period_id)?.outstanding_clp ?? 0
  // Whom the notice goes to: the guardian, for a dependent; nobody with no email.
  const who = welcome.data?.guardian ?? person.data?.name ?? ''
  const notice = welcome.data && !welcome.data.to ? form.noEmail(who) : form.notice(who)

  const undone = useSubmit({
    offline: 'refuse',
    mutationFn: () => recordPaymentVoid({ payment_id: payment.id, reason: reason.trim() }),
    onSuccess: async () => {
      onDone(form.done(month, clp(back)))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (!reasonOk) return refuse()
    if (step.confirming) undone.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={id} className="member__label">
        {form.reason}
      </label>
      <Input
        id={id}
        type="text"
        maxLength={500}
        value={reason}
        readOnly={step.confirming}
        aria-describedby={cx(hint, checked && !reasonOk && `${id}-error`)}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      <span id={hint} className="member__detail">
        {form.reasonHint}
      </span>
      {checked && !reasonOk && (
        <Banner tone="error" id={`${id}-error`}>
          {form.reasonNeeded}
        </Banner>
      )}
      <FixPreview month={month} owed={[owed, owed + back]} balance={[ledger.balance_clp, ledger.balance_clp + back]} />
      {step.confirming && <Banner tone="info">{notice}</Banner>}
      {undone.error && (
        <Banner tone="error">
          {paymentVoidRefusal(undone.error)}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={undone.isPending}
        words={form}
        submit={form.submit(clp(back))}
        confirm={form.confirm(clp(back))}
        variant="danger"
        onCancel={onCancel}
      />
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
  const formRef = useRef<HTMLFormElement>(null)
  const refuse = useRefusal(formRef)
  const step = useConfirmStep()
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
      return refuse()
    }
    if (step.confirming) refund.mutate()
    else step.ask()
  }

  return (
    <form ref={formRef} className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.payment} className="member__label">
        {form.payment}
      </label>
      <Select
        id={ids.payment}
        value={payment.id}
        disabled={step.confirming}
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
        readOnly={step.confirming}
        aria-invalid={amountNeeded && !value}
        aria-describedby={amountNeeded && !value ? `${ids.amount}-error` : undefined}
        onChange={(e) => setAmount(e.target.value)}
      />
      {amountNeeded && !value && (
        <Banner tone="error" id={`${ids.amount}-error`}>
          {form.amountNeeded}
        </Banner>
      )}

      <label htmlFor={ids.method} className="member__label">
        {form.method}
      </label>
      <Select
        id={ids.method}
        value={method}
        disabled={step.confirming}
        onChange={(e) => setMethod(e.target.value as Method)}
      >
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
        readOnly={step.confirming}
        onChange={(e) => setNote(e.target.value)}
      />
      <FixPreview
        month={monthName(payment.period_start)}
        owed={[owed, owed + back]}
        balance={[ledger.balance_clp, ledger.balance_clp + back]}
      />

      {step.confirming && <Banner tone="info">{form.notice(monthName(payment.period_start), clp(back))}</Banner>}
      {refund.error && (
        <Banner tone="error">
          {refusedAnonymised(refund.error)
            ? copy.anonymisedRefused
            : refund.error instanceof ApiError && refund.error.status === 409
              ? form.refused.exceeds
              : form.refused.failed}
        </Banner>
      )}

      <FixActions
        step={step}
        pending={refund.isPending}
        words={form}
        submit={form.submit(clp(value))}
        confirm={form.confirm(clp(value))}
        onCancel={onCancel}
      />
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
function Ledger({
  personId,
  membership,
  ledger,
  named = false,
  readOnly = false,
}: {
  personId: string
  membership: Membership
  ledger: MembershipLedger
  named?: boolean
  // Its lines with no fixes: an anonymous record's (#581).
  readOnly?: boolean
}) {
  const [all, setAll] = useState(false)
  const [fixing, setFixing] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const open = new Map(ledger.open_periods.map((p) => [p.id, p.paid_clp]))
  const periods = new Map(ledger.periods.map((p) => [p.id, p]))
  const refundable = new Map(ledger.refundable_payments.map((p) => [p.id, p]))
  const lines = timeline(ledger)
  const shown = all ? lines : lines.slice(0, LEDGER_SHOWN)
  const title = named ? copy.planLabel(copy.ledger.title, membership.plan_name) : copy.ledger.title
  const finish = (message: string) => {
    setFixing(null)
    setDone(message)
  }
  const cancel = () => setFixing(null)

  /** The line's fixes, if it has any: a charge's, an adjustment's "Revertir" (#282), or a
   * payment's: "Anular pago" (#281) and its refund. */
  const fixesOf = (entry: TimelineEntry): ReactElement | null => {
    if (readOnly) return null
    if (entry.kind === 'adjustment') {
      const period = entry.billing_period_id === null ? undefined : periods.get(entry.billing_period_id)
      if (!period || !revertible(entry, period, membership)) return null
      const { title } = describeEntry(entry, false)
      return (
        <Fixes title={copy.fix.adjustment(title)} fixes={REVERT_FIXES} label={(f) => copy.fix[f]}>
          {() => (
            <RevertForm
              entry={entry}
              title={title}
              period={period}
              balance={ledger.balance_clp}
              onCancel={cancel}
              onDone={finish}
            />
          )}
        </Fixes>
      )
    }
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
      <Fixes
        title={copy.fix.payment(monthName(payment.period_start))}
        fixes={entry.purpose === 'move' ? MOVED_PAYMENT_FIXES : PAYMENT_FIXES}
        label={(f) => copy.fix[f]}
      >
        {(fix) =>
          fix === 'move' ? (
            <MoveForm
              personId={personId}
              membership={membership}
              payment={payment}
              ledger={ledger}
              onCancel={cancel}
              onDone={finish}
            />
          ) : fix === 'voidPayment' ? (
            <VoidPaymentForm personId={personId} payment={payment} ledger={ledger} onCancel={cancel} onDone={finish} />
          ) : (
            <RefundForm payments={[payment]} ledger={ledger} onCancel={cancel} onDone={finish} />
          )
        }
      </Fixes>
    )
  }

  return (
    <section className="member__section" aria-label={title}>
      <SectionHeader title={title} />
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
            const period = entry.billing_period_id === null ? undefined : periods.get(entry.billing_period_id)
            return (
              <Entry
                key={entry.id}
                entry={entry}
                membershipId={membership.id}
                period={entry.kind === 'charge' ? period : undefined}
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

/** `Anuló cargo noviembre` · `$45.000 → $0` · `duplicado · Mensual · por Ana · 2 nov`;
 * a discount's `Cambió el descuento` · `50% → 30%` · `Beca · desde el cobro del 15 dic · …` (#25). */
function CorrectionLine({ correction: c }: { correction: Correction }) {
  const words = copy.corrections
  const { before, after, discount, anchor } = c
  const detail = [
    c.reason,
    discount ? words.discountFrom(shortDay(discount.starts_on)) : null,
    anchor ? words.anchorFrom(shortDay(anchor.starts_on)) : null,
    c.plan_name,
    c.actor_name ? words.by(c.actor_name) : null,
    shortDay(c.at),
  ]
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
      {discount && (
        <span className="member__entry-amount">{words.discountPct(discount.before.pct, discount.after.pct)}</span>
      )}
      {anchor && <span className="member__entry-amount">{words.anchorDays(anchor.before, anchor.after)}</span>}
      {c.due_date && (
        <span className="member__entry-amount">{words.dates(shortDay(c.due_date.before), shortDay(c.due_date.after))}</span>
      )}
    </li>
  )
}

function correctionTitle(c: Correction): string {
  const words = copy.corrections
  const month = c.period_start ? monthName(c.period_start) : ''
  switch (c.action) {
    case 'due_date_changed':
      return words.dueDate(month)
    case 'membership_reactivated':
      return words.reactivated
    case 'cancel_undone':
      return words.cancelUndone
    case 'anchor_changed':
      return words.anchorChanged
    case 'discount_changed':
      if (!c.discount?.before.pct) return words.discountSet
      return c.discount.after.pct ? words.discountChanged : words.discountRemoved
    case 'ledger_corrected':
      if (c.purpose === 'void') return (c.plan_void ? words.planVoid : words.void)(month)
      if (c.purpose === 'restore') return words.restore(month)
      if (c.purpose === 'revert') return words.revert(month)
      if (c.purpose === 'write_off') return words.writeOff(month)
      if (c.purpose === 'mistake') return words.paymentVoid(month)
      if (c.paid_through) return (c.paid_through === 'paid' ? words.paidBefore : words.gift)(month)
      if (c.purpose === 'move') {
        const other = c.other_period_start ? monthName(c.other_period_start) : ''
        return c.moved === 'in' ? words.movedIn(month, other) : words.movedOut(month, other)
      }
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
  membershipId,
  period,
  fix,
}: {
  entry: TimelineEntry
  unpaid: boolean
  paidClp: number
  // The Libro's plan: a payment moved to or from another names that one (#280).
  membershipId?: string
  // A charge's period: "vence 10 nov (antes 1 nov)" once its due date moved (#283).
  period?: LedgerPeriod
  fix?: LineFix | null
}) {
  const { title, detail, tone } = describeEntry(entry, unpaid, paidClp, membershipId, period)
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
  // A credit taken back with its payment undone (#281).
  if (entry.purpose === 'revert' && !entry.period_start) return t.common.signedClp(entry.amount_clp)
  return clp(entry.amount_clp)
}

type Tone = 'paid' | 'owed' | 'muted' | 'rejected'

/** What a ledger row says: `Pago septiembre`, `transferencia · validó Martín · 2 sep`. */
function describeEntry(
  entry: TimelineEntry,
  unpaid: boolean,
  paidClp = 0,
  membershipId?: string,
  period?: LedgerPeriod,
): { title: string; detail: string; tone: Tone } {
  const words = copy.ledger
  const month = entry.period_start ? monthName(entry.period_start) : ''
  const method = entry.method ? words.method[entry.method] : null
  const day = shortDay(entry.validated_at ?? entry.created_at)
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(' · ')
  // A payment moved (#280): the other half's month, and its plan when it is another one.
  const moved = entry.purpose === 'move' && entry.moved ? entry.moved : null
  const elsewhere =
    moved && membershipId !== undefined && moved.membership_id !== membershipId
      ? words.movedElsewhere(moved.plan_name, entry.moved!.person_name)
      : null

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
          entry.discount_pct ? words.discounted(entry.discount_pct, entry.discount_reason ?? null) : null,
          // Its due date moved by "Mover vencimiento" (#283).
          period?.due_date_was ? words.dueMoved(shortDay(period.due_date), shortDay(period.due_date_was)) : null,
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
      // Moved in from another month, plan or sibling (#280): "Movido de noviembre".
      if (moved) {
        return {
          title: `${words.payment(month)} · ${words.movedFrom(monthName(moved.period_start))}`,
          detail: join(elsewhere, entry.note, review, day),
          tone,
        }
      }
      // A month paid before Rakin (#286): it settles the period, and is no income of the month.
      if (entry.purpose === 'paid_before') {
        return { title: `${words.payment(month)} · ${words.paidBefore}`, detail: join(method, review, day), tone }
      }
      return { title: words.payment(month), detail: join(method, review, day), tone }
    }
    case 'adjustment': {
      if (entry.voids || entry.purpose === 'restore') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        const title = entry.voids ? words.void(month) : words.restore(month)
        return { title, detail: join(entry.note, by, day), tone: 'muted' }
      }
      // The credit a payment undone by mistake carried, taken back with it (#281).
      if (entry.purpose === 'revert' && !entry.period_start) {
        return { title: words.creditReverted, detail: join(entry.note, day), tone: 'muted' }
      }
      // An adjustment reverted (#282): the revert, and the adjustment it undid, saying so.
      if (entry.purpose === 'revert') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        return { title: words.revert(month), detail: join(entry.note, by, day), tone: 'muted' }
      }
      const reverted = entry.reverted
        ? words.reverted(entry.reverted.reason, entry.reverted.by_name, shortDay(entry.reverted.at))
        : null
      // A debt forgiven (#282): no longer owed, still expected.
      if (entry.purpose === 'write_off') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        return { title: words.writeOff(month), detail: join(entry.note, by, day, reverted), tone: 'muted' }
      }
      return {
        title: entry.period_start ? words.adjustment(entry.amount_clp > 0, month) : words.credit,
        detail: join(entry.note, day, reverted),
        tone:
          entry.status === 'rejected' ? 'rejected' : entry.amount_clp < 0 && !entry.reverted ? 'owed' : 'muted',
      }
    }
    case 'refund':
      // A payment undone as recorded by mistake (#281): no money left, unlike a refund.
      if (entry.purpose === 'mistake') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        return { title: words.paymentVoid(month), detail: join(words.mistake, entry.note, by, day), tone: 'muted' }
      }
      // Moved out to another month, plan or sibling (#280): no money left. "Movido a diciembre".
      if (entry.purpose === 'move') {
        const by = entry.validated_by_name && words.validatedBy(entry.validated_by_name)
        const title = moved ? words.movedTo(monthName(moved.period_start)) : words.movedTo('')
        return { title: `${words.payment(month)} · ${title}`, detail: join(elsewhere, entry.note, by, day), tone: 'muted' }
      }
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
