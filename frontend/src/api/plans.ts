import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

export const PLAN_KINDS = ['monthly', 'prepaid', 'fixed_period', 'credits', 'dropin', 'trial'] as const
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

// The matrícula a membership starting on the plan is charged once, as a cobro extra (#355);
// none when null. A plan a member joins and pays on again may have one; a drop-in or a
// trial never. Money, so a coach's plans come without it.
type Enrolment = { enrolment_fee_clp?: number | null }

/** One of the gym's plans (backend `Plan`): each kind carries exactly its own parameters. */
export type Plan =
  | (Base & Enrolment & { kind: 'monthly'; price_clp: number; anchor: Anchor })
  | (Base & Enrolment & { kind: 'prepaid'; price_clp: number; period_months: number })
  // The same days for every member: a season, a year, a term (#351), as `2027-03-01`.
  | (Base & Enrolment & { kind: 'fixed_period'; price_clp: number; period_start: string; period_end: string })
  | (Base & Enrolment & { kind: 'credits'; price_clp: number; credits: number; credit_expiry_days: number })
  | (Base & { kind: 'dropin'; price_clp: number })
  // Free: lasts `free_classes` classes, `free_days` days, or whichever comes first.
  | (Base & { kind: 'trial'; free_classes: number | null; free_days: number | null })

/** A plan's own parameters as sent: a number, or text as typed for the API to refuse. */
export type PlanFields = Partial<{
  name: string
  program_id: string | null
  price_clp: number | string
  enrolment_fee_clp: number | string | null
  anchor: string
  period_months: number | string
  period_start: string
  period_end: string
  credits: number | string
  credit_expiry_days: number | string
  free_classes: number | string | null
  free_days: number | string | null
}>

/** Every plan, active ones first, then by name. Any staff role may read them; a coach's
 * come without `price_clp` (#205), so only the owner's and admin's screens read it. */
export const plansQuery = queryOptions({
  queryKey: ['plans'],
  queryFn: () => apiFetch<Plan[]>('/api/plans'),
})

export function createPlan(body: PlanFields & { kind: PlanKind }): Promise<Plan> {
  return apiFetch<Plan>('/api/plans', { method: 'POST', body: JSON.stringify(body) })
}

/** Only the fields sent change; there is no delete, `active: false` deactivates. With a
 * monthly plan's `anchor`, `move_members` moves the members on it to the day it gives
 * them from their next period (#547), as `anchorMovesQuery` quotes it. */
export function updatePlan(
  planId: string,
  changes: PlanFields & { active?: boolean; move_members?: boolean },
): Promise<Plan> {
  return apiFetch<Plan>(`/api/plans/${encodeURIComponent(planId)}`, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

/** A membership on a plan now, active or frozen: the plan's list (`GET /api/plans/{id}/memberships`). */
export type PlanMembership = {
  membership_id: string
  person_id: string
  name: string
  status: 'active' | 'frozen'
  // A change to another plan already pending, which moving it replaces.
  next_plan_name: string | null
}

export const planMembershipsQuery = (planId: string) =>
  queryOptions({
    queryKey: ['plans', planId, 'memberships'],
    queryFn: () => apiFetch<PlanMembership[]>(`/api/plans/${encodeURIComponent(planId)}/memberships`),
  })

export type NextPeriod = {
  name: string
  price_clp: number | string
  period_start: string
  period_end: string
  membership_ids: string[]
}

/** "Duplicar para el próximo período" (#351): a copy of a fixed-period plan with the
 * next period's dates, and the memberships chosen moved to it from the day after they
 * are paid through. */
export function nextPeriod(planId: string, body: NextPeriod): Promise<{ plan: Plan; moved: number }> {
  return apiFetch(`/api/plans/${encodeURIComponent(planId)}/next-period`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** A member on a monthly plan as changing its anchor would move them (#547), from their
 * next period not billed: the day they pay on and the one they would, the transition
 * period to it, prorated, and the first whole period on the new day, after any discount. */
export type AnchorMove = {
  membership_id: string
  person_id: string
  name: string
  status: 'active' | 'frozen'
  from_day: number
  to_day: number
  starts_on: string
  ends_on: string
  amount_due_clp: number
  next_starts_on: string
  next_amount_clp: number
}

export const anchorMovesQuery = (planId: string, anchor: Anchor) =>
  queryOptions({
    queryKey: ['plans', planId, 'anchor-moves', anchor],
    queryFn: () =>
      apiFetch<AnchorMove[]>(
        `/api/plans/${encodeURIComponent(planId)}/anchor-moves?anchor=${encodeURIComponent(anchor)}`,
      ),
  })
