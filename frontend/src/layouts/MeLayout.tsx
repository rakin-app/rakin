import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import { useSignOut } from '../api/auth'
import { myAccessQuery, myselfQuery } from '../api/me'
import { Button } from '../components/Button'
import { InstallHint } from '../components/InstallHint'
import { t } from '../i18n/es'
import { TermsPending } from '../routes/TermsPending'
import './MeLayout.css'

/**
 * Shell for the student page reached by magic link. No navigation: the
 * student has one page, a phone's column that widens to two on a desktop, a way out,
 * and the gym's privacy notice. Staff who also train get a way back to the admin
 * screens (#214).
 */
export function MeLayout() {
  const signOut = useSignOut()
  const access = useQuery(myAccessQuery())
  const staff = access.data !== undefined && access.data !== null
  const me = useQuery(myselfQuery()).data
  // A gym that never accepted its terms has no one's data yet (#499): nothing to show.
  const pending = me?.terms === 'pending'
  return (
    <div className="me-shell">
      <main className="me-main">
        <InstallHint />
        {pending ? <TermsPending gym={me.gym_name} titular={me.titular_name ?? null} /> : <Outlet />}
      </main>
      <footer className="me-footer">
        {signOut.isError && (
          <p className="me-footer__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
        {staff && (
          <Link to="/admin" className="tap-link me-footer__link">
            {t.me.toAdmin}
          </Link>
        )}
        <Button disabled={signOut.isPending} onClick={() => signOut.mutate()}>
          {signOut.isPending ? t.signOut.working : t.signOut.label}
        </Button>
        <Link to="/privacidad" className="tap-link me-footer__link">
          {t.privacy.link}
        </Link>
      </footer>
    </div>
  )
}
