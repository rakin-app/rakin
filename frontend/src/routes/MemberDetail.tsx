import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import {
  freezeMembership,
  membershipLedgerQuery,
  membershipsQuery,
  personQuery,
  recordPayment,
  shownMembership,
  type FreezeLine,
  type Membership,
  type MembershipLedger,
  type Method,
  type OpenPeriod,
  type RecordedPayment,
  type TimelineEntry,
} from '../api/member'
import { myRoleQuery, readsLedger } from '../api/me'
import { ChevronLeftIcon } from '../components/icons'
import { isoDay, monthName, monthYear, shortDay } from '../format'
import { t } from '../i18n/es'
import { FamilyPanel } from './FamilyPanel'
import './MemberDetail.css'

const copy = t.admin.member
const clp = t.common.clp

const route = getRouteApi('/admin/alumnos/$personId')

/**
 * "Ficha de alumno": who the member is, the plan they are on and how it stands, their
 * family, and, for whoever reads the ledger, what they owe, their ledger with its
 * freezes, "Registrar pago" and "Congelar" (#26).
 * A coach sees the member and their plan, and whether it is frozen, never money.
 *
 * Rank, Ajuste, attendance, grading and custom fields join this screen with their
 * own tickets (#48, #38, #44, #20).
 */
export function MemberDetail() {
  const { personId } = route.useParams()
  const person = useQuery(personQuery(personId))
  const memberships = useQuery(membershipsQuery(personId))
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
            <button
              type="button"
              className="member__button"
              onClick={() => {
                void person.refetch()
                void memberships.refetch()
              }}
            >
              {copy.retry}
            </button>
          )}
        </div>
      </Shell>
    )
  }

  const membership = shownMembership(memberships.data)
  // Latest first, so the last is the earliest: a member since their first plan here.
  const since = memberships.data.at(-1)?.started_on ?? person.data.created_at

  return (
    <Shell title={person.data.name} subtitle={copy.since(monthYear(since))}>
      {membership ? (
        <Standing membership={membership} money={readsLedger(role.data)} />
      ) : (
        <p className="member__note">{copy.noPlan}</p>
      )}
      <section className="member__section" aria-label={t.admin.family.toggle}>
        <h2 className="member__section-title">{t.admin.family.toggle}</h2>
        <FamilyPanel person={person.data} />
      </section>
    </Shell>
  )
}

function Shell({ title, subtitle, children }: { title?: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="member">
      <header className="member__header">
        <Link to="/admin/alumnos" className="member__icon-button" aria-label={copy.back}>
          <ChevronLeftIcon />
        </Link>
        {title && (
          <div className="member__heading">
            <h1 className="member__title">{title}</h1>
            {subtitle && <span className="member__subtitle">{subtitle}</span>}
          </div>
        )}
      </header>
      <div className="member__body">{children}</div>
    </div>
  )
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
        {data && <Owed ledger={data} />}
        {money && ledger.isError && (
          <p className="member__error" role="alert">
            {copy.ledgerError}
          </p>
        )}
        {data && <Actions membership={membership} periods={data.open_periods} />}
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
 * is past due; else the membership's status. */
function Badge({ membership, ledger }: { membership: Membership; ledger: MembershipLedger | undefined }) {
  if (membership.freeze) {
    return (
      <span className="member__badge member__badge--frozen">{copy.frozenUntil(shortDay(membership.freeze.to_date))}</span>
    )
  }
  const late = ledger?.open_periods[0]?.days_overdue ?? 0
  if (late > 0) return <span className="member__badge member__badge--lapsed">{copy.overdue(late)}</span>
  return (
    <span className={`member__badge member__badge--${membership.status}`}>
      {t.admin.students.status[membership.status]}
    </span>
  )
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
    detail = copy.nextDue(shortDay(next.due_date))
  }
  return (
    <div className="member__owed">
      <span className="member__amount">{clp(amount)}</span>
      <span className="member__detail">{detail}</span>
    </div>
  )
}

type Open = 'payment' | 'freeze' | null

