import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

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
