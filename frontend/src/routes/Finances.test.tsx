import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FinanceMonth, FinanceYear } from '../api/finances'
import type { Permission } from '../api/me'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.finances

const NOVEMBER: FinanceMonth = {
  month: '2026-11-01',
  current_month: '2026-11-01',
  income: { total_clp: 2_430_000, plans_clp: 2_110_000, extra_clp: 320_000 },
  expenses_clp: 1_512_990,
  result_clp: 917_010,
  categories: [
    { category_id: 'c-arriendo', name: 'Arriendo', amount_clp: 650_000, count: 1 },
    { category_id: 'c-sueldos', name: 'Sueldos y honorarios', amount_clp: 600_000, count: 2 },
    { category_id: 'c-luz', name: 'Luz', amount_clp: 262_990, count: 1 },
  ],
}

const months = (income: (m: number) => number | null, spent: (m: number) => number) =>
  Array.from({ length: 12 }, (_, i) => {
    const month = `2026-${String(i + 1).padStart(2, '0')}-01`
    const came = income(i)
    return { month, income_clp: came, expenses_clp: spent(i), result_clp: came === null ? null : came - spent(i) }
  })

const YEAR: FinanceYear = {
  year: 2026,
  current_month: '2026-11-01',
  months: months(
    (i) => (i === 9 ? 2_000_000 : i === 10 ? 2_430_000 : 0),
    (i) => (i === 9 ? 2_100_000 : i === 10 ? 1_512_990 : 0),
  ),
  income_clp: 4_430_000,
  expenses_clp: 3_612_990,
  result_clp: 817_010,
  categories: [
    {
      category_id: 'c-arriendo',
      name: 'Arriendo',
      amount_clp: 1_300_000,
      months: [0, 0, 0, 0, 0, 0, 0, 0, 0, 650_000, 650_000, 0],
    },
  ],
}

const EXPENSES_ONLY_MONTH: FinanceMonth = { ...NOVEMBER, income: null, result_clp: null }
const EXPENSES_ONLY_YEAR: FinanceYear = {
  ...YEAR,
  income_clp: null,
  result_clp: null,
  months: months(
    () => null,
    (i) => (i === 10 ? 1_512_990 : 0),
  ),
}

type Call = { method: string; path: string }

function access(role: string | Permission[]) {
  if (Array.isArray(role)) return { role: 'coach', permissions: role, account_holder: false }
  return asRole(role)
}

