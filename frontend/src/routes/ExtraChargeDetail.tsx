import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import {
  cancelLine,
  cancelPreview,
  changeLineAmount,
  chargeQuery,
  notifyLine,
  payLine,
  refundPayment,
  remindPending,
  type ExtraCharge,
  type Line,
  type LinkedExpenses,
} from '../api/extraCharges'
import { myAccessQuery, readsLedger } from '../api/me'
import type { Method } from '../api/member'
import { useGymToday } from '../api/sessions'
import { Button, buttonClass } from '../components/Button'
import { cx } from '../components/classNames'
import { Banner, Card, CheckRow, PlainList, SectionHeader } from '../components/Card'
import { MoreMenu, moreItemClass } from '../components/MoreMenu'
import { Field, Input, Select } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { StatusPill, type Status } from '../components/StatusPill'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { Progress, SubHeader } from './ExtraCharges'
import './ExtraCharges.css'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'

const copy = t.admin.extra
const words = copy.detail
const clp = t.common.clp
const METHODS: Method[] = ['transfer', 'cash', 'other']

const route = getRouteApi('/admin/pagos/cobros/$chargeId')

/**
 * One cobro extra (#195): each person with their status, amount and any proof, and what
 * the admin does about a line: mark it paid, change its amount, cancel it (dividing the
 * total again while nobody has paid), give back a payment, re-send the notice, or
 * remind them on WhatsApp. "Recordar a los pendientes" emails everyone still owing.
 *
 * A cobro in instalments (#356) shows how far along each instalment is across everyone,
 * and one row per person (#417): how many of their instalments are paid, the next one
 * due and its one action, and under "Ver cuotas" each instalment as a line of its own.
 *
 * A row shows one action, the one its line most needs: "Ver comprobante" while a proof
 * waits, else "Marcar pagado" while it is owed; every other action is under its "Más",
 * so a cobro for the whole gym reads as a list of names (#357).
 */
export function ExtraChargeDetail() {
  const access = useQuery(myAccessQuery())
  const { chargeId } = route.useParams()
  const charge = useQuery({ ...chargeQuery(chargeId), enabled: readsLedger(access.data) })
  usePageTitle(charge.data?.title ?? copy.title)

  if (!readsLedger(access.data)) {
    return (
      <PageContainer>
        <PageHeader title={copy.title} />
        {access.isSuccess && <p className="extra__note">{t.admin.payments.coachesOnly}</p>}
      </PageContainer>
    )
  }
  if (charge.isPending) return <Loading className="extra__note">{words.loading}</Loading>
  if (charge.isError) {
    const missing = charge.error instanceof ApiError && charge.error.status === 404
    return (
      <PageContainer>
        <SubHeader title={copy.title} back="cobros" />
        <p className="extra__note" role="alert">
          {missing ? words.notFound : words.error}
        </p>
      </PageContainer>
    )
  }
  return <Detail charge={charge.data} />
}

