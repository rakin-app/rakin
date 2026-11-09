import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GradeEvent, Grading, GradingScheme } from '../api/grading'
import type { Membership, MembershipLedger, OpenPeriod, Person, TimelineEntry } from '../api/member'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.member

const FELIPE: Person = {
  id: 'felipe',
  phone: '+56912344417',
  name: 'Felipe Díaz',
  email: null,
  rut: null,
  dob: null,
  created_at: '2025-01-10T12:00:00Z',
}

const MONTHLY: Membership = {
  id: 'm-felipe',
  plan_id: 'plan-adults',
  plan_name: 'Mensual adultos',
  plan_kind: 'monthly',
  status: 'active',
  anchor_day: 30,
  started_on: '2024-03-30',
  current_period_end: '2026-10-29',
  credits_remaining: null,
}

const OCTOBER: OpenPeriod = {
  id: 'p-oct',
  period_start: '2026-10-30',
  period_end: '2026-11-29',
  due_date: '2026-10-31',
  amount_due_clp: 45000,
  paid_clp: 0,
  outstanding_clp: 45000,
  due: true,
  days_overdue: 9,
}

const entry = (fields: Partial<TimelineEntry> & Pick<TimelineEntry, 'id' | 'kind'>): TimelineEntry => ({
  status: 'validated',
  amount_clp: 45000,
  method: null,
  billing_period_id: null,
  period_start: null,
  note: null,
  created_at: '2026-10-23T12:00:00Z',
  validated_by_name: null,
  validated_at: null,
  ...fields,
})

const LEDGER: MembershipLedger = {
  open_periods: [OCTOBER],
  owed_clp: 45000,
  entries: [
    entry({ id: 'c-oct', kind: 'charge', billing_period_id: 'p-oct', period_start: '2026-10-30' }),
    entry({
      id: 'pay-sep',
      kind: 'payment',
      method: 'transfer',
      billing_period_id: 'p-sep',
      period_start: '2026-09-30',
      created_at: '2026-10-01T12:00:00Z',
      validated_by_name: 'Martín',
      validated_at: '2026-10-02T12:00:00Z',
    }),
    entry({
      id: 'claim',
      kind: 'payment',
      status: 'pending',
      method: 'transfer',
      billing_period_id: 'p-oct',
      period_start: '2026-10-30',
      amount_clp: 20000,
      created_at: '2026-11-05T12:00:00Z',
    }),
    entry({ id: 'credit', kind: 'adjustment', amount_clp: 5000, note: 'Pagó $50.000; quedan $5.000 a favor' }),
  ],
}

const stripes = [0, 1, 2, 3, 4].map((n) => ({ key: String(n), label: n === 0 ? 'Sin grados' : n === 1 ? '1 grado' : `${n} grados` }))

const SCHEME: GradingScheme = {
  ranks: [
    { key: 'white', label: 'Blanca', sub_ranks: stripes },
    { key: 'blue', label: 'Azul', sub_ranks: stripes },
    { key: 'purple', label: 'Morada', sub_ranks: stripes },
  ],
  kids_ladder: [{ key: 'grey', label: 'Gris', sub_ranks: stripes }],
  goal_metric: 'classes_since_promotion',
}

const grade = (fields: Partial<GradeEvent> & Pick<GradeEvent, 'id'>): GradeEvent => ({
  rank_key: 'blue',
  rank_label: 'Azul',
  sub_rank: '2',
  sub_rank_label: '2 grados',
  awarded_on: '2026-04-11',
  awarded_by_name: 'Sebastián Araya',
  note: null,
  created_at: '2026-04-12T01:00:00Z',
  ...fields,
})

const BLUE_2 = grade({ id: 'g-blue-2' })
const GRADING: Grading = {
  current: { rank_key: 'blue', rank_label: 'Azul', sub_rank: '2', sub_rank_label: '2 grados', awarded_on: '2026-04-11' },
  events: [BLUE_2, grade({ id: 'g-blue-1', sub_rank: '1', sub_rank_label: '1 grado', awarded_on: '2025-08-02', note: 'Open de Santiago' })],
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  person?: Answer
  memberships?: Membership[]
  ledger?: MembershipLedger
  payment?: Answer
  grading?: Grading
  scheme?: GradingScheme
  award?: Answer
}

