import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useSignOut } from '../api/auth'
import { myselfQuery } from '../api/me'
import { Button } from '../components/Button'
import { ListRow, ListRowContent, listRowClass } from '../components/Card'
import { ChevronRightIcon, SignOutIcon } from '../components/icons'
import { t } from '../i18n/es'

const copy = t.admin.settings.account

/**
 * "Cuenta": who is signed in, as the gym has them, and "Cerrar sesión". On a phone this
 * is where signing out lives, so the bottom bar keeps to five tabs (#177); the desktop
 * sidebar keeps its own. So is "Mi página", for staff who also train (#214).
 */
export function AccountSettings() {
  const me = useQuery(myselfQuery())
  const signOut = useSignOut()

  return (
    <section className="settings__section" aria-label={copy.title}>
      <div className="settings__card settings__card--rows">
        <ListRow title={copy.name} trailing={me.data?.name ?? copy.none} />
        <ListRow title={copy.email} trailing={me.data?.email ?? copy.none} />
        {me.data?.student_page && (
          <Link to="/me" className={listRowClass(true)}>
            <ListRowContent title={t.nav.myPage} trailing={<ChevronRightIcon />} />
          </Link>
        )}
      </div>
      {signOut.isError && (
        <p className="settings__error" role="alert">
          {t.signOut.failed}
        </p>
      )}
      <Button size="lg" fullWidth disabled={signOut.isPending} onClick={() => signOut.mutate()}>
        <SignOutIcon />
        {signOut.isPending ? t.signOut.working : t.signOut.label}
      </Button>
    </section>
  )
}