function Actions({ membership, periods }: { membership: Membership; periods: OpenPeriod[] }) {
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
      <div className="member__actions">
        <button
          type="button"
          className="member__button member__button--primary"
          aria-expanded={open === 'payment'}
          disabled={periods.length === 0}
          onClick={() => toggle('payment')}
        >
          {copy.record}
        </button>
        <button
          type="button"
          className="member__button"
          aria-expanded={open === 'freeze'}
          disabled={membership.status !== 'active'}
          onClick={() => toggle('freeze')}
        >
          {copy.freeze}
        </button>
      </div>
      {done && (
        <p className="member__done" role="status">
          {done}
        </p>
      )}
      {open === 'payment' && periods.length > 0 && (
        <PaymentForm membership={membership} periods={periods} onCancel={() => setOpen(null)} onDone={finish} />
      )}
      {open === 'freeze' && membership.status === 'active' && (
        <FreezeForm membership={membership} onCancel={() => setOpen(null)} onDone={finish} />
      )}
    </>
  )
}

// Tomorrow, the first day a freeze from today can end on: `2026-11-10`.
function tomorrow(): string {
  const day = new Date()
  day.setDate(day.getDate() + 1)
  return isoDay(day.toISOString())
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
  const queryClient = useQueryClient()
  const form = copy.freezeForm
  const ids = { until: useId(), hint: useId(), reason: useId() }
  const first = tomorrow()
  const [until, setUntil] = useState('')
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const untilOk = until >= first
  const reasonOk = reason.trim() !== ''

  const freeze = useMutation({
    mutationFn: () => freezeMembership(membership.id, { to_date: until, reason: reason.trim() }),
    onSuccess: async (frozen: Membership) => {
      onDone(form.done(shortDay(frozen.freeze?.to_date ?? until)))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['memberships'] }),
        queryClient.invalidateQueries({ queryKey: ['ledger'] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (untilOk && reasonOk) freeze.mutate()
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit}>
      <label htmlFor={ids.until} className="member__label">
        {form.until}
      </label>
      <input
        id={ids.until}
        className="member__input"
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
      <input
        id={ids.reason}
        className="member__input"
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
        <button type="button" className="member__button" disabled={freeze.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button type="submit" className="member__button member__button--primary" disabled={freeze.isPending}>
          {freeze.isPending ? form.working : form.submit}
        </button>
      </div>
    </form>
  )
}

const METHODS: readonly Method[] = ['cash', 'transfer', 'other']

function PaymentForm({
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
      onDone(form.recorded(clp(value)) + credit)
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
      <select
        id={ids.period}
        className="member__input"
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
      </select>

      <label htmlFor={ids.amount} className="member__label">
        {form.amount}
      </label>
      <input
        id={ids.amount}
        className="member__input"
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
      <select id={ids.method} className="member__input" value={method} onChange={(e) => setMethod(e.target.value as Method)}>
        {METHODS.map((m) => (
          <option key={m} value={m}>
            {form.methods[m]}
          </option>
        ))}
      </select>

      <label htmlFor={ids.note} className="member__label">
        {form.note}
      </label>
      <input
        id={ids.note}
        className="member__input"
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
        <button type="button" className="member__button" disabled={record.isPending} onClick={onCancel}>
          {form.cancel}
        </button>
        <button type="submit" className="member__button member__button--primary" disabled={record.isPending}>
          {record.isPending ? form.working : form.submit(clp(value))}
        </button>
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

function Ledger({ ledger }: { ledger: MembershipLedger }) {
  const open = new Set(ledger.open_periods.map((p) => p.id))
  const lines = timeline(ledger)
  return (
    <section className="member__section" aria-label={copy.ledger.title}>
      <h2 className="member__section-title">{copy.ledger.title}</h2>
      {lines.length === 0 ? (
        <p className="member__note">{copy.ledger.empty}</p>
      ) : (
        <ul className="member__ledger">
          {lines.map((line) =>
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
      <span className="member__entry-amount">{clp(entry.amount_clp)}</span>
    </li>
  )
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
        tone: entry.status === 'rejected' ? 'rejected' : 'muted',
      }
    case 'refund':
      return { title: words.refund, detail: join(entry.note, day), tone: 'muted' }
  }
}