function Detail({ charge }: { charge: ExtraCharge }) {
  const [done, setDone] = useState<string | null>(null)
  const remind = useSubmit({
    mutationFn: () => remindPending(charge.id),
    onSuccess: (r) => setDone(words.reminded(r.sent, r.without_email)),
  })
  const owing = charge.people.some((line) => line.status === 'open')
  const people = new Set(charge.people.map((line) => line.person.id)).size
  const when =
    charge.instalments > 1 ? words.firstDue(charge.instalments, shortDay(charge.due_date)) : copy.due(shortDay(charge.due_date))
  return (
    <PageContainer className="extra">
      <SubHeader title={charge.title} subtitle={`${copy.category[charge.category]} · ${when}`} back="cobros">
        {owing && (
          <Button disabled={remind.isPending} onClick={() => remind.mutate()}>
            {remind.isPending ? words.reminding : words.remind}
          </Button>
        )}
      </SubHeader>
      {/* The bar spans the card (#357). */}
      <Card className="extra__summary">
        <Progress charge={charge} />
        {charge.description && <p className="extra__message">{charge.description}</p>}
      </Card>
      {charge.expenses && charge.expenses.count > 0 && <Recovery figures={charge.expenses} />}
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {remind.isError && (
        <p className="extra__error" role="alert">
          {words.failed}
        </p>
      )}
      {charge.instalments > 1 && (
        <Card aria-labelledby="extra-schedule">
          <SectionHeader id="extra-schedule" title={words.scheduleLabel} trailing={String(charge.instalments)} />
          <PlainList className="extra__lines">
            {charge.schedule.map((instalment) => (
              <li key={instalment.instalment} className="extra__line extra__instalment">
                <span className="extra__line-name">
                  {words.instalmentDue(instalment.instalment, charge.instalments, shortDay(instalment.due_date))}
                </span>
                <Progress charge={instalment} />
              </li>
            ))}
          </PlainList>
        </Card>
      )}
      <Card aria-labelledby="extra-people">
        <SectionHeader id="extra-people" title={words.peopleLabel} trailing={String(people)} />
        <PlainList className="extra__lines">
          {charge.instalments > 1
            ? byPerson(charge.people).map((lines) => (
                <PersonRow key={lines[0]!.person.id} charge={charge} lines={lines} onDone={setDone} />
              ))
            : charge.people.map((line) => <LineRow key={line.id} charge={charge} line={line} onDone={setDone} />)}
        </PlainList>
      </Card>
    </PageContainer>
  )
}

type Panel = 'pay' | 'amount' | 'cancel' | 'refund' | null

/** The line's status; an open line past its due date, in the gym's day, is "Vencido". */
function lineStatus(line: Line, today: string): { status: Status; label: string } {
  if (line.status === 'open' && line.due_date < today) {
    return { status: 'overdue', label: copy.status.overdue }
  }
  const status: Record<Line['status'], Status> = {
    open: 'open',
    in_review: 'in_review',
    paid: 'paid',
    waived: 'none',
    cancelled: 'cancelled',
  }
  return { status: status[line.status], label: copy.status[line.status] }
}

/** Each person's lines, in the order the cobro lists them (by name, then instalment). */
function byPerson(lines: Line[]): Line[][] {
  const people = new Map<string, Line[]>()
  for (const line of lines) {
    const theirs = people.get(line.person.id)
    if (theirs) theirs.push(line)
    else people.set(line.person.id, [line])
  }
  return [...people.values()]
}

/** Closes a line's panel once its change is saved, and reloads what it touched. */
function useSettled(setPanel: (panel: Panel) => void, onDone: (message: string) => void) {
  const queryClient = useQueryClient()
  return async (message?: string) => {
    setPanel(null)
    await queryClient.invalidateQueries({ queryKey: ['extra'] })
    await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    if (message) onDone(message)
  }
}

/**
 * One person in a cobro in instalments (#417): "2 de 7 cuotas pagadas · $25.715 de
 * $89.990", the next instalment owed with its one action, and "Ver cuotas" for each
 * instalment's own row, where every other action is.
 */
