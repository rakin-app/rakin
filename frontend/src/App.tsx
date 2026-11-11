import { QueryClientProvider, useQuery, type QueryClient } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { useEffect } from 'react'
import { hostQuery } from './api/host'
import { myselfQuery } from './api/me'
import type { createAppRouter } from './router'
import { applyTheme, isTheme } from './theme'

type Props = {
  queryClient: QueryClient
  router: ReturnType<typeof createAppRouter>
}

export function App({ queryClient, router }: Props) {
  return (
    <QueryClientProvider client={queryClient}>
      <GymTheme />
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

/** Wears the gym's theme: the signed-in gym's, as `/api/me/role` says once a screen has
 * asked, else the one this address serves. Neither answered: what the last visit wore. */
function GymTheme() {
  const host = useQuery(hostQuery())
  // Read, never fetched here: the screens that need a session ask for it.
  const me = useQuery({ ...myselfQuery(), enabled: false })
  const theme = me.data?.theme ?? host.data?.gym?.theme
  useEffect(() => {
    if (isTheme(theme)) applyTheme(theme)
  }, [theme])
  return null
}
