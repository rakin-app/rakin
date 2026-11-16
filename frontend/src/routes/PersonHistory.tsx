import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from '@tanstack/react-router'
import { useId, useMemo, useState, type FormEvent } from 'react'
import {
  addHistoryPayments,
  coversPlan,
  historyPaymentsQuery,
  outsideHistory,
  removeHistoryPayment,
  type HistoryMethod,
  type HistoryPayment,
  type HistoryPaymentIn,
  type HistoryPayments,
} from '../api/history'
import type { Person } from '../api/member'
import { setHistory } from '../api/people'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input, Select, Textarea } from '../components/Field'
import { ChevronRightIcon, CloseIcon } from '../components/icons'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import './PersonHistory.css'

const copy = t.admin.member.history

// How far back a day of someone's history may go (backend `HISTORY_WINDOW_YEARS`): a
// typo guard. "Alumno desde", and the day they left (#294).
export const HISTORY_WINDOW_YEARS = 60
// Backend `MAX_PRIOR_CLASSES`.
const MAX_PRIOR_CLASSES = 20_000

type Open = 'menu' | 'start' | 'payments' | null

/**
 * "Historial" (#293): what the gym knew of the member before Rakin, beside billing and
 * never in it. The day they first trained here and their classes before Rakin ("Fecha
 * de inicio y clases"), then what they paid by year, newest first, each year opening to
 * its payments (#295, "Pagos anteriores"); grades of a later ticket join this card
 * (docs/design/historical-data.md, section 4). Owner and admin only: the ficha draws it
 * with the Libro. Just after "Agregar exalumno" its choices are open, offered (#294).
 */
