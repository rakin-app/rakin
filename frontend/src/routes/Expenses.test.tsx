import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Expense, ExpenseCategory, ExpenseMonth } from '../api/expenses'
import type { Permission } from '../api/me'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.expenses

const CATEGORIES: ExpenseCategory[] = [
  { id: 'c-arriendo', name: 'Arriendo', sort: 1, is_other: false, archived: false, expenses: 1 },
  { id: 'c-luz', name: 'Luz', sort: 2, is_other: false, archived: false, expenses: 1 },
  { id: 'c-otros', name: 'Otros', sort: 3, is_other: true, archived: false, expenses: 0 },
  { id: 'c-gas', name: 'Gas', sort: 4, is_other: false, archived: true, expenses: 2 },
]

const RENT: Expense = {
  id: 'e-rent',
  spent_on: '2026-11-05',
  amount_clp: 650_000,
  category_id: 'c-arriendo',
  category_name: 'Arriendo',
  payee: 'Inmobiliaria Los Robles',
  method: 'transfer',
  note: null,
  has_receipt: true,
  created_by_name: 'Ana Rojas',
  created_at: '2026-11-05T13:00:00Z',
  updated_at: null,
  voided_at: null,
  voided_by_name: null,
  void_reason: null,
}

const POWER: Expense = {
  ...RENT,
  id: 'e-power',
  spent_on: '2026-11-18',
  amount_clp: 84_000,
  category_id: 'c-luz',
  category_name: 'Luz',
  payee: 'Enel',
  has_receipt: false,
  voided_at: '2026-11-19T10:00:00Z',
  voided_by_name: 'Ana Rojas',
  void_reason: 'pagado dos veces',
}

const NOVEMBER: ExpenseMonth = {
  month: '2026-11-01',
  current_month: '2026-11-01',
  today: '2026-11-20',
  category_id: null,
  total_clp: 650_000,
  count: 1,
  items: [POWER, RENT],
}

type Call = { method: string; path: string; body: unknown }

function access(role: string | Permission[]) {
  if (Array.isArray(role)) return { role: 'coach', permissions: role, account_holder: false }
  return asRole(role)
}

