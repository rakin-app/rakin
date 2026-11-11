import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { apiFetch } from './client'
import type { StaffRole } from './me'

export const SIGN_IN_PATH = '/ingresar'

/** Emails a sign-in link. It answers 202 whether or not anyone is at the address. */
export function requestLink(email: string): Promise<void> {
  return apiFetch<void>('/api/auth/link', { method: 'POST', body: JSON.stringify({ email }) })
}

/** Seconds to wait before asking again, from a 429's `Retry-After`; `null` when it gives none. */
export function retryAfterSeconds(headers: Headers): number | null {
  const seconds = Number(headers.get('Retry-After'))
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null
}

// The page a signed-out visitor asked for, kept while they go to their inbox. A link
// always lands on `/` (the callback takes no path but its own few), and is often
// opened in another tab, so it is kept in `localStorage`, not in the URL.
const RETURN_KEY = 'rakin.returnTo'

/** A same-origin path inside the app, or `undefined`: never an address elsewhere. */
export function appPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return undefined
  return /^\/(admin|me)(\/|\?|$)/.test(value) ? value : undefined
}

export function rememberReturnPath(value: string | undefined): void {
  const path = appPath(value)
  try {
    if (path) localStorage.setItem(RETURN_KEY, path)
    else localStorage.removeItem(RETURN_KEY)
  } catch {
    // Storage off (private mode): they land on their role's default instead.
  }
}

/**
 * Where a freshly signed-in person goes: the page they had asked for, when their role
 * reaches it, else their default. Staff land in `/admin`, a member on `/me`. Staff
 * reach `/me` too, since a coach often trains at their own gym (#214); a member never
 * reaches `/admin`. The kept path is used once.
 */
export function landingFor(role: StaffRole | null): string {
  let kept: string | undefined
  try {
    kept = appPath(localStorage.getItem(RETURN_KEY))
    localStorage.removeItem(RETURN_KEY)
  } catch {
    kept = undefined
  }
  const home = role === null ? '/me' : '/admin'
  const reaches = role === null ? ['/me'] : ['/admin', '/me']
  const within = (base: string) => kept === base || kept?.startsWith(`${base}/`) || kept?.startsWith(`${base}?`)
  return kept && reaches.some(within) ? kept : home
}

/** "Cerrar sesión": ends the session, forgets what this browser had loaded, back to sign in. */
export function useSignOut() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: () => apiFetch<void>('/api/auth/logout', { method: 'POST' }),
    onSuccess: async () => {
      queryClient.clear()
      await navigate({ to: SIGN_IN_PATH, replace: true })
    },
  })
}