function stubApi(role: string | Permission[] = 'owner') {
  const calls: Call[] = []
  const reads = Array.isArray(role) && !role.includes('money_read')
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      calls.push({ method, path: url.pathname + url.search })
      let body: unknown = { detail: 'Not Found' }
      let status = 404
      const ok = (value: unknown) => {
        body = value
        status = 200
      }
      if (url.pathname === '/api/me/role') ok({ ...access(role), person_id: 'me', gym_name: 'Academia Sur' })
      else if (url.pathname === '/api/finances') {
        const month = url.searchParams.get('month') ?? NOVEMBER.month
        ok({ ...(reads ? EXPENSES_ONLY_MONTH : NOVEMBER), month })
      } else if (url.pathname === '/api/finances/year') ok(reads ? EXPENSES_ONLY_YEAR : YEAR)
      else if (url.pathname === '/api/ledger/pending') ok({ count: 0 })
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const monthCard = () => screen.findByRole('region', { name: copy.monthLabel('Noviembre 2026') })
const yearCard = () => screen.findByRole('region', { name: copy.yearLabel('2026') })

function tile(card: HTMLElement, label: string) {
  return within(card).getByText(label, { selector: 'dt' }).nextElementSibling?.textContent
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Finanzas', () => {
  it('shows the month: Entradas split into plans and cobros extra, Salidas by category, Resultado', async () => {
    stubApi()
    renderAt('/admin/finanzas')
    const card = await monthCard()

    expect(tile(card, copy.income)).toBe('$2.430.000')
    expect(tile(card, copy.expenses)).toBe('$1.512.990')
    expect(tile(card, copy.result)).toBe('+$917.010')
    const income = within(within(card).getByRole('region', { name: copy.income }))
    expect(income.getByText(copy.plans).nextElementSibling).toHaveTextContent('$2.110.000')
    expect(income.getByText(copy.extra).nextElementSibling).toHaveTextContent('$320.000')
    const out = within(within(card).getByRole('region', { name: copy.expenses }))
    expect(out.getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Arriendo$650.000',
      'Sueldos y honorarios$600.000',
      'Luz$262.990',
    ])
    // The current month is the last.
    expect(screen.getByRole('button', { name: copy.next })).toBeDisabled()
  })

  it('goes back a month with the arrow, in the URL', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/finanzas')
    await monthCard()
    await userEvent.setup().click(screen.getByRole('button', { name: copy.previous }))
    await waitFor(() => expect(router.state.location.search).toEqual({ month: '2026-10-01' }))
    expect(calls.some((c) => c.path === '/api/finances?month=2026-10-01')).toBe(true)
    expect(await screen.findByRole('region', { name: copy.monthLabel('Octubre 2026') })).toBeInTheDocument()
  })

  it('shows Salidas only to whoever sees expenses and not payments', async () => {
    stubApi(['expenses_read'])
    renderAt('/admin/finanzas')
    const card = await monthCard()
    expect(tile(card, copy.expenses)).toBe('$1.512.990')
    expect(within(card).queryByText(copy.income, { selector: 'dt' })).not.toBeInTheDocument()
    expect(within(card).queryByText(copy.result, { selector: 'dt' })).not.toBeInTheDocument()
    expect(within(card).queryByRole('region', { name: copy.income })).not.toBeInTheDocument()
    expect(within(card).getByText(copy.onlyExpenses)).toBeInTheDocument()
  })

  it('shows the year month by month, with its totals, a later month empty', async () => {
    stubApi()
    renderAt('/admin/finanzas?view=year')
    const card = await yearCard()

    expect(tile(card, copy.income)).toBe('$4.430.000')
    expect(tile(card, copy.result)).toBe('+$817.010')
    const table = within(card).getByRole('table')
    const rows = within(table).getAllByRole('row')
    // The head, twelve months and the totals.
    expect(rows).toHaveLength(14)
    expect(within(rows[10]!).getAllByRole('cell').map((c) => c.textContent)).toEqual(['$2.000.000', '$2.100.000', '−$100.000'])
    expect(within(rows[12]!).getAllByRole('cell').map((c) => c.textContent)).toEqual(['—', '—', '—'])
    expect(within(rows[13]!).getByRole('rowheader')).toHaveTextContent(copy.total)
    expect(screen.getByRole('button', { name: copy.nextYear })).toBeDisabled()
  })

  it("opens a category's row to its months", async () => {
    stubApi()
    renderAt('/admin/finanzas?view=year')
    await yearCard()
    const categories = await screen.findByRole('region', { name: copy.byCategory })
    await userEvent.setup().click(within(categories).getByRole('button', { name: /Arriendo/, expanded: false }))
    const opened = within(categories).getByRole('list', { name: copy.categoryMonths('Arriendo') })
    expect(within(opened).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Octubre$650.000', 'Noviembre$650.000'])
  })

  it("leaves the year's Entradas and Resultado out without payments", async () => {
    stubApi(['expenses_read'])
    renderAt('/admin/finanzas?view=year')
    const card = await yearCard()
    const table = within(card).getByRole('table')
    expect(within(table).getAllByRole('columnheader').map((c) => c.textContent)).toEqual([
      copy.columns.month,
      copy.columns.expenses,
    ])
  })

  it('switches between the month and the year', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/finanzas')
    await monthCard()
    await userEvent.setup().click(screen.getByRole('button', { name: copy.view.year }))
    await yearCard()
    expect(router.state.location.search).toEqual({ view: 'year' })
    expect(calls.some((c) => c.path === '/api/finances/year')).toBe(true)
  })

  it('tells an Administrador it is not theirs, and asks the API nothing about money out', async () => {
    const calls = stubApi('admin')
    renderAt('/admin/finanzas')
    expect(await screen.findByText(es.admin.expenses.onlyWho)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/finances'))).toBe(false)
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    expect(nav.queryByRole('link', { name: es.nav.finances })).not.toBeInTheDocument()
  })

  it("is beside Pagos in the sidebar for the titular, and out of the phone's bar", async () => {
    stubApi()
    renderAt('/admin/finanzas')
    await monthCard()
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    const links = nav.getAllByRole('link').map((l) => l.textContent)
    expect(links.indexOf(es.nav.finances)).toBe(links.indexOf(es.nav.payments) + 1)
    expect(nav.getByRole('link', { name: es.nav.finances }).closest('li')).toHaveClass('admin-nav__wide')
  })
})
