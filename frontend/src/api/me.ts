import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Rank } from './grading'
import type { OpenPeriod } from './proofs'

export type StaffRole = 'owner' | 'admin' | 'coach'

/** The signed-in person's staff role in this gym; `null` for a member. */
export function myRoleQuery() {
  return queryOptions({
    queryKey: ['me', 'role'],
    queryFn: () => apiFetch<{ role: StaffRole | null }>('/api/me/role'),
    select: (data) => data.role,
  })
}

/** Who sees money: the backend's `LEDGER_ROLES`. A coach never does. */
export function readsLedger(role: StaffRole | null | undefined): boolean {
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
  person_id: string
  person_name: string
  amount_clp: number
  status: PaymentStatus
  period_start: string | null
  claimed_at: string | null
  validated_at: string | null
  // A rejection's note, written for the student.
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
  bank_account: BankAccount | null
  // Their latest promotion; null until the gym records one.
  rank: Rank | null
  // Their classes here, this calendar month in the gym's timezone and in all.
  attendance: { this_month: number; total: number }
  // Newest first.
  payments: MyPayment[]
}

export function myPageQuery() {
  return queryOptions({
    queryKey: ['me', 'page'],
    queryFn: () => apiFetch<MyPage>('/api/me/page'),
  })
}
