import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { PersonRef } from './ledger'
import type { Method } from './member'

/** A cobro extra's kind (#195), which the book and Cobrado label it by. */
export const CATEGORIES = ['rifa', 'seminario', 'equipamiento', 'gasto_compartido', 'otro'] as const
export type Category = (typeof CATEGORIES)[number]

/** `fixed`: the amount from each person. `split`: the amount in all, divided among them. */
export type AmountMode = 'fixed' | 'split'

export type TargetKind = 'active' | 'program' | 'group' | 'people'

/** Whom a cobro is for: each kind names only what it needs. */
export type Target =
  | { kind: 'active' }
  | { kind: 'program'; program_id: string }
  | { kind: 'group'; group_id: string }
  | { kind: 'people'; person_ids: string[] }

/** A line's status: pendiente, comprobante enviado, pagado, exento ($0) or anulado. */
export type LineStatus = 'open' | 'in_review' | 'paid' | 'waived' | 'cancelled'

export type Override = { person_id: string; amount_clp: number }

/** The wizard's draft: what the preview reads and the create sends. */
export type Draft = {
  title: string
  description: string
  message: string
  category: Category
  due_date: string
  target: Target
  amount_mode: AmountMode
  amount_clp: number
  overrides: Override[]
  notify: boolean
}

export type PreviewLine = {
  person: PersonRef
  amount_clp: number
  overridden: boolean
  // Whom the notice goes to: them, or their guardian.
  contact_name: string
  on_behalf: boolean
  has_email: boolean
  // For someone with no email, once the draft has a title and due date.
  whatsapp_url: string | null
}

export type Preview = {
  lines: PreviewLine[]
  total_clp: number
  // A split's remainder: a peso more each for the first `remainder_clp` people.
  remainder_clp: number
  share_clp: number | null
}

export type RefundableLinePayment = {
  id: string
  amount_clp: number
  method: Method | null
  validated_at: string | null
  refundable_clp: number
}

export type Line = {
  id: string
  person: PersonRef
  guardian: PersonRef | null
  amount_due_clp: number
  overridden: boolean
  paid_clp: number
  outstanding_clp: number
  pending_clp: number
  status: LineStatus
  cancelled_at: string | null
  // Why it was cancelled (#256); null on a line cancelled before reasons were asked.
  cancel_reason?: string | null
  has_email: boolean
  // A reminder on WhatsApp, on a line still owed, when the gym uses it.
  whatsapp_url: string | null
  pending_proof_id: string | null
  refundable_payments: RefundableLinePayment[]
}

export type ExtraChargeSummary = {
  id: string
  title: string
  category: Category
  due_date: string
  amount_mode: AmountMode
  amount_clp: number
  target_kind: TargetKind
  target_label: string | null
  created_at: string
  // Lines owing something, and of them those paid: "7 de 9 pagaron". Exentos apart.
  lines: number
  paid_lines: number
  waived_lines: number
  due_clp: number
  collected_clp: number
}

export type ExtraCharge = ExtraChargeSummary & {
  description: string | null
  message: string | null
  people: Line[]
}

export type CancelPreview = { resplit_allowed: boolean; amounts: Record<string, number> }

export type Reminded = { sent: number; without_email: number }

/** A cobro line the signed-in person (or the ficha's) can pay. */
export type MyExtraLine = {
  id: string
  extra_charge_id: string
  title: string
  category: Category
  message: string | null
  due_date: string
  person_id: string
  person_name: string
  amount_due_clp: number
  paid_clp: number
  outstanding_clp: number
  pending_clp: number
  status: LineStatus
}

export type GroupSummary = { id: string; name: string; size: number }
export type Group = { id: string; name: string; members: PersonRef[] }

const BASE = '/api/extra-charges'
const enc = encodeURIComponent

/** What the preview takes: the draft so far, its amounts and, once given, title and day. */
export function previewBody(draft: Draft) {
  return {
    target: draft.target,
    amount_mode: draft.amount_mode,
    amount_clp: draft.amount_clp,
    overrides: draft.overrides,
    title: draft.title.trim() || null,
    due_date: draft.due_date || null,
  }
}

