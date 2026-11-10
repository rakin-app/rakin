import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import type { MembershipStart } from '../api/people'
import { plansQuery } from '../api/plans'
import { Input, Select } from '../components/Field'

/** A plan picked and the day it starts; no plan is `plan_id: ''`. */
export type PlanChoice = { plan_id: string; started_on: string }

/** What `choice` sends: nothing without a plan, and no day for today, which the API knows. */
export function membershipOf(choice: PlanChoice, today: string): MembershipStart | undefined {
  if (!choice.plan_id) return undefined
  const notToday = choice.started_on !== '' && choice.started_on !== today
  return { plan_id: choice.plan_id, ...(notToday && { started_on: choice.started_on }) }
}

/**
 * An optional plan, from a day: the gym's active plans, a drop-in aside (a single class,
 * not a membership). With no plan picked the day is not asked.
 */
export function PlanStart({
  choice,
  today,
  labels,
  onChange,
}: {
  choice: PlanChoice
  today: string
  labels: { plan: string; noPlan: string; startedOn: string }
  onChange: (choice: PlanChoice) => void
}) {
  const plans = useQuery(plansQuery)
  const ids = { plan: useId(), from: useId() }
  const offered = (plans.data ?? []).filter((plan) => plan.active && plan.kind !== 'dropin')
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
    </>
  )
}
