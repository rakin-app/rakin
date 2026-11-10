import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

export const PLAN_KINDS = ['monthly', 'prepaid', 'credits', 'dropin', 'trial'] as const
export type PlanKind = (typeof PLAN_KINDS)[number]

// The day of the month a monthly plan bills on: the member's signup day, or the 1st.
export const ANCHORS = ['signup', 'first'] as const
export type Anchor = (typeof ANCHORS)[number]

type Base = {
  id: string
  name: string
  // The program the plan is for; none for a plan open to any class.
  program_id: string | null
  active: boolean
  created_at: string
}

/** One of the gym's plans (backend `Plan`): each kind carries exactly its own parameters. */
export type Plan =
  | (Base & { kind: 'monthly'; price_clp: number; anchor: Anchor })
  | (Base & { kind: 'prepaid'; price_clp: number; period_months: number })
  | (Base & { kind: 'credits'; price_clp: number; credits: number; credit_expiry_days: number })
  | (Base & { kind: 'dropin'; price_clp: number })
  // Free: lasts `free_classes` classes, `free_days` days, or whichever comes first.
  | (Base & { kind: 'trial'; free_classes: number | null; free_days: number | null })

/** A plan's own parameters as sent: a number, or text as typed for the API to refuse. */
export type PlanFields = Partial<{
  name: string
  program_id: string | null
  price_clp: number | string
  anchor: string
  period_months: number | string
  credits: number | string
  credit_expiry_days: number | string
  free_classes: number | string | null
  free_days: number | string | null
}>

/** Every plan, active ones first, then by name. Any staff role may read them. */
export const plansQuery = queryOptions({
  queryKey: ['plans'],
  queryFn: () => apiFetch<Plan[]>('/api/plans'),
})

export function createPlan(body: PlanFields & { kind: PlanKind }): Promise<Plan> {
  return apiFetch<Plan>('/api/plans', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change; there is no delete, `active: false` deactivates. */
export function updatePlan(planId: string, changes: PlanFields & { active?: boolean }): Promise<Plan> {
  return apiFetch<Plan>(`/api/plans/${encodeURIComponent(planId)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}
