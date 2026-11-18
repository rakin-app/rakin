import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'
import type { Theme } from '../theme'
import type { Vocabulary } from '../i18n/vocabulary'

/** The gym this address is, on its own host (`meta.rakin.app`), the theme its pages
 * wear, its logo (`logo.ts`, `null` with none), its words (#344) and whether it is
 * suspended (#439), when every path shows only a notice; `null` on the shared one. */
export type Host = {
  gym: {
    slug: string
    name: string
    theme: Theme
    logo: string | null
    vocabulary?: Vocabulary
    suspended?: boolean
  } | null
}

export const hostQuery = () =>
  queryOptions({
    queryKey: ['host'],
    queryFn: () => apiFetch<Host>('/api/host'),
    // The host never changes under a loaded page.
    staleTime: Infinity,
    // Every page's, and none of its content: not "out of date" offline (#362).
    meta: { ambient: true },
  })
