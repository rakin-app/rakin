import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Rank } from './grading'
import type { MyExtraLine } from './extraCharges'
import type { FreezeRequest } from './freezeRequests'
import type { Freeze } from './member'
import type { OpenPeriod } from './proofs'
import type { TermsState } from './terms'
import type { Theme } from '../theme'
import type { PracticeNames, Vocabulary } from '../i18n/vocabulary'

/** The role a staff row still names (backend `app.roles.Role`), until #313. What a
 * person may do is their permissions, never this. */
export type StaffRole = 'owner' | 'admin' | 'coach'

/** What the gym's roles can let someone do (backend `app.permissions.Permission`). */
export type Permission =
  | 'money_read'
  | 'money_write'
  | 'expenses_read'
  | 'expenses_write'
  | 'members_manage'
  | 'members_add'
  | 'attendance'
  | 'gym_setup'
  | 'team_manage'

/** What the signed-in person may do here: their permissions, and whether they hold the
 * gym's account (the titular, who holds every permission). `null` for someone not on
 * the team, a member. */
export type Access = { permissions: Permission[]; account_holder: boolean }

/** Who is signed in: what they may do here, and their name and email as the gym has them; and the gym's name. */
export type MyRole = {
  role: StaffRole | null
  // `null` for someone not on the team (#308).
  permissions: Permission[] | null
  account_holder: boolean
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
  // Whether one of the gym's activities grades (#245): belts and ranks show only then.
  // `useGrades` in `activities.ts` reads it.
  uses_grades?: boolean
  // What the gym calls itself, its members and its coach (#344); `wearVocabulary`
  // puts them on every screen.
  vocabulary?: Vocabulary
  // What the gym calls its free practice and its open mat (#346); `wearPractice` puts
  // them on every screen.
  practice?: PracticeNames
  // Whether the gym accepted the current terms (#499): until it does, its titular sees
  // only the page to accept them, and while it never has, the team a notice.
  terms?: TermsState
  // Who accepts them for the gym, for that notice.
  titular_name?: string | null
}

/** What `me` may do here; `null` when they are not on the team. */
export function accessOf(me: MyRole): Access | null {
  return me.permissions === null ? null : { permissions: me.permissions, account_holder: me.account_holder }
}

/** What the signed-in person may do in this gym; `null` for a member. */
export function myAccessQuery() {
  return queryOptions({
    queryKey: ['me', 'role'],
    queryFn: () => apiFetch<MyRole>('/api/me/role'),
    select: accessOf,
    // Who is signed in, which no screen shows as its content (#362).
    meta: { ambient: true },
  })
}

/** Who is signed in, and what they may do: the same answer as `myAccessQuery`, kept whole. */
export function myselfQuery() {
  return queryOptions({
    queryKey: ['me', 'role'],
    queryFn: () => apiFetch<MyRole>('/api/me/role'),
    meta: { ambient: true },
  })
}

/** Whether `access` holds `permission`. The titular holds them all. */
export function holds(access: Access | null | undefined, permission: Permission): boolean {
  return access?.permissions.includes(permission) ?? false
}

/** Who sees money: the backend's `money_read` (`SeesMoney`). A coach never does. */
export function readsLedger(access: Access | null | undefined): boolean {
  return holds(access, 'money_read')
}

/** Who sees the gym's expenses, Gastos (#314): the backend's `expenses_read`. Its own
 * permission, never `money_read`: an Administrador sees payments and no expenses. */
export function readsExpenses(access: Access | null | undefined): boolean {
  return holds(access, 'expenses_read')
}

/** Who records, corrects and voids expenses: the backend's `expenses_write`. */
export function writesExpenses(access: Access | null | undefined): boolean {
  return holds(access, 'expenses_write')
}

/** Who configures the gym, its settings and plans: the backend's `gym_setup` (`AdminSession`). */
export function managesGym(access: Access | null | undefined): boolean {
  return holds(access, 'gym_setup')
}

/** Who holds the gym's account, the titular (`OwnerSession`): deleting a member, say. */
export function holdsAccount(access: Access | null | undefined): boolean {
  return access?.account_holder ?? false
}

/** Who may run a class's timer: the backend's `_runs`, its coach or whoever sets up the gym. */
export function runsSession(me: MyRole | undefined, coachId: string): boolean {
  if (me === undefined) return false
  const access = accessOf(me)
  return managesGym(access) || (access !== null && me.person_id === coachId)
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
  // The plan that period bills, for someone on two plans, a course beside a monthly one (#354).
  plan_name?: string | null
  // The cobro extra it pays instead, when it pays one (#195).
  charge_title?: string | null
  claimed_at: string | null
  validated_at: string | null
  // A rejection's note, or a carried credit's: the notes written for the student.
  note: string | null
  created_at: string
  // `mistake` on a refund undoing a payment recorded by mistake (#281), `revert` on the
  // credit it carried, taken back with it.
  purpose?: string | null
}

/** The student page, "Mi página": what is due next, where to pay it, what was paid. */
export type MyPage = {
  gym_name: string
  timezone: string
  person_id: string
  name: string
  // "Alumno desde": the earliest of the day they first trained here (#293) and their
  // first plan's start, else the day the gym added them.
  member_since: string
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
  // Their running plans and their dependents', with any freeze request (#270).
  plans?: MyPlan[]
}

/** A running plan on the student page, for "Pedir congelamiento" (backend `MyPlan`). */
export type MyPlan = {
  membership_id: string
  person_id: string
  person_name: string
  plan_name: string
  status: 'active' | 'frozen'
  // Running, or booked ahead.
  freeze: Freeze | null
  pending_request: FreezeRequest | null
  // The last one answered, in the last 30 days.
  last_decided: FreezeRequest | null
}

/** One of the signed-in guardian's dependents (backend `Dependent`): their rank and classes (#66). */
export type Dependent = {
  id: string
  name: string
  // Their latest promotion; null until the gym records one.
  rank: Rank | null
  // Their classes here, this calendar month in the gym's timezone and in all.
  attendance: { this_month: number; total: number }
}

/** Whom the signed-in person pays for; none for someone who is nobody's guardian. */
export function myDependentsQuery() {
  return queryOptions({
    queryKey: ['me', 'dependents'],
    queryFn: () => apiFetch<Dependent[]>('/api/me/dependents'),
  })
}

export function myPageQuery() {
  return queryOptions({
    queryKey: ['me', 'page'],
    queryFn: () => apiFetch<MyPage>('/api/me/page'),
  })
}
