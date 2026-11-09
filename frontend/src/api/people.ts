import { infiniteQueryOptions, queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

export const MEMBERSHIP_STATUSES = ['active', 'trial', 'frozen', 'lapsed', 'cancelled'] as const
export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number]

export type MemberRow = {
  id: string
  name: string
  phone: string | null
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
}

export type MemberPage = { items: MemberRow[]; total: number }

export type MemberFilters = {
  q: string
  status: readonly MembershipStatus[]
  plan: readonly string[]
  // A member is in a program through their plan.
  program: readonly string[]
}

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
      { q: filters.q.trim(), status: filters.status, plan: filters.plan, program: filters.program },
    ],
    queryFn: ({ pageParam }) => apiFetch<MemberPage>(membersPath(filters, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
}

export const plansQuery = queryOptions({
  queryKey: ['plans'],
  queryFn: () => apiFetch<Plan[]>('/api/plans'),
})

export const programsQuery = queryOptions({
  queryKey: ['programs'],
  queryFn: () => apiFetch<Program[]>('/api/programs'),
})
