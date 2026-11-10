import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { MembershipStatus } from './people'

/** This gym's record of a person (backend `Person`). */
export type Person = {
  id: string
  phone: string | null
  name: string
  email: string | null
  rut: string | null
  dob: string | null
  created_at: string
}

export type PlanKind = 'monthly' | 'prepaid' | 'credits' | 'dropin' | 'trial'

/** A freeze (backend `Freeze`): from its first day until `to_date`, the day it is Active again. */
export type Freeze = {
  id: string
  from_date: string
  to_date: string
  reason: string
}

/** A membership of a plan (backend `Membership`). */
export type Membership = {
  id: string
  plan_id: string
  plan_name: string
  plan_kind: PlanKind
  status: MembershipStatus
  // The day of the month a monthly plan bills on; null on every other kind.
  anchor_day: number | null
  started_on: string
  // Paid through, or the last day of a pack or trial.
  current_period_end: string | null
  credits_remaining: number | null
  // The freeze it is in, while frozen.
  freeze: Freeze | null
}

export type Method = 'cash' | 'transfer' | 'other'

export type OpenPeriod = {
  id: string
  period_start: string
  period_end: string
  due_date: string
  amount_due_clp: number
  paid_clp: number
  outstanding_clp: number
  // Due today or before: what `owed_clp` counts.
  due: boolean
  // 0 on or before the due date.
  days_overdue: number
}

export type TimelineEntry = {
  id: string
  kind: 'charge' | 'payment' | 'adjustment' | 'refund'
  status: 'pending' | 'validated' | 'rejected'
  // Signed on an adjustment: positive in the member's favour, negative owed.
  amount_clp: number
  method: Method | null
  billing_period_id: string | null
  period_start: string | null
  note: string | null
  created_at: string
  validated_by_name: string | null
  validated_at: string | null
  // The payment a refund gives back; null on every other kind.
  refund_of: string | null
  // What is left to give back of a validated payment; null on every other entry.
  refundable_clp: number | null
}

/** A freeze starting or ending, a ledger line with no amount (backend `FreezeLine`). */
export type FreezeLine = {
  freeze_id: string
  edge: 'start' | 'end'
  // The day it started or ended; today at the latest.
  day: string
  from_date: string
  to_date: string
  reason: string
}

/** One membership's money (backend `MembershipLedger`). Owner and admin only. */
export type MembershipLedger = {
  // Oldest first: the first is the one a payment settles next.
  open_periods: OpenPeriod[]
  // Outstanding on the open periods due today or before.
  owed_clp: number
  // Newest first.
  entries: TimelineEntry[]
  // Each freeze's start and end so far, newest first.
  freezes: FreezeLine[]
}

export type PaymentRecord = {
  membership_id: string
  billing_period_id: string
  amount_clp: number
  method: Method
  note?: string
}

/** A period as an entry just recorded leaves it (backend `Period`). */
export type SettledPeriod = { outstanding_clp: number; closed: boolean }

export type RecordedPayment = {
  credit: { amount_clp: number } | null
  period: SettledPeriod
}

/** An adjustment to what a period owes: positive in the member's favour, negative owed. */
export type AdjustmentRecord = {
  membership_id: string
  billing_period_id: string
  amount_clp: number
  note: string
}

export type RecordedAdjustment = { period: SettledPeriod }

/** Part or all of a validated payment, given back. */
export type RefundRecord = {
  payment_id: string
  amount_clp: number
  method: Method
  note?: string
}

export type RecordedRefund = { period: SettledPeriod }

export function personQuery(id: string) {
  return queryOptions({
    queryKey: ['people', 'detail', id],
    queryFn: () => apiFetch<Person>(`/api/people/${encodeURIComponent(id)}`),
  })
}

export function membershipsQuery(personId: string) {
  return queryOptions({
    queryKey: ['memberships', { person: personId }],
    queryFn: () => apiFetch<Membership[]>(`/api/memberships?person_id=${encodeURIComponent(personId)}`),
  })
}

export function membershipLedgerQuery(membershipId: string) {
  return queryOptions({
    queryKey: ['ledger', 'membership', membershipId],
    queryFn: () => apiFetch<MembershipLedger>(`/api/ledger/memberships/${encodeURIComponent(membershipId)}`),
  })
}

export function recordPayment(body: PaymentRecord): Promise<RecordedPayment> {
  return apiFetch<RecordedPayment>('/api/ledger/payments', { method: 'POST', body: JSON.stringify(body) })
}

export function recordAdjustment(body: AdjustmentRecord): Promise<RecordedAdjustment> {
  return apiFetch<RecordedAdjustment>('/api/ledger/adjustments', { method: 'POST', body: JSON.stringify(body) })
}

export function recordRefund(body: RefundRecord): Promise<RecordedRefund> {
  return apiFetch<RecordedRefund>('/api/ledger/refunds', { method: 'POST', body: JSON.stringify(body) })
}

export type FreezeRequest = { to_date: string; reason: string }

/** Freeze from today until `to_date`: the due date moves past the frozen days. */
export function freezeMembership(membershipId: string, body: FreezeRequest): Promise<Membership> {
  return apiFetch<Membership>(`/api/memberships/${encodeURIComponent(membershipId)}/freeze`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** The membership the detail shows, as the member list does: the latest one not
 * cancelled, else the latest. `memberships` comes latest first. */
export function shownMembership(memberships: readonly Membership[]): Membership | undefined {
  return memberships.find((m) => m.status !== 'cancelled') ?? memberships[0]
}