function PersonRow({ charge, lines, onDone }: { charge: ExtraCharge; lines: Line[]; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false)
  const [panel, setPanel] = useState<Panel>(null)
  const today = useGymToday()
  const settled = useSettled(setPanel, onDone)
  const first = lines[0]!
  // What they owe: neither cancelled nor exento ($0).
  const owed = lines.filter((line) => line.status !== 'cancelled' && line.status !== 'waived')
  const paid = owed.filter((line) => line.status === 'paid').length
  const due = owed.reduce((sum, line) => sum + line.amount_due_clp, 0)
  const collected = owed.reduce((sum, line) => sum + line.paid_clp, 0)
  // The earliest instalment still owed; none once every one is settled.
  const next = owed.find((line) => line.status === 'open' || line.status === 'in_review')
  const shown: { status: Status; label: string } = next
    ? lineStatus(next, today)
    : owed.length > 0
      ? { status: 'paid', label: copy.status.paid }
      : lines.some((line) => line.status === 'waived')
        ? { status: 'none', label: copy.status.waived }
        : { status: 'cancelled', label: copy.status.cancelled }
  const listId = `extra-cuotas-${first.person.id}`

  return (
    <li className="extra__line">
      <div className="extra__line-top">
        <span className="extra__line-name">
          <Link to="/admin/alumnos/$personId" params={{ personId: first.person.id }}>
            {first.person.name}
          </Link>
          {first.guardian && <span className="extra__hint">{words.guardianOf(first.guardian.name)}</span>}
        </span>
        <StatusPill status={shown.status}>{shown.label}</StatusPill>
      </div>
      <div className="extra__line-money">
        <span className="extra__line-amount">{words.instalmentsPaid(paid, owed.length)}</span>
        <span className="extra__hint">{words.paidOf(clp(collected), clp(due))}</span>
      </div>
      {next && (
        <p className="extra__hint">
          {words.nextDue(next.instalment, charge.instalments, shortDay(next.due_date), clp(next.outstanding_clp))}
        </p>
      )}
      <div className="extra__line-actions" role="group" aria-label={words.actions(first.person.name)}>
        {next?.status === 'in_review' ? (
          <Link to="/admin/pagos/comprobantes" className={buttonClass()}>
            {words.review}
          </Link>
        ) : (
          next && (
            <Button aria-expanded={panel === 'pay'} onClick={() => setPanel(panel === 'pay' ? null : 'pay')}>
              {words.markPaidInstalment(next.instalment)}
            </Button>
          )
        )}
        <Button
          variant="ghost"
          aria-expanded={open}
          aria-controls={listId}
          aria-label={words.showInstalmentsOf(first.person.name)}
          onClick={() => setOpen(!open)}
        >
          {words.showInstalments}
        </Button>
      </div>
      {panel === 'pay' && next && <PayForm charge={charge} line={next} onDone={settled} onClose={() => setPanel(null)} />}
      {open && (
        <PlainList id={listId} className="extra__lines extra__cuotas" aria-label={words.instalmentsOfPerson(first.person.name)}>
          {lines.map((line) => (
            <LineRow key={line.id} charge={charge} line={line} onDone={onDone} nested />
          ))}
        </PlainList>
      )}
    </li>
  )
}

