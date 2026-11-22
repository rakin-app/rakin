import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DueRecurring, Expense, ExpenseCategory, ExpenseMonth, RecurringMonth } from '../api/expenses'
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
  recurring_id: null,
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

const RENT_FIXED: DueRecurring = {
  id: 'r-rent',
  category_id: 'c-arriendo',
  category_name: 'Arriendo',
  category_archived: false,
  payee: null,
  method: 'transfer',
  amount_clp: 650_000,
  amount_kind: 'fixed',
  day_of_month: 5,
  active: true,
  created_at: '2026-08-01T12:00:00Z',
  due_on: '2026-11-05',
}

const INTERNET: DueRecurring = {
  ...RENT_FIXED,
  id: 'r-internet',
  category_id: 'c-otros',
  category_name: 'Otros',
  payee: 'Movistar',
  amount_clp: 32_990,
  day_of_month: 10,
  due_on: '2026-11-10',
}

const POWER_ESTIMATED: DueRecurring = {
  ...RENT_FIXED,
  id: 'r-power',
  category_id: 'c-luz',
  category_name: 'Luz',
  payee: 'Enel',
  amount_clp: 84_000,
  amount_kind: 'estimated',
  day_of_month: 25,
  due_on: '2026-11-20',
}

const NOVEMBER_DUE: RecurringMonth = {
  month: '2026-11-01',
  current_month: '2026-11-01',
  today: '2026-11-20',
  due: [RENT_FIXED, INTERNET, POWER_ESTIMATED],
  skipped: [],
}

type Call = { method: string; path: string; body: unknown }

function access(role: string | Permission[]) {
  if (Array.isArray(role)) return { role: 'coach', permissions: role, account_holder: false }
  return asRole(role)
}

