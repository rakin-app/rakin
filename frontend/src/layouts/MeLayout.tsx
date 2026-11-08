import { Outlet } from '@tanstack/react-router'
import './MeLayout.css'

/**
 * Shell for the student page reached by magic link. No navigation: the
 * student has one page, laid out as a single mobile-width column.
 */
export function MeLayout() {
  return (
    <div className="me-shell">
      <main className="me-main">
        <Outlet />
      </main>
    </div>
  )
}
