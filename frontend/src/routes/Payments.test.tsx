import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BookEntry, BookFreeze, LedgerBook } from '../api/ledger'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.payments

const entry = (fields: Partial<BookEntry> & Pick<BookEntry, 'id' | 'kind'>): BookEntry => ({
  created_at: '2026-11-08T17:12:00Z',
  status: 'validated',
  amount_clp: 45000,
  method: null,
  note: null,
  membership_id: 'm-diego',
  plan_name: 'Mensual adultos',
  person: { id: 'diego', name: 'Diego Morales' },
  guardian: null,
  period: {
    period_start: '2026-11-01',
    period_end: '2026-11-30',
    due_date: '2026-11-05',
    outstanding_clp: 45000,
    days_overdue: 0,
  },
  validated_by_name: null,
  refund_of: null,
  ...fields,
})

const ENTRIES: BookEntry[] = [
  // 14:12 in Santiago, UTC-3 in November.
  entry({ id: 'claim', kind: 'payment', status: 'pending', method: 'transfer' }),
  entry({
    id: 'kid',
    kind: 'payment',
    method: 'cash',
    created_at: '2026-11-07T12:05:00Z',
    person: { id: 'mateo', name: 'Mateo Ortiz' },
    guardian: { id: 'camila', name: 'Camila Ortiz' },
    validated_by_name: 'Martín',
  }),
  entry({
    id: 'prepaid',
    kind: 'charge',
    amount_clp: 240000,
    created_at: '2026-11-06T03:10:00Z',
    plan_name: 'Prepago 6 meses',
    person: { id: 'andres', name: 'Andrés Molina' },
    period: {
      period_start: '2026-12-01',
      period_end: '2027-05-31',
      due_date: '2026-12-01',
      outstanding_clp: 240000,
      days_overdue: 0,
    },
  }),
  entry({
    id: 'late',
    kind: 'charge',
    created_at: '2026-10-25T03:10:00Z',
    person: { id: 'felipe', name: 'Felipe Díaz' },
    period: {
      period_start: '2026-10-31',
      period_end: '2026-11-29',
      due_date: '2026-10-31',
      outstanding_clp: 45000,
      days_overdue: 9,
    },
  }),
  entry({
    id: 'credit',
    kind: 'adjustment',
    amount_clp: 5000,
    created_at: '2026-11-04T23:01:00Z',
    note: 'Pagó $50.000; quedan $5.000 a favor',
    person: { id: 'paula', name: 'Paula Contreras' },
    period: null,
    validated_by_name: 'Martín',
  }),
]

const BOOK: LedgerBook = {
  month: '2026-11-01',
  months: ['2026-11-01', '2026-10-01'],
  timezone: 'America/Santiago',
  kpis: {
    collected_clp: 2115000,
    collected_payments: 47,
    refunded_clp: 0,
    refunds: 0,
    pending_clp: 162000,
    pending_payments: 3,
    overdue_clp: 270000,
    overdue_members: 6,
    overdue_avg_days: 5.333,
    expected_clp: 2655000,
    active_memberships: 64,
    frozen_memberships: 2,
  },
  items: ENTRIES,
  total: ENTRIES.length,
  freezes: [],
}

const SOFIA_FROZEN: BookFreeze = {
  freeze_id: 'f-sofia',
  edge: 'start',
  day: '2026-11-07',
  from_date: '2026-11-07',
  to_date: '2026-11-28',
  reason: 'Viaje familiar',
  membership_id: 'm-sofia',
  plan_name: 'Kids',
  person: { id: 'sofia', name: 'Sofía Ortiz' },
  guardian: { id: 'camila', name: 'Camila Ortiz' },
}

type Stub = { role?: 'owner' | 'admin' | 'coach'; book?: (params: URLSearchParams) => LedgerBook }