function stubApi(role: string | Permission[] = 'owner') {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      calls.push({ method, path: url.pathname + url.search, body: init?.body ? JSON.parse(String(init.body)) : null })
      let body: unknown = { detail: 'Not Found' }
      let status = 404
      const ok = (value: unknown, code = 200) => {
        body = value
        status = code
      }
      if (url.pathname === '/api/me/role') ok({ ...access(role), person_id: 'me', gym_name: 'Academia Sur' })
      else if (url.pathname === '/api/expenses' && method === 'GET') {
        ok({ ...NOVEMBER, month: url.searchParams.get('month') ?? NOVEMBER.month })
      } else if (url.pathname === '/api/expenses' && method === 'POST') ok({ ...RENT, id: 'e-new', amount_clp: 32_990 }, 201)
      else if (url.pathname === '/api/expenses/categories') ok(CATEGORIES)
      else if (url.pathname === '/api/expenses/e-rent' && method === 'PATCH') ok({ ...RENT, amount_clp: 640_000 })
      else if (url.pathname === '/api/expenses/e-rent/void') ok({ ...RENT, voided_at: '2026-11-20T10:00:00Z' })
      else if (url.pathname === '/api/expenses/e-rent/receipt') ok({ url: 'https://blobs.example/r', content_type: 'application/pdf' })
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

const rows = async () => within(await screen.findByRole('region', { name: copy.listLabel('Noviembre 2026') })).getAllByRole('listitem')

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Gastos', () => {
  it('lists the month newest first, a voided expense struck through, with the total of the rest', async () => {
    stubApi()
    renderAt('/admin/pagos/gastos')

    const [power, rent] = await rows()
    expect(power).toHaveClass('expenses__row--voided')
    expect(within(power!).getByText(copy.voided)).toBeInTheDocument()
    expect(within(power!).getByText('$84.000')).toBeInTheDocument()
    expect(rent).not.toHaveClass('expenses__row--voided')
    expect(within(rent!).getByText('Inmobiliaria Los Robles · Transferencia')).toBeInTheDocument()
    expect(screen.getByText('$650.000', { selector: '.expenses__total-figure' })).toBeInTheDocument()
    expect(screen.getByText(copy.count(1), { selector: '.expenses__total-count' })).toBeInTheDocument()
    // The current month is the last: no later one.
    expect(screen.getByRole('button', { name: copy.next })).toBeDisabled()
  })

  it('opens a row to who recorded it, its receipt and why it was voided', async () => {
    const calls = stubApi()
    renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    const [power, rent] = await rows()

    await user.click(within(power!).getByRole('button', { expanded: false }))
    expect(within(power!).getByText('Anulado por Ana Rojas: pagado dos veces')).toBeInTheDocument()
    // A voided expense is not changed again.
    expect(within(power!).queryByRole('button', { name: copy.edit })).not.toBeInTheDocument()

    await user.click(within(rent!).getByRole('button', { expanded: false }))
    // The link is asked for on the tap, never earlier, so it is never a stale one.
    expect(calls.some((c) => c.path.endsWith('/receipt'))).toBe(false)
    const tab = { opener: {}, location: { href: '' }, close: vi.fn() }
    vi.stubGlobal('open', vi.fn(() => tab))
    await user.click(within(rent!).getByRole('button', { name: copy.receipt }))
    await waitFor(() => expect(tab.location.href).toBe('https://blobs.example/r'))
    expect(tab.opener).toBeNull()
    expect(within(rent!).getByRole('button', { name: copy.edit })).toBeInTheDocument()
  })

  it('records an expense from the form opened in place', async () => {
    const calls = stubApi()
    renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    await rows()

    await user.click(screen.getByRole('button', { name: copy.record }))
    const form = within(screen.getByRole('form', { name: copy.form.newTitle }))
    // Archived categories are not offered for a new expense.
    expect(form.queryByRole('option', { name: 'Gas' })).not.toBeInTheDocument()
    await user.click(form.getByRole('button', { name: copy.form.save }))
    expect(form.getByText(copy.form.amountNeeded)).toBeInTheDocument()
    expect(form.getByText(copy.form.categoryNeeded)).toBeInTheDocument()

    await user.type(form.getByLabelText(copy.form.amount), '32990')
    expect(form.getByLabelText(copy.form.amount)).toHaveValue('32.990')
    await user.selectOptions(form.getByLabelText(copy.form.category), 'c-luz')
    await user.type(form.getByLabelText(copy.form.payee, { exact: false }), 'Movistar')
    await user.selectOptions(form.getByLabelText(copy.form.method), 'card')
    await user.click(form.getByRole('button', { name: copy.form.save }))

    expect(await screen.findByText(copy.form.saved('$32.990'))).toBeInTheDocument()
    const posted = calls.find((c) => c.method === 'POST' && c.path === '/api/expenses')
    expect(posted?.body).toMatchObject({
      amount_clp: 32_990,
      category_id: 'c-luz',
      payee: 'Movistar',
      method: 'card',
      note: null,
      receipt_key: null,
    })
  })

  it('corrects an expense, and voids one only with a reason', async () => {
    const calls = stubApi()
    renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    const [, rent] = await rows()

    await user.click(within(rent!).getByRole('button', { expanded: false }))
    await user.click(within(rent!).getByRole('button', { name: copy.edit }))
    const form = within(within(rent!).getByRole('form', { name: copy.form.editTitle }))
    expect(form.getByText(copy.form.changeNote)).toBeInTheDocument()
    const amount = form.getByLabelText(copy.form.amount)
    await user.clear(amount)
    await user.type(amount, '640000')
    await user.click(form.getByRole('button', { name: copy.form.saveChange }))
    expect(await screen.findByText(copy.form.changed)).toBeInTheDocument()
    const patched = calls.find((c) => c.method === 'PATCH')
    expect(patched?.path).toBe('/api/expenses/e-rent')
    // Only what changed: someone else's correction of another field is left alone.
    expect(patched?.body).toEqual({ amount_clp: 640_000 })

    await user.click(within(rent!).getByRole('button', { expanded: false }))
    await user.click(within(rent!).getByRole('button', { name: copy.void }))
    const voiding = within(within(rent!).getByRole('form', { name: copy.voidForm.title('Arriendo · $650.000') }))
    await user.click(voiding.getByRole('button', { name: copy.voidForm.submit }))
    expect(voiding.getByText(copy.voidForm.reasonNeeded)).toBeInTheDocument()
    await user.type(voiding.getByLabelText(copy.voidForm.reason), 'era del mes pasado')
    await user.click(voiding.getByRole('button', { name: copy.voidForm.submit }))
    expect(await screen.findByText(copy.voidForm.done)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/expenses/e-rent/void')?.body).toEqual({ reason: 'era del mes pasado' })
  })

  it("dates a new expense on the gym's today, not the browser's UTC day", async () => {
    // 22:30 on 20 November in Santiago is already the 21st in UTC.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-21T01:30:00Z'))
    stubApi()
    renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    await rows()
    await user.click(screen.getByRole('button', { name: copy.record }))
    const day = within(screen.getByRole('form', { name: copy.form.newTitle })).getByLabelText(copy.form.spentOn)
    expect(day).toHaveValue('2026-11-20')
    expect(day).toHaveAttribute('max', '2026-11-20')
  })

  it('goes to the month before, keeping it in the address', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    await rows()
    await user.click(screen.getByRole('button', { name: copy.previous }))
    await waitFor(() => expect(router.state.location.search).toEqual({ month: '2026-10-01' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/expenses?month=2026-10-01')).toBe(true))
  })

  it('moves a category and archives it, but never Otros', async () => {
    const calls = stubApi()
    renderAt('/admin/pagos/gastos')
    const user = userEvent.setup()
    await rows()

    await user.click(screen.getByText(copy.categories.title))
    expect(screen.getByRole('button', { name: copy.categories.up('Arriendo') })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: copy.categories.down('Arriendo') }))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/expenses/categories/order')?.body).toEqual({
        ids: ['c-luz', 'c-arriendo', 'c-otros'],
      }),
    )
    const otros = screen.getByText('Otros', { selector: '.expenses__category-name' }).closest('li')!
    expect(within(otros).queryByRole('button', { name: copy.categories.archive })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.categories.restore })).toBeInTheDocument()
  })

  it('shows a reader the list with nothing to record, correct or void', async () => {
    stubApi(['expenses_read'])
    renderAt('/admin/pagos/gastos')
    const [, rent] = await rows()
    expect(screen.queryByRole('button', { name: copy.record })).not.toBeInTheDocument()
    expect(screen.queryByText(copy.categories.title)).not.toBeInTheDocument()
    await userEvent.setup().click(within(rent!).getByRole('button', { expanded: false }))
    expect(within(rent!).queryByRole('button', { name: copy.edit })).not.toBeInTheDocument()
    expect(within(rent!).getByRole('button', { name: copy.receipt })).toBeInTheDocument()
  })

  it('tells an Administrador it is not theirs, and asks the API nothing about expenses', async () => {
    const calls = stubApi('admin')
    renderAt('/admin/pagos/gastos')
    expect(await screen.findByText(copy.onlyWho)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/expenses'))).toBe(false)
  })

  it("puts Gastos in Pagos' tab for someone who sees expenses and not payments", async () => {
    stubApi(['expenses_read'])
    renderAt('/admin/pagos/gastos')
    await rows()
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    expect(nav.getByRole('link', { name: es.admin.payments.expenses })).toHaveAttribute('href', '/admin/pagos/gastos')
    expect(nav.queryByRole('link', { name: es.nav.payments })).not.toBeInTheDocument()
    // No way back to a Pagos they cannot read.
    expect(screen.queryByRole('link', { name: es.common.backTo(es.common.places.payments) })).not.toBeInTheDocument()
  })
})
