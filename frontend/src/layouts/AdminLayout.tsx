import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { pendingCountQuery } from '../api/proofs'
import { ClassesIcon, PaymentsIcon, StudentsIcon, TodayIcon } from '../components/icons'
import { t } from '../i18n/es'
import './AdminLayout.css'

type NavItem = {
  to: '/admin' | '/admin/alumnos' | '/admin/clases' | '/admin/pagos'
  label: string
  icon: ReactNode
  exact?: boolean
}

const NAV_ITEMS: readonly NavItem[] = [
  { to: '/admin', label: t.nav.today, icon: <TodayIcon />, exact: true },
  { to: '/admin/alumnos', label: t.nav.students, icon: <StudentsIcon /> },
  { to: '/admin/clases', label: t.nav.classes, icon: <ClassesIcon /> },
  { to: '/admin/pagos', label: t.nav.payments, icon: <PaymentsIcon /> },
]

/**
 * Shell for the owner and coach screens. On a phone the nav is the bottom tab
 * bar from the mobile designs; from 960px it becomes the sidebar of the
 * desktop ledger design. One <nav>, restyled by CSS, so both share a tab order.
 */
export function AdminLayout() {
  // Proofs waiting for review, on the Pagos tab. A coach is refused the ledger, so
  // the query fails and no badge shows.
  const pending = useQuery(pendingCountQuery())
  const badge = pending.data ?? 0

  return (
    <div className="admin-shell">
      <nav className="admin-nav" aria-label={t.nav.label}>
        <span className="admin-nav__brand" aria-hidden="true">
          {t.app.name}
        </span>
        <ul className="admin-nav__list">
          {NAV_ITEMS.map((item) => (
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
        </ul>
      </nav>
      <main className="admin-main">
        <Outlet />
      </main>
    </div>
  )
}
