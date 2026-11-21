import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useSignOut } from '../api/auth'
import { myselfQuery } from '../api/me'
import { Button } from '../components/Button'
import { Banner, Card, ListRow, listRowClass, ListRowContent } from '../components/Card'
import { ChevronRightIcon, SignOutIcon, StatusIcon } from '../components/icons'
import { STATUS_URL } from '../config'
import { t } from '../i18n/es'
import { SectionHead } from './settingsForm'

const copy = t.admin.settings.account

/**
 * "Cuenta": who is signed in, as the gym has them, and "Cerrar sesión". On a phone this
 * is where signing out lives, so the bottom bar keeps to five tabs (#177); the desktop
 * sidebar keeps its own. So is "Mi página", for staff who also train (#214), and
 * "Estado del servicio", the public uptime page in a new tab (#519).
 */
export function AccountSettings() {
  const me = useQuery(myselfQuery())
  const signOut = useSignOut()

  return (
    <section className="settings__section" aria-label={copy.title}>
      <SectionHead intro={t.admin.settings.descriptions.account} />
      <Card as="div" flush className="settings__card settings__card--rows">
        <ListRow title={copy.name} trailing={me.data?.name ?? copy.none} />
        <ListRow title={copy.email} trailing={me.data?.email ?? copy.none} />
        {me.data?.student_page && (
          <Link to="/me" className={listRowClass(true)}>
            <ListRowContent title={t.nav.myPage} trailing={<ChevronRightIcon />} />
          </Link>
        )}
        <a href={STATUS_URL} target="_blank" rel="noopener noreferrer" className={listRowClass(true)}>
          <ListRowContent title={t.nav.status} detail={t.nav.statusLine} trailing={<StatusIcon />} />
        </a>
      </Card>
      {signOut.isError && (
        <Banner tone="error">
          {t.signOut.failed}
        </Banner>
      )}
      <div className="settings__actions">
        <Button disabled={signOut.isPending} onClick={() => signOut.mutate()}>
          <SignOutIcon />
          {signOut.isPending ? t.signOut.working : t.signOut.label}
        </Button>
      </div>
    </section>
  )
}
