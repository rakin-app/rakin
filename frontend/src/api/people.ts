import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { ApiError, apiFetch } from './client'
import type { FieldValue } from './customFields'
import type { Person } from './member'

export const MEMBERSHIP_STATUSES = ['active', 'trial', 'frozen', 'lapsed', 'cancelled'] as const
export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number]

export type MemberRow = {
  id: string
  name: string
  phone: string | null
  // "No tiene WhatsApp": no WhatsApp link goes to them.
  no_whatsapp: boolean
  // A member with no phone and the box unticked: "Falta teléfono".
  missing_phone: boolean
  // No RUT and no email, found again only by name: "Falta RUT".
  missing_rut: boolean
  rut: string | null
  membership: {
    id: string
    status: MembershipStatus
    plan_id: string
    plan_name: string
  } | null
  // Who pays for them, and how many they pay for.
  guardian: { id: string; name: string } | null
  dependents: number
  // The day they left the gym (dado de baja); null while they are here.
  left_on: string | null
}

export type MemberPage = { items: MemberRow[]; total: number }

export type MemberFilters = {
  q: string
  status: readonly MembershipStatus[]
  plan: readonly string[]
  // A member is in a program through their plan.
  program: readonly string[]
  // Who has left the gym: left out (the default), only them ("Dados de baja"), or anyone.
  left?: LeftFilter
  // Only the members with "Falta teléfono", or "Falta RUT".
  missingPhone?: boolean
  missingRut?: boolean
  // Only those away 14 days or more: "A quién llamar", in full.
  away?: boolean
  // A current rank by key; or that rank or any above it in the gym's scheme (#219).
  rank?: readonly string[]
  rankMin?: string
}

export type LeftFilter = 'no' | 'only' | 'any'

export type Plan = { id: string; name: string; active: boolean }
export type Program = { id: string; name: string; active: boolean }

export const MEMBERS_PAGE_SIZE = 50

export function membersPath(filters: MemberFilters, offset: number): string {
  const params = new URLSearchParams()
  const q = filters.q.trim()
  if (q) params.set('q', q)
  for (const status of filters.status) params.append('status', status)
  for (const plan of filters.plan) params.append('plan_id', plan)
  for (const program of filters.program) params.append('program_id', program)
  if (filters.left && filters.left !== 'no') params.set('left', filters.left)
  if (filters.missingPhone) params.set('missing_phone', 'true')
  if (filters.missingRut) params.set('missing_rut', 'true')
  if (filters.away) params.set('away', 'true')
  for (const rank of filters.rank ?? []) params.append('rank', rank)
  if (filters.rankMin) params.set('rank_min', filters.rankMin)
  params.set('limit', String(MEMBERS_PAGE_SIZE))
  params.set('offset', String(offset))
  return `/api/people?${params}`
}

