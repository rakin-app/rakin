import { Outlet } from '@tanstack/react-router'
import { useSignOut } from '../api/auth'
import { t } from '../i18n/es'
import './MeLayout.css'

/**
 * Shell for the student page reached by magic link. No navigation: the
 * student has one page, laid out as a single mobile-width column, and a way out.
 */
export function MeLayout() {
  const signOut = useSignOut()
  return (
    <div className="me-shell">
      <main className="me-main">
        <Outlet />
      </main>
      <footer className="me-footer">
        {signOut.isError && (
          <p className="me-footer__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
        <button
          type="button"
          className="me-footer__sign-out"
          disabled={signOut.isPending}
          onClick={() => signOut.mutate()}
        >
          {signOut.isPending ? t.signOut.working : t.signOut.label}
        </button>
      </footer>
    </div>
  )
}
