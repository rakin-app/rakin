import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Rank } from './grading'
import type { MembershipStatus } from './people'

/**
 * "Mis datos" (#371): everything the gym holds on the signed-in person, and on each
 * dependent in their care (backend `app.schemas.my_data`). The page reads it; the
 * download (`MY_DATA_DOWNLOAD`) is the same document as a file.
 */

export type Someone = { person_id: string; name: string }

export type MyRecord = {
  name: string
  rut: string | null
  email: string | null
  phone: string | null
  dob: string | null
  no_whatsapp: boolean
  member_since: string | null
  prior_classes: number | null
  left_on: string | null
  left_reason: string | null
  added_at: string
  updated_at: string
}

export type MyField = { key: string; label: string; value: unknown; sensitive: boolean; archived: boolean }

export type MyMembership = {
  id: string
  plan_name: string
  status: MembershipStatus
  started_at: string
  current_period_end: string | null
  credits_remaining: number | null
  discount_pct: number | null
  discount_reason: string | null
  next_plan_name: string | null
  next_plan_from: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  cancel_undone_at: string | null
  reactivated_at: string | null
  voided_at: string | null
  void_reason: string | null
  created_at: string
}

export type MyPlanEvent = { membership_id: string; kind: 'frozen' | 'unfrozen' | 'lapsed' | 'promoted'; occurred_on: string }

export type MyFreeze = { membership_id: string; from_date: string; to_date: string | null; reason: string | null; created_at: string }

export type MyFreezeRequest = {
  membership_id: string
  from_date: string
  to_date: string | null
  reason: string | null
  note: string | null
  status: 'pending' | 'approved' | 'rejected' | 'withdrawn'
  decision_note: string | null
  decided_at: string | null
  created_at: string
}

export type MyPeriod = {
  id: string
  membership_id: string
  plan_name: string
  period_start: string
  period_end: string
  due_date: string
  amount_due_clp: number
  discount_pct: number | null
  discount_reason: string | null
}

export type MyExtraCharge = {
  id: string
  title: string
  amount_due_clp: number
  due_date: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  created_at: string
}

export type MyEntry = {
  id: string
  kind: 'charge' | 'payment' | 'adjustment' | 'refund'
  status: 'pending' | 'validated' | 'rejected'
  amount_clp: number
  method: 'cash' | 'transfer' | 'other' | null
  billing_period_id: string | null
  extra_line_id: string | null
  purpose: string | null
  has_proof: boolean
  note: string | null
  claimed_at: string | null
  validated_at: string | null
  created_at: string
}

export type MyHistoryPayment = {
  id: string
  paid_on: string
  amount_clp: number
  method: 'cash' | 'transfer' | 'other' | null
  covers_month: string | null
  plan_name: string | null
  source: 'manual' | 'import'
  created_at: string
}

export type MyVisit = {
  session_id: string
  starts_at: string
  class_type_name: string
  program_name: string
  credits_consumed: number | null
  marked_at: string
}

export type MyGrade = Rank & { id: string }

export type MyRequirement = { id: string; requirement_name: string; done_on: string; recorded_at: string }

export type MyConsentEvent = {
  id: string
  action: 'notice_accepted' | 'consent_given' | 'consent_withdrawn'
  source: 'join' | 'page'
  by_name: string | null
  template_on: string | null
  details_on: string | null
  at: string
}

export type MyMessage = {
  id: string
  channel: 'email' | 'whatsapp'
  template: string
  to_address: string
  status: 'sent' | 'failed' | 'suppressed'
  error: string | null
  payload: Record<string, unknown> | null
  sent_at: string
}

export type MyStaff = {
  role: string
  account_holder: boolean
  titles: { title_name: string; starts_on: string; ends_on: string | null; public_contact: string | null }[]
  added_at: string
}

export type PersonData = {
  person_id: string
  record: MyRecord
  guardians: Someone[]
  dependents: Someone[]
  fields: MyField[]
  memberships: MyMembership[]
  plan_events: MyPlanEvent[]
  freezes: MyFreeze[]
  freeze_requests: MyFreezeRequest[]
  periods: MyPeriod[]
  extra_charges: MyExtraCharge[]
  entries: MyEntry[]
  history_payments: MyHistoryPayment[]
  attendance: MyVisit[]
  grades: MyGrade[]
  requirements: MyRequirement[]
  consents: MyConsentEvent[]
  messages: MyMessage[]
  charge_groups: string[]
  unsubscribed_at: string | null
  staff: MyStaff | null
}

export type MyData = {
  exported_at: string
  gym: {
    name: string
    // Where its days are: the moments above read in it.
    timezone: string
    // Who is responsible for the data and where to write; `null` until the gym fills it in.
    privacy: { legal_name: string; rut: string; email: string; address: string | null } | null
  }
  // The person signed in first, then each dependent.
  people: PersonData[]
}

export function myDataQuery() {
  return queryOptions({
    queryKey: ['me', 'data'],
    queryFn: () => apiFetch<MyData>('/api/me/data'),
  })
}

/** The same document as a file, `mis-datos-<gym>-<day>.json`: a plain link, the session's cookie its credential. */
export const MY_DATA_DOWNLOAD = '/api/me/data?download=1'