function stubApi({
  role = 'owner',
  person,
  memberships = [MONTHLY],
  ledger = LEDGER,
  payment,
  grading = GRADING,
  scheme = SCHEME,
  award,
}: Stub = {}) {
  const calls: Call[] = []
  let current = ledger
  let grades = grading
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      calls.push({ method, path: url.pathname, body: typeof raw === 'string' ? JSON.parse(raw) : raw })
      const answer = route(url, method)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(url: URL, method: string): Answer {
    const path = url.pathname
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/ledger/pending') return { body: { count: 0 } }
    if (path === '/api/people/felipe') return person ?? { body: FELIPE }
    if (path === '/api/memberships' && url.searchParams.get('person_id') === 'felipe') return { body: memberships }
    if (path === '/api/ledger/memberships/m-felipe') return { body: current }
    if (path === '/api/gym/grading-scheme') return { body: scheme }
    if (path === '/api/people/felipe/grades' && method === 'GET') return { body: grades }
    if (path === '/api/people/felipe/grades' && method === 'POST') {
      if (award) return award
      const purple = grade({ id: 'g-new', rank_key: 'purple', rank_label: 'Morada', sub_rank: '0', sub_rank_label: 'Sin grados', awarded_on: '2026-11-08' })
      grades = { current: purple, events: [purple, ...grades.events] }
      return { status: 201, body: grades }
    }
    if (path === '/api/people/felipe/family') return { body: { guardian: null, dependents: [{ id: 'kid', name: 'Tomás Díaz' }] } }
    if (path === '/api/ledger/payments' && method === 'POST') {
      if (payment && (payment.status ?? 201) >= 400) return payment
      current = { open_periods: [], owed_clp: 0, entries: current.entries }
      return payment ?? { status: 201, body: { credit: null, period: { outstanding_clp: 0, closed: true } } }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

const PATH = '/admin/alumnos/felipe'
const money = () => screen.findByRole('region', { name: copy.paymentLabel })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ficha de alumno', () => {
  it('shows the member, their plan and due day, and how late they are', async () => {
    stubApi()
    renderAt(PATH)

    expect(await screen.findByRole('heading', { name: 'Felipe Díaz' })).toBeInTheDocument()
    expect(await screen.findByText(copy.rankSince('Azul · 2 grados', 'mar 2024'))).toBeInTheDocument()
    const card = await money()
    expect(within(card).getByText('Mensual adultos · vence el 30')).toBeInTheDocument()
    expect(await within(card).findByText(copy.overdue(9))).toBeInTheDocument()
    expect(within(card).getByText('$45.000')).toBeInTheDocument()
    expect(within(card).getByText(copy.pendingMonth('octubre'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: copy.back })).toHaveAttribute('href', '/admin/alumnos')
  })

  it('lists the ledger newest first, saying who validated each payment', async () => {
    stubApi()
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    const rows = within(ledger).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      'Cargo octubregenerado 23 oct · sin pago$45.000',
      'Pago septiembretransferencia · validó Martín · 2 oct$45.000',
      'Pago octubretransferencia · por validar · 5 nov$20.000',
      `${copy.ledger.credit}Pagó $50.000; quedan $5.000 a favor · 23 oct$5.000`,
    ])
  })

  it('shows the status when nothing is late, and the next amount due', async () => {
    const upcoming = { ...OCTOBER, due: false, days_overdue: 0, due_date: '2026-11-30' }
    stubApi({ ledger: { ...LEDGER, open_periods: [upcoming], owed_clp: 0 } })
    renderAt(PATH)

    const card = await money()
    expect(await within(card).findByText(copy.nextDue('30 nov'))).toBeInTheDocument()
    expect(within(card).getByText(es.admin.students.status.active)).toBeInTheDocument()
  })

  it('records a payment against the oldest open period', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    const form = screen.getByRole('form', { name: copy.form.title })
    expect(within(form).getByLabelText(copy.form.amount)).toHaveValue('45000')
    await userEvent.selectOptions(within(form).getByLabelText(copy.form.method), 'transfer')
    await userEvent.click(within(form).getByRole('button', { name: copy.form.submit('$45.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.form.recorded('$45.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/payments',
        body: { membership_id: 'm-felipe', billing_period_id: 'p-oct', amount_clp: 45000, method: 'transfer' },
      },
    ])
    // The ledger is read again: nothing is owed now.
    await waitFor(() => expect(within(card).getByText(copy.upToDate)).toBeInTheDocument())
    expect(within(card).getByRole('button', { name: copy.record })).toBeDisabled()
  })

  it('says so when the period was paid meanwhile', async () => {
    stubApi({ payment: { status: 409, body: { detail: 'billing period is already paid in full' } } })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    await userEvent.click(screen.getByRole('button', { name: copy.form.submit('$45.000') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.form.refused.paid)
  })

  it('asks for an amount before recording', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    await userEvent.clear(screen.getByLabelText(copy.form.amount))
    await userEvent.click(screen.getByRole('button', { name: copy.form.submit('$0') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.form.amountNeeded)
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('shows a coach the plan and status, never money', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt(PATH)

    const card = await money()
    expect(within(card).getByText('Mensual adultos · vence el 30')).toBeInTheDocument()
    expect(within(card).getByText(es.admin.students.status.active)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.record })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.ledger.title })).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.startsWith('/api/ledger/memberships'))).toBe(false)
  })

  it('shows who they pay for', async () => {
    stubApi()
    renderAt(PATH)

    const family = await screen.findByRole('region', { name: es.admin.family.toggle })
    expect(await within(family).findByText('Tomás Díaz')).toBeInTheDocument()
  })

  it('says when the member has no plan, and offers no promotion', async () => {
    stubApi({ memberships: [], grading: { current: null, events: [] } })
    renderAt(PATH)

    expect(await screen.findByText(copy.noPlan)).toBeInTheDocument()
    expect(screen.getByText(copy.since('ene 2025'))).toBeInTheDocument()
    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    expect(within(graduation).getByText(copy.grading.none)).toBeInTheDocument()
    expect(within(graduation).queryByRole('button', { name: copy.grading.award })).not.toBeInTheDocument()
  })

  it('says when there is no such member', async () => {
    stubApi({ person: { status: 404, body: { detail: 'person not found' } } })
    renderAt(PATH)

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.notFound)
  })
  it('shows the rank since when, and the promotion log newest first', async () => {
    stubApi()
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    expect(within(graduation).getByText('Azul · 2 grados', { selector: '.member__rank-label' })).toBeInTheDocument()
    expect(within(graduation).getByText(copy.grading.since('11 abr 2026'))).toBeInTheDocument()
    const log = within(graduation).getByRole('list', { name: copy.grading.log })
    expect(within(log).getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      'Azul · 2 grados11 abr 2026 · registró Sebastián Araya',
      'Azul · 1 grado2 ago 2025 · registró Sebastián Araya · Open de Santiago',
    ])
  })

  it('awards the next sub-rank by default, and shows the new rank', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const graduation = await screen.findByRole('region', { name: copy.grading.title })

    await userEvent.click(within(graduation).getByRole('button', { name: copy.grading.award }))
    const form = screen.getByRole('form', { name: copy.grading.form.title })
    expect(within(form).getByLabelText(copy.grading.form.rank)).toHaveValue('blue')
    expect(within(form).getByLabelText(copy.grading.form.subRank)).toHaveValue('3')
    // Another rank starts at its first sub-rank.
    await userEvent.selectOptions(within(form).getByLabelText(copy.grading.form.rank), 'purple')
    expect(within(form).getByLabelText(copy.grading.form.subRank)).toHaveValue('0')
    await userEvent.clear(within(form).getByLabelText(copy.grading.form.date))
    await userEvent.type(within(form).getByLabelText(copy.grading.form.date), '2026-11-08')
    await userEvent.type(within(form).getByLabelText(copy.grading.form.note), ' Examen ')
    await userEvent.click(within(form).getByRole('button', { name: copy.grading.form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.grading.form.done('Morada · Sin grados'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/people/felipe/grades',
        body: { rank_key: 'purple', sub_rank: '0', awarded_on: '2026-11-08', note: 'Examen' },
      },
    ])
    await waitFor(() => expect(screen.getByText(copy.rankSince('Morada · Sin grados', 'mar 2024'))).toBeInTheDocument())
  })

  it('moves to the next rank after the last sub-rank', async () => {
    const top = grade({ id: 'g-blue-4', sub_rank: '4', sub_rank_label: '4 grados' })
    stubApi({ grading: { current: top, events: [top] } })
    renderAt(PATH)

    await userEvent.click(await screen.findByRole('button', { name: copy.grading.award }))
    const form = screen.getByRole('form', { name: copy.grading.form.title })
    expect(within(form).getByLabelText(copy.grading.form.rank)).toHaveValue('purple')
    expect(within(form).getByLabelText(copy.grading.form.subRank)).toHaveValue('0')
  })

  it('lets a coach promote', async () => {
    stubApi({ role: 'coach' })
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    expect(within(graduation).getByRole('button', { name: copy.grading.award })).toBeInTheDocument()
  })

  it.each([
    ['awarded_in_future', copy.grading.form.refused.awarded_in_future],
    ['no_membership', copy.grading.form.refused.no_membership],
    ['unknown_rank', copy.grading.form.refused.failed],
  ] as const)('explains a %s refusal', async (code, message) => {
    stubApi({ award: { status: code === 'no_membership' ? 409 : 422, body: { detail: { code } } } })
    renderAt(PATH)

    await userEvent.click(await screen.findByRole('button', { name: copy.grading.award }))
    await userEvent.click(screen.getByRole('button', { name: copy.grading.form.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
  })

  it('has no graduación in a gym with no ranks', async () => {
    stubApi({ scheme: { ranks: [], kids_ladder: [], goal_metric: null }, grading: { current: null, events: [] } })
    renderAt(PATH)

    await money()
    expect(screen.getByText(copy.since('mar 2024'))).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.grading.title })).not.toBeInTheDocument()
  })
})