export function previewCharge(draft: Draft): Promise<Preview> {
  return apiFetch<Preview>(`${BASE}/preview`, { method: 'POST', body: JSON.stringify(previewBody(draft)) })
}

export function createCharge(draft: Draft): Promise<ExtraCharge> {
  const { description, message, title, ...rest } = draft
  return apiFetch<ExtraCharge>(BASE, {
    method: 'POST',
    body: JSON.stringify({
      ...rest,
      title: title.trim(),
      description: description.trim() || null,
      message: message.trim() || null,
    }),
  })
}

export function chargesQuery() {
  return queryOptions({ queryKey: ['extra', 'list'], queryFn: () => apiFetch<ExtraChargeSummary[]>(BASE) })
}

export function chargeQuery(id: string) {
  return queryOptions({ queryKey: ['extra', 'charge', id], queryFn: () => apiFetch<ExtraCharge>(`${BASE}/${enc(id)}`) })
}

const linePath = (charge: string, line: string) => `${BASE}/${enc(charge)}/lines/${enc(line)}`

export function changeLineAmount(charge: string, line: string, amount: number): Promise<Line> {
  return apiFetch<Line>(linePath(charge, line), { method: 'PATCH', body: JSON.stringify({ amount_clp: amount }) })
}

export function cancelPreview(charge: string, line: string): Promise<CancelPreview> {
  return apiFetch<CancelPreview>(`${linePath(charge, line)}/cancel`)
}

/** Anular a line, with the reason it needs (#256). */
export function cancelLine(charge: string, line: string, resplit: boolean, reason: string): Promise<ExtraCharge> {
  return apiFetch<ExtraCharge>(`${linePath(charge, line)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ resplit, reason }),
  })
}

export function payLine(charge: string, line: string, amount: number, method: Method): Promise<unknown> {
  return apiFetch(`${linePath(charge, line)}/payments`, {
    method: 'POST',
    body: JSON.stringify({ amount_clp: amount, method }),
  })
}

export function notifyLine(charge: string, line: string): Promise<Reminded> {
  return apiFetch<Reminded>(`${linePath(charge, line)}/notify`, { method: 'POST' })
}

export function remindPending(charge: string): Promise<Reminded> {
  return apiFetch<Reminded>(`${BASE}/${enc(charge)}/remind`, { method: 'POST' })
}

export function refundPayment(payment: string, amount: number, method: Method): Promise<unknown> {
  return apiFetch('/api/ledger/refunds', {
    method: 'POST',
    body: JSON.stringify({ payment_id: payment, amount_clp: amount, method }),
  })
}

/** "Cobros extra pendientes" on a member's ficha. */
export function personLinesQuery(personId: string) {
  return queryOptions({
    queryKey: ['extra', 'person', personId],
    queryFn: () => apiFetch<MyExtraLine[]>(`/api/people/${enc(personId)}/extra-lines`),
  })
}

/** The signed-in person's, and their dependents', still owed. */
export function myLinesQuery() {
  return queryOptions({ queryKey: ['me', 'extra-lines'], queryFn: () => apiFetch<MyExtraLine[]>('/api/me/extra-lines') })
}

export function groupsQuery() {
  return queryOptions({ queryKey: ['groups', 'list'], queryFn: () => apiFetch<GroupSummary[]>('/api/groups') })
}

export function groupQuery(id: string) {
  return queryOptions({ queryKey: ['groups', id], queryFn: () => apiFetch<Group>(`/api/groups/${enc(id)}`) })
}

export function saveGroup(id: string | null, name: string, personIds: string[]): Promise<Group> {
  return apiFetch<Group>(id ? `/api/groups/${enc(id)}` : '/api/groups', {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify({ name: name.trim(), person_ids: personIds }),
  })
}

export function deleteGroup(id: string): Promise<void> {
  return apiFetch<void>(`/api/groups/${enc(id)}`, { method: 'DELETE' })
}

/** "7 de 9 pagaron": how far along a cobro is. */
export function progress(charge: ExtraChargeSummary): number {
  return charge.lines === 0 ? 1 : charge.paid_lines / charge.lines
}
