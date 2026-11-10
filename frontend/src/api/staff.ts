import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { StaffRole } from './me'

/** The roles an invite or a change may give (backend `InvitableRole`): never owner. */
export const INVITABLE_ROLES = ['admin', 'coach'] as const
export type InvitableRole = (typeof INVITABLE_ROLES)[number]

/** Someone on the gym's staff (backend `StaffMember`). */
export type StaffMember = {
  person_id: string
  name: string
  phone: string | null
  email: string | null
  role: StaffRole
  // When they were given a role here.
  since: string
}

export type StaffInvite = { phone: string; name: string; email: string; role: InvitableRole }

/** The owner, then admins, then coaches. Owner and admin only. */
export const staffQuery = queryOptions({
  queryKey: ['staff'],
  queryFn: () => apiFetch<StaffMember[]>('/api/staff'),
})

/** Adds them by phone with the role and emails them a sign-in link; a 409 is someone already on the staff. */
export function inviteStaff(body: StaffInvite): Promise<StaffMember> {
  return apiFetch<StaffMember>('/api/staff', { method: 'POST', body: JSON.stringify(body) })
}

export function changeStaffRole(personId: string, role: InvitableRole): Promise<StaffMember> {
  return apiFetch<StaffMember>(`/api/staff/${encodeURIComponent(personId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
}

/** Takes their role away; the gym keeps its record of them. */
export function revokeStaff(personId: string): Promise<void> {
  return apiFetch<void>(`/api/staff/${encodeURIComponent(personId)}`, { method: 'DELETE' })
}

/** Whether `acting` may give or take away `role`, as the API decides: an admin manages coaches only. */
export function managesRole(acting: StaffRole | null | undefined, role: StaffRole): boolean {
  if (role === 'owner') return false
  return acting === 'owner' || (acting === 'admin' && role === 'coach')
}