function stubApi({ role = 'owner', book = () => BOOK }: Stub = {}) {
  const asked: URLSearchParams[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      let body: unknown = { detail: 'Not Found' }
      let status = 200
      if (url.pathname === '/api/me/role') body = { role }
      else if (url.pathname === '/api/ledger/pending') body = { count: 3 }
      else if (url.pathname === '/api/ledger/book') {
        asked.push(url.searchParams)
        body = book(url.searchParams)
      } else status = 404
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  return asked
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const table = () => screen.findByRole('table')
const cells = (row: HTMLElement) => within(row).getAllByRole('cell').map((cell) => cell.textContent)

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Libro de pagos', () => {
  it('shows the KPIs', async () => {
    stubApi()
    renderAt('/admin/pagos')

    const kpis = await screen.findByRole('region', { name: copy.kpisLabel })
    expect(kpis.textContent).toBe(
      [
        'Cobrado$2.115.00047 pagos validados',
        'Por validar$162.0003 comprobantes',
        'Vencido$270.0006 alumnos · 5,3 días promedio',
        'Esperado$2.655.00064 membresías activas · 2 congeladas',
      ].join(''),
    )
  })

  it('shows the month\'s refunds beside the collected figure, which is net of them', async () => {
    stubApi({ book: () => ({ ...BOOK, kpis: { ...BOOK.kpis, collected_clp: 2070000, refunded_clp: 45000, refunds: 1 } }) })
    renderAt('/admin/pagos')

    const kpis = await screen.findByRole('region', { name: copy.kpisLabel })
    expect(kpis.textContent).toContain('Cobrado$2.070.00047 pagos validados · Devuelto $45.000')
  })

  it('lists each entry with its date, student, kind, period, medium, status and amount', async () => {
    stubApi()
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Pago', 'Nov 2026', 'Transferencia', 'Por validar', '$45.000'],
      ['7 nov 09:05', 'Mateo OrtizApoderado: Camila Ortiz', 'Pago', 'Nov 2026', 'Efectivo', 'Validado · Martín', '$45.000'],
      ['6 nov 00:10', 'Andrés Molina', 'Cargo', 'Dic 2026 – May 2027', 'Prepago 6 meses', 'Abierto · vence 1 dic', '$240.000'],
      ['25 oct 00:10', 'Felipe Díaz', 'Cargo', 'Oct 2026', 'Mensual adultos', 'Vencido 9 d', '$45.000'],
      ['4 nov 20:01', 'Paula Contreras', 'Ajuste', 'A favor', 'Pagó $50.000; quedan $5.000 a favor', 'Validado · Martín', '+$5.000'],
    ])
    expect(within(rows[0]!).getByRole('link', { name: 'Diego Morales' })).toHaveAttribute('href', '/admin/alumnos/diego')
    expect(within(rows[0]!).getByRole('link', { name: copy.status.pending })).toHaveAttribute(
      'href',
      '/admin/pagos/comprobantes',
    )
    expect(screen.getByText(copy.showing(5, 5, 'noviembre'))).toBeInTheDocument()
  })

  it('lists adjustments with their sign and refunds as money out', async () => {
    const corrections = [
      entry({
        id: 'refund',
        kind: 'refund',
        amount_clp: 10000,
        method: 'cash',
        note: 'se lesionó',
        refund_of: 'pay',
        validated_by_name: 'Martín',
        period: { ...BOOK.items[0]!.period!, outstanding_clp: 10000 },
      }),
      entry({ id: 'owed', kind: 'adjustment', amount_clp: -5000, note: 'matrícula', validated_by_name: 'Martín' }),
    ]
    stubApi({ book: () => ({ ...BOOK, items: corrections, total: 2 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Devolución', 'Nov 2026', 'Efectivo', 'Validado · Martín', '−$10.000'],
      ['8 nov 14:12', 'Diego Morales', 'Ajuste', 'Nov 2026', 'matrícula', 'Validado · Martín', '−$5.000'],
    ])
  })

  it('lists the month\'s freezes among the entries, after their day\'s, with no amount', async () => {
    stubApi({ book: () => ({ ...BOOK, freezes: [SOFIA_FROZEN] }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells).slice(0, 4).map((row) => row[1])).toEqual([
      'Diego Morales',
      'Mateo OrtizApoderado: Camila Ortiz',
      'Sofía OrtizApoderado: Camila Ortiz',
      'Andrés Molina',
    ])
    expect(cells(rows[2]!)).toEqual([
      '7 nov',
      'Sofía OrtizApoderado: Camila Ortiz',
      copy.kind.freeze,
      '7 nov – 28 nov',
      'Viaje familiar',
      copy.status.freezeStart,
      es.common.noAmount,
    ])
    // Counted as entries are: it is not one.
    expect(screen.getByText(copy.showing(5, 5, 'noviembre'))).toBeInTheDocument()
  })

  it('holds a freeze older than the entries loaded until its page is', async () => {
    // Older than every entry on the first page, newer than the next page's.
    const early = { ...SOFIA_FROZEN, day: '2026-10-20', from_date: '2026-10-20' }
    const next = entry({ id: 'older', kind: 'payment', created_at: '2026-10-15T12:00:00Z' })
    stubApi({
      book: (params) =>
        params.get('offset') === '0'
          ? { ...BOOK, freezes: [early], total: 6 }
          : { ...BOOK, items: [next], freezes: [early], total: 6 },
    })
    renderAt('/admin/pagos')
    await table()

    expect(screen.queryByText('Sofía Ortiz')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.more }))

    expect(await screen.findByText('Sofía Ortiz')).toBeInTheDocument()
  })

  it('filters by chip, keeping the filter in the URL', async () => {
    const asked = stubApi()
    const router = renderAt('/admin/pagos')
    await table()

    const chips = screen.getByRole('group', { name: copy.filtersLabel })
    expect(within(chips).getByRole('button', { name: copy.filters.all })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(within(chips).getByRole('button', { name: copy.filters.overdue }))

    await waitFor(() => expect(asked.at(-1)?.get('filter')).toBe('overdue'))
    expect(router.state.location.search).toEqual({ filter: 'overdue' })
    expect(within(chips).getByRole('button', { name: copy.filters.overdue })).toHaveAttribute('aria-pressed', 'true')
    // Overdue is today's, not the month's.
    expect(await screen.findByText(copy.showing(5, 5, null))).toBeInTheDocument()
  })

  it('shows another month from the period selector', async () => {
    const asked = stubApi({ book: (params) => ({ ...BOOK, month: params.get('month') ?? BOOK.month }) })
    renderAt('/admin/pagos')
    await table()

    const select = screen.getByLabelText(copy.month)
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Noviembre 2026', 'Octubre 2026'])
    await userEvent.selectOptions(select, '2026-10-01')

    await waitFor(() => expect(asked.at(-1)?.get('month')).toBe('2026-10-01'))
    expect(await screen.findByText(copy.showing(5, 5, 'octubre'))).toBeInTheDocument()
  })

  it('loads the next page with "Cargar más", counting by the latest page', async () => {
    const next = entry({ id: 'older', kind: 'payment', created_at: '2026-11-01T12:00:00Z' })
    const asked = stubApi({
      book: (params) =>
        params.get('offset') === '0'
          ? { ...BOOK, total: 55 }
          : // An entry landed meanwhile: the count and the KPIs have moved on.
            { ...BOOK, items: [next], total: 56, kpis: { ...BOOK.kpis, pending_payments: 4 } },
    })
    renderAt('/admin/pagos')
    await table()

    expect(screen.getByText(copy.showing(5, 55, 'noviembre'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.more }))

    expect(await screen.findByText(copy.showing(6, 56, 'noviembre'))).toBeInTheDocument()
    expect(screen.getByRole('region', { name: copy.kpisLabel })).toHaveTextContent(copy.kpis.pendingDetail(4))
    expect(asked.map((params) => params.get('offset'))).toEqual(['0', '5'])
  })

  it('shows an entry once when the next page repeats it', async () => {
    // A new entry at the head shifted the list, so page 2 starts with page 1's last row.
    stubApi({
      book: (params) =>
        params.get('offset') === '0' ? { ...BOOK, total: 7 } : { ...BOOK, items: [ENTRIES.at(-1)!], total: 7 },
    })
    renderAt('/admin/pagos')
    await table()

    await userEvent.click(screen.getByRole('button', { name: copy.more }))

    await waitFor(() => expect(screen.queryByRole('button', { name: copy.more })).toBeInTheDocument())
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(ENTRIES.length)
    expect(screen.getAllByRole('link', { name: 'Paula Contreras' })).toHaveLength(1)
  })

  it('links to the proofs waiting for review', async () => {
    stubApi()
    renderAt('/admin/pagos')

    expect(await screen.findByRole('link', { name: copy.review(3) })).toHaveAttribute('href', '/admin/pagos/comprobantes')
  })

  it('says so when there is nothing to show', async () => {
    stubApi({ book: () => ({ ...BOOK, items: [], total: 0 }) })
    renderAt('/admin/pagos')

    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('keeps the Pagos tab hidden while the role is still loading', async () => {
    stubApi()
    // The role never answers.
    const fetch = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>((input, init) =>
        new URL(String(input), 'http://localhost').pathname === '/api/me/role' ? new Promise(() => {}) : fetch(input, init),
      ),
    )
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases'])
  })

  it('is hidden from coaches, who never ask for it', async () => {
    const asked = stubApi({ role: 'coach' })
    renderAt('/admin/pagos')

    expect(await screen.findByText(copy.coachesOnly)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases'])
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(asked).toEqual([])
  })
})
