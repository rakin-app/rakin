import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Rank } from './grading'
import type { MyExtraLine } from './extraCharges'
import type { OpenPeriod } from './proofs'
import type { Theme } from '../theme'

export type StaffRole = 'owner' | 'admin' | 'coach'

/** Who is signed in: their role here, and their name and email as the gym has them; and the gym's name. */
export type MyRole = {
  role: StaffRole | null
  person_id: string
  name: string | null
  email: string | null
  gym_name: string
  // Holds a membership here or pays for a dependent: the student page has something for them.
  student_page: boolean
  // The gym's theme (#199), which every signed-in screen wears.
  theme: Theme
  // Where the gym's logo is (`logo.ts`); `null` with none (#223).
  gym_logo: string | null
}

/** The signed-in person's staff role in this gym; `null` for a member. */
export function myRoleQuery() {
  return queryOptions({
    queryKey: ['me', 'role'],
    queryFn: () => apiFetch<MyRole>('/api/me/role'),
    select: (data) => data.role,
  })
}

/** Who is signed in, and their role: the same answer as `myRoleQuery`, kept whole. */
export function myselfQuery() {
  return queryOptions({ queryKey: ['me', 'role'], queryFn: () => apiFetch<MyRole>('/api/me/role') })
}

/** Who may run a class's timer: the backend's `_runs`, its coach or an owner or admin. */
export function runsSession(me: MyRole | undefined, coachId: string): boolean {
  return me !== undefined && (managesGym(me.role) || (me.role !== null && me.person_id === coachId))
}

/** Who sees money: the backend's `LEDGER_ROLES`. A coach never does. */
export function readsLedger(role: StaffRole | null | undefined): boolean {
  return role === 'owner' || role === 'admin'
}

/** Who configures the gym, its settings and plans: the backend's `ADMIN_ROLES`. */
export function managesGym(role: StaffRole | null | undefined): boolean {
  return role === 'owner' || role === 'admin'
}

/** Where students transfer to, as the gym set it (`PATCH /api/gym/settings`). */
export type BankAccount = {
  bank: string
  account_type: string
  holder: string
  // Normalised, `76432109-K`.
  rut: string
  number: string
  email: string | null
}

export type NextPaymentStatus = 'in_review' | 'overdue' | 'due'

export type PaymentStatus = 'pending' | 'validated' | 'rejected'

/** A payment on the person's memberships or a dependent's, as it was reviewed. */
export type MyPayment = {
  id: string
  // A refund gives a payment back; an adjustment is positive in the student's favour,
  // negative owed on top, and with no period a credit carried from an overpayment (#210).
  kind: 'payment' | 'refund' | 'adjustment'
  person_id: string
  person_name: string
  amount_clp: number
  status: PaymentStatus
  period_start: string | null
  // The cobro extra it pays instead, when it pays one (#195).
  charge_title?: string | null
  claimed_at: string | null
  validated_at: string | null
  // A rejection's note, or a carried credit's: the notes written for the student.
  note: string | null
  created_at: string
}

/** The student page, "Mi página": what is due next, where to pay it, what was paid. */
export type MyPage = {
  gym_name: string
  timezone: string
  person_id: string
  name: string
  next_payment: { period: OpenPeriod; status: NextPaymentStatus } | null
  // With nothing owed, the day they are paid through (#196); null when no period is paid yet.
  paid_through?: string | null
  bank_account: BankAccount | null
  // Their latest promotion; null until the gym records one.
  rank: Rank | null
  // Their classes here, this calendar month in the gym's timezone and in all.
  attendance: { this_month: number; total: number }
  // Newest first.
  payments: MyPayment[]
  // Cobros extra still owed, theirs and their dependents', earliest due first (#195).
  extra_charges?: MyExtraLine[]
}

export function myPageQuery() {
  return queryOptions({
    queryKey: ['me', 'page'],
    queryFn: () => apiFetch<MyPage>('/api/me/page'),
  })
}
