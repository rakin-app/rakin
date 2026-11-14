import { useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import {
  FREEZE_REASONS,
  freezeRefusal,
  requestFreeze,
  withdrawFreezeRequest,
  type FreezeReason,
} from '../api/freezeRequests'
import { myPageQuery, type MyPage, type MyPlan } from '../api/me'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { StatusPill } from '../components/StatusPill'
import { addDays, isoDay } from '../format'
import { t } from '../i18n/es'
import './MyPlans.css'

const copy = t.me.plans

/**
 * "Mi plan" (#270): each running plan, theirs and their dependents', with its freeze,
 * and "Pedir congelamiento" on an Active one with none running or booked: dates, a
 * reason and a note, for the owner or an admin to approve. While it waits it reads
 * "Solicitud enviada · pendiente", with "Retirar" for whoever sent it; once answered,
 * the answer, with the academy's note on a rejection.
 */
export function MyPlans({ page }: { page: MyPage }) {
  const titleId = useId()
  const plans = page.plans ?? []
  if (plans.length === 0) return null
  const today = isoDay(new Date().toISOString(), page.timezone)
  return (
    <section className="my-plans" aria-labelledby={titleId}>
      <h2 id={titleId} className="history__title">
        {copy.title}
      </h2>
      <ul className="my-plans__list">
        {plans.map((plan) => (
          <PlanRow key={plan.membership_id} plan={plan} me={page.person_id} today={today} />
        ))}
      </ul>
    </section>
  )
}

function PlanRow({ plan, me, today }: { plan: MyPlan; me: string; today: string }) {
  const [asking, setAsking] = useState(false)
  const queryClient = useQueryClient()
  const pending = plan.pending_request
  const decided = pending ? null : plan.last_decided
  const freeze = plan.freeze
  const withdraw = useSubmit({
    offline: 'refuse',
    mutationFn: (id: string) => withdrawFreezeRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: myPageQuery().queryKey }),
  })
  const asks = plan.status === 'active' && !freeze && !pending

  return (
    <li className="my-plans__row" aria-label={plan.plan_name}>
      <div className="my-plans__top">
        <span className="my-plans__name">
          {plan.person_id === me ? plan.plan_name : `${plan.plan_name} · ${copy.theirs(plan.person_name)}`}
        </span>
        <StatusPill status={plan.status}>{copy.status[plan.status]}</StatusPill>
      </div>
      {freeze && (
        <p className="my-plans__detail">
          {freeze.started
            ? copy.frozen(t.common.longDay(freeze.to_date))
            : copy.booked(t.common.longDay(freeze.from_date), t.common.longDay(freeze.to_date))}
        </p>
      )}
      {pending && (
        <div className="my-plans__request" role="status">
          <span className="my-plans__state">{copy.pending}</span>
          <span className="my-plans__detail">
            {copy.pendingDates(t.common.longDay(pending.from_date), t.common.longDay(pending.to_date))}
          </span>
          {pending.requested_by === me && (
            <Button
              aria-label={copy.withdrawLabel}
              disabled={withdraw.isPending}
              busy={withdraw.isPending}
              onClick={() => withdraw.mutate(pending.id)}
            >
              {withdraw.isPending ? copy.withdrawing : copy.withdraw}
            </Button>
          )}
          {withdraw.error && (
            <p className="my-plans__error" role="alert">
              {copy.withdrawFailed}
            </p>
          )}
        </div>
      )}
      {decided?.status === 'approved' && <p className="my-plans__detail">{copy.approved}</p>}
      {decided?.status === 'rejected' && (
        <div className="my-plans__request my-plans__request--rejected">
          <span className="my-plans__detail">
            {copy.rejected(t.common.longDay(decided.from_date), t.common.longDay(decided.to_date))}
          </span>
          {decided.decision_note && (
            <p className="my-plans__note">{copy.rejectedNote(decided.decision_note)}</p>
          )}
        </div>
      )}
      {asks && !asking && (
        <Button aria-label={copy.askLabel(plan.plan_name)} onClick={() => setAsking(true)}>
          {copy.ask}
        </Button>
      )}
      {asks && asking && <AskForm plan={plan} today={today} onDone={() => setAsking(false)} />}
    </li>
  )
}

