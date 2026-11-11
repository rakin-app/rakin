import { QueryClientProvider, useQuery, type QueryClient } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { useEffect } from 'react'
import { hostQuery } from './api/host'
import { myselfQuery } from './api/me'
import { OfflineNotice } from './components/OfflineNotice'
import type { createAppRouter } from './router'
import { logoIcon } from './logo'
import { setTabIcon } from './tabIcon'
import { applyTheme, isTheme } from './theme'

type Props = {
  queryClient: QueryClient
  router: ReturnType<typeof createAppRouter>
}

export function App({ queryClient, router }: Props) {
  return (
    <QueryClientProvider client={queryClient}>
      <GymTheme />
      <GymTabIcon />
      <RouterProvider router={router} />
      <OfflineNotice />
    </QueryClientProvider>
  )
}

/** Wears the gym's theme: the signed-in gym's, as `/api/me/role` says once a screen has
 * asked, else the one this address serves. With neither (the shared address, nobody
 * signed in, where `/api/host` names no gym) it leaves what the last visit wore, kept by
 * `theme.ts`, on purpose: someone who signs in to a gym from there sees its colours
 * from the first screen. That is the default until anyone has signed in on this browser. */
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

/** On a gym's own address, the tab shows the gym's logo once it has one (#223); else,
 * and on the shared address, Rakin's. */
function GymTabIcon() {
  const logo = useQuery(hostQuery()).data?.gym?.logo
  useEffect(() => {
    setTabIcon(logo ? logoIcon(logo) : null)
  }, [logo])
  return null
}