function stubApi(
  role: string | Permission[] = 'owner',
  due: RecurringMonth = NOVEMBER_DUE,
  // How `/record` refuses, if it does: the API's 422 for the template that stops a batch.
  refuseRecord: { code: string; recurring_id: string } | null = null,
) {
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
      else if (url.pathname === '/api/expenses/recurring/month') ok(due)
      else if (url.pathname === '/api/expenses/recurring/record' && refuseRecord) {
        ok({ detail: { ...refuseRecord, message: 'refused' } }, 422)
      } else if (url.pathname === '/api/expenses/recurring/record') {
        const ids = (calls.at(-1)!.body as { ids: string[] }).ids
        const templates = [...due.due, ...due.skipped].filter((r) => ids.includes(r.id))
        ok(
          templates.map((r) => ({ ...RENT, id: `e-${r.id}`, amount_clp: r.amount_clp, recurring_id: r.id })),
          201,
        )
      } else if (url.pathname === '/api/expenses/recurring' && method === 'GET') ok([RENT_FIXED, { ...POWER_ESTIMATED, active: false }])
      else if (url.pathname === '/api/expenses/recurring' && method === 'POST') ok({ ...RENT_FIXED, id: 'r-new' }, 201)
      else if (url.pathname.startsWith('/api/expenses/recurring/') && method === 'PATCH') ok(RENT_FIXED)
      else if (url.pathname.includes('/skip')) ok(null, 204)
      if (status === 204) return new Response(null, { status })
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
    renderAt('/admin/finanzas/gastos')

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
    renderAt('/admin/finanzas/gastos')
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
    renderAt('/admin/finanzas/gastos')
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
    renderAt('/admin/finanzas/gastos')
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
    renderAt('/admin/finanzas/gastos')
    const user = userEvent.setup()
    await rows()
    await user.click(screen.getByRole('button', { name: copy.record }))
    const day = within(screen.getByRole('form', { name: copy.form.newTitle })).getByLabelText(copy.form.spentOn)
    expect(day).toHaveValue('2026-11-20')
    expect(day).toHaveAttribute('max', '2026-11-20')
  })

  it('goes to the month before, keeping it in the address', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/finanzas/gastos')
    const user = userEvent.setup()
    await rows()
    await user.click(screen.getByRole('button', { name: copy.previous }))
    await waitFor(() => expect(router.state.location.search).toEqual({ month: '2026-10-01' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/api/expenses?month=2026-10-01')).toBe(true))
  })

  it('moves a category and archives it, but never Otros', async () => {
    const calls = stubApi()
    renderAt('/admin/finanzas/gastos')
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
    renderAt('/admin/finanzas/gastos')
    const [, rent] = await rows()
    expect(screen.queryByRole('button', { name: copy.record })).not.toBeInTheDocument()
    expect(screen.queryByText(copy.categories.title)).not.toBeInTheDocument()
    await userEvent.setup().click(within(rent!).getByRole('button', { expanded: false }))
    expect(within(rent!).queryByRole('button', { name: copy.edit })).not.toBeInTheDocument()
    expect(within(rent!).getByRole('button', { name: copy.receipt })).toBeInTheDocument()
  })

  it('tells an Administrador it is not theirs, and asks the API nothing about expenses', async () => {
    const calls = stubApi('admin')
    renderAt('/admin/finanzas/gastos')
    expect(await screen.findByText(copy.onlyWho)).toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/expenses'))).toBe(false)
  })

  it("puts Finanzas in Pagos' place for someone who sees expenses and not payments, with two tabs", async () => {
    stubApi(['expenses_read'])
    renderAt('/admin/finanzas/gastos')
    await rows()
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    const finances = nav.getByRole('link', { name: es.nav.finances })
    expect(finances).toHaveAttribute('href', '/admin/finanzas')
    expect(finances).toHaveAttribute('aria-current', 'page')
    expect(nav.queryByRole('link', { name: es.nav.payments })).not.toBeInTheDocument()
    // A tesorero's row: Finanzas and Gastos, no Pagos (#531).
    const tabs = within(screen.getByRole('navigation', { name: es.admin.money.tabs.label }))
    expect(tabs.getAllByRole('link').map((l) => l.textContent)).toEqual([
      es.admin.money.tabs.finances,
      es.admin.money.tabs.expenses,
    ])
  })

  it("is the money section's third tab, the nav's Pagos current (#531)", async () => {
    stubApi()
    renderAt('/admin/finanzas/gastos')
    await rows()
    expect(screen.getByRole('heading', { level: 1, name: copy.title })).toBeInTheDocument()
    const tabs = within(screen.getByRole('navigation', { name: es.admin.money.tabs.label }))
    expect(tabs.getAllByRole('link').map((l) => l.textContent)).toEqual([
      es.admin.money.tabs.payments,
      es.admin.money.tabs.finances,
      es.admin.money.tabs.expenses,
    ])
    expect(tabs.getByRole('link', { name: es.admin.money.tabs.expenses })).toHaveAttribute('aria-current', 'page')
    expect(tabs.getByRole('link', { name: es.admin.money.tabs.finances })).not.toHaveAttribute('aria-current')
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    expect(nav.getByRole('link', { name: es.nav.payments })).toHaveAttribute('aria-current', 'page')
  })

  it('takes the path it had under Pagos to Finanzas, with its month', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/pagos/gastos?month=2026-10-01')
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/finanzas/gastos'))
    expect(router.state.location.search).toEqual({ month: '2026-10-01' })
    await waitFor(() => expect(calls.some((c) => c.path === '/api/expenses?month=2026-10-01')).toBe(true))
  })

  describe('Gastos fijos por registrar', () => {
    const due = es.admin.expenses.due
    const card = async () => within(await screen.findByRole('region', { name: due.title('noviembre') }))

    it('lists what is not yet recorded: a fixed one at its amount, an estimate as a hint', async () => {
      stubApi()
      renderAt('/admin/finanzas/gastos')
      const shown = await card()
      expect(shown.getByText('$650.000')).toBeInTheDocument()
      expect(shown.getByText('~$84.000')).toBeInTheDocument()
      expect(shown.getByText(due.day(5))).toBeInTheDocument()
      expect(shown.getByRole('button', { name: due.recordWhat('Arriendo') })).toHaveTextContent(due.record)
      expect(shown.getByRole('button', { name: due.recordWhat('Luz · Enel') })).toHaveTextContent(due.recordEstimated)
      expect(shown.getByRole('button', { name: due.recordAll(2) })).toBeInTheDocument()
    })

    it('records a fixed one in one tap, and every fixed one at once', async () => {
      const calls = stubApi()
      renderAt('/admin/finanzas/gastos')
      const user = userEvent.setup()
      const shown = await card()

      await user.click(shown.getByRole('button', { name: due.recordWhat('Arriendo') }))
      expect(await screen.findByText(due.recorded(1, '$650.000'))).toBeInTheDocument()
      expect(calls.find((c) => c.path === '/api/expenses/recurring/record')?.body).toEqual({
        month: '2026-11-01',
        ids: ['r-rent'],
      })

      await user.click((await card()).getByRole('button', { name: due.recordAll(2) }))
      expect(await screen.findByText(due.recorded(2, '$682.990'))).toBeInTheDocument()
      expect(calls.filter((c) => c.path === '/api/expenses/recurring/record').at(-1)?.body).toEqual({
        month: '2026-11-01',
        ids: ['r-rent', 'r-internet'],
      })
      // Nothing was posted as an expense of its own: only the taps recorded.
      expect(calls.some((c) => c.method === 'POST' && c.path === '/api/expenses')).toBe(false)
    })

    it('says which gasto fijo stopped a batch, that none was recorded, and reads the card again', async () => {
      const calls = stubApi('owner', NOVEMBER_DUE, { code: 'paused', recurring_id: 'r-internet' })
      renderAt('/admin/finanzas/gastos')
      const user = userEvent.setup()
      const reads = () => calls.filter((c) => c.path.startsWith('/api/expenses/recurring/month')).length
      await card()
      const before = reads()

      await user.click((await card()).getByRole('button', { name: due.recordAll(2) }))
      expect(await screen.findByText(due.noneRecorded(due.refused.paused!('Otros · Movistar')))).toBeInTheDocument()
      await waitFor(() => expect(reads()).toBeGreaterThan(before))
    })

    it('opens an estimated one in the form, filled in, its amount selected for the bill', async () => {
      const calls = stubApi()
      renderAt('/admin/finanzas/gastos')
      const user = userEvent.setup()
      await user.click((await card()).getByRole('button', { name: due.recordWhat('Luz · Enel') }))

      const form = within(screen.getByRole('form', { name: due.recordWhat('Luz') }))
      const amount = form.getByLabelText(copy.form.amount)
      expect(amount).toHaveValue('84.000')
      expect(amount).toHaveFocus()
      expect([(amount as HTMLInputElement).selectionStart, (amount as HTMLInputElement).selectionEnd]).toEqual([0, 6])
      expect(form.getByLabelText(copy.form.spentOn)).toHaveValue('2026-11-20')
      expect(form.getByLabelText(copy.form.category)).toHaveValue('c-luz')
      expect(form.getByText(due.estimateHint('$84.000'))).toBeInTheDocument()
      // The card steps aside while its form is open.
      expect(screen.queryByRole('region', { name: due.title('noviembre') })).not.toBeInTheDocument()

      await user.keyboard('91240')
      await user.click(form.getByRole('button', { name: copy.form.save }))
      await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/api/expenses')).toBe(true))
      expect(calls.find((c) => c.method === 'POST' && c.path === '/api/expenses')?.body).toMatchObject({
        amount_clp: 91_240,
        category_id: 'c-luz',
        payee: 'Enel',
        spent_on: '2026-11-20',
        recurring_id: 'r-power',
      })
    })

    it('skips one for the month, and takes the skip back', async () => {
      const calls = stubApi('owner', { ...NOVEMBER_DUE, due: [RENT_FIXED], skipped: [POWER_ESTIMATED] })
      renderAt('/admin/finanzas/gastos')
      const user = userEvent.setup()
      const shown = await card()
      // One fixed one: no "Registrar los 1 fijos".
      expect(shown.queryByRole('button', { name: due.recordAll(1) })).not.toBeInTheDocument()

      await user.click(shown.getByRole('button', { name: due.skipWhat('Arriendo') }))
      await waitFor(() =>
        expect(calls.find((c) => c.path === '/api/expenses/recurring/r-rent/skip')).toMatchObject({
          method: 'POST',
          body: { month: '2026-11-01' },
        }),
      )
      await user.click(shown.getByRole('button', { name: due.unskipWhat('Luz · Enel') }))
      await waitFor(() =>
        expect(calls.find((c) => c.path === '/api/expenses/recurring/r-power/skip/2026-11-01')?.method).toBe('DELETE'),
      )
    })

    it('is not there when every gasto fijo is recorded, nor for a reader', async () => {
      stubApi('owner', { ...NOVEMBER_DUE, due: [] })
      renderAt('/admin/finanzas/gastos')
      await rows()
      expect(screen.queryByRole('region', { name: due.title('noviembre') })).not.toBeInTheDocument()

      vi.unstubAllGlobals()
      const calls = stubApi(['expenses_read'])
      renderAt('/admin/finanzas/gastos')
      await rows()
      expect(calls.some((c) => c.path.startsWith('/api/expenses/recurring'))).toBe(false)
    })
  })

  describe('Gastos fijos', () => {
    const words = es.admin.expenses.recurring

    it('adds a gasto fijo and pauses one', async () => {
      const calls = stubApi()
      renderAt('/admin/finanzas/gastos')
      const user = userEvent.setup()
      await rows()
      await user.click(screen.getByText(words.title))
      const section = within(screen.getByText(words.title).closest('details')!)
      expect(await section.findByText(words.paused)).toBeInTheDocument()

      await user.click(section.getByRole('button', { name: words.add }))
      const form = within(section.getByRole('form', { name: words.newTitle }))
      await user.click(form.getByRole('button', { name: words.save }))
      expect(form.getByText(words.dayNeeded)).toBeInTheDocument()
      await user.selectOptions(form.getByLabelText(copy.form.category), 'c-luz')
      await user.click(form.getByLabelText(words.kind.estimated))
      await user.type(form.getByLabelText(words.amountEstimated), '84000')
      await user.type(form.getByLabelText(words.dayOfMonth, { exact: false }), '20')
      await user.click(form.getByRole('button', { name: words.save }))
      await waitFor(() =>
        expect(calls.find((c) => c.method === 'POST' && c.path === '/api/expenses/recurring')?.body).toEqual({
          category_id: 'c-luz',
          payee: null,
          method: null,
          amount_clp: 84_000,
          amount_kind: 'estimated',
          day_of_month: 20,
        }),
      )

      const [rent] = section.getAllByRole('listitem')
      await user.click(within(rent!).getByRole('button', { name: words.pause }))
      await waitFor(() =>
        expect(calls.find((c) => c.method === 'PATCH')).toMatchObject({
          path: '/api/expenses/recurring/r-rent',
          body: { active: false },
        }),
      )
    })
  })
})