// One query per filter combination; "Ver más" fetches the next page into it.
export function membersQuery(filters: MemberFilters) {
  return infiniteQueryOptions({
    queryKey: [
      'people',
      'list',
      {
        q: filters.q.trim(),
        status: filters.status,
        plan: filters.plan,
        program: filters.program,
        left: filters.left ?? 'no',
        missingPhone: filters.missingPhone ?? false,
        missingRut: filters.missingRut ?? false,
        away: filters.away ?? false,
        rank: filters.rank ?? [],
        rankMin: filters.rankMin ?? null,
      },
    ],
    queryFn: ({ pageParam }) => apiFetch<MemberPage>(membersPath(filters, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}

/** How many members the gym has, dados de baja left out: one row asked for, its total
 * read. Under `['people']`, so adding or importing someone refreshes it. */
export const memberCountQuery = queryOptions({
  queryKey: ['people', 'count'],
  queryFn: async () => (await apiFetch<MemberPage>('/api/people?limit=1&offset=0')).total,
})

// The plans, as the filters and the import read them: their id, name and whether active.
export { plansQuery } from './plans'

export const programsQuery = queryOptions({
  queryKey: ['programs'],
  queryFn: () => apiFetch<Program[]>('/api/programs'),
})

/** A plan to start someone on, from a day (today in the gym's timezone when omitted). */
export type MembershipStart = { plan_id: string; started_on?: string }

/** Who answers for a minor: someone already in the gym, or someone new by their RUT or
 * email. The guardian is who the gym messages, so a new one needs a phone, unless they
 * have no WhatsApp. */
export type GuardianChoice =
  | { person_id: string }
  | { name: string; rut?: string; email?: string; phone?: string; no_whatsapp?: boolean }

/** A member added by hand (backend `Enrolment`): all of it is written, or none. */
export type Enrolment = {
  name: string
  // Who they are: a RUT, or an email. A dependent may have neither.
  rut?: string
  email?: string
  // Required for an adult, unless `no_whatsapp`; a minor's guardian's is the one used.
  phone?: string
  no_whatsapp?: boolean
  dob?: string
  guardian?: GuardianChoice
  fields?: Record<string, FieldValue>
  membership?: MembershipStart
  // The welcome, with their sign-in link: about the plan, or with none that they are in (#246).
  send_welcome?: boolean
}

export function enrol(body: Enrolment): Promise<Person> {
  return apiFetch<Person>('/api/people/enrol', { method: 'POST', body: JSON.stringify(body) })
}

/** Their sign-in link, on the ficha (#246): the address the welcome goes to, theirs or
 * their guardian's (`guardian` names them then), and how the latest welcome went. */
export type WelcomeState = {
  to: string | null
  guardian: string | null
  last: { status: 'sent' | 'failed'; sent_at: string; to: string } | null
}

/** `waiting`: a welcome is on its way (one just asked for on "Nuevo alumno"), so it is
 * read again each second until it is recorded, for up to `WELCOME_WAIT_MS`. */
export const WELCOME_WAIT_MS = 15_000

export function welcomeQuery(id: string, waitingSince: number | null = null) {
  return queryOptions({
    queryKey: ['people', 'welcome', id],
    queryFn: () => apiFetch<WelcomeState>(`/api/people/${encodeURIComponent(id)}/welcome`),
    refetchInterval: (query) =>
      waitingSince !== null && !query.state.data?.last && Date.now() - waitingSince < WELCOME_WAIT_MS ? 1000 : false,
  })
}

/** "Enviar link para entrar": the welcome, sent now; the answer says how it went. */
export function sendWelcome(id: string): Promise<WelcomeState> {
  return apiFetch<WelcomeState>(`/api/people/${encodeURIComponent(id)}/welcome`, { method: 'POST' })
}

/** Only the fields sent change; `null` clears an optional one. A member's phone is
 * cleared only with `no_whatsapp` in its place. */
export type PersonEdit = Partial<{
  name: string
  email: string | null
  phone: string | null
  no_whatsapp: boolean
  rut: string | null
  dob: string | null
}>

export function updatePerson(id: string, body: PersonEdit): Promise<Person> {
  return apiFetch<Person>(`/api/people/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) })
}

/** Dar de baja from `left_on`, today when omitted: every membership ends and nothing more is billed. */
export function leaveGym(id: string, leftOn?: string): Promise<Person> {
  return apiFetch<Person>(`/api/people/${encodeURIComponent(id)}/leave`, {
    method: 'POST',
    body: JSON.stringify(leftOn ? { left_on: leftOn } : {}),
  })
}

/** Reactivar, on `membership`'s plan if given. */
export function returnToGym(id: string, membership?: MembershipStart): Promise<Person> {
  return apiFetch<Person>(`/api/people/${encodeURIComponent(id)}/return`, {
    method: 'POST',
    body: JSON.stringify(membership ? { membership } : {}),
  })
}

/** Why the owner cannot delete someone: their ledger, their staff role, or a dependent. */
export type DeletionRefusal = 'ledger' | 'staff' | 'guardian'

export function deletionQuery(id: string) {
  return queryOptions({
    queryKey: ['people', 'deletion', id],
    queryFn: () => apiFetch<{ refused: DeletionRefusal | null }>(`/api/people/${encodeURIComponent(id)}/deletion`),
  })
}

export function deletePerson(id: string): Promise<void> {
  return apiFetch<void>(`/api/people/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

/** The 409's refusal, when the API kept someone `deletePerson` was asked to delete. */
export function deletionRefused(error: unknown): DeletionRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const code = (error.body as { detail?: { code?: unknown } } | undefined)?.detail?.code
  return code === 'ledger' || code === 'staff' || code === 'guardian' ? code : null
}

/** Someone in the gym already has the RUT, or the email: who, to
 * open them instead. */
export type Duplicate = { code: 'rut_in_gym' | 'email_in_gym'; person_id: string }

export function duplicateOf(error: unknown): Duplicate | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.body as { detail?: { code?: unknown; person_id?: unknown } } | undefined)?.detail
  if ((detail?.code !== 'rut_in_gym' && detail?.code !== 'email_in_gym') || typeof detail.person_id !== 'string') {
    return null
  }
  return { code: detail.code, person_id: detail.person_id }
}
