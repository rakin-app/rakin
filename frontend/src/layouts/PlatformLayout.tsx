import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Outlet, useNavigate } from '@tanstack/react-router'
import { PLATFORM_SIGN_IN_PATH, platformLogout, platformMeQuery } from '../api/platform'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { t } from '../i18n/es'
import './PlatformLayout.css'

const copy = t.platform

/**
 * Shell for the platform's panel (#436): a plain header, "Rakin · Plataforma", with the
 * operator's email and a way out. None of a gym's: no theme, no gym's mark, no nav yet,
 * since the panel has one screen.
 */
export function PlatformLayout() {
  const me = useQuery(platformMeQuery()).data
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const signOut = useSubmit({
    mutationFn: platformLogout,
    onSuccess: async () => {
      queryClient.clear()
      await navigate({ to: PLATFORM_SIGN_IN_PATH, replace: true })
    },
  })
  return (
    <div className="platform-shell">
      <header className="platform-top">
        <span className="platform-top__brand">{copy.brand}</span>
        <div className="platform-top__account">
          {me && <span className="platform-top__email">{me.email}</span>}
          <Button disabled={signOut.isPending} onClick={() => signOut.mutate()}>
            {signOut.isPending ? copy.signingOut : copy.signOut}
          </Button>
        </div>
      </header>
      {signOut.isError && (
        <p className="platform-top__error" role="alert">
          {copy.signOutFailed}
        </p>
      )}
      <main className="platform-main">
        <Outlet />
      </main>
    </div>
  )
}
