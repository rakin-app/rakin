import { queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'
import type { MembershipStart, MembershipStatus } from './people'

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
  // A minor by birth date with no guardian here: nothing is sent to them until one is
  // added, "Falta apoderado" (#368).
  missing_guardian: boolean
  name: string
  email: string | null
  rut: string | null
  dob: string | null
  // The day they left the gym (dado de baja); null while they are here.
  left_on: string | null
  // Why they left (#294), as the gym wrote it. Owner and admin only: a coach always
  // reads null, since it is personal. Never health data (#384), though the text is the gym's.
  left_reason?: string | null
  // History from before Rakin (#293): the day they first trained here, and how many
  // classes they had. Shown on the ficha, never read by billing.
  member_since: string | null
  prior_classes: number
  created_at: string
}

export type PlanKind = 'monthly' | 'prepaid' | 'fixed_period' | 'credits' | 'dropin' | 'trial'

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
  // A plan change waiting for the first period not yet billed (#249).
  next_plan: PendingPlanChange | null
  // The freeze it is in, while frozen; the one booked ahead, while active.
  freeze: Freeze | null
  // Voided as started by mistake (#256): cancelled as of its start, its unpaid charges voided.
  voided_at?: string | null
  void_reason?: string | null
  // The trial this plan converted (#27); null on a trial and on a plan with none.
  converted_from?: ConvertedTrial | null
  // A percentage off every period, and why (#25); left out for a coach, who sees no money.
  discount_pct?: number
  discount_reason?: string | null
}

/** A trial a paid plan converted, or would (backend `ConvertedTrial`, #27); `running`: the
 * plan starting ends it. */
export type ConvertedTrial = { id: string; plan_name: string; started_on: string; running: boolean }

/** A fixed percentage off every period a membership bills, and why (backend `Discount`, #25). */
export type Discount = { pct: number; reason: string }

/** A plan change saved, from `starts_on`, the first day not yet billed (backend `PendingPlanChange`). */
export type PendingPlanChange = { plan_id: string; plan_name: string; starts_on: string }

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
  // Why a correction was written (#278): `void`, `restore`, …; null on other entries.
  purpose?: Purpose | null
  // An adjustment voiding its period's charge (#256), its reason in `note`.
  voids?: boolean
  // On a charge whose period's void stands: why, by whom and when.
  voided?: Voided | null
  // On a charge whose period had a void restored, the latest (#278).
  restored?: Restored | null
  // The discount its period was billed at, and why (#25); 0 and null with none.
  discount_pct?: number
  discount_reason?: string | null
  // On either half of a payment moved (#280): the other half's period, plan and person.
  moved?: MovedWith | null
  // On an adjustment reverted (#282): why, by whom and when.
  reverted?: Voided | null
}

/** The other half of a payment moved (backend `MovedWith`, #280). */
export type MovedWith = {
  billing_period_id: string
  period_start: string
  membership_id: string
  plan_name: string
  person_id: string
  person_name: string
}

/** What a correcting entry is for (backend `Purpose`, #278). */
export type Purpose = 'void' | 'restore' | 'revert' | 'write_off' | 'move' | 'mistake'

/** A charge's void (backend `Voided`, #256): "Anulado: <motivo>, por <quien>, <fecha>". */
export type Voided = { reason: string; by_name: string | null; at: string }

/** A charge's void, restored (backend `Restored`, #278): "Anulado: … · Restaurado: …". */
export type Restored = Voided & { void: Voided }

