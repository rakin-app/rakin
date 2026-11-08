import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

export type Health = { status: string }

export const healthQuery = queryOptions({
  queryKey: ['healthz'],
  queryFn: () => apiFetch<Health>('/healthz'),
})
