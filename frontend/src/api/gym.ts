import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { BankAccount } from './me'
import type { Privacy } from './privacy'
import type { Theme } from '../theme'

/** The bank's account types the API takes (backend `AccountType`). */
export const ACCOUNT_TYPES = ['Cuenta Corriente', 'Cuenta Vista', 'Cuenta RUT', 'Cuenta de Ahorro'] as const

/** The gym's own settings (backend `GymSettings`), owner and admin only. */
export type GymSettings = {
  name: string
  // The gym's address in URLs; set when the gym is created, not editable.
  slug: string
  // Where it is served, as the address bar shows it: `academia-sur.rakin.app`.
  web_address: string
  timezone: string
  // The colours every screen of the gym wears (#199).
  theme: Theme
  // Where its logo is (`logo.ts`), `null` with none; changed by `uploadLogo` and `removeLogo`.
  logo: string | null
  grace_days: number
  reminder_every_days: number
  channels: { whatsapp: boolean }
  bank_account: BankAccount | null
  // What the privacy notice names the gym by (#168); the join link works only once set.
  privacy: (Privacy & { updated_on: string }) | null
}

/** Only the fields sent change; `bank_account: null` clears it, and `privacy` cannot
 * be cleared. Values the API would refuse are sent as typed, for its 422 to name them. */
export type GymSettingsUpdate = Partial<{
  name: string
  timezone: string
  theme: Theme
  grace_days: number | string
  reminder_every_days: number | string
  channels: { whatsapp: boolean }
  bank_account: Omit<BankAccount, 'account_type'> & { account_type: string } | null
  privacy: Privacy
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

/** The square of the picture to keep, in its pixels as it shows upright. */
export type LogoCrop = { x: number; y: number; size: number }

/** The logo, as the owner picked it, cut to `crop` on the server (#223). */
export function uploadLogo(file: Blob, crop: LogoCrop): Promise<GymSettings> {
  const query = new URLSearchParams({ x: String(crop.x), y: String(crop.y), size: String(crop.size) })
  return apiFetch<GymSettings>(`/api/gym/logo?${query}`, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': file.type },
  })
}

/** "Quitar logo": the gym shows its initials again. */
export function removeLogo(): Promise<GymSettings> {
  return apiFetch<GymSettings>('/api/gym/logo', { method: 'DELETE' })
}
