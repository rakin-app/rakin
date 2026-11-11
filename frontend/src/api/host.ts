import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Theme } from '../theme'

/** The gym this address is, on its own host (`meta.rakin.app`), the theme its pages
 * wear and its logo (`logo.ts`, `null` with none); `null` on the shared one. */
export type Host = { gym: { slug: string; name: string; theme: Theme; logo: string | null } | null }

export const hostQuery = () =>
  queryOptions({
    queryKey: ['host'],
    queryFn: () => apiFetch<Host>('/api/host'),
    // The host never changes under a loaded page.
    staleTime: Infinity,
  })
