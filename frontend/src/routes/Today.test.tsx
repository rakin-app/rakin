import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { InactiveMember } from '../api/inactive'
import type { ProofReview } from '../api/review'
import type { Overdue, OverduePeriod } from '../api/today'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { ago } from './Today'

const copy = es.admin.today

const DIEGO: ProofReview = {
  id: 'e-diego',
  membership_id: 'm-diego',
  person_id: 'diego',
  person_name: 'Diego Morales',
  amount_clp: 45000,
  method: 'transfer',
  claimed_at: null,
  claimed_by_name: 'Diego Morales',
  proof_url: null,
  proof_content_type: null,
  plan_name: 'Mensual adultos',
  plan_kind: 'monthly',
  anchor_day: 10,
  period: {
    id: 'p-diego',
    period_start: '2026-11-10',
    period_end: '2026-12-09',
    due_date: '2026-11-10',
    amount_due_clp: 45000,
    paid_clp: 0,
    outstanding_clp: 45000,
  },
  prior_balance_clp: 0,
  last_payments: [],
  attendance_30d: 0,
}

const MATEO: ProofReview = {
  ...DIEGO,
  id: 'e-mateo',
  person_id: 'mateo',
  person_name: 'Mateo Ortiz',
  claimed_by_name: 'Camila Ortiz',
  amount_clp: 36000,
}

const late = (name: string, days: number, amount = 45000): OverduePeriod => ({
  billing_period_id: `p-${name}`,
  membership_id: `m-${name}`,
  person_id: name,
  person_name: name,
  plan_name: 'Mensual adultos',
  period_start: '2026-10-30',
  due_date: '2026-10-30',
  outstanding_clp: amount,
  days_overdue: days,
})

const OVERDUE: Overdue = {
  total_clp: 120000,
  periods: [late('Felipe Díaz', 9), late('Javiera Silva', 4), late('Tomás Pérez', 2, 30000)],
}

const away = (name: string, days: number, extra: Partial<InactiveMember> = {}): InactiveMember => ({
  person_id: name,
  name,
  last_attended_on: '2026-10-25',
  days_absent: days,
  bucket: days >= 30 ? 30 : 14,
  payment_status: 'up_to_date',
  overdue_clp: 0,
  contact_name: name,
  whatsapp_url: `https://wa.me/56912345678?text=Hola%20${days}`,
  nudged_at: null,
  ...extra,
})

const INACTIVE: InactiveMember[] = [
  away('Ignacio Vera', 16),
  away('Tomás Rojas', 20, { contact_name: 'Ana Rojas', payment_status: 'overdue', overdue_clp: 30000 }),
  away('Paula Contreras', 41, { last_attended_on: null, payment_status: 'trial', whatsapp_url: null }),
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }
type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  proofs?: Answer
  overdue?: Overdue
  payment?: Answer
  inactive?: InactiveMember[]
}

