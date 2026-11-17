import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import type { MembershipStart } from '../api/people'
import { plansQuery } from '../api/plans'
import { Input, Select } from '../components/Field'
import { CheckRow } from '../components/Card'
import { t } from '../i18n/es'

/** A plan picked and the day it starts; no plan is `plan_id: ''`. `enrolment_paid`: "ya
 * pagó matrícula", ticked on a plan with an enrolment fee (#355). */
export type PlanChoice = { plan_id: string; started_on: string; enrolment_paid?: boolean }

/** What `choice` sends: nothing without a plan, no day for today, which the API knows,
 * and the plan's matrícula unless it was paid already. */
export function membershipOf(choice: PlanChoice, today: string): MembershipStart | undefined {
  if (!choice.plan_id) return undefined
  const notToday = choice.started_on !== '' && choice.started_on !== today
  return {
    plan_id: choice.plan_id,
    ...(notToday && { started_on: choice.started_on }),
    ...(choice.enrolment_paid && { charge_enrolment: false }),
  }
}

/**
 * An optional plan, from a day: the gym's active plans, a drop-in aside (a single class,
 * not a membership). With no plan picked the day is not asked. With `enrolment`, a plan
 * with a matrícula says so and offers "Ya pagó la matrícula" (#355); Reactivar has none,
 * since they paid it when they first joined.
 */
export function PlanStart({
  choice,
  today,
  labels,
  enrolment = false,
  onChange,
}: {
  choice: PlanChoice
  today: string
  labels: { plan: string; noPlan: string; startedOn: string }
  enrolment?: boolean
  onChange: (choice: PlanChoice) => void
}) {
  const plans = useQuery(plansQuery)
  const ids = { plan: useId(), from: useId(), paid: useId(), fee: useId() }
  const offered = (plans.data ?? []).filter((plan) => plan.active && plan.kind !== 'dropin')
  const picked = offered.find((plan) => plan.id === choice.plan_id)
  const fee = (enrolment && picked && 'enrolment_fee_clp' in picked && picked.enrolment_fee_clp) || null
  const words = t.admin.member.enrolment
  return (
    <>
      <label htmlFor={ids.plan} className="member__label">
        {labels.plan}
      </label>
      <Select
        id={ids.plan}
        value={choice.plan_id}
        onChange={(e) => onChange({ ...choice, plan_id: e.target.value })}
      >
        <option value="">{labels.noPlan}</option>
        {offered.map((plan) => (
          <option key={plan.id} value={plan.id}>
            {plan.name}
          </option>
        ))}
      </Select>
      {choice.plan_id && (
        <>
          <label htmlFor={ids.from} className="member__label">
            {labels.startedOn}
          </label>
          <Input
            id={ids.from}
            type="date"
            value={choice.started_on || today}
            onChange={(e) => onChange({ ...choice, started_on: e.target.value })}
          />
        </>
      )}
      {fee !== null && (
        <>
          <CheckRow htmlFor={ids.paid}>
            <input
              id={ids.paid}
              type="checkbox"
              checked={choice.enrolment_paid ?? false}
              aria-describedby={ids.fee}
              onChange={(e) => onChange({ ...choice, enrolment_paid: e.target.checked })}
            />
            {words.paid}
          </CheckRow>
          <p id={ids.fee} className="member__detail">
            {choice.enrolment_paid ? words.notCharged(t.common.clp(fee)) : words.charged(t.common.clp(fee))}
          </p>
        </>
      )}
    </>
  )
}
