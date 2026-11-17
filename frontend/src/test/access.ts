import type { MyRole, Permission, StaffRole } from '../api/me'

// What each of today's roles may do, as the backend's Academia preset gives them
// (`app.permissions`): the owner holds the account and every permission.
const PERMISSIONS: Record<StaffRole, Permission[]> = {
  owner: [
    'attendance',
    'expenses_read',
    'expenses_write',
    'gym_setup',
    'members_add',
    'members_manage',
    'money_read',
    'money_write',
    'team_manage',
  ],
  admin: ['attendance', 'gym_setup', 'members_add', 'members_manage', 'money_read', 'money_write', 'team_manage'],
  coach: ['attendance', 'members_add'],
}

/** `/api/me/role`'s answer about what someone in `role` may do; a member (any other
 * `role`) is on no team. */
export function asRole(role: StaffRole | string | null | undefined): Pick<MyRole, 'role' | 'permissions' | 'account_holder'> {
  if (role !== 'owner' && role !== 'admin' && role !== 'coach') {
    return { role: null, permissions: null, account_holder: false }
  }
  return { role, permissions: PERMISSIONS[role], account_holder: role === 'owner' }
}