function stubApi({ role = 'owner', proofs, overdue = OVERDUE, payment, inactive = INACTIVE }: Stub = {}) {
  const calls: Call[] = []
  let current = overdue
  let away = inactive
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      calls.push({ method, path: url.pathname, body: typeof raw === 'string' ? JSON.parse(raw) : raw })
      const answer = route(url.pathname, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string): Answer {
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/ledger/pending') return { body: { count: 2 } }
    if (path === '/api/ledger/proofs') return proofs ?? { body: [DIEGO, MATEO] }
    if (path === '/api/ledger/overdue') return { body: current }
    if (path === '/api/inactive') return { body: away }
    const nudged = /^\/api\/inactive\/(.+)\/nudge$/.exec(path)
    if (nudged && method === 'POST') {
      const sentAt = new Date().toISOString()
      away = away.map((m) => (m.person_id === decodeURIComponent(nudged[1]!) ? { ...m, nudged_at: sentAt } : m))
      return { status: 201, body: { message_id: 'msg-1', sent_at: sentAt } }
    }
    if (path === '/api/ledger/payments' && method === 'POST') {
      if (payment && (payment.status ?? 201) >= 400) return payment
      const [, ...rest] = current.periods
      current = { total_clp: rest.reduce((sum, p) => sum + p.outstanding_clp, 0), periods: rest }
      return { status: 201, body: { credit: null, period: { outstanding_clp: 0, closed: true } } }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderToday() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin'] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const section = (name: string) => screen.findByRole('region', { name })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Hoy', () => {
  it('counts what is overdue and what waits for review', async () => {
    stubApi()
    renderToday()

    const counters = await screen.findByRole('group', { name: copy.countersLabel })
    const overdue = await within(counters).findByRole('link', { name: `3 ${copy.overdue.title}` })
    expect(overdue).toHaveAttribute('href', '#vencidos')
    expect(await within(counters).findByRole('link', { name: `2 ${copy.proofs.title}` })).toHaveAttribute(
      'href',
      '#validar',
    )
  })

  it('lists the pending proofs, each leading to the review queue', async () => {
    stubApi()
    renderToday()

    const proofs = await section(copy.proofs.title)
    expect(await within(proofs).findByText(copy.proofs.count(2))).toBeInTheDocument()
    const rows = within(proofs).getAllByRole('link')
    expect(rows.map((row) => row.getAttribute('aria-label'))).toEqual([
      copy.proofs.reviewLabel('Diego Morales'),
      copy.proofs.reviewLabel(copy.proofs.sentFor('Camila Ortiz', 'Mateo Ortiz')),
    ])
    expect(rows.every((row) => row.getAttribute('href') === '/admin/pagos/comprobantes')).toBe(true)
    expect(within(rows[0]!).getByText('Transfirió $45.000 · noviembre')).toBeInTheDocument()
  })

  it('lists the overdue with their total, each linking to the member', async () => {
    stubApi()
    renderToday()

    const overdue = await section(copy.overdue.title)
    expect(await within(overdue).findByText(copy.overdue.total('$120.000'))).toBeInTheDocument()
    const felipe = within(overdue).getByRole('link', { name: /Felipe Díaz/ })
    expect(felipe).toHaveAttribute('href', '/admin/alumnos/Felipe%20D%C3%ADaz')
    expect(within(felipe).getByText('Venció hace 9 días · $45.000 · Mensual adultos')).toBeInTheDocument()
  })

  it('shows three overdue until asked for all', async () => {
    stubApi({ overdue: { total_clp: 180000, periods: [...OVERDUE.periods, late('Ana Rojas', 1)] } })
    renderToday()

    const overdue = await section(copy.overdue.title)
    expect(await within(overdue).findAllByRole('listitem')).toHaveLength(3)
    await userEvent.click(within(overdue).getByRole('button', { name: copy.overdue.showAll(4) }))
    expect(within(overdue).getAllByRole('listitem')).toHaveLength(4)
    expect(within(overdue).getByText('Venció hace 1 día · $45.000 · Mensual adultos')).toBeInTheDocument()
  })

  it('records the outstanding amount with "Pagó", and drops the row', async () => {
    const calls = stubApi()
    renderToday()
    const overdue = await section(copy.overdue.title)

    await userEvent.click(await within(overdue).findByRole('button', { name: copy.overdue.paidLabel('Felipe Díaz') }))
    const form = within(overdue).getByRole('form', { name: copy.overdue.paidLabel('Felipe Díaz') })
    await userEvent.selectOptions(within(form).getByLabelText(copy.overdue.method), 'transfer')
    await userEvent.click(within(form).getByRole('button', { name: copy.overdue.submit('$45.000') }))

    expect(await within(overdue).findByRole('status')).toHaveTextContent(
      copy.overdue.recorded('Felipe Díaz', '$45.000'),
    )
    expect(calls.find((c) => c.path === '/api/ledger/payments')?.body).toEqual({
      membership_id: 'm-Felipe Díaz',
      billing_period_id: 'p-Felipe Díaz',
      amount_clp: 45000,
      method: 'transfer',
    })
    expect(await within(overdue).findByText(copy.overdue.total('$75.000'))).toBeInTheDocument()
    expect(within(overdue).queryByRole('link', { name: /Felipe Díaz/ })).not.toBeInTheDocument()
  })

  it('says so when the period was paid meanwhile', async () => {
    stubApi({ payment: { status: 409, body: { detail: 'billing period is already paid in full' } } })
    renderToday()
    const overdue = await section(copy.overdue.title)

    await userEvent.click(await within(overdue).findByRole('button', { name: copy.overdue.paidLabel('Felipe Díaz') }))
    await userEvent.click(within(overdue).getByRole('button', { name: copy.overdue.submit('$45.000') }))

    expect(await within(overdue).findByRole('alert')).toHaveTextContent(copy.overdue.refused.paid)
  })

  it('says when nothing is overdue or waiting', async () => {
    stubApi({ proofs: { body: [] }, overdue: { total_clp: 0, periods: [] } })
    renderToday()

    expect(await within(await section(copy.proofs.title)).findByText(copy.proofs.empty)).toBeInTheDocument()
    expect(await within(await section(copy.overdue.title)).findByText(copy.overdue.empty)).toBeInTheDocument()
  })

  it('offers a retry when a list fails to load', async () => {
    // A 4xx, which is not retried.
    stubApi({ proofs: { status: 403, body: { detail: 'forbidden' } } })
    renderToday()

    const proofs = await section(copy.proofs.title)
    expect(await within(proofs).findByRole('alert')).toHaveTextContent(copy.proofs.error)
    expect(within(proofs).getByRole('button', { name: copy.retry })).toBeInTheDocument()
  })

  it('shows a coach no money, and never asks for it', async () => {
    const calls = stubApi({ role: 'coach' })
    renderToday()

    expect(await screen.findByRole('heading', { level: 1, name: /^Hoy,/ })).toBeInTheDocument()
    // The role answers before the lists would be asked for.
    await screen.findByRole('navigation', { name: es.nav.label })
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/api/me/role')).toBe(true))
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/ledger/') || c.path.startsWith('/api/inactive'))).toEqual(
      [],
    )
  })

  it('counts who has not come in 14 days', async () => {
    stubApi()
    renderToday()

    const counters = await screen.findByRole('group', { name: copy.countersLabel })
    expect(await within(counters).findByRole('link', { name: `3 ${copy.inactive.counter}` })).toHaveAttribute(
      'href',
      '#inactivos',
    )
  })

  it('lists who to call in the 14 and 30 day buckets, with how they stand on payments', async () => {
    stubApi()
    renderToday()

    const inactive = await section(copy.inactive.title)
    const fourteen = await within(inactive).findByRole('list', { name: new RegExp(copy.inactive.buckets[14]) })
    const thirty = within(inactive).getByRole('list', { name: new RegExp(copy.inactive.buckets[30]) })
    expect(within(fourteen).getAllByRole('listitem')).toHaveLength(2)
    expect(within(fourteen).getByText('16 días sin venir · al día en pagos')).toBeInTheDocument()
    expect(within(fourteen).getByText('20 días sin venir · debe $30.000')).toBeInTheDocument()
    expect(within(thirty).getByText(`${copy.inactive.never(41)} · en prueba`)).toBeInTheDocument()
    expect(within(inactive).getByRole('link', { name: /^Ignacio Vera/ })).toHaveAttribute(
      'href',
      '/admin/alumnos/Ignacio%20Vera',
    )
  })

  it('opens WhatsApp in one tap, to the guardian for a dependent, and logs it', async () => {
    const calls = stubApi()
    renderToday()
    const inactive = await section(copy.inactive.title)

    const ignacio = await within(inactive).findByRole('link', { name: copy.inactive.write('Ignacio Vera') })
    expect(ignacio).toHaveAttribute('href', 'https://wa.me/56912345678?text=Hola%2016')
    expect(ignacio).toHaveAttribute('target', '_blank')
    expect(
      within(inactive).getByRole('link', { name: copy.inactive.writeFor('Ana Rojas', 'Tomás Rojas') }),
    ).toBeInTheDocument()
    // No phone to write to, or WhatsApp off: no link.
    expect(within(inactive).queryByRole('link', { name: /WhatsApp a Paula/ })).not.toBeInTheDocument()

    await userEvent.click(ignacio)

    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
      '/api/inactive/Ignacio%20Vera/nudge',
    ])
    expect(await within(inactive).findByText(/16 días sin venir · al día en pagos · avisado/)).toBeInTheDocument()
  })

  it('logs a nudge opened with a middle-click too', async () => {
    const calls = stubApi()
    renderToday()
    const inactive = await section(copy.inactive.title)

    const ignacio = await within(inactive).findByRole('link', { name: copy.inactive.write('Ignacio Vera') })
    await userEvent.pointer({ keys: '[MouseMiddle]', target: ignacio })

    await vi.waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
        '/api/inactive/Ignacio%20Vera/nudge',
      ]),
    )
  })

  it('says when everyone came in the last two weeks', async () => {
    stubApi({ inactive: [] })
    renderToday()

    expect(await within(await section(copy.inactive.title)).findByText(copy.inactive.empty)).toBeInTheDocument()
  })
})

describe('ago', () => {
  const now = new Date(2026, 10, 9, 15, 0)

  it.each([
    [new Date(2026, 10, 9, 14, 59, 30), copy.ago.now],
    [new Date(2026, 10, 9, 14, 20), copy.ago.minutes(40)],
    [new Date(2026, 10, 9, 13, 0), copy.ago.hours(2)],
    [new Date(2026, 10, 8, 23, 0), copy.ago.yesterday],
    [new Date(2026, 10, 5, 12, 0), '5 nov'],
  ])('%s is %s', (then, expected) => {
    expect(ago(then.toISOString(), now)).toBe(expected)
  })
})
