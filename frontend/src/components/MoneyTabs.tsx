import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { myAccessQuery, readsExpenses, readsLedger } from '../api/me'
import { t } from '../i18n/es'
import './MoneyTabs.css'

const copy = t.admin.money.tabs

type MoneyTab = {
  to: '/admin/pagos' | '/admin/finanzas' | '/admin/finanzas/gastos'
  label: string
  exact: boolean
}

/**
 * Pagos, Finanzas and Gastos, one money section (#531): the same row of tabs at the top
 * of each of the three, one tap between any two. `money_read` shows Pagos and
 * `expenses_read` Finanzas and Gastos; with one tab to show, there is no row. The
 * bottom bar's and the sidebar's Pagos stays current on all three (AdminLayout).
 */
export function MoneyTabs() {
  const access = useQuery(myAccessQuery()).data
  const tabs: MoneyTab[] = [
    ...(readsLedger(access) ? [{ to: '/admin/pagos', label: copy.payments, exact: true } as const] : []),
    ...(readsExpenses(access)
      ? ([
          { to: '/admin/finanzas', label: copy.finances, exact: true },
          { to: '/admin/finanzas/gastos', label: copy.expenses, exact: false },
        ] as const)
      : []),
  ]
  if (tabs.length < 2) return null
  return (
    <nav className="money-tabs" aria-label={copy.label}>
      {tabs.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          activeOptions={{ exact: tab.exact, includeSearch: false }}
          className="money-tabs__link"
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  )
}
