import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FieldValue, PersonField } from '../api/customFields'
import type { GradeEvent, Grading, GradingScheme } from '../api/grading'
import type { Membership, MembershipLedger, OpenPeriod, Person, TimelineEntry } from '../api/member'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { isoDay, shortDay } from '../format'
import type { PersonTime } from '../api/matTime'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.member

// A class with sparring, and an open mat whose time is sparring too.
const FELIPE_TIME: PersonTime = (() => {
  const totals = {
    by_kind: [
      { block_kind_id: 'k-tec', name: 'Técnica', is_sparring: false, seconds: 1200 },
      { block_kind_id: 'k-spar', name: 'Sparring', is_sparring: true, seconds: 5400 },
    ],
    sparring_seconds: 5400,
    open_mat_seconds: 1800,
    classes: 1,
    open_mats: 1,
  }
  return { timezone: 'America/Santiago', month_start: '2026-11-01', this_month: totals, all_time: totals }
})()

const FELIPE: Person = {
  id: 'felipe',
  phone: '+56912344417',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  name: 'Felipe Díaz',
  email: null,
  rut: null,
  dob: null,
  left_on: null,
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
  freeze: null,
}

const FROZEN: Membership = {
  ...MONTHLY,
  status: 'frozen',
  freeze: { id: 'f1', from_date: '2026-11-03', to_date: '2026-11-24', reason: 'Viaje', started: true },
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
  refund_of: null,
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
  freezes: [],
  periods: [
    { id: 'p-oct', period_start: '2026-10-30', period_end: '2026-11-29', outstanding_clp: 45000 },
    { id: 'p-sep', period_start: '2026-09-30', period_end: '2026-10-29', outstanding_clp: 0 },
  ],
  refundable_payments: [
    {
      id: 'pay-sep',
      billing_period_id: 'p-sep',
      period_start: '2026-09-30',
      amount_clp: 45000,
      method: 'transfer',
      validated_at: '2026-10-02T12:00:00Z',
      refundable_clp: 45000,
    },
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
  adjustment?: Answer
  refund?: Answer
  grading?: Grading
  scheme?: GradingScheme
  award?: Answer
  // The freeze's answer; by default the membership comes back frozen until the day asked.
  freeze?: Answer
  fields?: PersonField[]
  fieldsUpdate?: Answer
  attendance?: Answer
  time?: Answer
  // The gym's timezone, as today's sessions give it.
  timeZone?: string
  // The member's WhatsApp payment reminders (#55); none by default.
  reminders?: unknown[]
  // Answers anything else first: the record's own actions (#157).
  extra?: (path: string, method: string, body: unknown) => Answer | undefined
}

function stubApi({
  role = 'owner',
  person,
  memberships = [MONTHLY],
  ledger = LEDGER,
  payment,
  adjustment,
  refund,
  grading = GRADING,
  scheme = SCHEME,
  award,
  freeze,
  fields = [],
  fieldsUpdate,
  attendance = { body: { last_30_days: 9, total: 184, since_promotion: 62 } },
  time = { body: FELIPE_TIME },
  timeZone = 'America/Santiago',
  reminders = [],
  extra,
}: Stub = {}) {
  const calls: Call[] = []
  let current = ledger
  let members = memberships
  let grades = grading
  let currentFields = fields
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
    const answered = extra?.(path, method, calls.at(-1)?.body)
    if (answered) return answered
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/sessions') return { body: { date: '2026-11-10', timezone: timeZone, sessions: [] } }
    if (path === '/api/ledger/pending') return { body: { count: 0 } }
    if (path === '/api/people/felipe') return person ?? { body: FELIPE }
    if (path === '/api/memberships' && url.searchParams.get('person_id') === 'felipe') return { body: members }
    if (path === '/api/memberships/m-felipe/freeze' && method === 'POST') {
      if (freeze) return freeze
      const { from_date, ...asked } = calls.at(-1)!.body as { from_date?: string; to_date: string; reason: string }
      const frozen: Membership = {
        ...MONTHLY,
        status: from_date ? 'active' : 'frozen',
        freeze: { id: 'f1', from_date: from_date ?? isoDay(new Date().toISOString()), started: !from_date, ...asked },
      }
      members = [frozen]
      return { body: frozen }
    }
    if (path === '/api/memberships/m-felipe/freeze' && method === 'PATCH') {
      const asked = calls.at(-1)!.body as { to_date?: string; reason?: string }
      const edited: Membership = { ...members[0]!, freeze: { ...members[0]!.freeze!, ...asked } }
      members = [edited]
      return { body: edited }
    }
    if (path === '/api/memberships/m-felipe/freeze/end' && method === 'POST') {
      const ended: Membership = { ...members[0]!, status: 'active', freeze: null }
      members = [ended]
      return { body: ended }
    }
    if (path === '/api/ledger/memberships/m-felipe') return { body: current }
    if (path === '/api/reminders' && url.searchParams.get('person_id') === 'felipe') return { body: reminders }
    if (path.startsWith('/api/reminders/') && method === 'POST') return { status: 201, body: {} }
    if (path === '/api/gym/grading-scheme') return { body: scheme }
    if (path === '/api/people/felipe/attendance') return attendance
    if (path === '/api/people/felipe/time') return time
    if (path === '/api/people/felipe/grades' && method === 'GET') return { body: grades }
    if (path === '/api/people/felipe/grades' && method === 'POST') {
      if (award) return award
      const purple = grade({ id: 'g-new', rank_key: 'purple', rank_label: 'Morada', sub_rank: '0', sub_rank_label: 'Sin grados', awarded_on: '2026-11-08' })
      grades = { current: purple, events: [purple, ...grades.events] }
      return { status: 201, body: grades }
    }
    if (path === '/api/people/felipe/family') return { body: { guardian: null, dependents: [{ id: 'kid', name: 'Tomás Díaz' }] } }
    if (path === '/api/people/felipe/fields' && method === 'GET') return { body: currentFields }
    if (path === '/api/people/felipe/fields' && method === 'PATCH') {
      if (fieldsUpdate) return fieldsUpdate
      const { values } = calls.at(-1)!.body as { values: Record<string, FieldValue> }
      currentFields = currentFields.map((f) => (f.key in values ? { ...f, value: values[f.key]! } : f))
      return { body: currentFields }
    }
    if (path === '/api/ledger/payments' && method === 'POST') {
      if (payment && (payment.status ?? 201) >= 400) return payment
      current = { ...current, open_periods: [], owed_clp: 0 }
      return payment ?? { status: 201, body: { credit: null, period: { outstanding_clp: 0, closed: true } } }
    }
    if (path === '/api/ledger/adjustments' && method === 'POST') {
      return adjustment ?? { status: 201, body: { period: { outstanding_clp: 0, closed: true } } }
    }
    if (path === '/api/ledger/refunds' && method === 'POST') {
      return refund ?? { status: 201, body: { period: { outstanding_clp: 45000, closed: false } } }
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
  vi.useRealTimers()
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

  it('says what has come in against a partly paid charge, not "sin pago"', async () => {
    // $40.000 of $45.000 validated (#210).
    stubApi({
      ledger: { ...LEDGER, open_periods: [{ ...OCTOBER, paid_clp: 40000, outstanding_clp: 5000 }], owed_clp: 5000 },
    })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    expect(within(ledger).getAllByRole('listitem')[0]).toHaveTextContent(
      `Cargo octubregenerado 23 oct · ${copy.ledger.partlyPaid('$40.000')}$45.000`,
    )
  })

  it('lists a discount and a surcharge by what each does to what is owed, and refunds as money out', async () => {
    stubApi({
      ledger: {
        ...LEDGER,
        entries: [
          entry({
            id: 'refund',
            kind: 'refund',
            amount_clp: 10000,
            method: 'cash',
            billing_period_id: 'p-sep',
            period_start: '2026-09-30',
            note: 'se lesionó',
            refund_of: 'pay-sep',
            created_at: '2026-11-06T12:00:00Z',
            validated_at: '2026-11-06T12:00:00Z',
          }),
          entry({
            id: 'owed',
            kind: 'adjustment',
            amount_clp: -5000,
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            note: 'matrícula',
            created_at: '2026-11-04T12:00:00Z',
          }),
          entry({
            id: 'favor',
            kind: 'adjustment',
            amount_clp: 3000,
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            note: 'beca',
            created_at: '2026-11-03T12:00:00Z',
          }),
        ],
      },
    })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    expect(within(ledger).getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      'Devolución septiembreefectivo · se lesionó · 6 nov−$10.000',
      'Recargo octubrematrícula · 4 nov+$5.000',
      'Descuento octubrebeca · 3 nov−$3.000',
    ])
  })

  it('shows the status when nothing is late, and the next amount due', async () => {
    const upcoming = { ...OCTOBER, due: false, days_overdue: 0, due_date: '2026-11-30' }
    stubApi({ ledger: { ...LEDGER, open_periods: [upcoming], owed_clp: 0 } })
    renderAt(PATH)

    const card = await money()
    expect(await within(card).findByText(copy.upToDateNext('30 nov'))).toBeInTheDocument()
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
    // Still offered, and it says why there is nothing to record against (#179).
    const record = within(card).getByRole('button', { name: copy.record })
    expect(record).toBeEnabled()
    await userEvent.click(record)
    expect(within(card).getByText(copy.nothingToRecord)).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: copy.form.title })).not.toBeInTheDocument()
  })

  it('offers only what can be done: no adjustment, refund or freeze with nothing to do it on', async () => {
    stubApi({
      memberships: [{ ...MONTHLY, status: 'lapsed' }],
      ledger: { ...LEDGER, periods: [], refundable_payments: [] },
    })
    renderAt(PATH)
    const card = await money()

    expect(await within(card).findByRole('button', { name: copy.record })).toBeEnabled()
    expect(within(card).queryByRole('button', { name: copy.adjust })).not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.refund })).not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.freeze })).not.toBeInTheDocument()
    expect(within(card).queryAllByRole('button').filter((b) => b.hasAttribute('disabled'))).toEqual([])
  })

  it('says what a partial payment leaves to pay', async () => {
    stubApi({ payment: { status: 201, body: { credit: null, period: { outstanding_clp: 25000, closed: false } } } })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    const amount = screen.getByLabelText(copy.form.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '20000')
    await userEvent.click(screen.getByRole('button', { name: copy.form.submit('$20.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.form.recorded('$20.000') + copy.form.remainder('$25.000'),
    )
  })

  it('adjusts a period in the member\'s favour, with its reason', async () => {
    const calls = stubApi({
      adjustment: { status: 201, body: { period: { outstanding_clp: 40000, closed: false } } },
    })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.adjust }))
    const form = screen.getByRole('form', { name: copy.adjustForm.title })
    expect(within(form).getByLabelText(copy.adjustForm.direction)).toHaveValue('favor')
    await userEvent.type(within(form).getByLabelText(copy.adjustForm.amount), '5000')
    await userEvent.type(within(form).getByLabelText(copy.adjustForm.note), ' descuento hermano ')
    await userEvent.click(within(form).getByRole('button', { name: copy.adjustForm.submit(true, '$5.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.adjustForm.done(true, '$5.000') + copy.form.remainder('$40.000'),
    )
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/adjustments',
        body: { membership_id: 'm-felipe', billing_period_id: 'p-oct', amount_clp: 5000, note: 'descuento hermano' },
      },
    ])
  })

  it('adjusts a paid period against the member, owed on top', async () => {
    // An old period, long out of the timeline: the ledger still offers it.
    const paid = { id: 'p-sep', period_start: '2026-09-30', period_end: '2026-10-29', outstanding_clp: 0 }
    const calls = stubApi({
      ledger: { ...LEDGER, open_periods: [], owed_clp: 0, entries: [], periods: [paid] },
      adjustment: { status: 201, body: { period: { outstanding_clp: 5000, closed: false } } },
    })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.adjust }))
    const form = screen.getByRole('form', { name: copy.adjustForm.title })
    // Nothing is owed, so nothing can be taken off.
    expect(within(form).getByLabelText(copy.adjustForm.direction)).toHaveValue('owed')
    expect(within(form).getByRole('option', { name: copy.adjustForm.directions.favor })).toBeDisabled()
    expect(within(form).getByLabelText(copy.adjustForm.period)).toHaveTextContent(
      copy.adjustForm.periodOption('septiembre', '$0'),
    )
    await userEvent.type(within(form).getByLabelText(copy.adjustForm.amount), '5000')
    await userEvent.type(within(form).getByLabelText(copy.adjustForm.note), 'matrícula')
    await userEvent.click(within(form).getByRole('button', { name: copy.adjustForm.submit(false, '$5.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.adjustForm.done(false, '$5.000'))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([
      { membership_id: 'm-felipe', billing_period_id: 'p-sep', amount_clp: -5000, note: 'matrícula' },
    ])
  })

  it('asks for an amount and a reason before adjusting', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.adjust }))
    await userEvent.click(screen.getByRole('button', { name: copy.adjustForm.submit(true, '$0') }))

    const alerts = await screen.findAllByRole('alert')
    expect(alerts.map((a) => a.textContent)).toEqual([copy.adjustForm.amountNeeded, copy.adjustForm.noteNeeded])
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('says so when an adjustment in the member\'s favour exceeds what is owed', async () => {
    stubApi({ adjustment: { status: 409, body: { detail: 'the adjustment exceeds what the period owes' } } })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.adjust }))
    await userEvent.type(screen.getByLabelText(copy.adjustForm.amount), '50000')
    await userEvent.type(screen.getByLabelText(copy.adjustForm.note), 'beca')
    await userEvent.click(screen.getByRole('button', { name: copy.adjustForm.submit(true, '$50.000') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.adjustForm.refused.exceeds)
  })

  it('refunds part of a validated payment', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.refund }))
    const form = screen.getByRole('form', { name: copy.refundForm.title })
    // Only the validated payment, not the claim waiting for review.
    expect(within(form).getAllByRole('option', { name: /^Pago/ }).map((o) => o.textContent)).toEqual([
      copy.refundForm.paymentOption('septiembre', '2 oct', '$45.000'),
    ])
    const amount = within(form).getByLabelText(copy.refundForm.amount)
    expect(amount).toHaveValue('45000')
    expect(within(form).getByLabelText(copy.refundForm.method)).toHaveValue('transfer')
    await userEvent.clear(amount)
    await userEvent.type(amount, '15000')
    await userEvent.type(within(form).getByLabelText(copy.refundForm.note), 'se lesionó')
    await userEvent.click(within(form).getByRole('button', { name: copy.refundForm.submit('$15.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.refundForm.done('$15.000') + copy.form.remainder('$45.000'),
    )
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/refunds',
        body: { payment_id: 'pay-sep', amount_clp: 15000, method: 'transfer', note: 'se lesionó' },
      },
    ])
  })

  it('says so when the payment has less left to give back', async () => {
    stubApi({ refund: { status: 409, body: { detail: 'a refund exceeds what is left of its payment' } } })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.refund }))
    await userEvent.click(screen.getByRole('button', { name: copy.refundForm.submit('$45.000') }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refundForm.refused.exceeds)
  })

  it('offers a payment for refund long after it left the timeline', async () => {
    stubApi({ ledger: { ...LEDGER, entries: [] } })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.refund }))
    expect(screen.getByLabelText(copy.refundForm.payment)).toHaveTextContent(
      copy.refundForm.paymentOption('septiembre', '2 oct', '$45.000'),
    )
  })

  it('offers no refund while no payment has anything left to give back', async () => {
    stubApi({ ledger: { ...LEDGER, refundable_payments: [] } })
    renderAt(PATH)
    const card = await money()

    await within(card).findByRole('button', { name: copy.record })
    expect(within(card).queryByRole('button', { name: copy.refund })).not.toBeInTheDocument()
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
    expect(calls.some((c) => c.path.startsWith('/api/reminders'))).toBe(false)
  })

  it('has the WhatsApp reminder in the header when they owe, and logs it as it opens', async () => {
    const calls = stubApi({
      reminders: [
        {
          billing_period_id: 'p-oct',
          person_id: 'felipe',
          person_name: 'Felipe Díaz',
          kind: 'payment_overdue',
          rejection_note: null,
          contact_name: 'Felipe Díaz',
          whatsapp_url: 'https://wa.me/56912345678?text=Hola',
          reminders_sent: 1,
          reminded_at: '2026-11-01T12:00:00Z',
          reminder_due: true,
        },
      ],
    })
    renderAt(PATH)

    const header = (await screen.findByRole('heading', { level: 1, name: 'Felipe Díaz' })).closest('header')!
    const link = await within(header).findByRole('link', {
      name: es.admin.reminders.write('Felipe Díaz', '2.º'),
    })
    expect(link).toHaveAttribute('href', 'https://wa.me/56912345678?text=Hola')
    expect(link).toHaveTextContent(es.admin.reminders.next('2.º'))
    // The reminder takes the plain chat's place: one WhatsApp button, never two (#179).
    expect(within(header).queryByRole('link', { name: copy.whatsapp('Felipe Díaz') })).not.toBeInTheDocument()

    await userEvent.click(link)

    await vi.waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/reminders/p-oct']),
    )
  })

  it('has no reminder in the header when nothing is due', async () => {
    stubApi()
    renderAt(PATH)

    await money()
    expect(screen.queryByRole('link', { name: /Recordar por WhatsApp/ })).not.toBeInTheDocument()
  })

  it('freezes the membership until the day chosen, with a reason', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()
    const until = isoDay(new Date(Date.now() + 15 * 86_400_000).toISOString())

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    const form = screen.getByRole('form', { name: copy.freezeForm.title })
    fireEvent.change(within(form).getByLabelText(copy.freezeForm.until), { target: { value: until } })
    await userEvent.type(within(form).getByLabelText(copy.freezeForm.reason), '  Lesión de rodilla ')
    await userEvent.click(within(form).getByRole('button', { name: copy.freezeForm.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.freezeForm.done(shortDay(until)))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/memberships/m-felipe/freeze', body: { to_date: until, reason: 'Lesión de rodilla' } },
    ])
    // Read again, the header says it is frozen, and it can be edited or ended instead.
    expect(await within(card).findByText(copy.frozenUntil(shortDay(until)))).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.freeze })).not.toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.editFreeze })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.endFreeze })).toBeInTheDocument()
  })

  it('books a freeze to start on a later day', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()
    const from = isoDay(new Date(Date.now() + 5 * 86_400_000).toISOString())
    const until = isoDay(new Date(Date.now() + 15 * 86_400_000).toISOString())

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    const form = screen.getByRole('form', { name: copy.freezeForm.title })
    fireEvent.change(within(form).getByLabelText(copy.freezeForm.from), { target: { value: from } })
    fireEvent.change(within(form).getByLabelText(copy.freezeForm.until), { target: { value: until } })
    await userEvent.type(within(form).getByLabelText(copy.freezeForm.reason), 'Viaje')
    await userEvent.click(within(form).getByRole('button', { name: copy.freezeForm.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.freezeForm.booked(shortDay(from), shortDay(until)))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/memberships/m-felipe/freeze',
        body: { from_date: from, to_date: until, reason: 'Viaje' },
      },
    ])
    // Not frozen until then: the freeze booked is a line under the plan, and it can be called off.
    expect(await within(card).findByText(copy.freezeBooked(shortDay(from), shortDay(until)))).toBeInTheDocument()
    expect(within(card).queryByText(copy.frozenUntil(shortDay(until)))).not.toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.callOffFreeze })).toBeInTheDocument()
  })

  it.each([
    // 22:30 in Santiago is 01:30 the next day in UTC: still the 10th at the gym.
    ['America/Santiago', '2026-11-10', '2026-11-11'],
    // The same instant is the 11th in Tokyo, whatever zone this device is in.
    ['Asia/Tokyo', '2026-11-11', '2026-11-12'],
  ])('starts a freeze on the gym\'s today in %s', async (timeZone, today, tomorrow) => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-11T01:30:00Z') })
    const calls = stubApi({ timeZone })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    const from = screen.getByLabelText(copy.freezeForm.from)
    await waitFor(() => expect(from).toHaveValue(today))
    expect(from).toHaveAttribute('min', today)
    expect(screen.getByLabelText(copy.freezeForm.until)).toHaveAttribute('min', tomorrow)
    fireEvent.change(screen.getByLabelText(copy.freezeForm.until), { target: { value: '2026-11-20' } })
    await userEvent.type(screen.getByLabelText(copy.freezeForm.reason), 'Viaje')
    await userEvent.click(screen.getByRole('button', { name: copy.freezeForm.submit }))

    // From the gym's today, which the server takes when no day is sent.
    await screen.findByRole('status')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ to_date: '2026-11-20', reason: 'Viaje' })
  })

  it('offers an end from the day after the freeze starts', async () => {
    stubApi()
    renderAt(PATH)
    const card = await money()
    const from = isoDay(new Date(Date.now() + 5 * 86_400_000).toISOString())
    const next = isoDay(new Date(Date.now() + 6 * 86_400_000).toISOString())

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    // Today in the gym's timezone, not the test runner's.
    expect(screen.getByLabelText(copy.freezeForm.from)).toHaveValue(isoDay(new Date().toISOString(), 'America/Santiago'))
    fireEvent.change(screen.getByLabelText(copy.freezeForm.from), { target: { value: from } })

    expect(screen.getByLabelText(copy.freezeForm.until)).toHaveAttribute('min', next)
  })

  it('edits a running freeze: a new end and reason', async () => {
    const calls = stubApi({ memberships: [FROZEN] })
    renderAt(PATH)
    const card = await money()
    const until = isoDay(new Date(Date.now() + 30 * 86_400_000).toISOString())

    await userEvent.click(await within(card).findByRole('button', { name: copy.editFreeze }))
    const form = screen.getByRole('form', { name: copy.editFreezeForm.title })
    expect(within(form).getByLabelText(copy.editFreezeForm.reason)).toHaveValue('Viaje')
    fireEvent.change(within(form).getByLabelText(copy.editFreezeForm.until), { target: { value: until } })
    await userEvent.clear(within(form).getByLabelText(copy.editFreezeForm.reason))
    await userEvent.type(within(form).getByLabelText(copy.editFreezeForm.reason), 'Lesión ')
    await userEvent.click(within(form).getByRole('button', { name: copy.editFreezeForm.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.editFreezeForm.done(shortDay(until)))
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/memberships/m-felipe/freeze', body: { to_date: until, reason: 'Lesión' } },
    ])
    expect(await within(card).findByText(copy.frozenUntil(shortDay(until)))).toBeInTheDocument()
  })

  it('ends a running freeze today, once confirmed', async () => {
    const calls = stubApi({ memberships: [FROZEN] })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.endFreeze }))
    const form = screen.getByRole('form', { name: copy.endFreezeForm.title })
    expect(form).toHaveTextContent(copy.endFreezeForm.endHint)
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
    await userEvent.click(within(form).getByRole('button', { name: copy.endFreezeForm.end }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.endFreezeForm.ended)
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/memberships/m-felipe/freeze/end', body: undefined },
    ])
    expect(await within(card).findByRole('button', { name: copy.freeze })).toBeEnabled()
  })

  it('calls off a booked freeze', async () => {
    const booked: Membership = {
      ...MONTHLY,
      freeze: { ...FROZEN.freeze!, from_date: '2026-12-01', to_date: '2026-12-15', started: false },
    }
    const calls = stubApi({ memberships: [booked] })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.callOffFreeze }))
    const form = screen.getByRole('form', { name: copy.endFreezeForm.title })
    expect(form).toHaveTextContent(copy.endFreezeForm.callOffHint('1 dic', '15 dic'))
    await userEvent.click(within(form).getByRole('button', { name: copy.endFreezeForm.callOff }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.endFreezeForm.calledOff)
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/memberships/m-felipe/freeze/end'])
  })

  it('asks for the day it ends and a reason before freezing', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    await userEvent.click(screen.getByRole('button', { name: copy.freezeForm.submit }))

    const alerts = await screen.findAllByRole('alert')
    expect(alerts.map((a) => a.textContent)).toEqual([copy.freezeForm.untilNeeded, copy.freezeForm.reasonNeeded])
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('says so when the membership can no longer be frozen', async () => {
    stubApi({ freeze: { status: 409, body: { detail: 'membership: lapsed → frozen' } } })
    renderAt(PATH)
    const card = await money()
    const until = isoDay(new Date(Date.now() + 15 * 86_400_000).toISOString())

    await userEvent.click(await within(card).findByRole('button', { name: copy.freeze }))
    fireEvent.change(screen.getByLabelText(copy.freezeForm.until), { target: { value: until } })
    await userEvent.type(screen.getByLabelText(copy.freezeForm.reason), 'Viaje')
    await userEvent.click(screen.getByRole('button', { name: copy.freezeForm.submit }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.freezeForm.refused.notActive)
  })

  it('shows a frozen membership in the header, to a coach as well', async () => {
    stubApi({ role: 'coach', memberships: [FROZEN] })
    renderAt(PATH)

    const card = await money()
    expect(within(card).getByText(copy.frozenUntil('24 nov'))).toBeInTheDocument()
    expect(within(card).queryByText(copy.overdue(9))).not.toBeInTheDocument()
  })

  it('lists freezes in the ledger as lines with no amount', async () => {
    const line = { freeze_id: 'f1', from_date: '2026-10-10', to_date: '2026-10-24', reason: 'Viaje' }
    stubApi({
      ledger: {
        ...LEDGER,
        entries: LEDGER.entries.slice(0, 2),
        freezes: [
          { ...line, edge: 'end', day: '2026-10-24' },
          { ...line, edge: 'start', day: '2026-10-10' },
        ],
      },
    })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    expect(within(ledger).getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      `${copy.ledger.freezeEnd}Viaje · 24 oct${es.common.noAmount}`,
      'Cargo octubregenerado 23 oct · sin pago$45.000',
      `${copy.ledger.freezeStart}Viaje · vuelve el 24 oct · 10 oct${es.common.noAmount}`,
      'Pago septiembretransferencia · validó Martín · 2 oct$45.000',
    ])
  })

  it('shows the last four ledger lines, and the rest in place', async () => {
    const more = [1, 2, 3].map((n) =>
      entry({ id: `old-${n}`, kind: 'charge', period_start: '2026-0' + (n + 5) + '-30', created_at: '2026-0' + (n + 5) + '-23T12:00:00Z' }),
    )
    stubApi({ ledger: { ...LEDGER, entries: [...LEDGER.entries, ...more] } })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    expect(within(ledger).getAllByRole('listitem')).toHaveLength(4)
    await userEvent.click(within(ledger).getByRole('button', { name: copy.ledger.all(7) }))
    expect(within(ledger).getAllByRole('listitem')).toHaveLength(7)
    await userEvent.click(within(ledger).getByRole('button', { name: copy.ledger.fewer }))
    expect(within(ledger).getAllByRole('listitem')).toHaveLength(4)
  })

  it('has no "Ver todo el libro" while the ledger is four lines or fewer', async () => {
    stubApi()
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    expect(within(ledger).getAllByRole('listitem')).toHaveLength(4)
    expect(within(ledger).queryByRole('button')).not.toBeInTheDocument()
  })

  it('has a WhatsApp button to the member in the header', async () => {
    stubApi()
    renderAt(PATH)

    const link = await screen.findByRole('link', { name: copy.whatsapp('Felipe Díaz') })
    expect(link).toHaveAttribute('href', 'https://wa.me/56912344417')
  })

  it("writes to a dependent's guardian on WhatsApp", async () => {
    stubApi({
      person: { body: { ...FELIPE, phone: null } },
      extra: (path) => {
        if (path === '/api/people/felipe/family') return { body: { guardian: { id: 'ana', name: 'Ana Díaz' }, dependents: [] } }
        if (path === '/api/people/ana') return { body: { ...FELIPE, id: 'ana', name: 'Ana Díaz', phone: '+56987654321' } }
        return undefined
      },
    })
    renderAt(PATH)

    const link = await screen.findByRole('link', { name: copy.whatsappGuardian('Ana Díaz') })
    expect(link).toHaveAttribute('href', 'https://wa.me/56987654321')
  })

  it('has no WhatsApp button without a phone, or with "No tiene WhatsApp"', async () => {
    stubApi({ person: { body: { ...FELIPE, no_whatsapp: true } } })
    renderAt(PATH)

    await screen.findByRole('region', { name: es.admin.family.toggle })
    await screen.findByText('Tomás Díaz')
    expect(screen.queryByRole('link', { name: copy.whatsapp('Felipe Díaz') })).not.toBeInTheDocument()
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
  it('shows the classes in 30 days and in all', async () => {
    stubApi()
    renderAt(PATH)

    const card = await screen.findByRole('region', { name: copy.attendance.title })
    expect(within(card).getByText('9')).toBeInTheDocument()
    expect(within(card).getByText(copy.attendance.detail(9, 184))).toBeInTheDocument()
  })

  it("shows the member's time on the mat", async () => {
    stubApi()
    renderAt(PATH)

    const card = await screen.findByRole('region', { name: es.matTime.theirs, busy: false })
    expect(within(card).getByRole('list', { name: es.matTime.byKind })).toHaveTextContent('Sparring1 h 30 min')
    expect(within(card).getByText(es.matTime.openMat(1, '30 min'))).toBeInTheDocument()
  })

  it('says so when the time on the mat cannot be read', async () => {
    stubApi({ time: { status: 403, body: {} } })
    renderAt(PATH)

    expect(await screen.findByText(es.matTime.error)).toBeInTheDocument()
  })

  it('says no classes since the last promotion only once there is a rank', async () => {
    stubApi({ grading: { current: null, events: [] }, attendance: { body: { last_30_days: 0, total: 0, since_promotion: null } } })
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    expect(within(graduation).getByText(copy.grading.none)).toBeInTheDocument()
    expect(within(graduation).queryByText(/desde la última graduación/)).not.toBeInTheDocument()
  })

  it('says so when the attendance cannot be read', async () => {
    stubApi({ attendance: { status: 403, body: {} } })
    renderAt(PATH)

    expect(await screen.findByText(copy.attendance.error)).toBeInTheDocument()
  })

  it('shows the rank since when, and the promotion log newest first', async () => {
    stubApi()
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    expect(within(graduation).getByText('Azul · 2 grados', { selector: '.member__rank-label' })).toBeInTheDocument()
    expect(within(graduation).getByText(copy.grading.since('11 abr 2026'))).toBeInTheDocument()
    expect(within(graduation).getByText(copy.grading.sincePromotion(62))).toBeInTheDocument()
    const log = within(graduation).getByRole('list', { name: copy.grading.log })
    expect(within(log).getAllByRole('listitem').map((row) => row.textContent)).toEqual([
      'Azul · 2 grados11 abr 2026 · registró Sebastián Araya',
      'Azul · 1 grado2 ago 2025 · registró Sebastián Araya · Open de Santiago',
    ])
    // A scheme without colours: the label alone, and the log's dots.
    expect(within(graduation).queryByRole('img')).not.toBeInTheDocument()
  })

  it('draws the belt the scheme colours, on the ficha and in the log', async () => {
    const belt = (stripes: number) => ({ colors: ['#1f4fa3'], stripes, max_stripes: 4 })
    stubApi({
      grading: {
        current: { ...GRADING.current!, belt: belt(2) },
        events: GRADING.events.map((e) => ({ ...e, belt: belt(Number(e.sub_rank)) })),
      },
    })
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    const [ficha, ...log] = await within(graduation).findAllByRole('img')
    expect(ficha).not.toHaveClass('belt--compact')
    expect(ficha).toHaveAccessibleName('Azul, 2 grados')
    expect(log.map((b) => [b.getAttribute('aria-label'), b.classList.contains('belt--compact')])).toEqual([
      ['Azul, 2 grados', true],
      ['Azul, 1 grado', true],
    ])
    // The rank still says itself in words beside the drawing.
    expect(within(graduation).getByText('Azul · 2 grados', { selector: '.member__rank-label' })).toBeInTheDocument()
  })

  it("shows the progress towards the next promotion against the rank's target", async () => {
    const targeted = { ...stripes[2]!, target: 80 }
    const blue = { ...SCHEME.ranks[1]!, sub_ranks: stripes.map((s) => (s.key === '2' ? targeted : s)) }
    stubApi({ scheme: { ...SCHEME, ranks: [SCHEME.ranks[0]!, blue, SCHEME.ranks[2]!] } })
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    const text = copy.grading.goal(62, 80, 'classes_since_promotion', 'Azul · 3 grados')
    expect(text).toBe('62 / 80 clases para Azul · 3 grados')
    expect(await within(graduation).findByText(text)).toBeInTheDocument()
    const bar = within(graduation).getByRole('progressbar', { name: copy.grading.goalLabel })
    expect(bar).toHaveAttribute('aria-valuenow', '62')
    expect(bar).toHaveAttribute('aria-valuemax', '80')
  })

  it('counts months in rank when that is the goal metric', async () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 10, 9, 12) })
    const blue = { ...SCHEME.ranks[1]!, target: 12 }
    stubApi({ scheme: { ...SCHEME, ranks: [SCHEME.ranks[0]!, blue, SCHEME.ranks[2]!], goal_metric: 'time_in_rank' } })
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    // Awarded 11 abr 2026: six whole months by 9 nov.
    expect(await within(graduation).findByText(copy.grading.goal(6, 12, 'time_in_rank', 'Azul · 3 grados'))).toBeInTheDocument()
  })

  it('shows no progress when the rank has no target', async () => {
    stubApi()
    renderAt(PATH)

    const graduation = await screen.findByRole('region', { name: copy.grading.title })
    await within(graduation).findByText(copy.grading.sincePromotion(62))
    expect(within(graduation).queryByRole('progressbar')).not.toBeInTheDocument()
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
    expect(screen.queryByRole('button', { name: copy.grading.award })).not.toBeInTheDocument()
    expect(document.querySelector('.belt')).toBeNull()
  })
})

