import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { MembershipStatus } from './people'

/** This gym's record of a person (backend `Person`). */
export type Person = {
  id: string
  // A contact, this gym's: what WhatsApp links go to. Never who they are.
  phone: string | null
  // "No tiene WhatsApp": no WhatsApp link goes to them (#165).
  no_whatsapp: boolean
  // A member with no phone and the box unticked: "Falta teléfono".
  missing_phone: boolean
  // No RUT and no email, found again only by name: "Falta RUT".
  missing_rut: boolean
  name: string
  email: string | null
  rut: string | null
  dob: string | null
  // The day they left the gym (dado de baja); null while they are here.
  left_on: string | null
  created_at: string
}

export type PlanKind = 'monthly' | 'prepaid' | 'credits' | 'dropin' | 'trial'

/** A freeze (backend `Freeze`): from its first day until `to_date`, the day it is Active again. */
export type Freeze = {
  id: string
  from_date: string
  to_date: string
  reason: string
  // False on a freeze booked ahead, until it starts on `from_date`.
  started: boolean
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
  // The freeze it is in, while frozen; the one booked ahead, while active.
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
}

/** A billing period, open or paid: one an adjustment may go to (backend `LedgerPeriod`). */
export type LedgerPeriod = {
  id: string
  period_start: string
  period_end: string
  // 0 once paid.
  outstanding_clp: number
}

/** A validated payment with something left to give back (backend `RefundablePayment`). */
export type RefundablePayment = {
  id: string
  billing_period_id: string
  period_start: string
  amount_clp: number
  method: Method | null
  validated_at: string | null
  refundable_clp: number
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
  // Every period, and every payment with something left to give back, newest first;
  // not cut to the latest entries as `entries` is.
  periods: LedgerPeriod[]
  refundable_payments: RefundablePayment[]
  // The last day its periods are paid through, none owing before it: "Pagado hasta".
  // Null with no period yet, or with the first one still owing.
  paid_through: string | null
}

/** A period paying ahead would bill, not written yet (backend `AheadPeriod`, #196). */
export type AheadPeriod = { period_start: string; period_end: string; amount_due_clp: number }

/** The next periods after the last one billed, oldest first; empty when the membership
 *  cannot pay ahead: not active, not monthly or prepaid, or with a period still open. */
export type AheadQuote = { periods: AheadPeriod[] }

export type PaymentAheadRecord = {
  membership_id: string
  periods: number
  // What those periods cost, as the quote said; anything else is a 409.
  amount_clp: number
  method: Method
  note?: string
}

export type RecordedAhead = { paid_through: string }

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

export function aheadQuery(membershipId: string) {
  return queryOptions({
    queryKey: ['ledger', 'ahead', membershipId],
    queryFn: () => apiFetch<AheadQuote>(`/api/ledger/memberships/${encodeURIComponent(membershipId)}/ahead`),
  })
}

export function recordPaymentAhead(body: PaymentAheadRecord): Promise<RecordedAhead> {
  return apiFetch<RecordedAhead>('/api/ledger/payments/ahead', { method: 'POST', body: JSON.stringify(body) })
}

export function recordAdjustment(body: AdjustmentRecord): Promise<RecordedAdjustment> {
  return apiFetch<RecordedAdjustment>('/api/ledger/adjustments', { method: 'POST', body: JSON.stringify(body) })
}

export function recordRefund(body: RefundRecord): Promise<RecordedRefund> {
  return apiFetch<RecordedRefund>('/api/ledger/refunds', { method: 'POST', body: JSON.stringify(body) })
}

// `from_date` is today when omitted; a later day books the freeze ahead.
export type FreezeRequest = { from_date?: string; to_date: string; reason: string }

function freezePath(membershipId: string): string {
  return `/api/memberships/${encodeURIComponent(membershipId)}/freeze`
}

/** Freeze from `from_date` until `to_date`: the due date moves past the frozen days as it starts. */
export function freezeMembership(membershipId: string, body: FreezeRequest): Promise<Membership> {
  return apiFetch<Membership>(freezePath(membershipId), { method: 'POST', body: JSON.stringify(body) })
}

export type FreezeEdit = { to_date?: string; reason?: string }

/** A new end or reason for the freeze running or booked; the due date moves by the days it gains or loses. */
export function editFreeze(membershipId: string, body: FreezeEdit): Promise<Membership> {
  return apiFetch<Membership>(freezePath(membershipId), { method: 'PATCH', body: JSON.stringify(body) })
}

/** End the freeze running today, the due date moved back by the days left; a booked one is called off. */
export function endFreeze(membershipId: string): Promise<Membership> {
  return apiFetch<Membership>(`${freezePath(membershipId)}/end`, { method: 'POST' })
}

/** The membership the detail shows, as the member list does: the latest one not
 * cancelled, else the latest. `memberships` comes latest first. */
export function shownMembership(memberships: readonly Membership[]): Membership | undefined {
  return memberships.find((m) => m.status !== 'cancelled') ?? memberships[0]
}