/** A line: a person in a cobro paid at once, or, `nested` under its person, one instalment. */
function LineRow({
  charge,
  line,
  onDone,
  nested = false,
}: {
  charge: ExtraCharge
  line: Line
  onDone: (message: string) => void
  nested?: boolean
}) {
  const [panel, setPanel] = useState<Panel>(null)
  const notify = useSubmit({
    mutationFn: () => notifyLine(charge.id, line.id),
    onSuccess: (r) => onDone(r.sent ? words.notified : words.noEmail),
  })
  const shown = lineStatus(line, useGymToday())
  const instalments = charge.instalments > 1
  const live = line.status !== 'cancelled'
  const payable = line.status === 'open' || line.status === 'in_review'
  const settled = useSettled(setPanel, onDone)
  const toggle = (next: Panel) => setPanel(panel === next ? null : next)

  return (
    <li className="extra__line">
      <div className="extra__line-top">
        {nested ? (
          <span className="extra__line-name">
            {words.instalmentDue(line.instalment, charge.instalments, shortDay(line.due_date))}
          </span>
        ) : (
          <span className="extra__line-name">
            <Link to="/admin/alumnos/$personId" params={{ personId: line.person.id }}>
              {line.person.name}
            </Link>
            {line.guardian && <span className="extra__hint">{words.guardianOf(line.guardian.name)}</span>}
          </span>
        )}
        <StatusPill status={shown.status}>{shown.label}</StatusPill>
      </div>
      <div className="extra__line-money">
        <span className="extra__line-amount">{clp(line.amount_due_clp)}</span>
        <span className="extra__hint">
          {line.paid_clp > 0 ? words.paidOf(clp(line.paid_clp), clp(line.amount_due_clp)) : null}
          {line.overridden ? ` · ${words.overridden}` : null}
        </span>
      </div>
      {!live && line.cancel_reason && <p className="extra__hint">{words.cancelledBecause(line.cancel_reason)}</p>}
      {live && (
        <div
          className="extra__line-actions"
          role="group"
          aria-label={instalments ? words.actionsOf(line.person.name, line.instalment) : words.actions(line.person.name)}
        >
          {/* One action per person, what the line most needs; the rest under "Más" (#357). */}
          {line.status === 'in_review' ? (
            <Link to="/admin/pagos/comprobantes" className={buttonClass()}>
              {words.review}
            </Link>
          ) : (
            payable && (
              <Button aria-expanded={panel === 'pay'} onClick={() => toggle('pay')}>
                {words.markPaid}
              </Button>
            )
          )}
          <MoreMenu
            label={words.more}
            ariaLabel={instalments ? words.moreForOf(line.person.name, line.instalment) : words.moreFor(line.person.name)}
          >
            {line.status === 'in_review' && (
              <button type="button" className={moreItemClass()} aria-expanded={panel === 'pay'} onClick={() => toggle('pay')}>
                {words.markPaid}
              </button>
            )}
            {line.whatsapp_url && (
              <a
                className={moreItemClass()}
                href={line.whatsapp_url}
                target="_blank"
                rel="noreferrer"
                aria-label={words.whatsapp(line.person.name)}
              >
                {words.whatsappShort}
              </a>
            )}
            {line.status === 'open' && (
              <button type="button" className={moreItemClass()} disabled={notify.isPending} onClick={() => notify.mutate()}>
                {words.notify}
              </button>
            )}
            <button type="button" className={moreItemClass()} aria-expanded={panel === 'amount'} onClick={() => toggle('amount')}>
              {words.editAmount}
            </button>
            {line.refundable_payments.length > 0 && (
              <button type="button" className={moreItemClass()} aria-expanded={panel === 'refund'} onClick={() => toggle('refund')}>
                {words.refund}
              </button>
            )}
            <button
              type="button"
              className={moreItemClass(true)}
              aria-expanded={panel === 'cancel'}
              onClick={() => toggle('cancel')}
            >
              {words.cancelLine}
            </button>
          </MoreMenu>
        </div>
      )}
      {panel === 'pay' && <PayForm charge={charge} line={line} onDone={settled} onClose={() => setPanel(null)} />}
      {panel === 'amount' && <AmountForm charge={charge} line={line} onDone={settled} onClose={() => setPanel(null)} />}
      {panel === 'refund' && <RefundForm line={line} onDone={settled} onClose={() => setPanel(null)} />}
      {panel === 'cancel' && <CancelForm charge={charge} line={line} onDone={settled} onClose={() => setPanel(null)} />}
    </li>
  )
}

type FormProps = { charge: ExtraCharge; line: Line; onDone: (message?: string) => Promise<void>; onClose: () => void }

function refusal(error: unknown): string {
  if (!(error instanceof ApiError) || error.status !== 409) return words.failed
  const detail = (error.body as { detail?: unknown } | undefined)?.detail
  if (detail === 'the line is already paid in full') return words.refused.paid
  if (detail === 'less than they have already paid') return words.refused.belowPaid
  if (detail === 'this cobro cannot be divided again') return words.refused.resplit
  if (detail === 'this line is cancelled') return words.refused.cancelled
  return words.refused.money
}

function digits(value: string): string {
  return value.replace(/\D/g, '').replace(/^0+(?=\d)/, '').slice(0, 12)
}

