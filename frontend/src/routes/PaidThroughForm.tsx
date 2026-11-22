import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import {
  METHODS,
  paidThroughQuery,
  paidThroughRefused,
  recordPaidThrough,
  type Membership,
  type Method,
  type PaidThroughMode,
} from '../api/member'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Banner, cardClass, CheckRow, PlainList } from '../components/Card'
import { Input, Select } from '../components/Field'
import { Loading } from '../components/Loading'
import { monthName, shortDay } from '../format'
import { t } from '../i18n/es'

const copy = t.admin.member
const clp = t.common.clp

const MODES: readonly PaidThroughMode[] = ['paid', 'gift']

/** Whether "Pagado hasta…" is offered on `membership` (#286): an Active monthly or prepaid plan. */
export function paysThrough(membership: Membership): boolean {
  return (
    membership.status === 'active' &&
    !membership.voided_at &&
    (membership.plan_kind === 'monthly' || membership.plan_kind === 'prepaid')
  )
}

/**
 * "Pagado hasta…" under "Corregir plan" (#286): for a member who paid some months before
 * the gym used Rakin, or was given them. "Pagado hasta" is never typed in: every month up
 * to the date gets a payment ("Pagado antes de Rakin", no receipt) or a bonificación, so
 * the ledger says what the date says. The quote shows the months, their total and the
 * "Pagado hasta" they leave before anything is saved. A date before the plan started
 * belongs in the Historial (#295), which it links to.
 */
export function PaidThroughForm({
  membership,
  onCancel,
  onDone,
}: {
  membership: Membership
  onCancel: () => void
  onDone: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const form = copy.paidThroughForm
  const refusedCopy = copy.paidThroughRefused
  const ids = { through: useId(), mode: useId(), method: useId() }
  const [through, setThrough] = useState('')
  const [mode, setMode] = useState<PaidThroughMode>('paid')
  const [method, setMethod] = useState<Method>('cash')
  const [checked, setChecked] = useState(false)
  const quote = useQuery({ ...paidThroughQuery(membership.id, through), enabled: through !== '' })
  const total = quote.data?.total_clp ?? 0

  const record = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      recordPaidThrough(membership.id, {
        through,
        mode,
        total_clp: total,
        ...(mode === 'paid' ? { method } : {}),
      }),
    onSuccess: async (result) => {
      const day = shortDay(result.paid_through)
      onDone(mode === 'paid' ? form.done(clp(total), day) : form.doneGift(day))
      await queryClient.invalidateQueries({ queryKey: ['ledger'] })
    },
    // A total changed since the quote: read it again, so the one shown is the one to record.
    onError: async (error: Error) => {
      if (paidThroughRefused(error)?.code === 'amount_changed') {
        await queryClient.invalidateQueries({ queryKey: ['ledger', 'paid-through', membership.id] })
      }
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (quote.data) record.mutate()
  }

  /** What a refusal says; a date before the plan links to the Historial. */
  const refusal = (error: unknown, failed: string) => {
    const refused = paidThroughRefused(error)
    if (!refused) return <Banner tone="error">{failed}</Banner>
    if (refused.code === 'before_plan') {
      return (
        <Banner tone="error" as="div">
          <p>{refusedCopy.before_plan(shortDay(refused.started_on ?? membership.started_on))}</p>
          <a href="#member-history" className="tap-link">
            {form.history}
          </a>
        </Banner>
      )
    }
    if (refused.code === 'already_paid') {
      return <Banner tone="error">{refusedCopy.already_paid(shortDay(refused.paid_through ?? through))}</Banner>
    }
    return <Banner tone="error">{refusedCopy[refused.code]}</Banner>
  }

  return (
    <form className={cardClass({}, 'member__form')} aria-label={form.title} onSubmit={submit}>
      <p className="member__detail">{form.intro}</p>
      <label htmlFor={ids.through} className="member__label">
        {form.through}
      </label>
      <Input
        id={ids.through}
        type="date"
        value={through}
        aria-invalid={checked && through === ''}
        onChange={(e) => {
          setThrough(e.target.value)
          record.reset()
        }}
      />
      {checked && through === '' && <Banner tone="error">{form.dayNeeded}</Banner>}

      <fieldset className="member__choices">
        <legend className="member__label">{form.how}</legend>
        {MODES.map((value) => (
          <CheckRow start key={value} className="member__choice">
            <input type="radio" name={ids.mode} checked={mode === value} onChange={() => setMode(value)} />
            <span>
              <span className="member__choice-title">{form[value]}</span>
              <span className="member__detail">{value === 'paid' ? form.paidHint : form.giftHint}</span>
            </span>
          </CheckRow>
        ))}
      </fieldset>

      {mode === 'paid' && (
        <>
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
        </>
      )}

      {through !== '' && quote.isPending && (
        <Loading className="member__detail" role="status">
          {form.loading}
        </Loading>
      )}
      {quote.isError && refusal(quote.error, refusedCopy.quoteFailed)}
      {quote.data && (
        <>
          <p className="member__label">{form.quoteTitle}</p>
          <PlainList className="member__bill">
            {quote.data.periods.map((p) => (
              <li key={p.period_start}>{form.period(monthName(p.period_start), clp(p.amount_clp))}</li>
            ))}
            <li className="member__bill-total">{form.total(clp(total))}</li>
          </PlainList>
          <p className="member__detail" role="status">
            {form.result(shortDay(quote.data.paid_through))}
          </p>
        </>
      )}
      {record.error && refusal(record.error, refusedCopy.failed)}

      <div className="member__form-actions">
        <Button disabled={record.isPending} onClick={onCancel}>
          {form.cancel}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={record.isPending || (through !== '' && !quote.data)}
          busy={record.isPending}
        >
          {record.isPending ? form.working : mode === 'gift' ? form.submitGift : quote.data ? form.submit(clp(total)) : form.submitPaid}
        </Button>
      </div>
    </form>
  )
}