/** A billing period, open or paid: one an adjustment may go to (backend `LedgerPeriod`). */
export type LedgerPeriod = {
  id: string
  period_start: string
  period_end: string
  // 0 once paid.
  outstanding_clp: number
  // What the void of its charge took off (#256), 0 if none or once restored, and that
  // void, which "Restaurar cargo" restores (#278).
  voided_clp: number
  void_id: string | null
  // What it charges, its adjustments taken off but not its payments: what "Cambiar
  // monto" changes (#279).
  charged_clp: number
  // When it falls due, and, once "Mover vencimiento" moved it (#283), the due date it was
  // billed with; null if never moved, or if a freeze moved it since.
  due_date: string
  due_date_was: string | null
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
  // Its running balance, owed if positive: the "Saldo" each fix shows before → after (#279).
  balance_clp: number
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

/** A period and its membership's balance, as a correction found or left them (#277). */
export type Figures = { outstanding_clp: number; balance_clp: number }

/** One correction of a person's billing (backend `Correction`): the ficha's "Correcciones". */
export type Correction = {
  id: string
  at: string
  action: 'ledger_corrected' | 'due_date_changed' | 'membership_reactivated' | 'cancel_undone' | 'discount_changed'
  // The entry's: null for a plain adjustment, `void` for a void, `restore` (#278).
  purpose: string | null
  // One of the voids of a plan voided by mistake (#256).
  plan_void: boolean
  reason: string | null
  actor_name: string | null
  period_start: string | null
  plan_name: string | null
  before: Figures | null
  after: Figures | null
  // On a `discount_changed` row (#25): the discount before and after, and the first day billed at the new one.
  discount?: DiscountShift | null
  // On a payment moved (#280): `out` of this person's period or `in` to it, and the other period's start.
  moved?: 'out' | 'in' | null
  other_period_start?: string | null
  // On a `due_date_changed` row (#283): the period's due date before and after.
  due_date?: { before: string; after: string } | null
}

/** A discount at one moment: 0 and null with none (backend `DiscountFigures`). */
export type DiscountFigures = { pct: number; reason: string | null }

export type DiscountShift = { before: DiscountFigures; after: DiscountFigures; starts_on: string }

export type Corrections = { total: number; items: Correction[] }

// Under `ledger`, so every correction's invalidation reads it again.
export function correctionsQuery(personId: string) {
  return queryOptions({
    queryKey: ['ledger', 'corrections', personId],
    queryFn: () => apiFetch<Corrections>(`/api/ledger/people/${encodeURIComponent(personId)}/corrections`),
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

/** Anular un cargo (#256): what the period still owes, voided with `reason`. */
export type VoidRecord = { membership_id: string; billing_period_id: string; reason: string }

export type VoidRefusal = 'paid' | 'pending' | 'nothing_owed'

/** The period as the void leaves it: owing nothing. */
export type RecordedVoid = { period: SettledPeriod }

export function recordVoid(body: VoidRecord): Promise<RecordedVoid> {
  return apiFetch<RecordedVoid>('/api/ledger/voids', { method: 'POST', body: JSON.stringify(body) })
}

/** Restaurar un cargo (#278): a charge voided by mistake, owed again. */
export type RestoreRecord = { void_id: string; reason: string }

export type RestoreRefusal = 'not_a_void' | 'restored' | 'plan_voided'

/** The period as the restore leaves it: owing the void's amount again. */
export type RecordedRestore = { period: SettledPeriod }

export function recordRestore(body: RestoreRecord): Promise<RecordedRestore> {
  return apiFetch<RecordedRestore>('/api/ledger/restores', { method: 'POST', body: JSON.stringify(body) })
}

/** Revertir un ajuste (#282): an adjustment made by mistake, undone. */
export type RevertRecord = { adjustment_id: string; reason: string }

export const REVERT_REFUSALS = [
  'not_an_adjustment',
  'void',
  'correction',
  'credit',
  'reverted',
  'voided',
  'plan_voided',
  'exceeds',
] as const
export type RevertRefusal = (typeof REVERT_REFUSALS)[number]

/** The period as the revert leaves it: as before the adjustment. */
export type RecordedRevert = { period: SettledPeriod }

export function recordRevert(body: RevertRecord): Promise<RecordedRevert> {
  return apiFetch<RecordedRevert>('/api/ledger/reverts', { method: 'POST', body: JSON.stringify(body) })
}

/** Condonar una deuda (#282): a real charge forgiven; "Esperado" still counts it. */
export type WriteOffRecord = { membership_id: string; billing_period_id: string; reason: string }

export type WriteOffRefusal = 'pending' | 'nothing_owed' | 'plan_voided'

/** The period as the write-off leaves it: owing nothing. */
export type RecordedWriteOff = { period: SettledPeriod }

export function recordWriteOff(body: WriteOffRecord): Promise<RecordedWriteOff> {
  return apiFetch<RecordedWriteOff>('/api/ledger/write-offs', { method: 'POST', body: JSON.stringify(body) })
}

/** Mover vencimiento (#283): "le doy hasta el 10", the period falls due on another day. */
export type DueDateRecord = { due_date: string; reason: string }

export type DueDateRefusal = 'paid' | 'out_of_range' | 'unchanged'

export type MovedDueDate = { id: string; due_date: string; due_date_was: string }

export function moveDueDate(periodId: string, body: DueDateRecord): Promise<MovedDueDate> {
  return apiFetch<MovedDueDate>(`/api/ledger/periods/${encodeURIComponent(periodId)}/due-date`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

/** The 409's refusal of "Mover vencimiento", for the form to say why. */
export function dueDateRefused(error: unknown): DueDateRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'paid' || code === 'out_of_range' || code === 'unchanged' ? code : null
}

/** Anular un pago registrado por error (#281): all that is left of it undone; the
 * student is told. */
export type PaymentVoidRecord = { payment_id: string; reason: string }

export type PaymentVoidRefusal = 'not_validated' | 'nothing_left' | 'a_correction'

/** The period as the undoing leaves it: owing the payment again. */
export type RecordedPaymentVoid = { period: SettledPeriod }

export function recordPaymentVoid(body: PaymentVoidRecord): Promise<RecordedPaymentVoid> {
  return apiFetch<RecordedPaymentVoid>('/api/ledger/payment-voids', { method: 'POST', body: JSON.stringify(body) })
}

/** The 409's refusal of "Anular pago", for the form to say why. */
export function paymentVoidRefused(error: unknown): PaymentVoidRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'not_validated' || code === 'nothing_left' || code === 'a_correction' ? code : null
}

/** Mover un pago (#280): all or part of it, to another month, plan, or a sibling's. */
export type MoveRecord = { payment_id: string; billing_period_id: string; amount_clp: number; reason: string }

export type MoveRefusal =
  | 'not_validated'
  | 'extra_line'
  | 'same_period'
  | 'unrelated'
  | 'plan_voided'
  | 'pending'
  | 'paid'
  | 'nothing_left'
  | 'beyond_left'
  | 'whole_only'

const MOVE_REFUSALS: readonly MoveRefusal[] = [
  'not_validated',
  'extra_line',
  'same_period',
  'unrelated',
  'plan_voided',
  'pending',
  'paid',
  'nothing_left',
  'beyond_left',
  'whole_only',
]

/** A period a payment may go to (backend `MoveTarget`). */
export type MoveTarget = {
  membership_id: string
  billing_period_id: string
  person_id: string
  person_name: string
  plan_name: string
  period_start: string
  period_end: string
  outstanding_clp: number
  // A proof waits on it: refused until it is reviewed.
  pending: boolean
}

export type MoveTargets = {
  // What is left of the payment to move.
  movable_clp: number
  // It carried credit: it moves only as a whole.
  whole_only: boolean
  targets: MoveTarget[]
}

// Under `ledger`, so any correction reads it again.
export function moveTargetsQuery(paymentId: string) {
  return queryOptions({
    queryKey: ['ledger', 'move-targets', paymentId],
    queryFn: () => apiFetch<MoveTargets>(`/api/ledger/moves/targets?payment_id=${encodeURIComponent(paymentId)}`),
  })
}

/** Both periods as the move leaves them; `credit` what the new one did not need. */
export type RecordedMove = {
  from_period: SettledPeriod
  to_period: SettledPeriod
  credit: { amount_clp: number } | null
}

export function recordMove(body: MoveRecord): Promise<RecordedMove> {
  return apiFetch<RecordedMove>('/api/ledger/moves', { method: 'POST', body: JSON.stringify(body) })
}

/** The 409's refusal of "Mover pago", for the form to say why. */
export function moveRefused(error: unknown): MoveRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return MOVE_REFUSALS.find((r) => r === code) ?? null
}

/** Anular un plan started by mistake (#256): ended as of its start, every unpaid charge voided. */
export function voidMembership(membershipId: string, reason: string): Promise<Membership> {
  return apiFetch<Membership>(`/api/memberships/${encodeURIComponent(membershipId)}/void`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

/** "Reactivar plan" (#284): bill after the last period billed, catching up the months
 * since the lapse, or from today, the days between never billed. */
export type BillFrom = 'last' | 'today'

export type QuotedPeriod = { period_start: string; period_end: string; due_date: string; amount_due_clp: number }

/** What a reactivation bills at once (backend `ReactivationBill`): from `bills_from`, these
 * periods, oldest first, for `total_clp`. */
export type ReactivationBill = { bills_from: string; periods: QuotedPeriod[]; total_clp: number }

export type ReactivationQuote = Record<BillFrom, ReactivationBill>

export type ReactivationRefusal = 'not_lapsed' | 'not_recurring' | 'period_ended' | 'unpaid' | 'live_plan'

/** The refusal of a reactivation (backend `ReactivationConflict`), with what it is about. */
export type ReactivationRefused = {
  code: ReactivationRefusal
  amount_clp: number | null
  period_start: string | null
  plan_name: string | null
}

export function reactivationQuery(membershipId: string) {
  return queryOptions({
    queryKey: ['memberships', 'reactivate', membershipId],
    queryFn: () => apiFetch<ReactivationQuote>(`/api/memberships/${encodeURIComponent(membershipId)}/reactivate`),
    // Read as the form shows it: what has been paid since decides it. Dropped once the
    // form closes, so reopening it never shows the last quote while the new one loads.
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
}

export function reactivateMembership(membershipId: string, reason: string, billFrom: BillFrom): Promise<Membership> {
  return apiFetch<Membership>(`/api/memberships/${encodeURIComponent(membershipId)}/reactivate`, {
    method: 'POST',
    body: JSON.stringify({ reason, bill_from: billFrom }),
  })
}

/** The 409's refusal of a reactivation, for the form to say what to do first. */
export function reactivationRefused(error: unknown): ReactivationRefused | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: Record<string, unknown> } | undefined)?.detail
  const code = detail?.code
  if (
    code !== 'not_lapsed' &&
    code !== 'not_recurring' &&
    code !== 'period_ended' &&
    code !== 'unpaid' &&
    code !== 'live_plan'
  )
    return null
  const text = (value: unknown) => (typeof value === 'string' ? value : null)
  return {
    code,
    amount_clp: typeof detail?.amount_clp === 'number' ? detail.amount_clp : null,
    period_start: text(detail?.period_start),
    plan_name: text(detail?.plan_name),
  }
}

/** The 409's refusal of a void, and the payment it is about, for the form to say how to clear it. */
export function voidRefused(error: unknown): { code: VoidRefusal; amount_clp: number | null } | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown; amount_clp?: unknown } } | undefined)?.detail
  const code = detail?.code
  if (code !== 'paid' && code !== 'pending' && code !== 'nothing_owed') return null
  return { code, amount_clp: typeof detail?.amount_clp === 'number' ? detail.amount_clp : null }
}

