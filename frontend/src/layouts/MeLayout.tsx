import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { useSignOut } from '../api/auth'
import { myRoleQuery } from '../api/me'
import { Button } from '../components/Button'
import { InstallHint } from '../components/InstallHint'
import { t } from '../i18n/es'
import './MeLayout.css'

/**
 * Shell for the student page reached by magic link. No navigation: the
 * student has one page, a phone's column that widens to two on a desktop, a way out,
 * and the gym's privacy notice. Staff who also train get a way back to the admin
 * screens (#214).
 */
export function MeLayout() {
  const signOut = useSignOut()
  const role = useQuery(myRoleQuery())
  const staff = role.data !== undefined && role.data !== null
  return (
    <div className="me-shell">
      <main className="me-main">
        <InstallHint />
        <Outlet />
      </main>
      <footer className="me-footer">
        {signOut.isError && (
          <p className="me-footer__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
        {staff && (
          <Link to="/admin" className="me-footer__link">
            {t.me.toAdmin}
          </Link>
        )}
        <Button disabled={signOut.isPending} onClick={() => signOut.mutate()}>
          {signOut.isPending ? t.signOut.working : t.signOut.label}
        </Button>
        <Link to="/privacidad" className="me-footer__link">
          {t.privacy.link}
        </Link>
      </footer>
    </div>
  )
}