const field = (fields: Partial<PersonField> & Pick<PersonField, 'key' | 'label'>): PersonField => ({
  type: 'text',
  options: null,
  sensitive: false,
  value: null,
  ...fields,
})

const FIELDS: PersonField[] = [
  field({ key: 'contacto', label: 'Contacto de emergencia', value: 'Ana Díaz +56 9 8765 4321' }),
  field({ key: 'categoria', label: 'Categoría competencia', type: 'enum', options: ['Gallo', 'Pluma'], value: 'Pluma' }),
  field({ key: 'peso', label: 'Peso (kg)', type: 'number', value: 72.5 }),
  field({ key: 'ingreso', label: 'Fecha de ingreso', type: 'date', value: null }),
  field({ key: 'salud', label: 'Notas médicas', sensitive: true, value: 'Asma' }),
]

describe('Ficha de alumno: datos', () => {
  const fields = () => screen.findByRole('region', { name: copy.fields.title })

  it('shows the fields the API answers, sensitive ones marked', async () => {
    stubApi({ fields: FIELDS })
    renderAt(PATH)

    const section = await fields()
    await within(section).findByText('Contacto de emergencia')
    const rows = within(section).getAllByRole('term').map((term) => [term.textContent, term.nextSibling?.textContent])
    expect(rows).toEqual([
      [copy.fields.phone, '+56 9 1234 4417'],
      [copy.fields.email, copy.fields.empty],
      [copy.fields.rut, copy.fields.empty],
      [copy.fields.dob, copy.fields.empty],
      ['Contacto de emergencia', 'Ana Díaz +56 9 8765 4321'],
      ['Categoría competencia', 'Pluma'],
      ['Peso (kg)', '72,5'],
      ['Fecha de ingreso', copy.fields.empty],
      [`Notas médicas${copy.fields.sensitive}`, 'Asma'],
    ])
  })

  it('shows only the record when no field is open to the role', async () => {
    stubApi({ role: 'coach', fields: [] })
    renderAt(PATH)

    const section = await fields()
    await waitFor(() => expect(within(section).getByRole('button', { name: copy.editPerson })).toBeEnabled())
    expect(within(section).getAllByRole('term').map((term) => term.textContent)).toEqual([
      copy.fields.phone,
      copy.fields.email,
      copy.fields.rut,
      copy.fields.dob,
    ])
  })

  it('has "Editar datos" once on the ficha', async () => {
    stubApi({ fields: FIELDS })
    renderAt(PATH)

    await within(await fields()).findByText('Contacto de emergencia')
    expect(screen.getAllByRole('button', { name: copy.editPerson })).toHaveLength(1)
  })

  it('saves the record and the fields from the one form', async () => {
    const calls = stubApi({
      fields: FIELDS,
      extra: (path, method, body) =>
        path === '/api/people/felipe' && method === 'PATCH' ? { body: { ...FELIPE, ...(body as object) } } : undefined,
    })
    renderAt(PATH)

    const section = await fields()
    await within(section).findByText('Contacto de emergencia')
    await userEvent.click(within(section).getByRole('button', { name: copy.editPerson }))
    const form = screen.getByRole('form', { name: copy.editForm.title })
    await userEvent.type(within(form).getByLabelText(copy.editForm.email), 'felipe@example.cl')
    await userEvent.clear(within(form).getByLabelText('Peso (kg)'))
    await userEvent.type(within(form).getByLabelText('Peso (kg)'), '74')
    await userEvent.click(within(form).getByRole('button', { name: copy.editForm.save }))

    expect(await screen.findByText(copy.fields.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/people/felipe', body: { email: 'felipe@example.cl' } },
      { method: 'PATCH', path: '/api/people/felipe/fields', body: { values: { peso: 74 } } },
    ])
  })

  it('saves only the fields that changed', async () => {
    const calls = stubApi({ fields: FIELDS })
    renderAt(PATH)

    const opened = await fields()
    await within(opened).findByText('Contacto de emergencia')
    await userEvent.click(within(opened).getByRole('button', { name: copy.fields.edit }))
    const form = screen.getByRole('form', { name: copy.fields.formTitle })
    expect(within(form).getByLabelText('Peso (kg)')).toHaveValue('72.5')
    await userEvent.clear(within(form).getByLabelText('Peso (kg)'))
    await userEvent.type(within(form).getByLabelText('Peso (kg)'), '74,2')
    await userEvent.selectOptions(within(form).getByLabelText('Categoría competencia'), '')
    await userEvent.type(within(form).getByLabelText('Fecha de ingreso'), '2026-03-01')
    await userEvent.click(within(form).getByRole('button', { name: copy.fields.save }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.fields.saved)
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/people/felipe/fields',
        body: { values: { categoria: null, peso: 74.2, ingreso: '2026-03-01' } },
      },
    ])
    const section = await fields()
    expect(within(section).getByText('74,2')).toBeInTheDocument()
    expect(within(section).getByText('01-03-2026')).toBeInTheDocument()
  })

  it('marks the fields the API refused', async () => {
    const refused = { status: 422, body: { detail: { fields: { peso: 'must be a number' } } } }
    const calls = stubApi({ fields: FIELDS, fieldsUpdate: refused })
    renderAt(PATH)

    const opened = await fields()
    await within(opened).findByText('Contacto de emergencia')
    await userEvent.click(within(opened).getByRole('button', { name: copy.fields.edit }))
    const form = screen.getByRole('form', { name: copy.fields.formTitle })
    await userEvent.clear(within(form).getByLabelText('Peso (kg)'))
    await userEvent.type(within(form).getByLabelText('Peso (kg)'), 'setenta')
    await userEvent.click(within(form).getByRole('button', { name: copy.fields.save }))

    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.fields.refused.invalid)
    expect(within(form).getByLabelText('Peso (kg)')).toHaveAttribute('aria-invalid', 'true')
    expect(within(form).getByLabelText('Contacto de emergencia')).toHaveAttribute('aria-invalid', 'false')
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ values: { peso: 'setenta' } }])
  })
})

