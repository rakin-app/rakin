import { useQuery } from '@tanstack/react-query'
import { useSignOut } from '../api/auth'
import { myselfQuery } from '../api/me'
import { Button } from '../components/Button'
import { ListRow } from '../components/Card'
import { SignOutIcon } from '../components/icons'
import { t } from '../i18n/es'

const copy = t.admin.settings.account

/**
 * "Cuenta": who is signed in, as the gym has them, and "Cerrar sesión". On a phone this
 * is where signing out lives, so the bottom bar keeps to five tabs (#177); the desktop
 * sidebar keeps its own.
 */
export function AccountSettings() {
  const me = useQuery(myselfQuery())
  const signOut = useSignOut()

  return (
    <section className="settings__section" aria-label={copy.title}>
      <div className="settings__card settings__card--rows">
        <ListRow title={copy.name} trailing={me.data?.name ?? copy.none} />
        <ListRow title={copy.email} trailing={me.data?.email ?? copy.none} />
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