function AskForm({ plan, today, onDone }: { plan: MyPlan; today: string; onDone: () => void }) {
  const queryClient = useQueryClient()
  const ids = { from: useId(), until: useId(), hint: useId(), reason: useId(), note: useId() }
  const [from, setFrom] = useState(today)
  const [until, setUntil] = useState('')
  const [reason, setReason] = useState<FreezeReason | ''>('')
  const [note, setNote] = useState('')
  const [checked, setChecked] = useState(false)
  const fromOk = from >= today
  const untilOk = until > from
  const reasonOk = reason !== ''
  const noteOk = reason !== 'otro' || note.trim() !== ''

  const send = useSubmit({
    offline: 'refuse',
    mutationFn: () =>
      requestFreeze({
        membership_id: plan.membership_id,
        from_date: from,
        to_date: until,
        reason: reason as FreezeReason,
        ...(note.trim() ? { note: note.trim() } : {}),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: myPageQuery().queryKey })
      onDone()
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setChecked(true)
    if (fromOk && untilOk && reasonOk && noteOk) send.mutate()
  }

  const refusal = send.error ? freezeRefusal(send.error) : null
  return (
    <form className="my-plans__form" aria-label={copy.formTitle} onSubmit={submit} noValidate>
      <p className="my-plans__detail">{copy.intro}</p>
      <div className="my-plans__dates">
        <div className="my-plans__field">
          <label htmlFor={ids.from} className="my-plans__label">
            {copy.from}
          </label>
          <Input
            id={ids.from}
            type="date"
            min={today}
            value={from}
            aria-invalid={checked && !fromOk}
            onChange={(e) => setFrom(e.target.value)}
          />
        </div>
        <div className="my-plans__field">
          <label htmlFor={ids.until} className="my-plans__label">
            {copy.until}
          </label>
          <Input
            id={ids.until}
            type="date"
            min={addDays(fromOk ? from : today, 1)}
            value={until}
            aria-invalid={checked && !untilOk}
            onChange={(e) => setUntil(e.target.value)}
          />
        </div>
      </div>
      {checked && !fromOk && (
        <p className="my-plans__error" role="alert">
          {copy.fromNeeded}
        </p>
      )}
      {checked && !untilOk && (
        <p className="my-plans__error" role="alert">
          {copy.untilNeeded}
        </p>
      )}

      <label htmlFor={ids.reason} className="my-plans__label">
        {copy.reason}
      </label>
      <Select
        id={ids.reason}
        value={reason}
        aria-invalid={checked && !reasonOk}
        onChange={(e) => setReason(e.target.value as FreezeReason | '')}
      >
        <option value="">{copy.reasonPick}</option>
        {FREEZE_REASONS.map((each) => (
          <option key={each} value={each}>
            {copy.reasons[each]}
          </option>
        ))}
      </Select>
      {checked && !reasonOk && (
        <p className="my-plans__error" role="alert">
          {copy.reasonNeeded}
        </p>
      )}

      <label htmlFor={ids.note} className="my-plans__label">
        {reason === 'otro' ? copy.noteOther : copy.note}
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
        <p className="my-plans__error" role="alert">
          {copy.noteNeeded}
        </p>
      )}

      {send.error && (
        <p className="my-plans__error" role="alert">
          {refusal ? copy.refused[refusal] : copy.refused.failed}
        </p>
      )}
      <div className="my-plans__actions">
        <Button disabled={send.isPending} onClick={onDone}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={send.isPending} busy={send.isPending}>
          {send.isPending ? copy.working : copy.submit}
        </Button>
      </div>
    </form>
  )
}
