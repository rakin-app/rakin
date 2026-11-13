import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useSignOut } from '../api/auth'
import { managesGym, myRoleQuery, myselfQuery, readsLedger } from '../api/me'
import { pendingCountQuery } from '../api/proofs'
import { useTimerSync } from '../api/sessionBlocks'
import { GymMark } from '../components/GymMark'
import { InstallHint } from '../components/InstallHint'
import { RakinLogo } from '../components/RakinLogo'
import { ClassesIcon, MyPageIcon, PaymentsIcon, SettingsIcon, SignOutIcon, StudentsIcon, TodayIcon } from '../components/icons'
import { t } from '../i18n/es'
import { useRise } from '../motion'
import { useGymName } from '../pageTitle'
import './AdminLayout.css'

type NavItem = {
  to: '/admin' | '/admin/alumnos' | '/admin/clases' | '/admin/pagos' | '/admin/ajustes'
  label: string
  icon: ReactNode
  exact?: boolean
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: '/admin', label: t.nav.today, icon: <TodayIcon />, exact: true },
  { to: '/admin/alumnos', label: t.nav.students, icon: <StudentsIcon /> },
  { to: '/admin/clases', label: t.nav.classes, icon: <ClassesIcon /> },
  { to: '/admin/pagos', label: t.nav.payments, icon: <PaymentsIcon /> },
  { to: '/admin/ajustes', label: t.nav.settings, icon: <SettingsIcon /> },
]

/**
 * Shell for the owner and coach screens. On a phone the nav is the bottom tab
 * bar from the mobile designs, five tabs at most, under a dark bar with the mark and the
 * gym's name; from 960px it becomes the dark sidebar of the desktop ledger design, with
 * the gym's name under the mark (#199). One <nav>, restyled by CSS,
 * so both share a tab order. "Cerrar sesión" is the sidebar's last item; on a phone it
 * is in Ajustes → Cuenta instead, so the bar keeps to the sections (#177), except for a
 * coach, who has no Ajustes and three tabs. "Mi página", the student page of staff who
 * also train (#214), sits above it, and goes the same way: in Cuenta on an owner's phone,
 * a fourth tab on a coach's.
 */
export function AdminLayout() {
  // Proofs waiting for review, on the Pagos tab: asked for only by those who read
  // the ledger, so a coach never polls a request that would be refused.
  const role = useQuery(myRoleQuery())
  const studentPage = useQuery(myselfQuery()).data?.student_page ?? false
  const signOut = useSignOut()
  // A class timed without signal reaches the API from whichever screen is open.
  useTimerSync()
  const pending = useQuery({ ...pendingCountQuery(), enabled: readsLedger(role.data) })
  const badge = pending.data ?? 0
  const gym = useGymName()
  const logo = useQuery(myselfQuery()).data?.gym_logo
  const rise = useRise<HTMLDivElement>()
  // Pagos is money and Ajustes the gym's configuration: each shown only once the role
  // is known to reach it, so a coach never sees either tab, not even while the role loads.
  const navItems = NAV_ITEMS.filter(
    (item) =>
      (item.to !== '/admin/pagos' || readsLedger(role.data)) && (item.to !== '/admin/ajustes' || managesGym(role.data)),
  )

  const endClass = role.isSuccess && !managesGym(role.data) ? 'admin-nav__end admin-nav__end--bar' : 'admin-nav__end'

  return (
    <div className="admin-shell">
      {/* A phone's dark bar over the page: the mark, and the gym's own with its name. */}
      <header className="admin-top">
        <span className="admin-top__brand">
          <RakinLogo surface="dark" />
        </span>
        {gym && (
          <span className="admin-top__gym">
            <GymMark name={gym} logo={logo} />
            <span className="admin-top__gym-name">{gym}</span>
          </span>
        )}
      </header>
      <nav className="admin-nav" aria-label={t.nav.label}>
        <div className="admin-nav__head">
          <span className="admin-nav__brand">
            <RakinLogo surface="dark" />
          </span>
          {gym && (
            <span className="admin-nav__gym">
              <GymMark name={gym} logo={logo} />
              <span className="admin-nav__gym-name">{gym}</span>
            </span>
          )}
        </div>
        <ul className="admin-nav__list">
          {navItems.map((item) => (
            <li key={item.to}>
              <Link to={item.to} activeOptions={{ exact: item.exact ?? false }} className="admin-nav__link">
                <span className="admin-nav__icon">
                  {item.icon}
                  {item.to === '/admin/pagos' && badge > 0 && (
                    <span className="admin-nav__badge" aria-hidden="true">
                      {badge}
                    </span>
                  )}
                </span>
                <span>{item.label}</span>
                {item.to === '/admin/pagos' && badge > 0 && (
                  <span className="visually-hidden">{t.nav.pendingBadge(badge)}</span>
                )}
              </Link>
            </li>
          ))}
          {studentPage && (
            <li className={endClass}>
              <Link to="/me" className="admin-nav__link">
                <span className="admin-nav__icon">
                  <MyPageIcon />
                </span>
                <span>{t.nav.myPage}</span>
              </Link>
            </li>
          )}
          {/* On a phone it is in Ajustes → Cuenta; a coach has no Ajustes, so their bar keeps it. Only
              once the role is known: a bar that showed it while loading would flash a sixth tab. */}
          <li className={endClass}>
            <button
              type="button"
              className="admin-nav__link"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              <span className="admin-nav__icon">
                <SignOutIcon />
              </span>
              <span>{t.signOut.label}</span>
            </button>
          </li>
        </ul>
        {signOut.isError && (
          <p className="admin-nav__error" role="alert">
            {t.signOut.failed}
          </p>
        )}
      </nav>
      <main className="admin-main">
        <InstallHint />
        <div ref={rise} className="page-rise">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