function Actions({ busy, error, onClose }: { busy: boolean; error: unknown; onClose: () => void }) {
  return (
    <>
      {error ? (
        <p className="extra__error" role="alert">
          {refusal(error)}
        </p>
      ) : null}
      {/* Cerrar first, then the save, as every form footer (#419). */}
      <div className="extra__form-actions">
        <Button onClick={onClose}>{words.close}</Button>
        <Button type="submit" variant="primary" disabled={busy} busy={busy}>
          {busy ? words.saving : words.save}
        </Button>
      </div>
    </>
  )
}

function PayForm({ charge, line, onDone, onClose }: FormProps) {
  const [amount, setAmount] = useState(String(line.outstanding_clp))
  const [method, setMethod] = useState<Method>('transfer')
  const pay = useSubmit({
    offline: 'refuse',
    mutationFn: () => payLine(charge.id, line.id, Number(amount), method),
    onSuccess: () => onDone(),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (Number(amount) > 0) pay.mutate()
  }
  return (
    <form className="extra__panel" onSubmit={submit}>
      <Field label={words.amountLabel}>
        {(props) => <Input {...props} inputMode="numeric" value={amount} onChange={(e) => setAmount(digits(e.target.value))} />}
      </Field>
      <MethodField label={words.methodLabel} value={method} onChange={setMethod} />
      <Actions busy={pay.isPending} error={pay.error} onClose={onClose} />
    </form>
  )
}

function AmountForm({ charge, line, onDone, onClose }: FormProps) {
  const instalments = charge.instalments > 1
  const [amount, setAmount] = useState(String(line.amount_due_clp))
  const change = useSubmit({
    offline: 'refuse',
    mutationFn: () => changeLineAmount(charge.id, line.id, Number(amount)),
    onSuccess: () => onDone(),
  })
  return (
    <form
      className="extra__panel"
      onSubmit={(event) => {
        event.preventDefault()
        if (amount !== '') change.mutate()
      }}
    >
      <Field label={words.amountLabel} hint={instalments ? words.amountOneInstalment : undefined}>
        {(props) => <Input {...props} inputMode="numeric" value={amount} onChange={(e) => setAmount(digits(e.target.value))} />}
      </Field>
      <Actions busy={change.isPending} error={change.error} onClose={onClose} />
    </form>
  )
}

function RefundForm({ line, onDone, onClose }: Omit<FormProps, 'charge'>) {
  const [paymentId, setPaymentId] = useState(line.refundable_payments[0]!.id)
  const payment = line.refundable_payments.find((p) => p.id === paymentId) ?? line.refundable_payments[0]!
  const [amount, setAmount] = useState(String(payment.refundable_clp))
  const [method, setMethod] = useState<Method>('transfer')
  const refund = useSubmit({
    offline: 'refuse',
    mutationFn: () => refundPayment(payment.id, Number(amount), method),
    onSuccess: () => onDone(),
  })
  return (
    <form
      className="extra__panel"
      onSubmit={(event) => {
        event.preventDefault()
        if (Number(amount) > 0) refund.mutate()
      }}
    >
      <Field label={words.refund}>
        {(props) => (
          <Select
            {...props}
            value={payment.id}
            onChange={(e) => {
              setPaymentId(e.target.value)
              const picked = line.refundable_payments.find((p) => p.id === e.target.value)
              if (picked) setAmount(String(picked.refundable_clp))
            }}
          >
            {line.refundable_payments.map((p) => (
              <option key={p.id} value={p.id}>
                {words.refundOf(clp(p.amount_clp), clp(p.refundable_clp))}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={words.amountLabel}>
        {(props) => <Input {...props} inputMode="numeric" value={amount} onChange={(e) => setAmount(digits(e.target.value))} />}
      </Field>
      <MethodField label={words.refundMethodLabel} value={method} onChange={setMethod} />
      <Actions busy={refund.isPending} error={refund.error} onClose={onClose} />
    </form>
  )
}

function CancelForm({ charge, line, onDone, onClose }: FormProps) {
  const preview = useQuery({
    queryKey: ['extra', 'cancel', charge.id, line.id],
    queryFn: () => cancelPreview(charge.id, line.id),
  })
  const [resplit, setResplit] = useState(false)
  const [reason, setReason] = useState('')
  const [checked, setChecked] = useState(false)
  const reasonOk = reason.trim() !== ''
  const cancel = useSubmit({
    offline: 'refuse',
    mutationFn: () => cancelLine(charge.id, line.id, resplit, reason.trim()),
    onSuccess: () => onDone(),
  })
  const names = new Map(charge.people.map((l) => [l.id, l.person.name]))
  return (
    <form
      className="extra__panel"
      onSubmit={(event) => {
        event.preventDefault()
        setChecked(true)
        if (reasonOk) cancel.mutate()
      }}
    >
      <Field label={words.cancelReason} error={checked && !reasonOk ? words.cancelReasonNeeded : undefined}>
        {(props) => <Input {...props} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />}
      </Field>
      {preview.isPending ? (
        <p className="extra__note">{words.cancelChecking}</p>
      ) : preview.data?.resplit_allowed ? (
        <>
          <CheckRow start>
            <input type="checkbox" checked={resplit} onChange={(e) => setResplit(e.target.checked)} />
            <span>{words.resplit}</span>
          </CheckRow>
          {resplit && (
            <PlainList className="extra__preview-list">
              {Object.entries(preview.data.amounts).map(([id, amount]) => (
                <li key={id} className="extra__hint">
                  {words.resplitAmount(names.get(id) ?? '', clp(amount))}
                </li>
              ))}
            </PlainList>
          )}
        </>
      ) : charge.instalments > 1 ? (
        <p className="extra__hint">{words.noResplitInstalments}</p>
      ) : (
        charge.amount_mode === 'split' && <p className="extra__hint">{words.noResplit}</p>
      )}
      {cancel.error ? (
        <p className="extra__error" role="alert">
          {refusal(cancel.error)}
        </p>
      ) : null}
      <div className="extra__form-actions">
        <Button onClick={onClose}>{words.close}</Button>
        <Button type="submit" variant="danger" disabled={preview.isPending} busy={cancel.isPending}>
          {cancel.isPending ? words.saving : words.cancelConfirm}
        </Button>
      </div>
    </form>
  )
}

function MethodField({ label, value, onChange }: { label: string; value: Method; onChange: (m: Method) => void }) {
  return (
    <Field label={label}>
      {(props) => (
        <Select {...props} value={value} onChange={(e) => onChange(e.target.value as Method)}>
          {METHODS.map((m) => (
            <option key={m} value={m}>
              {words.method[m]}
            </option>
          ))}
        </Select>
      )}
    </Field>
  )
}

/** What the gym spent that the cobro recovers, beside what it collected (#318):
 * "Gastos asociados $X · Recaudado $Y · Diferencia". Shown to who holds both
 * `money_read` and `expenses_read`; the cobro's lines are as they were. */
function Recovery({ figures }: { figures: LinkedExpenses }) {
  const words = t.admin.extra.detail
  const titleId = useId()
  const difference = figures.difference_clp
  return (
    <Card aria-labelledby={titleId}>
      <SectionHeader id={titleId} title={words.expensesLabel} trailing={words.expensesCount(figures.count)} />
      <dl className="extra__recovery">
        <div>
          <dt>{words.expensesLabel}</dt>
          <dd>{clp(figures.expenses_clp)}</dd>
        </div>
        <div>
          <dt>{words.collectedLabel}</dt>
          <dd>{clp(figures.collected_clp)}</dd>
        </div>
        <div>
          <dt>{words.differenceLabel}</dt>
          <dd className={cx(difference < 0 && 'extra__negative')}>
            {difference === 0 ? clp(0) : t.common.signedClp(difference)}
          </dd>
        </div>
      </dl>
      <p className="extra__hint">{words.expensesNote}</p>
    </Card>
  )
}