describe('the record and the ways out (#157)', () => {
  const actions = () => screen.findByRole('region', { name: copy.exitLabel })
  // "Editar datos", in Datos, once its custom fields are read.
  const edit = async () => {
    const section = await screen.findByRole('region', { name: copy.fields.title })
    const button = within(section).getByRole('button', { name: copy.editPerson })
    await waitFor(() => expect(button).toBeEnabled())
    return button
  }

  it('shows a coach "Editar datos" and neither "Dar de baja" nor "Eliminar"', async () => {
    stubApi({ role: 'coach' })
    renderAt(PATH)

    expect(await edit()).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.exitLabel })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.leave })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.remove })).not.toBeInTheDocument()
  })

  it('gives an admin "Dar de baja" but not "Eliminar"', async () => {
    stubApi({ role: 'admin' })
    renderAt(PATH)

    const section = await actions()
    expect(within(section).getByRole('button', { name: copy.leave })).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: copy.remove })).not.toBeInTheDocument()
  })

  it('draws "Dar de baja" and "Eliminar" as destructive, apart from "Editar datos"', async () => {
    stubApi()
    renderAt(PATH)

    const section = await actions()
    expect(within(section).getByRole('button', { name: copy.leave })).toHaveClass('button--danger')
    expect(within(section).getByRole('button', { name: copy.remove })).toHaveClass('button--danger')
    expect(within(section).queryByRole('button', { name: copy.editPerson })).not.toBeInTheDocument()
  })

  it('edits the record through PATCH, sending only what changed', async () => {
    const calls = stubApi({
      extra: (path, method, body) =>
        path === '/api/people/felipe' && method === 'PATCH' ? { body: { ...FELIPE, ...(body as object) } } : undefined,
    })
    renderAt(PATH)

    await userEvent.click(await edit())
    const form = screen.getByRole('form', { name: copy.editForm.title })
    // The phone is a contact, edited like the rest (#165).
    const phone = within(form).getByLabelText(copy.editForm.phone)
    await userEvent.clear(phone)
    await userEvent.type(phone, '9 1111 2222')
    await userEvent.type(within(form).getByLabelText(copy.editForm.rut), '7.654.321-6')
    await userEvent.click(within(form).getByRole('button', { name: copy.editForm.save }))

    expect(await screen.findByText(copy.editForm.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/people/felipe', body: { phone: '9 1111 2222', rut: '7.654.321-6' } },
    ])
  })

  it('clears the phone only with "No tiene WhatsApp", and says so when the API refuses', async () => {
    const calls = stubApi({
      extra: (path, method, body) =>
        path === '/api/people/felipe' && method === 'PATCH'
          ? (body as { no_whatsapp?: boolean }).no_whatsapp
            ? { body: { ...FELIPE, ...(body as object) } }
            : { status: 422, body: { detail: 'a phone is required unless no_whatsapp is set' } }
          : undefined,
    })
    renderAt(PATH)

    await userEvent.click(await edit())
    const form = screen.getByRole('form', { name: copy.editForm.title })
    await userEvent.clear(within(form).getByLabelText(copy.editForm.phone))
    await userEvent.click(within(form).getByRole('button', { name: copy.editForm.save }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.editForm.refused.phone)

    await userEvent.click(within(form).getByRole('checkbox', { name: copy.editForm.noWhatsapp }))
    await userEvent.click(within(form).getByRole('button', { name: copy.editForm.save }))
    expect(await screen.findByText(copy.editForm.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { phone: null },
      { phone: null, no_whatsapp: true },
    ])
  })

  it('says whose RUT it already is, with a link to them', async () => {
    stubApi({
      extra: (path, method) =>
        path === '/api/people/felipe' && method === 'PATCH'
          ? { status: 409, body: { detail: { code: 'rut_in_gym', person_id: 'camila' } } }
          : undefined,
    })
    renderAt(PATH)

    await userEvent.click(await edit())
    const form = screen.getByRole('form', { name: copy.editForm.title })
    await userEvent.type(within(form).getByLabelText(copy.editForm.rut), '7.654.321-6')
    await userEvent.click(within(form).getByRole('button', { name: copy.editForm.save }))

    const alert = await within(form).findByRole('alert')
    expect(alert).toHaveTextContent(copy.editForm.refused.rut_in_gym)
    expect(within(alert).getByRole('link', { name: copy.editForm.refused.open })).toHaveAttribute(
      'href',
      '/admin/alumnos/camila',
    )
  })

  it('dar de baja from today leaves the day to the API, then says since when', async () => {
    let left: string | null = null
    const calls = stubApi({
      extra: (path, method) => {
        if (path === '/api/people/felipe/leave' && method === 'POST') {
          left = '2026-11-10'
          return { body: { ...FELIPE, left_on: left } }
        }
        if (path === '/api/people/felipe' && method === 'GET') return { body: { ...FELIPE, left_on: left } }
        return undefined
      },
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.leave }))
    const form = screen.getByRole('form', { name: copy.leaveForm.title })
    await userEvent.click(within(form).getByRole('button', { name: copy.leaveForm.submit }))

    expect(await screen.findByText(copy.leftBanner('10-11-2026'))).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/people/felipe/leave')).toEqual([
      { method: 'POST', path: '/api/people/felipe/leave', body: {} },
    ])
    expect(within(await actions()).getByRole('button', { name: copy.reactivate })).toBeInTheDocument()
  })

  it('reactivar can start them on a plan again', async () => {
    const calls = stubApi({
      extra: (path, method) => {
        if (path === '/api/plans') return { body: [{ id: 'plan-adults', name: 'Mensual adultos', kind: 'monthly', active: true }] }
        if (path === '/api/people/felipe/return' && method === 'POST') return { body: FELIPE }
        if (path === '/api/people/felipe' && method === 'GET') return { body: { ...FELIPE, left_on: '2026-10-01' } }
        return undefined
      },
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.reactivate }))
    const form = screen.getByRole('form', { name: copy.returnForm.title })
    await userEvent.selectOptions(await within(form).findByLabelText(copy.returnForm.plan), 'plan-adults')
    await userEvent.click(within(form).getByRole('button', { name: copy.returnForm.submit }))

    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/people/felipe/return')).toEqual([
        { method: 'POST', path: '/api/people/felipe/return', body: { membership: { plan_id: 'plan-adults' } } },
      ]),
    )
  })

  it('eliminar explains a ledger keeps them, and offers dar de baja', async () => {
    stubApi({
      extra: (path) => (path === '/api/people/felipe/deletion' ? { body: { refused: 'ledger' } } : undefined),
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.remove }))
    expect(await screen.findByText(copy.removeForm.refused.ledger)).toBeInTheDocument()
    const section = await actions()
    const offered = within(section).getAllByRole('button', { name: copy.leave })
    await userEvent.click(offered.at(-1)!)
    expect(screen.getByRole('form', { name: copy.leaveForm.title })).toBeInTheDocument()
  })

  it('eliminar needs their name typed, then deletes and goes back to the list', async () => {
    const calls = stubApi({
      extra: (path, method) => {
        if (path === '/api/people/felipe/deletion') return { body: { refused: null } }
        if (path === '/api/people/felipe' && method === 'DELETE') return { status: 204 }
        if (path === '/api/people') return { body: { items: [], total: 0 } }
        return undefined
      },
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.remove }))
    const form = await screen.findByRole('form', { name: copy.removeForm.title })
    const submit = within(form).getByRole('button', { name: copy.removeForm.submit })
    expect(submit).toBeDisabled()
    await userEvent.type(within(form).getByLabelText(copy.removeForm.confirm(FELIPE.name)), 'felipe  díaz')
    await userEvent.click(submit)

    expect(await screen.findByRole('heading', { name: es.admin.students.title })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/people/felipe'])
  })
})