/** The 409's refusal of a restore, for the form to say why. */
export function restoreRefused(error: unknown): RestoreRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'not_a_void' || code === 'restored' || code === 'plan_voided' ? code : null
}

/** The 409's refusal of a revert, for the form to say why (#282). */
export function revertRefused(error: unknown): RevertRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return REVERT_REFUSALS.find((c) => c === code) ?? null
}

/** The 409's refusal of a write-off, for the form to say how to clear it (#282). */
export function writeOffRefused(error: unknown): WriteOffRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'pending' || code === 'nothing_owed' || code === 'plan_voided' ? code : null
}

export function recordRefund(body: RefundRecord): Promise<RecordedRefund> {
  return apiFetch<RecordedRefund>('/api/ledger/refunds', { method: 'POST', body: JSON.stringify(body) })
}

// `from_date` is today when omitted; a later day books the freeze ahead.
export type FreezeCreate = { from_date?: string; to_date: string; reason: string }

function freezePath(membershipId: string): string {
  return `/api/memberships/${encodeURIComponent(membershipId)}/freeze`
}

/** Freeze from `from_date` until `to_date`: the due date moves past the frozen days as it starts. */
export function freezeMembership(membershipId: string, body: FreezeCreate): Promise<Membership> {
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

/** "Asignar plan" (#249): start the person on a plan, billed as it starts, with the welcome if asked. */
export function startMembership(
  personId: string,
  start: MembershipStart,
  sendWelcome: boolean,
  discount?: Discount,
): Promise<Membership> {
  return apiFetch<Membership>('/api/memberships', {
    method: 'POST',
    body: JSON.stringify({ person_id: personId, ...start, send_welcome: sendWelcome, ...(discount && { discount }) }),
  })
}

/** What a change to a plan would do, before it is saved (backend `PlanChangeQuote`, #249):
 * from `starts_on` on the new plan, its first period until `period_end` for `amount_due_clp`. */
export type PlanChangeQuote = { starts_on: string; period_end: string; amount_due_clp: number }

export function planChangeQuery(membershipId: string, planId: string) {
  return queryOptions({
    queryKey: ['memberships', 'plan-change', membershipId, planId],
    queryFn: () =>
      apiFetch<PlanChangeQuote>(
        `/api/memberships/${encodeURIComponent(membershipId)}/plan-change?plan_id=${encodeURIComponent(planId)}`,
      ),
    // Read as the form shows it: what has been billed since decides the day.
    staleTime: 0,
    retry: false,
  })
}

/** "Cambiar plan": to `planId` from the first period not yet billed; the plan it is on withdraws a pending change. */
export function changePlan(membershipId: string, planId: string): Promise<Membership> {
  return apiFetch<Membership>(`/api/memberships/${encodeURIComponent(membershipId)}/plan-change`, {
    method: 'POST',
    body: JSON.stringify({ plan_id: planId }),
  })
}

/** What a discount would bill, before it is saved (backend `DiscountQuote`, #25): the next
 * period not yet billed, from `starts_on` until `period_end`, for `amount_due_clp`. */
export type DiscountQuote = { starts_on: string; period_end: string; amount_due_clp: number }

export function discountQuery(membershipId: string, pct: number) {
  return queryOptions({
    queryKey: ['memberships', 'discount', membershipId, pct],
    queryFn: () =>
      apiFetch<DiscountQuote>(`/api/memberships/${encodeURIComponent(membershipId)}/discount?pct=${pct}`),
    // Read as the form shows it: what has been billed since decides the period.
    staleTime: 0,
    retry: false,
  })
}

/** "Descuento": set from the next period not yet billed; `null` takes it off. */
export function setDiscount(membershipId: string, discount: Discount | null): Promise<Membership> {
  return apiFetch<Membership>(`/api/memberships/${encodeURIComponent(membershipId)}/discount`, {
    method: 'PUT',
    body: JSON.stringify({ discount }),
  })
}

const LIVE: readonly MembershipStatus[] = ['trial', 'active', 'frozen']

/** The membership the detail shows, as the member list does (#271): one the member is on
 * now, else one not cancelled, else any; the latest created of them, as the API lists
 * them (`current_first`), never down to their ids. */
export function shownMembership(memberships: readonly Membership[]): Membership | undefined {
  return (
    memberships.find((m) => LIVE.includes(m.status)) ??
    memberships.find((m) => m.status !== 'cancelled') ??
    memberships[0]
  )
}

/** The memberships the detail shows a card for (#354): every one the member is on now,
 * a course beside a monthly plan say, the first started first; else the one
 * `shownMembership` picks. */
export function shownMemberships(memberships: readonly Membership[]): Membership[] {
  const live = memberships.filter((m) => LIVE.includes(m.status))
  // The API lists the latest created first: reversed, a tie on the day keeps the earlier.
  if (live.length > 0) return [...live].reverse().sort((a, b) => a.started_on.localeCompare(b.started_on))
  const shown = shownMembership(memberships)
  return shown ? [shown] : []
}

/** What "Asignar plan" would start, before it is saved (backend `StartQuote`, #271): the
 * day it starts, after `billed_through`, the last day a lapsed plan billed, when that moved
 * it; `debt_clp`, what the lapsed plans still owe; and `converts`, the trial it converts (#27). */
export type StartQuote = {
  starts_on: string
  billed_through: string | null
  debt_clp: number
  converts?: ConvertedTrial | null
}

/** How the trials of the last `days` days went (backend `TrialConversions`, #27): Hoy's "Pruebas". */
export type TrialConversions = { days: number; started: number; converted: number; running: number }

export const trialConversionsQuery = queryOptions({
  queryKey: ['memberships', 'trials'],
  queryFn: () => apiFetch<TrialConversions>('/api/memberships/trials'),
})

export function startQuery(personId: string, planId: string, startedOn: string) {
  const params = new URLSearchParams({ person_id: personId, plan_id: planId, started_on: startedOn })
  return queryOptions({
    queryKey: ['memberships', 'start', personId, planId, startedOn],
    queryFn: () => apiFetch<StartQuote>(`/api/memberships/start?${params}`),
    // Read as the form shows it: what has been billed and paid since decides it.
    staleTime: 0,
    retry: false,
  })
}
