import { Link, Outlet } from '@tanstack/react-router'
import type { ReactNode } from 'react'
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
                {item.icon}
                <span>{item.label}</span>
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
