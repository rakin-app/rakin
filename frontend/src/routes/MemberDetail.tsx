import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { personAttendanceQuery } from '../api/attendance'
import { familyQuery } from '../api/family'
import { ApiError } from '../api/client'
import {
  awardGrade,
  goalProgress,
  gradesQuery,
  gradingSchemeQuery,
  rankLabel,
  type GradeEvent,
  type Grading,
  type GradingScheme,
  type Rank,
} from '../api/grading'
import {
  editFreeze,
  endFreeze,
  freezeMembership,
  membershipLedgerQuery,
  membershipsQuery,
  personQuery,
  recordAdjustment,
  recordPayment,
  recordRefund,
  shownMembership,
  type Freeze,
  type FreezeLine,
  type LedgerPeriod,
  type Membership,
  type MembershipLedger,
  type Method,
  type OpenPeriod,
  type Person,
  type RecordedAdjustment,
  type RecordedPayment,
  type RecordedRefund,
  type RefundablePayment,
  type TimelineEntry,
} from '../api/member'
import { myRoleQuery, readsLedger } from '../api/me'
import { useGymToday } from '../api/sessions'
import { RankBelt } from '../components/Belt'
import { Button, buttonClass } from '../components/Button'
import { Input, Select } from '../components/Field'
import { ChevronLeftIcon, WhatsAppIcon } from '../components/icons'
import { Grid, PageContainer } from '../components/Layout'
import { MemberMatTime } from '../components/MatTime'
import { StatusPill } from '../components/StatusPill'
import { isoDay, monthName, monthYear, shortDay } from '../format'
import { t } from '../i18n/es'
import { FamilyPanel } from './FamilyPanel'
import { PersonActions } from './PersonActions'
import { PersonData } from './PersonData'
import './MemberDetail.css'

const copy = t.admin.member
const clp = t.common.clp

const route = getRouteApi('/admin/alumnos/$personId')

/**
 * "Ficha de alumno": who the member is and their rank, the plan they are on and how it
 * stands, their graduación and family, and, for whoever reads the ledger, what they
 * owe, their ledger with its freezes, "Registrar pago", "Congelar" (#26), "Ajuste"
 * and "Devolver" (#38).
 * A coach sees the member, their plan and rank, whether it is frozen, and promotes
 * them; never money.
 *
 * Their attendance, in the last 30 days and in all, and in Graduación the classes since
 * their last promotion; their time on the mat by block kind (#141).
 *
 * Below them, "Datos": their record and the gym's custom fields the signed-in role may
 * see (#20), edited together; then "Dar de baja" or "Reactivar", and "Eliminar" (#157).
 * On a desktop, the money and its ledger on the left and the rest on the right (#179).
 */
