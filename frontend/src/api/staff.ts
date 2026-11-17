import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Permission, StaffRole } from './me'

/** Every permission a role can carry, in the order Ajustes lists them (backend `Permission`). */
export const PERMISSIONS: readonly Permission[] = [
  'money_read',
  'money_write',
  'expenses_read',
  'expenses_write',
  'members_manage',
  'members_add',
  'attendance',
  'gym_setup',
  'team_manage',
]

/** What holding the first brings with it, as a role stores it (backend `IMPLIES`). */
export const IMPLIES: Partial<Record<Permission, Permission>> = {
  money_write: 'money_read',
  expenses_write: 'expenses_read',
  members_manage: 'members_add',
}

/** `permissions` with what each implies. */
export function withImplied(permissions: readonly Permission[]): Permission[] {
  const all = new Set(permissions)
  for (const p of permissions) {
    const implied = IMPLIES[p]
    if (implied) all.add(implied)
  }
  return PERMISSIONS.filter((p) => all.has(p))
}

/** An appointment that holds today or from a later day (backend `StaffAppointment`): the
 * role's name today, and whether the signed-in person may end or correct it. */
export type StaffAppointment = {
  id: string
  title_id: string
  title_name: string
  starts_on: string
  // The first day without it; `null` while open.
  ends_on: string | null
  public_contact: 'email' | 'phone' | null
  manageable: boolean
}

/** Someone on the gym's team (backend `StaffMember`). */
export type StaffMember = {
  person_id: string
  name: string
  phone: string | null
  email: string | null
  // The role the staff row still names, until #313: never what they may do.
  role: StaffRole
  // When they joined the team.
  since: string
  account_holder: boolean
  // What they may do today; every one for the titular.
  permissions: Permission[]
  appointments: StaffAppointment[]
  // Whether the signed-in person may appoint them, end or correct their appointments.
  manageable: boolean
}

/** A term: from `starts_on` (today unless given) until the day before `ends_on`, or open. */
export type Term = { starts_on?: string; ends_on?: string }

/** Who to invite: by their RUT when they give one, else by the email they sign in with
 * (#165), to one or more of the gym's roles. The phone is optional, a contact only. */
export type StaffInvite = Term & { name: string; email: string; rut?: string; phone?: string; title_ids: string[] }

/** The titular, then everyone by name. Whoever manages the team. */
export const staffQuery = queryOptions({
  queryKey: ['staff'],
  queryFn: () => apiFetch<StaffMember[]>('/api/staff'),
})

/** Adds them with the roles and emails them a sign-in link; a 409 is someone already on the staff. */
export function inviteStaff(body: StaffInvite): Promise<StaffMember> {
  return apiFetch<StaffMember>('/api/staff', { method: 'POST', body: JSON.stringify(body) })
}

/** "Agregar cargo": appoint them to one of the gym's roles. A 409 overlaps one they hold. */
export function appoint(personId: string, body: Term & { title_id: string }): Promise<StaffMember> {
  return apiFetch<StaffMember>(`/api/staff/${encodeURIComponent(personId)}/appointments`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

function appointmentPath(personId: string, appointmentId: string): string {
  return `/api/staff/${encodeURIComponent(personId)}/appointments/${encodeURIComponent(appointmentId)}`
}

/** "Terminar cargo": it ends today. Their last ended, they leave the team. */
export function endAppointment(personId: string, appointmentId: string): Promise<void> {
  return apiFetch<void>(`${appointmentPath(personId, appointmentId)}/end`, { method: 'POST' })
}

/** A correction of an appointment's dates; `ends_on: null` makes it open. */
export function correctAppointment(
  personId: string,
  appointmentId: string,
  body: { starts_on: string; ends_on: string | null },
): Promise<void> {
  return apiFetch<void>(appointmentPath(personId, appointmentId), { method: 'PATCH', body: JSON.stringify(body) })
}

/** An appointment as it was (backend `HistoryEntry`): the role's name when it was made. */
export type HistoryEntry = {
  id: string
  person_id: string
  person_name: string
  title_name: string
  starts_on: string
  ends_on: string | null
}

/** Every appointment, newest first. Whoever manages the team. */
export const staffHistoryQuery = queryOptions({
  queryKey: ['staff', 'history'],
  queryFn: () => apiFetch<HistoryEntry[]>('/api/staff/history'),
})

export type PresetKey = 'academia' | 'club_federado'

/** One of the gym's roles (backend `Title`): how many hold it today, and whether the
 * signed-in person may edit it, archive it and appoint to it. */
export type Title = {
  id: string
  name: string
  permissions: Permission[]
  public: boolean
  preset: PresetKey | null
  holders: number
  manageable: boolean
}

/** The gym's roles, and whether it has yet to choose how its team is organised. */
export type Titles = { titles: Title[]; setup_pending: boolean }

export const titlesQuery = queryOptions({
  queryKey: ['staff', 'titles'],
  queryFn: () => apiFetch<Titles>('/api/titles'),
})

export type TitleDraft = { name: string; permissions: Permission[]; public: boolean }

export function createTitle(body: TitleDraft): Promise<Title> {
  return apiFetch<Title>('/api/titles', { method: 'POST', body: JSON.stringify(body) })
}

export function changeTitle(id: string, body: Partial<TitleDraft>): Promise<Title> {
  return apiFetch<Title>(`/api/titles/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) })
}

/** A 409 when somebody holds it today or from a later day. */
export function archiveTitle(id: string): Promise<void> {
  return apiFetch<void>(`/api/titles/${encodeURIComponent(id)}/archive`, { method: 'POST' })
}

/** "Agregar plantilla": the preset's roles the gym has none of the name of; the ones added. */
export function addPreset(preset: PresetKey): Promise<Title[]> {
  return apiFetch<Title[]>('/api/titles/presets', { method: 'POST', body: JSON.stringify({ preset }) })
}

/** A new gym's first choice: a preset, or none. */
export function chooseSetup(preset: PresetKey | null): Promise<Titles> {
  return apiFetch<Titles>('/api/titles/setup', { method: 'POST', body: JSON.stringify({ preset }) })
}
