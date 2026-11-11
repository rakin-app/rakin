import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'
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
} from '../api/extraCharges'
import { myRoleQuery, readsLedger } from '../api/me'
import type { Method } from '../api/member'
import { Button, buttonClass } from '../components/Button'
import { Card, SectionHeader } from '../components/Card'
import { Field, Input, Select } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { StatusPill, type Status } from '../components/StatusPill'
import { isoDay, shortDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { Progress, SubHeader } from './ExtraCharges'
import './ExtraCharges.css'
import { useSubmit } from '../api/submit'

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
 */
export function ExtraChargeDetail() {
  const role = useQuery(myRoleQuery())
  const { chargeId } = route.useParams()
  const charge = useQuery({ ...chargeQuery(chargeId), enabled: readsLedger(role.data) })
  usePageTitle(charge.data?.title ?? copy.title)

  if (!readsLedger(role.data)) {
    return (
      <PageContainer>
        <PageHeader title={copy.title} />
        {role.isSuccess && <p className="extra__note">{t.admin.payments.coachesOnly}</p>}
      </PageContainer>
    )
  }
  if (charge.isPending) return <p className="extra__note">{words.loading}</p>
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
  return (
    <PageContainer className="extra">
      <SubHeader
        title={charge.title}
        subtitle={`${copy.category[charge.category]} · ${copy.due(shortDay(charge.due_date))}`}
        back="cobros"
      >
        {owing && (
          <Button disabled={remind.isPending} onClick={() => remind.mutate()}>
            {remind.isPending ? words.reminding : words.remind}
          </Button>
        )}
      </SubHeader>
      <Progress charge={charge} />
      {charge.description && <p className="extra__message">{charge.description}</p>}
      {done && (
        <p className="extra__done" role="status">
          {done}
        </p>
      )}
      {remind.isError && (
        <p className="extra__error" role="alert">
          {words.failed}
        </p>
      )}
      <Card aria-labelledby="extra-people">
        <SectionHeader id="extra-people" title={words.peopleLabel} trailing={String(charge.people.length)} />
        <ul className="extra__lines">
          {charge.people.map((line) => (
            <LineRow key={line.id} charge={charge} line={line} onDone={setDone} />
          ))}
        </ul>
      </Card>
    </PageContainer>
  )
}

type Panel = 'pay' | 'amount' | 'cancel' | 'refund' | null

function lineStatus(line: Line, dueDate: string): { status: Status; label: string } {
  if (line.status === 'open' && dueDate < isoDay(new Date().toISOString())) {
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

function LineRow({ charge, line, onDone }: { charge: ExtraCharge; line: Line; onDone: (message: string) => void }) {
  const [panel, setPanel] = useState<Panel>(null)
  const queryClient = useQueryClient()
  const notify = useSubmit({
    mutationFn: () => notifyLine(charge.id, line.id),
    onSuccess: (r) => onDone(r.sent ? words.notified : words.noEmail),
  })
  const shown = lineStatus(line, charge.due_date)
  const live = line.status !== 'cancelled'
  const settled = async (message?: string) => {
    setPanel(null)
    await queryClient.invalidateQueries({ queryKey: ['extra'] })
    await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    if (message) onDone(message)
  }
  const toggle = (next: Panel) => setPanel(panel === next ? null : next)

  return (
    <li className="extra__line">
      <div className="extra__line-top">
        <span className="extra__line-name">
          <Link to="/admin/alumnos/$personId" params={{ personId: line.person.id }}>
            {line.person.name}
          </Link>
          {line.guardian && <span className="extra__hint">{words.guardianOf(line.guardian.name)}</span>}
        </span>
        <StatusPill status={shown.status}>{shown.label}</StatusPill>
      </div>
      <div className="extra__line-money">
        <span className="extra__line-amount">{clp(line.amount_due_clp)}</span>
        <span className="extra__hint">
          {line.paid_clp > 0 ? words.paidOf(clp(line.paid_clp), clp(line.amount_due_clp)) : null}
          {line.overridden ? ` · ${words.overridden}` : null}
        </span>
      </div>
      {live && (
        <div className="extra__line-actions" role="group" aria-label={words.actions(line.person.name)}>
          {line.status === 'in_review' && (
            <Link to="/admin/pagos/comprobantes" className={buttonClass({ variant: 'primary' })}>
              {words.review}
            </Link>
          )}
          {(line.status === 'open' || line.status === 'in_review') && (
            <Button aria-expanded={panel === 'pay'} onClick={() => toggle('pay')}>
              {words.markPaid}
            </Button>
          )}
          <Button aria-expanded={panel === 'amount'} onClick={() => toggle('amount')}>
            {words.editAmount}
          </Button>
          {line.status === 'open' && (
            <Button disabled={notify.isPending} onClick={() => notify.mutate()}>
              {words.notify}
            </Button>
          )}
          {line.whatsapp_url && (
            <a
              className={buttonClass()}
              href={line.whatsapp_url}
              target="_blank"
              rel="noreferrer"
              aria-label={words.whatsapp(line.person.name)}
            >
              {words.whatsappShort}
            </a>
          )}
          {line.refundable_payments.length > 0 && (
            <Button aria-expanded={panel === 'refund'} onClick={() => toggle('refund')}>
              {words.refund}
            </Button>
          )}
          <Button variant="danger" aria-expanded={panel === 'cancel'} onClick={() => toggle('cancel')}>
            {words.cancelLine}
          </Button>
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
      <div className="extra__form-actions">
        <Button type="submit" variant="primary" disabled={busy} busy={busy}>
          {busy ? words.saving : words.save}
        </Button>
        <Button onClick={onClose}>{words.close}</Button>
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
      <Field label={words.amountLabel}>
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
  const cancel = useSubmit({
    offline: 'refuse',
    mutationFn: () => cancelLine(charge.id, line.id, resplit),
    onSuccess: () => onDone(),
  })
  const names = new Map(charge.people.map((l) => [l.id, l.person.name]))
  return (
    <form
      className="extra__panel"
      onSubmit={(event) => {
        event.preventDefault()
        cancel.mutate()
      }}
    >
      {preview.isPending ? (
        <p className="extra__note">{words.cancelChecking}</p>
      ) : preview.data?.resplit_allowed ? (
        <>
          <label className="extra__check">
            <input type="checkbox" checked={resplit} onChange={(e) => setResplit(e.target.checked)} />
            <span>{words.resplit}</span>
          </label>
          {resplit && (
            <ul className="extra__preview-list">
              {Object.entries(preview.data.amounts).map(([id, amount]) => (
                <li key={id} className="extra__hint">
                  {words.resplitAmount(names.get(id) ?? '', clp(amount))}
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        charge.amount_mode === 'split' && <p className="extra__hint">{words.noResplit}</p>
      )}
      {cancel.error ? (
        <p className="extra__error" role="alert">
          {refusal(cancel.error)}
        </p>
      ) : null}
      <div className="extra__form-actions">
        <Button type="submit" variant="danger" disabled={preview.isPending} busy={cancel.isPending}>
          {cancel.isPending ? words.saving : words.cancelConfirm}
        </Button>
        <Button onClick={onClose}>{words.close}</Button>
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