export function PersonHistory({ person }: { person: Person }) {
  const offered = useLocation({ select: (location) => location.state.offerHistory === true })
  const [open, setOpen] = useState<Open>(offered ? 'menu' : null)
  const [done, setDone] = useState<string | null>(null)
  // Shared with `HistoryYears`: "Nada anterior" only once it is known there are no payments.
  const payments = useQuery(historyPaymentsQuery(person.id))
  const noPayments = payments.isSuccess && payments.data.years.length === 0
  const lines = [
    person.member_since ? copy.memberSince(t.common.dayYear(person.member_since)) : null,
    person.prior_classes > 0 ? copy.priorClasses(person.prior_classes) : null,
  ].filter((line): line is string => line !== null)

  return (
    <section className="member__section" aria-labelledby="member-history">
      <h2 id="member-history" className="member__section-title">
        {copy.title}
      </h2>
      <div className="member__card member__history">
        {lines.length > 0 ? (
          lines.map((line) => (
            <span key={line} className="member__detail">
              {line}
            </span>
          ))
        ) : (
          noPayments && <span className="member__detail">{copy.empty}</span>
        )}
        <HistoryYears personId={person.id} onRemoved={() => setDone(copy.remove.done)} />
        {done && (
          <p className="member__done" role="status">
            {done}
          </p>
        )}
        {open === 'start' ? (
          <StartForm
            person={person}
            onCancel={() => setOpen(null)}
            onDone={() => {
              setOpen(null)
              setDone(copy.saved)
            }}
          />
        ) : open === 'payments' ? (
          <PaymentsForm
            personId={person.id}
            onCancel={() => setOpen(null)}
            onDone={(count) => {
              setOpen(null)
              setDone(copy.paymentsForm.saved(count))
            }}
          />
        ) : (
          <>
            <div className="member__actions">
              <Button
                aria-expanded={open === 'menu'}
                onClick={() => {
                  setDone(null)
                  setOpen(open === 'menu' ? null : 'menu')
                }}
              >
                {copy.add}
              </Button>
            </div>
            {open === 'menu' && (
              <div className="member__actions" role="group" aria-label={copy.add}>
                <Button onClick={() => setOpen('payments')}>{copy.payments}</Button>
                <Button onClick={() => setOpen('start')}>{copy.start}</Button>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}

/** The `YYYY-MM-DD` `years` before `iso`. */
export function yearsBefore(iso: string, years: number): string {
  return `${String(Number(iso.slice(0, 4)) - years).padStart(4, '0')}${iso.slice(4)}`
}

function StartForm({ person, onCancel, onDone }: { person: Person; onCancel: () => void; onDone: () => void }) {
  const form = copy.form
  const today = useGymToday()
  const queryClient = useQueryClient()
  const sinceId = useId()
  const classesId = useId()
  const [since, setSince] = useState(person.member_since ?? '')
  const [classes, setClasses] = useState(String(person.prior_classes))
  const [checked, setChecked] = useState(false)
  const earliest = today ? yearsBefore(today, HISTORY_WINDOW_YEARS) : ''
  const sinceOk = since === '' || (since <= today && since >= earliest)
  const count = Number(classes)
  const classesOk = classes.trim() !== '' && Number.isInteger(count) && count >= 0 && count <= MAX_PRIOR_CLASSES

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: () => setHistory(person.id, { member_since: since || null, prior_classes: count }),
    onSuccess: async () => {
      onDone()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['people'] }),
        queryClient.invalidateQueries({ queryKey: ['attendance', person.id] }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (sinceOk && classesOk) save.mutate()
  }

  return (
    <form className="member__form" aria-label={form.title} onSubmit={submit} noValidate>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={sinceId} className="member__label">
        {form.since}
      </label>
      <Input
        id={sinceId}
        type="date"
        min={earliest || undefined}
        max={today || undefined}
        value={since}
        aria-invalid={checked && !sinceOk}
        onChange={(e) => setSince(e.target.value)}
      />
      {checked && !sinceOk && (
        <p className="member__error" role="alert">
          {form.sinceNeeded}
        </p>
      )}
      <label htmlFor={classesId} className="member__label">
        {form.classes}
      </label>
      <Input
        id={classesId}
        type="number"
        inputMode="numeric"
        min={0}
        max={MAX_PRIOR_CLASSES}
        step={1}
        value={classes}
        aria-invalid={checked && !classesOk}
        onChange={(e) => setClasses(e.target.value)}
      />
      {checked && !classesOk && (
        <p className="member__error" role="alert">
          {form.classesNeeded}
        </p>
      )}
      {save.error && (
        <p className="member__error" role="alert">
          {form.failed}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit}
        </Button>
      </div>
    </form>
  )
}

// --- Historial de pagos (#295) --------------------------------------------------------

// Years shown before "Ver años anteriores".
const YEARS_SHOWN = 3
// Backend `MAX_PAYMENTS_AT_ONCE` and `MAX_PRICE_CLP`.
export const MAX_PAYMENTS_AT_ONCE = 360
const MAX_AMOUNT_CLP = 100_000_000
const DEFAULT_PAY_DAY = 5
const METHODS: readonly HistoryMethod[] = ['transfer', 'cash', 'other']

/** The card's years, each collapsed to its count and total, opening to its payments. */
function HistoryYears({ personId, onRemoved }: { personId: string; onRemoved: () => void }) {
  const payments = useQuery(historyPaymentsQuery(personId))
  const [all, setAll] = useState(false)
  const [openYears, setOpenYears] = useState<ReadonlySet<number>>(new Set())
  if (payments.isError) {
    return (
      <p className="member__error" role="alert">
        {copy.paymentsError}
      </p>
    )
  }
  const years = payments.data?.years ?? []
  if (years.length === 0) return null
  const shown = all ? years : years.slice(0, YEARS_SHOWN)
  const toggle = (year: number) => {
    const next = new Set(openYears)
    if (!next.delete(year)) next.add(year)
    setOpenYears(next)
  }
  return (
    <>
      <ul className="member__ledger past-pay__years" aria-label={copy.payments}>
        {shown.map((y) => {
          const open = openYears.has(y.year)
          return (
            <li key={y.year} className="past-pay__year">
              <button
                type="button"
                className="member__entry-button past-pay__year-button"
                aria-expanded={open}
                onClick={() => toggle(y.year)}
              >
                <span className="member__entry-chevron" aria-hidden="true">
                  <ChevronRightIcon />
                </span>
                <span className="member__entry-title">{copy.year(y.year, y.count)}</span>
                <span className="member__entry-amount">{t.common.clp(y.total_clp)}</span>
              </button>
              {open && (
                <ul className="member__ledger past-pay__payments">
                  {y.payments.map((p) => (
                    <PaymentLine key={p.id} personId={personId} payment={p} onRemoved={onRemoved} />
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      {years.length > YEARS_SHOWN && (
        <Button variant="ghost" className="member__more" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? copy.fewer : copy.earlier(years.length - YEARS_SHOWN)}
        </Button>
      )}
    </>
  )
}

/** `marzo 2024`, or `Pago` when the month it paid is not known. */
function paymentTitle(p: HistoryPayment): string {
  return p.covers_month ? copy.line.month(p.covers_month) : copy.line.payment
}

/** Where a line came from: `importado de pagos.xlsx · Ana · 14 nov`, or typed by whom. */
function paymentSource(p: HistoryPayment): string {
  const day = shortDay(p.created_at)
  if (p.source === 'import' && p.import_name) return copy.line.imported(p.import_name, p.created_by_name, day)
  return p.created_by_name ? copy.line.typed(p.created_by_name, day) : copy.line.typedNobody(day)
}

/** `marzo 2024` · `pagado el 5 mar 2024 · transferencia · Mensual 3x semana` · `$25.000`,
 * opening "Eliminar" with a reason. */
function PaymentLine({
  personId,
  payment: p,
  onRemoved,
}: {
  personId: string
  payment: HistoryPayment
  onRemoved: () => void
}) {
  const [open, setOpen] = useState(false)
  const detail = [
    copy.line.paid(t.common.dayYear(p.paid_on)),
    p.method ? copy.line.method[p.method] : null,
    p.plan_name,
    p.note,
  ]
  return (
    <li className="member__entry member__entry--fixable past-pay__payment">
      <button type="button" className="member__entry-button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="member__dot" aria-hidden="true" />
        <span className="member__entry-text">
          <span className="member__entry-title">{paymentTitle(p)}</span>
          <span className="member__detail">{detail.filter(Boolean).join(' · ')}</span>
          <span className="member__detail">{paymentSource(p)}</span>
        </span>
        <span className="member__entry-amount">{t.common.clp(p.amount_clp)}</span>
        <span className="member__entry-chevron" aria-hidden="true">
          <ChevronRightIcon />
        </span>
      </button>
      {open && (
        <div className="member__fix">
          <RemoveForm personId={personId} payment={p} onCancel={() => setOpen(false)} onDone={onRemoved} />
        </div>
      )}
    </li>
  )
}

function RemoveForm({
  personId,
  payment,
  onCancel,
  onDone,
}: {
  personId: string
  payment: HistoryPayment
  onCancel: () => void
  onDone: () => void
}) {
  const words = copy.remove
  const queryClient = useQueryClient()
  const reasonId = useId()
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''
  const remove = useSubmit({
    offline: 'refuse',
    mutationFn: () => removeHistoryPayment(personId, payment.id, reason.trim()),
    onSuccess: (data: HistoryPayments) => {
      queryClient.setQueryData(historyPaymentsQuery(personId).queryKey, data)
      onDone()
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (reasonOk) remove.mutate()
  }
  const title = words.title(`${paymentTitle(payment)} · ${t.common.clp(payment.amount_clp)}`)
  return (
    <form className="member__form" aria-label={title} onSubmit={submit} noValidate>
      <span className="member__fix-title">{title}</span>
      <p className="member__detail">{words.intro}</p>
      <label htmlFor={reasonId} className="member__label">
        {words.reason}
      </label>
      <Textarea
        id={reasonId}
        maxLength={500}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value)}
      />
      {checked && !reasonOk && (
        <p className="member__error" role="alert">
          {words.reasonNeeded}
        </p>
      )}
      {remove.error && (
        <p className="member__error" role="alert">
          {words.failed}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={remove.isPending} onClick={onCancel}>
          {words.cancel}
        </Button>
        <Button type="submit" variant="danger" disabled={remove.isPending} busy={remove.isPending}>
          {remove.isPending ? words.working : words.submit}
        </Button>
      </div>
    </form>
  )
}

/** The first day of each month from `from` to `to` (`YYYY-MM`), in order. */
/** The first `YYYY-MM` whose 1st is on or after `iso`: the earliest month a payment can be
 * for when `iso` is the first day the history window allows. */
export function firstMonthFrom(iso: string): string {
  if (iso.slice(8, 10) === '01') return iso.slice(0, 7)
  const year = Number(iso.slice(0, 4))
  const month = Number(iso.slice(5, 7))
  return month === 12
    ? `${String(year + 1).padStart(4, '0')}-01`
    : `${String(year).padStart(4, '0')}-${String(month + 1).padStart(2, '0')}`
}

export function monthsBetween(from: string, to: string): string[] {
  const months: string[] = []
  let year = Number(from.slice(0, 4))
  let month = Number(from.slice(5, 7))
  const last = Number(to.slice(0, 4)) * 12 + Number(to.slice(5, 7))
  while (year * 12 + month <= last && months.length <= MAX_PAYMENTS_AT_ONCE) {
    months.push(`${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-01`)
    month += 1
    if (month > 12) {
      month = 1
      year += 1
    }
  }
  return months
}

/** The day `day` of `month` (its first day), its last day when shorter, and never after
 * `today`. */
export function paidOn(month: string, day: number, today: string): string {
  const last = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0).getDate()
  const iso = `${month.slice(0, 8)}${String(Math.min(day, last)).padStart(2, '0')}`
  return today && iso > today ? today : iso
}

type RowEdit = { amount?: string; day?: string; method?: HistoryMethod | '' }

type Row = { month: string; amount: string; day: string; method: HistoryMethod | ''; edited: RowEdit }

const amountOf = (text: string) => Number(text.replace(/\D/g, ''))
const amountOk = (text: string) => {
  const value = amountOf(text)
  return text.trim() !== '' && value > 0 && value <= MAX_AMOUNT_CLP
}
const dayOk = (text: string) => /^\d{1,2}$/.test(text.trim()) && Number(text) >= 1 && Number(text) <= 31

/** The same day, amount and month as a payment already there: a warning, not a refusal. */
function sameAs(existing: readonly HistoryPayment[], payment: HistoryPaymentIn): boolean {
  return existing.some(
    (p) =>
      p.paid_on === payment.paid_on && p.amount_clp === payment.amount_clp && p.covers_month === payment.covers_month,
  )
}

/**
 * "Pagos anteriores": desde, hasta, monto por mes, método, día de pago and plan, asked
 * once, fill one row per month, each editable or removable ("ese mes no pagó"), with the
 * total. A month on or after their first plan is left out, pointing at "Pagado hasta"
 * (#286). Guardar writes them all in one transaction, or none.
 */
function PaymentsForm({
  personId,
  onCancel,
  onDone,
}: {
  personId: string
  onCancel: () => void
  onDone: (count: number) => void
}) {
  const form = copy.paymentsForm
  const today = useGymToday()
  const queryClient = useQueryClient()
  const history = useQuery(historyPaymentsQuery(personId))
  const ids = {
    from: useId(),
    to: useId(),
    amount: useId(),
    method: useId(),
    day: useId(),
    plan: useId(),
  }
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [amount, setAmount] = useState('')
  const [method, setMethod] = useState<HistoryMethod | ''>('transfer')
  const [day, setDay] = useState(String(DEFAULT_PAY_DAY))
  const [plan, setPlan] = useState('')
  const [edits, setEdits] = useState<Readonly<Record<string, RowEdit>>>({})
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set())
  const [checked, setChecked] = useState(false)

  const planFrom = history.data?.plan_from ?? null
  const thisMonth = today.slice(0, 7)
  // A month's 1st is the day it is for, so the oldest month is the first wholly in the window.
  const earliest = today ? firstMonthFrom(yearsBefore(today, HISTORY_WINDOW_YEARS)) : ''
  const rangeOk = from !== '' && to !== '' && from <= to && to <= thisMonth && from >= earliest
  const months = useMemo(() => (rangeOk ? monthsBetween(from, to) : []), [rangeOk, from, to])
  // From the month their first plan began, it is the plan's: the API refuses it (`covers_plan`).
  const inPlan = planFrom ? months.filter((m) => m.slice(0, 7) >= planFrom.slice(0, 7)) : []
  const rows: Row[] = months
    .filter((m) => !inPlan.includes(m) && !removed.has(m))
    .map((m) => {
      const edited = edits[m] ?? {}
      return {
        month: m,
        amount: edited.amount ?? amount,
        day: edited.day ?? day,
        method: edited.method ?? method,
        edited,
      }
    })
  const tooMany = rows.length > MAX_PAYMENTS_AT_ONCE
  const rowsOk = rows.every((r) => amountOk(r.amount) && dayOk(r.day))
  const payments: HistoryPaymentIn[] = rows.map((r) => ({
    paid_on: paidOn(r.month, Number(r.day) || DEFAULT_PAY_DAY, today),
    amount_clp: amountOf(r.amount),
    method: r.method || null,
    covers_month: r.month,
    plan_name: plan.trim() || null,
  }))
  const existing = history.data?.years.flatMap((y) => y.payments) ?? []
  const duplicates = payments.filter((p) => sameAs(existing, p))
  const total = payments.reduce((sum, p) => sum + p.amount_clp, 0)

  const edit = (month: string, change: RowEdit) => setEdits({ ...edits, [month]: { ...edits[month], ...change } })

  const save = useSubmit({
    offline: 'refuse',
    mutationFn: (body: HistoryPaymentIn[]) => addHistoryPayments(personId, body),
    onSuccess: (data: HistoryPayments, body) => {
      queryClient.setQueryData(historyPaymentsQuery(personId).queryKey, data)
      onDone(body.length)
    },
  })
  const refusedFrom = coversPlan(save.error)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (rangeOk && rows.length > 0 && !tooMany && rowsOk) save.mutate(payments)
  }

  return (
    <form className="member__form past-pay__form" aria-label={form.title} onSubmit={submit} noValidate>
      <span className="member__fix-title">{form.title}</span>
      <p className="member__detail">{form.intro}</p>
      <div className="past-pay__form-body">
        <div className="past-pay__fields">
          <div className="member__field">
            <label htmlFor={ids.from} className="member__label">
              {form.from}
            </label>
            <Input
              id={ids.from}
              type="month"
              min={earliest || undefined}
              max={thisMonth || undefined}
              value={from}
              aria-invalid={checked && !rangeOk}
              onChange={(e) => setFrom(e.target.value)}
            />
          </div>
          <div className="member__field">
            <label htmlFor={ids.to} className="member__label">
              {form.to}
            </label>
            <Input
              id={ids.to}
              type="month"
              min={from || earliest || undefined}
              max={thisMonth || undefined}
              value={to}
              aria-invalid={checked && !rangeOk}
              onChange={(e) => setTo(e.target.value)}
            />
          </div>
          {checked && !rangeOk && (
            <p className="member__error past-pay__wide" role="alert">
              {form.rangeNeeded}
            </p>
          )}
          <div className="member__field">
            <label htmlFor={ids.amount} className="member__label">
              {form.amount}
            </label>
            <Input
              id={ids.amount}
              inputMode="numeric"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </div>
          <div className="member__field">
            <label htmlFor={ids.method} className="member__label">
              {form.method}
            </label>
            <Select id={ids.method} value={method} onChange={(e) => setMethod(e.target.value as HistoryMethod | '')}>
              {METHODS.map((m) => (
                <option key={m} value={m}>
                  {form.methods[m]}
                </option>
              ))}
              <option value="">{form.methodUnknown}</option>
            </Select>
          </div>
          <div className="member__field">
            <label htmlFor={ids.day} className="member__label">
              {form.day}
            </label>
            <Input
              id={ids.day}
              type="number"
              inputMode="numeric"
              min={1}
              max={31}
              step={1}
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          </div>
          <div className="member__field">
            <label htmlFor={ids.plan} className="member__label">
              {form.plan}
            </label>
            <Input
              id={ids.plan}
              maxLength={200}
              placeholder={form.planPlaceholder}
              value={plan}
              onChange={(e) => setPlan(e.target.value)}
            />
          </div>
        </div>

        <div className="past-pay__list">
          {inPlan.length > 0 && <p className="member__note">{form.inPlan(copy.line.month(inPlan[0]!))}</p>}
          {rows.length > 0 && (
            <ul className="past-pay__months" aria-label={form.months}>
              {rows.map((r, i) => {
                const label = form.month(r.month)
                const duplicate = sameAs(existing, payments[i]!)
                return (
                  <li key={r.month} className="past-pay__month">
                    <span className="past-pay__month-name">{label}</span>
                    <Input
                      className="past-pay__month-amount"
                      aria-label={form.rowAmount(label)}
                      inputMode="numeric"
                      value={r.amount}
                      aria-invalid={checked && !amountOk(r.amount)}
                      onChange={(e) => edit(r.month, { amount: e.target.value })}
                    />
                    <Button
                      icon
                      variant="ghost"
                      aria-label={form.removeRow(label)}
                      onClick={() => setRemoved(new Set([...removed, r.month]))}
                    >
                      <CloseIcon />
                    </Button>
                    <Input
                      className="past-pay__month-day"
                      aria-label={form.rowDay(label)}
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={31}
                      value={r.day}
                      aria-invalid={checked && !dayOk(r.day)}
                      onChange={(e) => edit(r.month, { day: e.target.value })}
                    />
                    <Select
                      className="past-pay__month-method"
                      aria-label={form.rowMethod(label)}
                      value={r.method}
                      onChange={(e) => edit(r.month, { method: e.target.value as HistoryMethod | '' })}
                    >
                      {METHODS.map((m) => (
                        <option key={m} value={m}>
                          {form.methods[m]}
                        </option>
                      ))}
                      <option value="">{form.methodUnknown}</option>
                    </Select>
                    {duplicate && <span className="past-pay__month-note">{form.duplicate}</span>}
                  </li>
                )
              })}
            </ul>
          )}
          {rangeOk && <p className="member__entry-title">{form.total(rows.length, t.common.clp(total))}</p>}
          {duplicates.length > 0 && (
            <div className="member__warning" role="status">
              <p className="member__warning-line">{form.duplicates(duplicates.length)}</p>
            </div>
          )}
          {checked && rangeOk && rows.length === 0 && (
            <p className="member__error" role="alert">
              {form.noneLeft}
            </p>
          )}
          {checked && tooMany && (
            <p className="member__error" role="alert">
              {form.tooMany(MAX_PAYMENTS_AT_ONCE)}
            </p>
          )}
          {checked && rows.length > 0 && !rowsOk && (
            <p className="member__error" role="alert">
              {rows.some((r) => !amountOk(r.amount)) ? form.amountNeeded : form.dayNeeded}
            </p>
          )}
        </div>
      </div>
      {save.error && (
        <p className="member__error" role="alert">
          {refusedFrom
            ? form.coversPlan(t.common.dayYear(refusedFrom))
            : outsideHistory(save.error)
              ? form.outsideWindow
              : form.failed}
        </p>
      )}
      <div className="member__form-actions">
        <Button disabled={save.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? form.working : form.submit(rows.length)}
        </Button>
      </div>
    </form>
  )
}
