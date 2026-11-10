import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { BankAccount } from './me'

/** The bank's account types the API takes (backend `AccountType`). */
export const ACCOUNT_TYPES = ['Cuenta Corriente', 'Cuenta Vista', 'Cuenta RUT', 'Cuenta de Ahorro'] as const

/** The gym's own settings (backend `GymSettings`), owner and admin only. */
export type GymSettings = {
  name: string
  // The gym's address in URLs; set when the gym is created, not editable.
  slug: string
  timezone: string
  grace_days: number
  reminder_every_days: number
  channels: { whatsapp: boolean }
  bank_account: BankAccount | null
}

/** Only the fields sent change; `bank_account: null` clears it. Values the API would
 * refuse are sent as typed, for its 422 to name them. */
export type GymSettingsUpdate = Partial<{
  name: string
  timezone: string
  grace_days: number | string
  reminder_every_days: number | string
  channels: { whatsapp: boolean }
  bank_account: Omit<BankAccount, 'account_type'> & { account_type: string } | null
}>

export function gymSettingsQuery() {
  return queryOptions({
    queryKey: ['gym', 'settings'],
    queryFn: () => apiFetch<GymSettings>('/api/gym/settings'),
  })
}

export function updateGymSettings(changes: GymSettingsUpdate): Promise<GymSettings> {
  return apiFetch<GymSettings>('/api/gym/settings', { method: 'PATCH', body: JSON.stringify(changes) })
}