export function MemberDetail() {
  const { personId } = route.useParams()
  const person = useQuery(personQuery(personId))
  const memberships = useQuery(membershipsQuery(personId))
  const grades = useQuery(gradesQuery(personId))
  const role = useQuery(myRoleQuery())

  if (person.isPending || memberships.isPending) {
    return (
      <Shell>
        <p className="member__note">{copy.loading}</p>
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
  // Latest first, so the last is the earliest: a member since their first plan here.
  const since = monthYear(memberships.data.at(-1)?.started_on ?? person.data.created_at)
  const rank = grades.data?.current

  return (
    <Shell
      title={person.data.name}
      subtitle={rank ? copy.rankSince(rankLabel(rank), since) : copy.since(since)}
      action={<WhatsAppButton person={person.data} />}
    >
      {person.data.left_on && (
        <p className="member__error" role="status">
          {copy.leftBanner(t.common.day(person.data.left_on))}
        </p>
      )}
      {/* On a desktop the money on the left, everything else beside it. */}
      <Grid className="member__columns">
        <div className="member__column">
          {membership ? (
            <Standing membership={membership} money={readsLedger(role.data)} />
          ) : (
            <p className="member__note">{copy.noPlan}</p>
          )}
        </div>
        <div className="member__column">
          <Attendance personId={personId} />
          <MemberMatTime personId={personId} />
          <Graduation personId={personId} canAward={membership !== undefined && membership.status !== 'cancelled'} />
          <section className="member__section" aria-label={t.admin.family.toggle}>
            <h2 className="member__section-title">{t.admin.family.toggle}</h2>
            <FamilyPanel person={person.data} />
          </section>
          <PersonData person={person.data} />
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
        <Link to="/admin/alumnos" className={buttonClass({ icon: true })} aria-label={copy.back}>
          <ChevronLeftIcon />
        </Link>
        {title && (
          <div className="member__heading">
            <h1 className="member__title">{title}</h1>
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

/** The plan and how it stands; with `money`, what is owed, the actions and the ledger. */
function Standing({ membership, money }: { membership: Membership; money: boolean }) {
  const ledger = useQuery({ ...membershipLedgerQuery(membership.id), enabled: money })
  const data = money ? ledger.data : undefined

  return (
    <>
      <section className="member__card" aria-label={copy.paymentLabel}>
        <div className="member__card-head">
          <span className="member__eyebrow">{planLine(membership)}</span>
          <Badge membership={membership} ledger={data} />
        </div>
        {membership.freeze && !membership.freeze.started && (
          <p className="member__detail">
            {copy.freezeBooked(shortDay(membership.freeze.from_date), shortDay(membership.freeze.to_date))}
          </p>
        )}
        {data && <Owed ledger={data} />}
        {money && ledger.isError && (
          <p className="member__error" role="alert">
            {copy.ledgerError}
          </p>
        )}
        {data && <Actions membership={membership} ledger={data} />}
      </section>
      {data && <Ledger ledger={data} />}
    </>
  )
}

function planLine(membership: Membership): string {
  if (membership.anchor_day !== null) return copy.dueDay(membership.plan_name, membership.anchor_day)
  if (membership.current_period_end) return copy.until(membership.plan_name, t.common.day(membership.current_period_end))
  return membership.plan_name
}

/** `Congelado · vuelve el 24 nov` while frozen; `Vencido 9 d` while the oldest open period
 * is past due; else the membership's status. A freeze booked ahead is a line of its own. */
function Badge({ membership, ledger }: { membership: Membership; ledger: MembershipLedger | undefined }) {
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
  }
  return (
    <div className="member__owed">
      <span className="member__amount">{clp(amount)}</span>
      <span className="member__detail">{detail}</span>
    </div>
  )
}

type Open = 'payment' | 'adjustment' | 'refund' | 'freeze' | 'editFreeze' | 'endFreeze' | null

/** The periods that still owe, oldest first, then the paid ones, newest first: an
 * adjustment in the member's favour goes to the first, one owed to either. */
function adjustable(ledger: MembershipLedger): LedgerPeriod[] {
  const owing = ledger.periods.filter((p) => p.outstanding_clp > 0).reverse()
  return [...owing, ...ledger.periods.filter((p) => p.outstanding_clp === 0)]
}

function Actions({ membership, ledger }: { membership: Membership; ledger: MembershipLedger }) {
  const periods = ledger.open_periods
  const known = adjustable(ledger)
  const payments = ledger.refundable_payments
  const freeze = membership.freeze
  const [open, setOpen] = useState<Open>(null)
  const [done, setDone] = useState<string | null>(null)
  const toggle = (form: Open) => {
    setDone(null)
    setOpen(open === form ? null : form)
  }
  const finish = (message: string) => {
    setOpen(null)
    setDone(message)
  }
  return (
    <>
      {/* "Registrar pago" on a line of its own: the others fit beside each other at 390px only without it. */}
      <Button variant="primary" fullWidth aria-expanded={open === 'payment'} onClick={() => toggle('payment')}>
        {copy.record}
      </Button>
      {/* What cannot be done here is not offered, rather than greyed out with no reason. */}
      {(known.length > 0 || payments.length > 0 || (!freeze && membership.status === 'active')) && (
        <div className="member__actions">
          {known.length > 0 && (
            <Button aria-expanded={open === 'adjustment'} onClick={() => toggle('adjustment')}>
              {copy.adjust}
            </Button>
          )}
          {payments.length > 0 && (
            <Button aria-expanded={open === 'refund'} onClick={() => toggle('refund')}>
              {copy.refund}
            </Button>
          )}
          {!freeze && membership.status === 'active' && (
            <Button aria-expanded={open === 'freeze'} onClick={() => toggle('freeze')}>
              {copy.freeze}
            </Button>
          )}
        </div>
      )}
      {/* Two long labels: side by side where they fit whole, else one under the other. */}
      {freeze && (
        <div className="member__actions member__actions--wrap">
          <Button aria-expanded={open === 'editFreeze'} onClick={() => toggle('editFreeze')}>
            {copy.editFreeze}
          </Button>
          <Button aria-expanded={open === 'endFreeze'} onClick={() => toggle('endFreeze')}>
            {freeze.started ? copy.endFreeze : copy.callOffFreeze}
          </Button>
        </div>
      )}
      {done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )}
      {open === 'payment' &&
        (periods.length > 0 ? (
          <PaymentForm membership={membership} periods={periods} onCancel={() => setOpen(null)} onDone={finish} />
        ) : (
          // Al día, with no period open yet: a payment needs one to go to.
          <p className="member__note" role="status">
            {copy.nothingToRecord}
          </p>
        ))}
      {open === 'adjustment' && known.length > 0 && (
        <AdjustmentForm membership={membership} periods={known} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'refund' && payments.length > 0 && (
        <RefundForm payments={payments} onCancel={() => setOpen(null)} onDone={finish} />
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
    </>
  )
}

// The day `days` after `day`, both as `2026-11-10`.
function addDays(day: string, days: number): string {
  const next = new Date(`${day}T00:00:00Z`)
  next.setUTCDate(next.getUTCDate() + days)
  return next.toISOString().slice(0, 10)
}

/** A change to a freeze: the membership and its ledger are read again after it. */
function useFreezeChange(mutationFn: () => Promise<Membership>, onSuccess: (membership: Membership) => void) {
  const queryClient = useQueryClient()
  return useMutation({
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
  const ids = { from: useId(), until: useId(), hint: useId(), reason: useId() }
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
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
        <p className="member__error" role="alert">
          {form.fromNeeded}
        </p>
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
        <p className="member__error" role="alert">
          {form.untilNeeded}
        </p>
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
        <p className="member__error" role="alert">
          {form.reasonNeeded}
        </p>
      )}

      {freeze.error && (
        <p className="member__error" role="alert">
          {freeze.error instanceof ApiError && freeze.error.status === 409 ? form.refused.notActive : form.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={freeze.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={freeze.isPending}>
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
  const ids = { until: useId(), hint: useId(), reason: useId() }
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
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
        <p className="member__error" role="alert">
          {form.untilNeeded}
        </p>
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
        <p className="member__error" role="alert">
          {form.reasonNeeded}
        </p>
      )}

      {edit.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={edit.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={edit.isPending}>
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">
        {freeze.started ? form.endHint : form.callOffHint(shortDay(freeze.from_date), shortDay(freeze.to_date))}
      </p>

      {end.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={end.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={end.isPending}>
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
  onDone: (message: string) => void
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

  const record = useMutation({
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
      onDone(form.recorded(clp(value)) + credit + rest)
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
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
        <p className="member__error" role="alert">
          {form.amountNeeded}
        </p>
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
        <p className="member__error" role="alert">
          {record.error instanceof ApiError && record.error.status === 409 ? form.refused.paid : form.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={record.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={record.isPending}>
          {record.isPending ? form.working : form.submit(clp(value))}
        </Button>
      </div>
    </form>
  )
}

/** "Asistencia": classes in the last 30 days, and in all. */
function Attendance({ personId }: { personId: string }) {
  const words = copy.attendance
  const attendance = useQuery(personAttendanceQuery(personId))
  if (attendance.isPending) return null
  if (attendance.isError) {
    return (
      <p className="member__error" role="alert">
        {words.error}
      </p>
    )
  }
  const { last_30_days: recent, total } = attendance.data
  return (
    <section className="member__card" aria-label={words.title}>
      <span className="member__eyebrow">{words.title}</span>
      <div className="member__rank">
        <span className="member__rank-label">{recent}</span>
        <span className="member__detail">{words.detail(recent, total)}</span>
      </div>
    </section>
  )
}

/**
 * The member's rank, "Registrar graduación" and the promotion log. Hidden in a gym with
 * no ranks, unless the member has promotions from when it had them.
 */
function Graduation({ personId, canAward }: { personId: string; canAward: boolean }) {
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
      <p className="member__error" role="alert">
        {words.error}
      </p>
    )
  }
  const { current, events } = grades.data
  if (!ranked && events.length === 0) return null

  return (
    <section className="member__section" aria-label={words.title}>
      <h2 className="member__section-title">{words.title}</h2>
      <div className="member__card">
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
              <p className="member__done" role="status">
                {done}
              </p>
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
      </div>
      {events.length > 0 && (
        <ul className="member__ledger" aria-label={words.log}>
          {events.map((event) => (
            <GradeRow key={event.id} event={event} />
          ))}
        </ul>
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

/** The rank and sub-rank the form starts on: the current rank's next sub-rank, else the
 * next rank, else the first. */
function nextRank(scheme: GradingScheme, current: Rank | null | undefined): { rank: string; sub: string | null } {
  const all = [...scheme.ranks, ...scheme.kids_ladder]
  const at = current ? all.findIndex((r) => r.key === current.rank_key) : -1
  const here = all[at]
  if (here && current) {
    const sub = here.sub_ranks.findIndex((s) => s.key === current.sub_rank)
    const following = here.sub_ranks[sub + 1]
    if (sub >= 0 && following) return { rank: here.key, sub: following.key }
  }
  const ladder = here && scheme.kids_ladder.includes(here) ? scheme.kids_ladder : scheme.ranks
  const rank = (here && ladder[ladder.indexOf(here) + 1]) ?? here ?? all[0]!
  return { rank: rank.key, sub: rank.sub_ranks[0]?.key ?? null }
}

function GradeForm({
  personId,
  scheme,
  current,
  onCancel,
  onDone,
}: {
  personId: string
  scheme: GradingScheme
  current: Rank | null
  onCancel: () => void
  onDone: (grading: Grading) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.grading.form
  const ids = { rank: useId(), sub: useId(), date: useId(), note: useId() }
  const start = nextRank(scheme, current)
  const [rankKey, setRankKey] = useState(start.rank)
  const [subRank, setSubRank] = useState<string | null>(start.sub)
  // Today in the gym's timezone, which the API refuses a later day than, until a day is picked.
  const today = useGymToday()
  const [picked, setAwardedOn] = useState<string | null>(null)
  const awardedOn = picked ?? today
  const [note, setNote] = useState('')
  const rank = [...scheme.ranks, ...scheme.kids_ladder].find((r) => r.key === rankKey)

  const award = useMutation({
    mutationFn: () =>
      awardGrade(personId, {
        rank_key: rankKey,
        sub_rank: subRank,
        awarded_on: awardedOn,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: async (grading) => {
      onDone(grading)
      // A new rank restarts the count of classes since it.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['grades', personId] }),
        queryClient.invalidateQueries({ queryKey: personAttendanceQuery(personId).queryKey }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    award.mutate()
  }

  return (
    <form className="member__form member__form--inset" aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.rank} className="member__label">
        {form.rank}
      </label>
      <Select
        id={ids.rank}
        value={rankKey}
        onChange={(e) => {
          setRankKey(e.target.value)
          const chosen = [...scheme.ranks, ...scheme.kids_ladder].find((r) => r.key === e.target.value)
          setSubRank(chosen?.sub_ranks[0]?.key ?? null)
        }}
      >
        {scheme.kids_ladder.length > 0 ? (
          <>
            <optgroup label={form.ranks}>
              <RankOptions ranks={scheme.ranks} />
            </optgroup>
            <optgroup label={form.kids}>
              <RankOptions ranks={scheme.kids_ladder} />
            </optgroup>
          </>
        ) : (
          <RankOptions ranks={scheme.ranks} />
        )}
      </Select>

      {rank && rank.sub_ranks.length > 0 && (
        <>
          <label htmlFor={ids.sub} className="member__label">
            {form.subRank}
          </label>
          <Select id={ids.sub} value={subRank ?? ''} onChange={(e) => setSubRank(e.target.value)}>
            {rank.sub_ranks.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
        </>
      )}

      <label htmlFor={ids.date} className="member__label">
        {form.date}
      </label>
      <Input
        id={ids.date}
        type="date"
        required
        max={today}
        value={awardedOn}
        onChange={(e) => setAwardedOn(e.target.value)}
      />

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

      {award.error && (
        <p className="member__error" role="alert">
          {refusal(award.error)}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={award.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={award.isPending}>
          {award.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

function RankOptions({ ranks }: { ranks: GradingScheme['ranks'] }) {
  return ranks.map((r) => (
    <option key={r.key} value={r.key}>
      {r.label}
    </option>
  ))
}

/** What the API's refusal `code` means to the admin; anything else is a plain failure. */
function refusal(error: Error): string {
  const refused = copy.grading.form.refused
  const code =
    error instanceof ApiError && typeof error.body === 'object' && error.body !== null
      ? (error.body as { detail?: { code?: unknown } }).detail?.code
      : undefined
  return typeof code === 'string' && code in refused ? refused[code as keyof typeof refused] : refused.failed
}

type Direction = 'favor' | 'owed'
const DIRECTIONS: readonly Direction[] = ['favor', 'owed']

function AdjustmentForm({
  membership,
  periods,
  onCancel,
  onDone,
}: {
  membership: Membership
  periods: LedgerPeriod[]
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.adjustForm
  const ids = { direction: useId(), period: useId(), amount: useId(), note: useId() }
  const owing = periods.filter((p) => p.outstanding_clp > 0)
  const [direction, setDirection] = useState<Direction>(owing.length > 0 ? 'favor' : 'owed')
  // In the member's favour, only a period that still owes: no more than that settles.
  const choices = direction === 'favor' ? owing : periods
  const [periodId, setPeriodId] = useState(choices[0]?.id ?? '')
  const period = choices.find((p) => p.id === periodId) ?? choices[0]
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [checked, setChecked] = useState(false)
  const value = Number(amount.replace(/\D/g, ''))
  const signed = direction === 'favor' ? value : -value
  const noteOk = note.trim() !== ''

  const adjust = useMutation({
    mutationFn: () =>
      recordAdjustment({
        membership_id: membership.id,
        billing_period_id: period!.id,
        amount_clp: signed,
        note: note.trim(),
      }),
    onSuccess: async (result: RecordedAdjustment) => {
      const rest = result.period.closed ? '' : copy.form.remainder(clp(result.period.outstanding_clp))
      onDone(form.done(t.common.signedClp(signed)) + rest)
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (value && noteOk && period) adjust.mutate()
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.direction} className="member__label">
        {form.direction}
      </label>
      <Select
        id={ids.direction}
        value={direction}
        onChange={(e) => setDirection(e.target.value as Direction)}
      >
        {DIRECTIONS.map((d) => (
          <option key={d} value={d} disabled={d === 'favor' && owing.length === 0}>
            {form.directions[d]}
          </option>
        ))}
      </Select>

      <label htmlFor={ids.period} className="member__label">
        {form.period}
      </label>
      <Select id={ids.period} value={period?.id ?? ''} onChange={(e) => setPeriodId(e.target.value)}>
        {choices.map((p) => (
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
        aria-invalid={checked && !value}
        onChange={(e) => setAmount(e.target.value)}
      />
      {checked && !value && (
        <p className="member__error" role="alert">
          {form.amountNeeded}
        </p>
      )}

      <label htmlFor={ids.note} className="member__label">
        {form.note}
      </label>
      <Input
        id={ids.note}
        type="text"
        maxLength={500}
        value={note}
        aria-invalid={checked && !noteOk}
        onChange={(e) => setNote(e.target.value)}
      />
      {checked && !noteOk && (
        <p className="member__error" role="alert">
          {form.noteNeeded}
        </p>
      )}

      {adjust.error && (
        <p className="member__error" role="alert">
          {adjust.error instanceof ApiError && adjust.error.status === 409 ? form.refused.exceeds : form.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={adjust.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={adjust.isPending}>
          {adjust.isPending ? form.working : form.submit(t.common.signedClp(signed))}
        </Button>
      </div>
    </form>
  )
}

function RefundForm({
  payments,
  onCancel,
  onDone,
}: {
  payments: RefundablePayment[]
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

  const refund = useMutation({
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
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
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
        <p className="member__error" role="alert">
          {form.amountNeeded}
        </p>
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

      {refund.error && (
        <p className="member__error" role="alert">
          {refund.error instanceof ApiError && refund.error.status === 409 ? form.refused.exceeds : form.refused.failed}
        </p>
      )}

      <div className="member__form-actions">
        <Button disabled={refund.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={refund.isPending}>
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

function Ledger({ ledger }: { ledger: MembershipLedger }) {
  const [all, setAll] = useState(false)
  const open = new Set(ledger.open_periods.map((p) => p.id))
  const lines = timeline(ledger)
  const shown = all ? lines : lines.slice(0, LEDGER_SHOWN)
  return (
    <section className="member__section" aria-label={copy.ledger.title}>
      <h2 className="member__section-title">{copy.ledger.title}</h2>
      {lines.length === 0 ? (
        <p className="member__note">{copy.ledger.empty}</p>
      ) : (
        <ul className="member__ledger">
          {shown.map((line) =>
            line.kind === 'entry' ? (
              <Entry
                key={line.entry.id}
                entry={line.entry}
                unpaid={line.entry.billing_period_id !== null && open.has(line.entry.billing_period_id)}
              />
            ) : (
              <FreezeEntry key={`${line.line.freeze_id}-${line.line.edge}`} line={line.line} />
            ),
          )}
        </ul>
      )}
      {lines.length > LEDGER_SHOWN && (
        <Button variant="ghost" className="member__more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? copy.ledger.fewer : copy.ledger.all(lines.length)}
        </Button>
      )}
    </section>
  )
}

/** `Congelación` · `Lesión · vuelve el 24 nov · 10 nov`, with no amount. */
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

function Entry({ entry, unpaid }: { entry: TimelineEntry; unpaid: boolean }) {
  const { title, detail, tone } = describeEntry(entry, unpaid)
  return (
    <li className={`member__entry member__entry--${tone}`}>
      <span className="member__dot" aria-hidden="true" />
      <div className="member__entry-text">
        <span className="member__entry-title">{title}</span>
        <span className="member__detail">{detail}</span>
      </div>
      <span className="member__entry-amount">{entryAmount(entry)}</span>
    </li>
  )
}

/** An adjustment with its sign, `+$5.000` or `−$5.000`; a refund, money out, `−$10.000`. */
function entryAmount(entry: TimelineEntry): string {
  if (entry.kind === 'adjustment') return t.common.signedClp(entry.amount_clp)
  if (entry.kind === 'refund') return t.common.signedClp(-entry.amount_clp)
  return clp(entry.amount_clp)
}

type Tone = 'paid' | 'owed' | 'muted' | 'rejected'

/** What a ledger row says: `Pago septiembre`, `transferencia · validó Martín · 2 sep`. */
function describeEntry(entry: TimelineEntry, unpaid: boolean): { title: string; detail: string; tone: Tone } {
  const words = copy.ledger
  const month = entry.period_start ? monthName(entry.period_start) : ''
  const method = entry.method ? words.method[entry.method] : null
  const day = shortDay(entry.validated_at ?? entry.created_at)
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(' · ')

  switch (entry.kind) {
    case 'charge':
      return {
        title: words.charge(month),
        detail: join(words.generated(shortDay(entry.created_at)), unpaid ? words.unpaid : null),
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
      return {
        title: entry.period_start ? words.adjustment(month) : words.credit,
        detail: join(entry.note, day),
        tone: entry.status === 'rejected' ? 'rejected' : entry.amount_clp < 0 ? 'owed' : 'muted',
      }
    case 'refund':
      return { title: words.refund(month), detail: join(method, entry.note, day), tone: 'muted' }
  }
}
