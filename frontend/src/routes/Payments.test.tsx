import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BookEntry, BookFreeze, LedgerBook } from '../api/ledger'
import type { Membership, MembershipLedger, OpenPeriod } from '../api/member'
import type { MemberPage } from '../api/people'
import type { PaymentReminder } from '../api/reminders'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.payments

const entry = (fields: Partial<BookEntry> & Pick<BookEntry, 'id' | 'kind'>): BookEntry => ({
  created_at: '2026-11-08T17:12:00Z',
  status: 'validated',
  amount_clp: 45000,
  method: null,
  note: null,
  membership_id: 'm-diego',
  plan_name: 'Mensual adultos',
  membership_status: 'active',
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

// "Registrar pago" from the book: Diego, found by the picker, owes November.
const DIEGO = {
  id: 'diego',
  name: 'Diego Morales',
  phone: '+56912345678',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  missing_guardian: false,
  rut: null,
  membership: { id: 'm-diego', status: 'active', plan_id: 'p-adultos', plan_name: 'Mensual adultos' },
  guardian: null,
  dependents: 0,
  left_on: null,
  owes: true,
} satisfies MemberPage['items'][number]

const DIEGO_MEMBERSHIP: Membership = {
  id: 'm-diego',
  plan_id: 'p-adultos',
  plan_name: 'Mensual adultos',
  plan_kind: 'monthly',
  status: 'active',
  anchor_day: 5,
  started_on: '2026-03-05',
  current_period_end: '2026-10-31',
  credits_remaining: null,
  next_plan: null,
  freeze: null,
}

const NOVEMBER: OpenPeriod = {
  id: 'bp-nov',
  period_start: '2026-11-01',
  period_end: '2026-11-30',
  due_date: '2026-11-05',
  amount_due_clp: 45000,
  paid_clp: 0,
  outstanding_clp: 45000,
  due: true,
  days_overdue: 4,
}

const DIEGO_LEDGER: MembershipLedger = {
  open_periods: [NOVEMBER],
  owed_clp: 45000,
  entries: [],
  freezes: [],
  periods: [],
  refundable_payments: [],
  paid_through: null,
  balance_clp: 0,
}

type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  book?: (params: URLSearchParams) => LedgerBook
  people?: (params: URLSearchParams) => MemberPage
  memberships?: Membership[]
  ledger?: MembershipLedger
  // Proofs waiting for review.
  pending?: number
  // The reminders' list, for "Enviar recordatorio" on the overdue list (#260).
  reminders?: PaymentReminder[]
  // The ledgers of Diego's other memberships, by id: a course beside his plan (#354).
  others?: Record<string, MembershipLedger>
}

function stubApi({
  role = 'owner',
  book = () => BOOK,
  people = () => ({ items: [DIEGO], total: 1 }),
  memberships = [DIEGO_MEMBERSHIP],
  ledger = DIEGO_LEDGER,
  pending = 3,
  reminders = [],
  others = {},
}: Stub = {}) {
  const asked: URLSearchParams[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      let body: unknown = { detail: 'Not Found' }
      let status = 200
      if (url.pathname === '/api/me/role') body = asRole(role)
      else if (url.pathname === '/api/ledger/pending') body = { count: pending }
      else if (url.pathname === '/api/ledger/book') {
        asked.push(url.searchParams)
        body = book(url.searchParams)
      } else if (url.pathname === '/api/people') body = people(url.searchParams)
      else if (url.pathname === '/api/memberships') body = memberships
      else if (url.pathname === '/api/reminders') body = reminders
      else if (url.pathname.endsWith('/email') && init?.method === 'POST') {
        emailed.push(url.pathname)
        status = 201
        body = { sent_at: new Date().toISOString(), contact_name: 'Felipe Díaz' }
      }
      else if (url.pathname === `/api/ledger/memberships/${DIEGO_MEMBERSHIP.id}`) body = ledger
      else if (url.pathname.replace('/api/ledger/memberships/', '') in others) {
        body = others[url.pathname.replace('/api/ledger/memberships/', '')]
      }
      // Nothing to pay ahead: the member is on a plan that cannot (#196).
      else if (url.pathname === `/api/ledger/memberships/${DIEGO_MEMBERSHIP.id}/ahead`) body = { periods: [] }
      else if (url.pathname === '/api/ledger/payments' && init?.method === 'POST') {
        payments.push(JSON.parse(String(init.body)))
        status = 201
        body = { credit: null, period: { outstanding_clp: 0, closed: true } }
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

// What "Registrar pago" posted, and the overdue emails sent.
let payments: unknown[] = []
let emailed: string[] = []

const table = () => screen.findByRole('table')
const cells = (row: HTMLElement) => within(row).getAllByRole('cell').map((cell) => cell.textContent)

afterEach(() => {
  vi.unstubAllGlobals()
  payments = []
  emailed = []
})

describe('Pagos', () => {
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

  it('shows payments undone by mistake as "Pagos anulados", apart from the refunds (#281)', async () => {
    const undone = entry({
      id: 'undo',
      kind: 'refund',
      note: 'era de otro alumno',
      refund_of: 'pay',
      purpose: 'mistake',
      validated_by_name: 'Martín',
    })
    stubApi({
      book: () => ({
        ...BOOK,
        items: [undone],
        total: 1,
        kpis: { ...BOOK.kpis, collected_clp: 2070000, corrected_clp: 45000, corrections: 1 },
      }),
    })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Pago anulado', 'nov 2026', 'Error de registro · era de otro alumno', 'Validado · Martín', '−$45.000'],
    ])
    const kpis = screen.getByRole('region', { name: copy.kpisLabel })
    expect(kpis.textContent).toContain('Cobrado$2.070.00047 pagos validados · Pagos anulados $45.000')
    expect(kpis.textContent).not.toContain('Devuelto')
  })

  it('labels a debt forgiven and an adjustment reverted, and shows "Condonado" beside Vencido (#282)', async () => {
    const forgiven = entry({ id: 'wo', kind: 'adjustment', method: null, amount_clp: 45000, note: 'se fue', purpose: 'write_off' })
    const reverted = entry({ id: 'rv', kind: 'adjustment', method: null, amount_clp: -5000, note: 'error', purpose: 'revert' })
    stubApi({
      book: () => ({ ...BOOK, items: [forgiven, reverted], total: 2, kpis: { ...BOOK.kpis, written_off_clp: 45000 } }),
    })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map((row) => cells(row)[2])).toEqual([copy.writeOff, copy.reverted])
    const kpis = screen.getByRole('region', { name: copy.kpisLabel })
    expect(kpis.textContent).toContain(copy.kpis.writtenOff('$45.000'))
  })

  it('labels a month paid before Rakin apart from the payments (#286)', async () => {
    const before = entry({ id: 'pb', kind: 'payment', method: 'cash', note: 'Pagado antes de Rakin', purpose: 'paid_before' })
    stubApi({ book: () => ({ ...BOOK, items: [before], total: 1 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map((row) => cells(row)[2])).toEqual([copy.paidBefore])
  })

  it('labels both halves of a payment moved, neither income nor a refund (#280)', async () => {
    const out = entry({ id: 'out', kind: 'refund', method: null, note: 'era de diciembre', refund_of: 'pay', purpose: 'move' })
    const into = entry({ id: 'in', kind: 'payment', method: 'transfer', note: 'era de diciembre', purpose: 'move' })
    stubApi({ book: () => ({ ...BOOK, items: [into, out], total: 2 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1).map(cells)
    expect(rows.map((r) => r[2])).toEqual([copy.moved.in, copy.moved.out])
    expect(rows[0]![4]).toContain('era de diciembre')
    expect(rows.map((r) => r[6])).toEqual(['$45.000', '−$45.000'])
  })

  it('names the credit reverted with a payment undone, not a plain adjustment (#281)', async () => {
    const reverted = entry({ id: 'rev', kind: 'adjustment', amount_clp: -5000, period: null, purpose: 'revert', note: 'x' })
    stubApi({ book: () => ({ ...BOOK, items: [reverted], total: 1 }) })
    renderAt('/admin/pagos')

    const [row] = within(await table()).getAllByRole('row').slice(1)
    expect(cells(row!)[2]).toBe(copy.creditReverted)
    expect(cells(row!)[6]).toBe('−$5.000')
  })

  it('lists each entry with its date, student, kind, period, medium, status and amount', async () => {
    stubApi()
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Pago', 'nov 2026', 'Transferencia', 'Por validar', '$45.000'],
      ['7 nov 09:05', 'Mateo OrtizApoderado: Camila Ortiz', 'Pago', 'nov 2026', 'Efectivo', 'Validado · Martín', '$45.000'],
      // A charge is dated by its period's start, the day the book files it under (#206).
      ['1 dic', 'Andrés Molina', 'Cargo', 'dic 2026 – may 2027', 'Prepago 6 meses', 'Abierto · vence 1 dic', '$240.000'],
      ['31 oct', 'Felipe Díaz', 'Cargo', 'oct 2026', 'Mensual adultos', 'Vencido 9 d', '$45.000'],
      ['4 nov 20:01', 'Paula Contreras', 'Ajuste', 'A favor', 'Pagó $50.000; quedan $5.000 a favor', 'Validado · Martín', '$5.000'],
    ])
    expect(within(rows[0]!).getByRole('link', { name: 'Diego Morales' })).toHaveAttribute('href', '/admin/alumnos/diego')
    expect(within(rows[0]!).getByRole('link', { name: copy.status.pending })).toHaveAttribute(
      'href',
      '/admin/pagos/comprobantes',
    )
    expect(screen.getByText(copy.showing(5, 5, 'noviembre'))).toBeInTheDocument()
  })

  it("says beside a charge when its member's plan lapsed or was cancelled", async () => {
    // The debt outlives the plan (#207).
    const charges = [
      entry({ id: 'lapsed', kind: 'charge', membership_status: 'lapsed' }),
      entry({ id: 'cancelled', kind: 'charge', membership_status: 'cancelled' }),
      entry({ id: 'active', kind: 'charge' }),
    ]
    stubApi({ book: () => ({ ...BOOK, items: charges, total: 3 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map((row) => cells(row)[4])).toEqual([
      'Mensual adultos · Plan caducado',
      'Mensual adultos · Dado de baja',
      'Mensual adultos',
    ])
  })

  it('says beside a charge the discount it was billed at', async () => {
    // A discount with its reason (#25), kept as the period was billed.
    const period = { ...entry({ id: 'x', kind: 'charge' }).period!, discount_pct: 50, discount_reason: 'Beca' }
    const charges = [
      entry({ id: 'discounted', kind: 'charge', amount_clp: 22500, period }),
      entry({ id: 'lapsed', kind: 'charge', membership_status: 'lapsed', period }),
    ]
    stubApi({ book: () => ({ ...BOOK, items: charges, total: 2 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map((row) => cells(row)[4])).toEqual([
      'Mensual adultos · descuento 50% (Beca)',
      'Mensual adultos · descuento 50% (Beca) · Plan caducado',
    ])
  })

  it('lists a discount and a surcharge by what each does to what is owed, and refunds as money out', async () => {
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
      // A discount takes from what is owed (#210): not the sign of a payment.
      entry({ id: 'favor', kind: 'adjustment', amount_clp: 5000, note: 'hermano', validated_by_name: 'Martín' }),
    ]
    stubApi({ book: () => ({ ...BOOK, items: corrections, total: 3 }) })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Devolución', 'nov 2026', 'Efectivo', 'Validado · Martín', '−$10.000'],
      ['8 nov 14:12', 'Diego Morales', 'Recargo', 'nov 2026', 'matrícula', 'Validado · Martín', '+$5.000'],
      ['8 nov 14:12', 'Diego Morales', 'Descuento', 'nov 2026', 'hermano', 'Validado · Martín', '−$5.000'],
    ])
  })

  it('lists a cobro extra\'s payment by its title and category, and Cobrado says what they brought', async () => {
    const rifa = entry({
      id: 'rifa',
      kind: 'payment',
      amount_clp: 10000,
      method: 'transfer',
      membership_id: null,
      plan_name: null,
      period: null,
      validated_by_name: 'Martín',
      extra: { id: 'x-rifa', title: 'Rifa de fin de año', category: 'rifa' },
    })
    stubApi({
      book: () => ({ ...BOOK, items: [rifa], total: 1, kpis: { ...BOOK.kpis, collected_extra_clp: 10000 } }),
    })
    renderAt('/admin/pagos')

    const rows = within(await table()).getAllByRole('row').slice(1)
    expect(rows.map(cells)).toEqual([
      ['8 nov 14:12', 'Diego Morales', 'Pago', 'Rifa de fin de año', 'Rifa · Transferencia', 'Validado · Martín', '$10.000'],
    ])
    const kpis = screen.getByRole('region', { name: copy.kpisLabel })
    expect(kpis.textContent).toContain(copy.kpiExtra('$10.000'))
    expect(screen.getByRole('link', { name: copy.extra })).toHaveAttribute('href', '/admin/pagos/cobros')
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

  it('emails the overdue reminder from a row of the overdue list', async () => {
    stubApi({
      reminders: [
        {
          billing_period_id: 'p-late',
          membership_id: 'm-diego',
          person_id: 'felipe',
          person_name: 'Felipe Díaz',
          plan_name: 'Mensual adultos',
          period_start: '2026-10-31',
          due_date: '2026-10-31',
          outstanding_clp: 45000,
          days_overdue: 9,
          kind: 'payment_overdue',
          rejection_note: null,
          contact_name: 'Felipe Díaz',
          whatsapp_url: null,
          reminders_sent: 0,
          reminded_at: null,
          reminder_due: true,
          can_email: true,
          emailed_at: null,
          emailed_today: false,
        },
      ],
    })
    renderAt('/admin/pagos?filter=overdue')
    await table()
    const words = es.admin.reminders.email

    await userEvent.click(await screen.findByRole('button', { name: words.sendTo('Felipe Díaz') }))

    expect(await screen.findByText(words.sent('Felipe Díaz'))).toBeInTheDocument()
    expect(emailed).toEqual(['/api/reminders/p-late/email'])
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

  it('exports the month shown as CSV and Excel for the accountant', async () => {
    stubApi({ book: (params) => ({ ...BOOK, month: params.get('month') ?? BOOK.month }) })
    renderAt('/admin/pagos')
    await table()

    const csv = () => screen.getByRole('link', { name: copy.exportCsv })
    const xlsx = () => screen.getByRole('link', { name: copy.exportXlsx })
    expect(csv()).toHaveAttribute('href', '/api/ledger/export?month=2026-11-01&format=csv')
    expect(csv()).toHaveAttribute('download')
    expect(xlsx()).toHaveAttribute('href', '/api/ledger/export?month=2026-11-01&format=xlsx')

    const expenses = () => screen.getByRole('link', { name: copy.exportExpensesCsv })
    expect(expenses()).toHaveAttribute('href', '/api/ledger/export/expenses?month=2026-11-01')
    expect(expenses()).toHaveAttribute('download')

    await userEvent.selectOptions(screen.getByLabelText(copy.month), '2026-10-01')
    await waitFor(() => expect(csv()).toHaveAttribute('href', '/api/ledger/export?month=2026-10-01&format=csv'))
    expect(expenses()).toHaveAttribute('href', '/api/ledger/export/expenses?month=2026-10-01')
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

  it('makes reviewing the waiting proofs the one primary action, recording a payment the other', async () => {
    stubApi()
    renderAt('/admin/pagos')

    const review = await screen.findByRole('link', { name: copy.review(3) })
    expect(review).toHaveClass('button--primary')
    expect(screen.getByRole('button', { name: copy.record })).not.toHaveClass('button--primary')
    expect(document.querySelectorAll('.payments__header .button--primary')).toHaveLength(1)
  })

  it('shows an Administrador, who sees no expenses, no row of money tabs (#531)', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/pagos')
    await table()
    expect(screen.queryByRole('navigation', { name: es.admin.money.tabs.label })).not.toBeInTheDocument()
    const more = document.querySelector('.payments__toolbar .more-menu__list')!
    expect([...more.children].map((c) => c.textContent)).toEqual([copy.extra, copy.exportCsv, copy.exportXlsx])
  })

  it('opens the titular\'s money section on its Pagos tab, beside Finanzas and Gastos (#531)', async () => {
    stubApi()
    renderAt('/admin/pagos')
    await table()
    const tabs = within(screen.getByRole('navigation', { name: es.admin.money.tabs.label }))
    expect(tabs.getAllByRole('link').map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      [es.admin.money.tabs.payments, '/admin/pagos'],
      [es.admin.money.tabs.finances, '/admin/finanzas'],
      [es.admin.money.tabs.expenses, '/admin/finanzas/gastos'],
    ])
    expect(tabs.getByRole('link', { name: es.admin.money.tabs.payments })).toHaveAttribute('aria-current', 'page')
    const nav = within(screen.getByRole('navigation', { name: es.nav.label }))
    // "Pagos", then its badge's proofs waiting.
    expect(nav.getByRole('link', { name: new RegExp(`^${es.nav.payments}`) })).toHaveAttribute('aria-current', 'page')
  })

  it('keeps Cobros extra and the exports under "Más", the header holding two actions (#357)', async () => {
    stubApi()
    renderAt('/admin/pagos')
    await table()

    const header = document.querySelector<HTMLElement>('.payments__actions')!
    expect([...header.querySelectorAll('a, button, summary')].map((c) => c.textContent)).toEqual([copy.review(3), copy.record])
    // "Más" beside the period picker, holding the rest.
    const more = document.querySelector('.payments__toolbar .more-menu__list')!
    // Finanzas and Gastos are tabs above, not here, even for the titular (#531); the
    // month's expenses as a CSV sit beside the ledger's, for whoever sees them (#317).
    expect([...more.children].map((c) => c.textContent)).toEqual([
      copy.extra,
      copy.exportCsv,
      copy.exportExpensesCsv,
      copy.exportXlsx,
    ])
  })

  it('draws the period picker before the book answers, so the header does not move (#357)', async () => {
    let answer: () => void = () => {}
    const held = new Promise<void>((resolve) => {
      answer = resolve
    })
    stubApi()
    const real = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(async (input, init) => {
        if (new URL(String(input), 'http://localhost').pathname === '/api/ledger/book') await held
        return real(input, init)
      }),
    )
    renderAt('/admin/pagos?month=2026-11-01')

    const select = await screen.findByLabelText(copy.month)
    expect(select).toBeDisabled()
    expect(select).toHaveValue('2026-11-01')
    answer()
    await table()
    expect(screen.getByLabelText(copy.month)).toBe(select)
    expect(select).toBeEnabled()
  })

  it('makes recording a payment the primary action when no proof waits', async () => {
    stubApi({ pending: 0 })
    renderAt('/admin/pagos')

    await table()
    expect(screen.queryByRole('link', { name: copy.review(0) })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.record })).toHaveClass('button--primary')
  })

  it('names the lines in plain words, with no accounting jargon', async () => {
    stubApi()
    renderAt('/admin/pagos')

    await table()
    expect(screen.getByRole('heading', { level: 1, name: 'Pagos' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: copy.columns.kind })).toHaveTextContent('Tipo')
    expect(screen.getByRole('columnheader', { name: copy.columns.detail })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/asiento/i)
  })

  it('keeps its table roles explicit, which the phone cards would otherwise lose in WebKit', async () => {
    stubApi()
    renderAt('/admin/pagos')

    const book = await table()
    expect(book).toHaveAttribute('role', 'table')
    const rows = within(book).getAllByRole('row')
    expect(rows.every((row) => row.getAttribute('role') === 'row')).toBe(true)
    expect(within(rows[1]!).getAllByRole('cell').every((cell) => cell.getAttribute('role') === 'cell')).toBe(true)
  })

  it('says so when there is nothing to show', async () => {
    stubApi({ book: () => ({ ...BOOK, items: [], total: 0 }) })
    renderAt('/admin/pagos')

    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('keeps the Pagos tab hidden while the role is still loading', async () => {
    stubApi()
    // The role fails once, which lets the shell render, and then never answers.
    const fetch = globalThis.fetch
    let asked = 0
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>((input, init) => {
        if (new URL(String(input), 'http://localhost').pathname !== '/api/me/role') return fetch(input, init)
        asked += 1
        return asked === 1 ? Promise.resolve(new Response(null, { status: 503 })) : new Promise(() => {})
      }),
    )
    renderAt('/admin')

    const nav = await screen.findByRole('navigation', { name: es.nav.label })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases', 'Estado del servicio'])
  })

  it('is hidden from coaches, who never ask for it', async () => {
    const asked = stubApi({ role: 'coach' })
    renderAt('/admin/pagos')

    expect(await screen.findByText(copy.coachesOnly)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual(['Hoy', 'Alumnos', 'Clases', 'Estado del servicio'])
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(asked).toEqual([])
  })

  it('searches the book by member, keeping the search in the URL', async () => {
    const asked = stubApi({
      book: (params) => {
        const q = params.get('q')
        return q === 'zzz'
          ? { ...BOOK, items: [], total: 0 }
          : q
            ? { ...BOOK, items: ENTRIES.slice(0, 1), total: 1 }
            : BOOK
      },
    })
    const router = renderAt('/admin/pagos?filter=pending')
    await table()

    await userEvent.type(screen.getByRole('searchbox', { name: copy.searchLabel }), 'diego')

    await waitFor(() => expect(asked.at(-1)?.get('q')).toBe('diego'))
    // Within the filter chosen.
    expect(asked.at(-1)?.get('filter')).toBe('pending')
    expect(router.state.location.search).toEqual({ filter: 'pending', q: 'diego' })
    expect(await screen.findByText(copy.showing(1, 1, null))).toBeInTheDocument()

    await userEvent.clear(screen.getByRole('searchbox', { name: copy.searchLabel }))
    await userEvent.type(screen.getByRole('searchbox', { name: copy.searchLabel }), 'zzz')
    expect(await screen.findByText(copy.noMatch('zzz'))).toBeInTheDocument()
  })

  it('opens on the search a link carries', async () => {
    const asked = stubApi()
    renderAt('/admin/pagos?q=diego')

    await table()
    expect(screen.getByRole('searchbox', { name: copy.searchLabel })).toHaveValue('diego')
    expect(asked[0]?.get('q')).toBe('diego')
  })

  it('records a payment from the header: pick a member, then the member detail\'s form', async () => {
    const searched: string[] = []
    stubApi({
      people: (params) => {
        searched.push(params.get('q') ?? '')
        return { items: [DIEGO], total: 1 }
      },
    })
    renderAt('/admin/pagos')
    await table()

    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    const panel = screen.getByRole('region', { name: copy.record })
    await userEvent.type(within(panel).getByLabelText(copy.picker.label), 'dieg')
    const results = await within(panel).findByRole('list', { name: copy.picker.results })
    expect(searched.at(-1)).toBe('dieg')
    await userEvent.click(within(results).getByRole('button', { name: /Diego Morales/ }))

    const form = await within(panel).findByRole('form', { name: es.admin.member.form.title })
    expect(within(form).getByLabelText(es.admin.member.form.amount)).toHaveValue('45000')
    await userEvent.selectOptions(within(form).getByLabelText(es.admin.member.form.method), 'transfer')
    await userEvent.click(within(form).getByRole('button', { name: es.admin.member.form.submit('$45.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(es.admin.member.form.recorded('$45.000'))
    expect(payments).toEqual([
      { membership_id: 'm-diego', billing_period_id: 'bp-nov', amount_clp: 45000, method: 'transfer' },
    ])
    expect(screen.queryByRole('region', { name: copy.record })).not.toBeInTheDocument()
  })

  it('asks which plan a payment is for when two run, each with its own periods (#354)', async () => {
    const COURSE: Membership = {
      ...DIEGO_MEMBERSHIP,
      id: 'm-curso',
      plan_id: 'p-curso',
      plan_name: 'Curso de iniciación',
      plan_kind: 'credits',
      anchor_day: null,
      started_on: '2026-11-02',
      current_period_end: '2027-01-01',
      credits_remaining: 8,
    }
    const COURSE_PERIOD: OpenPeriod = { ...NOVEMBER, id: 'bp-curso', period_start: '2026-11-02', amount_due_clp: 60000, outstanding_clp: 60000 }
    // The API lists the latest created first.
    stubApi({
      memberships: [COURSE, DIEGO_MEMBERSHIP],
      others: { 'm-curso': { ...DIEGO_LEDGER, open_periods: [COURSE_PERIOD], owed_clp: 60000 } },
    })
    renderAt('/admin/pagos')
    await table()

    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    const panel = screen.getByRole('region', { name: copy.record })
    await userEvent.type(within(panel).getByLabelText(copy.picker.label), 'diego')
    await userEvent.click(await within(panel).findByRole('button', { name: /Diego Morales/ }))

    expect(await within(panel).findByText('Mensual adultos · Curso de iniciación')).toBeInTheDocument()
    const plans = await within(panel).findByRole('group', { name: copy.picker.plan })
    // The plan started first is picked first.
    expect(within(plans).getByRole('button', { name: 'Mensual adultos' })).toHaveAttribute('aria-pressed', 'true')
    let form = await within(panel).findByRole('form', { name: es.admin.member.form.title })
    expect(within(form).getByLabelText(es.admin.member.form.amount)).toHaveValue('45000')

    await userEvent.click(within(plans).getByRole('button', { name: 'Curso de iniciación' }))
    form = await within(panel).findByRole('form', { name: es.admin.member.form.title })
    await waitFor(() => expect(within(form).getByLabelText(es.admin.member.form.amount)).toHaveValue('60000'))
    await userEvent.click(within(form).getByRole('button', { name: es.admin.member.form.submit('$60.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(es.admin.member.form.recorded('$60.000'))
    expect(payments).toEqual([{ membership_id: 'm-curso', billing_period_id: 'bp-curso', amount_clp: 60000, method: 'cash' }])
  })

  it('says when the member picked has nothing to pay', async () => {
    stubApi({ ledger: { ...DIEGO_LEDGER, open_periods: [], owed_clp: 0 } })
    renderAt('/admin/pagos')
    await table()

    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    await userEvent.type(screen.getByLabelText(copy.picker.label), 'diego')
    await userEvent.click(await screen.findByRole('button', { name: /Diego Morales/ }))

    expect(await screen.findByText(copy.picker.upToDate)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.picker.change }))
    expect(screen.getByLabelText(copy.picker.label)).toBeInTheDocument()
  })

  it('says when the member picked has no plan', async () => {
    stubApi({ memberships: [] })
    renderAt('/admin/pagos')
    await table()

    await userEvent.click(screen.getByRole('button', { name: copy.record }))
    await userEvent.type(screen.getByLabelText(copy.picker.label), 'diego')
    await userEvent.click(await screen.findByRole('button', { name: /Diego Morales/ }))

    expect(await screen.findByText(copy.picker.noPlan)).toBeInTheDocument()
  })
})
