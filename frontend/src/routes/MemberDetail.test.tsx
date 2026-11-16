import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FieldValue, PersonField } from '../api/customFields'
import type { GradeEvent, Grading, GradingScheme } from '../api/grading'
import type { HistoryPayment, HistoryPaymentIn, HistoryPayments } from '../api/history'
import type { Correction, Membership, MembershipLedger, OpenPeriod, Person, TimelineEntry } from '../api/member'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { isoDay, shortDay } from '../format'
import type { PersonTime } from '../api/matTime'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { monthsBetween, paidOn } from './PersonHistory'

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
  member_since: null,
  prior_classes: 0,
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
  next_plan: null,
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
    { id: 'p-oct', period_start: '2026-10-30', period_end: '2026-11-29', outstanding_clp: 45000, voided_clp: 0, void_id: null, charged_clp: 45000 },
    { id: 'p-sep', period_start: '2026-09-30', period_end: '2026-10-29', outstanding_clp: 0, voided_clp: 0, void_id: null, charged_clp: 45000 },
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
  paid_through: null,
  balance_clp: 45000,
}

const correction = (fields: Partial<Correction> & Pick<Correction, 'id'>): Correction => ({
  at: '2026-11-02T12:00:00Z',
  action: 'ledger_corrected',
  purpose: 'void',
  plan_void: false,
  reason: 'duplicado',
  actor_name: 'Ana',
  period_start: '2026-10-30',
  plan_name: 'Mensual adultos',
  before: { outstanding_clp: 45000, balance_clp: 90000 },
  after: { outstanding_clp: 0, balance_clp: 45000 },
  ...fields,
})

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
  ahead?: Answer
  aheadPayment?: Answer
  adjustment?: Answer
  refund?: Answer
  grading?: Grading
  scheme?: GradingScheme
  // Whether an activity of the gym grades (#245); by default one does.
  grades?: boolean
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
  // The person's corrections (#277); none by default.
  corrections?: Correction[]
  // Answers anything else first: the record's own actions (#157).
  extra?: (path: string, method: string, body: unknown) => Answer | undefined
}

function stubApi({
  role = 'owner',
  person,
  memberships = [MONTHLY],
  ledger = LEDGER,
  payment,
  ahead,
  aheadPayment,
  adjustment,
  refund,
  grading = GRADING,
  scheme = SCHEME,
  grades: graded = true,
  award,
  freeze,
  fields = [],
  fieldsUpdate,
  attendance = { body: { last_30_days: 9, total: 184, since_promotion: 62 } },
  time = { body: FELIPE_TIME },
  timeZone = 'America/Santiago',
  reminders = [],
  corrections = [],
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
    if (path === '/api/me/role') return { body: { role, uses_grades: graded } }
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
    if (path === '/api/ledger/people/felipe/corrections') return { body: { total: corrections.length, items: corrections } }
    if (path === '/api/people/felipe/history/payments' && method === 'GET') return { body: { plan_from: null, years: [] } }
    if (path === '/api/ledger/memberships/m-felipe/ahead') return ahead ?? { body: { periods: [] } }
    if (path === '/api/ledger/payments/ahead' && method === 'POST') {
      return aheadPayment ?? { status: 201, body: { paid_through: '2027-02-28' } }
    }
    if (path === '/api/reminders' && url.searchParams.get('person_id') === 'felipe') return { body: reminders }
    if (path.startsWith('/api/reminders/') && method === 'POST') return { status: 201, body: {} }
    if (path === '/api/gym/grading-scheme') return { body: scheme }
    if (path === '/api/people/felipe/attendance') return attendance
    if (path === '/api/people/felipe/time') return time
    if (path === '/api/people/felipe/tag-hours') {
      return { body: { first_day: '2026-11-01', last_day: '2026-11-30', tags: [], untagged_minutes: 0, no_duration_classes: 0, no_duration: [] } }
    }
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

function renderAt(path: string | string[]) {
  const queryClient = createQueryClient()
  const initialEntries = typeof path === 'string' ? [path] : path
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const PATH = '/admin/alumnos/felipe'
const money = () => screen.findByRole('region', { name: copy.paymentLabel })
const libro = () => screen.findByRole('region', { name: copy.ledger.title })

/** Opens the fixes of the Libro line whose button reads `line` (#279), named `title`. */
async function fixLine(line: RegExp, title: string) {
  const ledger = await libro()
  await userEvent.click(await within(ledger).findByRole('button', { name: line }))
  return within(ledger).getByRole('group', { name: title })
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Ficha de alumno', () => {
  it('shows the member, their plan and due day, and how late they are', async () => {
    stubApi()
    renderAt(PATH)

    expect(await screen.findByRole('heading', { name: 'Felipe Díaz' })).toBeInTheDocument()
    // A member since, said whole: the belt's own date is in Graduación (#213).
    expect(await screen.findByText('Azul · 2 grados · alumno desde mar 2024')).toBeInTheDocument()
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

  it('says a member dado de baja has no charge coming to record against (#213)', async () => {
    stubApi({
      person: { body: { ...FELIPE, left_on: '2026-10-01' } },
      memberships: [{ ...MONTHLY, status: 'cancelled' }],
      ledger: { ...LEDGER, open_periods: [], owed_clp: 0 },
    })
    renderAt(PATH)

    const card = await money()
    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    expect(within(card).getByText(copy.nothingToRecordLeft)).toBeInTheDocument()
    expect(within(card).queryByText(copy.nothingToRecord)).not.toBeInTheDocument()
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

  it('records a payment ahead for a member al día, for what the periods cost (#196)', async () => {
    const ahead = [
      { period_start: '2026-12-01', period_end: '2026-12-31', amount_due_clp: 45000 },
      { period_start: '2027-01-01', period_end: '2027-01-31', amount_due_clp: 45000 },
      { period_start: '2027-02-01', period_end: '2027-02-28', amount_due_clp: 40000 },
    ]
    const calls = stubApi({
      ledger: { ...LEDGER, open_periods: [], owed_clp: 0, paid_through: '2026-11-30' },
      ahead: { body: { periods: ahead } },
    })
    renderAt(PATH)
    const card = await money()
    expect(await within(card).findByText(copy.paidThrough('30 nov'))).toBeInTheDocument()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    const form = await screen.findByRole('form', { name: copy.form.title })
    const periods = within(form).getByLabelText(copy.form.ahead.periods)
    expect(within(periods).getAllByRole('option').map((o) => o.textContent)).toEqual([
      copy.form.ahead.option(1, true, '31 dic', '$45.000'),
      copy.form.ahead.option(2, true, '31 ene', '$90.000'),
      copy.form.ahead.option(3, true, '28 feb', '$130.000'),
    ])
    await userEvent.selectOptions(periods, '3')
    await userEvent.selectOptions(within(form).getByLabelText(copy.form.method), 'transfer')
    await userEvent.click(within(form).getByRole('button', { name: copy.form.submit('$130.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.form.ahead.recorded('$130.000', '28 feb'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/payments/ahead',
        body: { membership_id: 'm-felipe', periods: 3, amount_clp: 130000, method: 'transfer' },
      },
    ])
  })

  it.each(['cannot_pay_ahead', 'amount_changed', 'already_billed'] as const)(
    'says why paying ahead was refused: %s',
    async (code) => {
      stubApi({
        ledger: { ...LEDGER, open_periods: [], owed_clp: 0, paid_through: '2026-11-30' },
        ahead: { body: { periods: [{ period_start: '2026-12-01', period_end: '2026-12-31', amount_due_clp: 45000 }] } },
        aheadPayment: { status: 409, body: { detail: { code, message: 'refused' } } },
      })
      renderAt(PATH)
      const card = await money()

      await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
      const form = await screen.findByRole('form', { name: copy.form.title })
      await userEvent.click(within(form).getByRole('button', { name: copy.form.submit('$45.000') }))

      expect(await within(form).findByRole('alert')).toHaveTextContent(copy.form.ahead.refused[code])
    },
  )

  it('offers only what can be done: no refund, freeze or fix with nothing to do it on', async () => {
    stubApi({
      memberships: [{ ...MONTHLY, status: 'lapsed' }],
      ledger: { ...LEDGER, periods: [], refundable_payments: [] },
    })
    renderAt(PATH)
    const card = await money()

    expect(await within(card).findByRole('button', { name: copy.record })).toBeEnabled()
    expect(within(card).queryByRole('button', { name: copy.refund })).not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.freeze })).not.toBeInTheDocument()
    expect(within(card).queryAllByRole('button').filter((b) => b.hasAttribute('disabled'))).toEqual([])
    // No line has a fix: the charge's period is not one to correct, no payment has anything to give back.
    expect(within(await libro()).queryAllByRole('button')).toEqual([])
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

  it('keeps the fixes off the plan card: under the Libro lines and "Corregir plan" (#279)', async () => {
    stubApi()
    renderAt(PATH)
    const card = await money()

    expect(await within(card).findByRole('button', { name: copy.record })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.refund })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.freeze })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: copy.changePlan })).toBeInTheDocument()
    for (const gone of ['Ajuste', copy.fix.voidCharge, copy.fix.restoreCharge, copy.voidPlan]) {
      expect(within(card).queryByRole('button', { name: gone })).not.toBeInTheDocument()
    }
    // Only the lines with a fix are buttons: the charge owing and the payment with
    // something to give back, not the claim waiting for review nor the credit.
    const ledger = await libro()
    expect(within(ledger).getAllByRole('button').map((b) => b.getAttribute('aria-expanded'))).toEqual(['false', 'false'])
    expect(within(ledger).getByRole('button', { name: /^Cargo octubre/ })).toBeInTheDocument()
    expect(within(ledger).getByRole('button', { name: /^Pago septiembre/ })).toBeInTheDocument()
  })

  it('offers a charge that still owes "Cambiar monto" and "Anular cargo", opened under it (#279)', async () => {
    stubApi()
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    const chips = within(fixes).getAllByRole('button').filter((b) => b.hasAttribute('aria-pressed'))
    expect(chips.map((b) => b.textContent)).toEqual([
      copy.fix.changeAmount,
      copy.fix.voidCharge,
    ])
    expect(within(fixes).getByRole('button', { name: copy.fix.changeAmount })).toHaveAttribute('aria-pressed', 'true')
    expect(within(fixes).getByRole('form', { name: copy.amountForm.title })).toBeInTheDocument()
    await userEvent.click(within(fixes).getByRole('button', { name: copy.fix.voidCharge }))
    expect(within(fixes).getByRole('form', { name: copy.voidForm.title })).toBeInTheDocument()

    // One line open at a time, closed by its button.
    const ledger = await libro()
    await userEvent.click(within(ledger).getByRole('button', { name: /^Pago septiembre/ }))
    expect(within(ledger).queryByRole('group', { name: copy.fix.charge('octubre', null) })).not.toBeInTheDocument()
    expect(within(ledger).getByRole('group', { name: copy.fix.payment('septiembre') })).toBeInTheDocument()
    await userEvent.click(within(ledger).getByRole('button', { name: /^Pago septiembre/ }))
    expect(within(ledger).queryByRole('group')).not.toBeInTheDocument()
  })

  it('lowers a charge: the difference in the member\'s favour, with its reason (#279)', async () => {
    const calls = stubApi({
      adjustment: { status: 201, body: { period: { outstanding_clp: 40000, closed: false } } },
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))
    const form = within(fixes).getByRole('form', { name: copy.amountForm.title })

    expect(within(form).getByText(copy.amountForm.current('$45.000'))).toBeInTheDocument()
    const amount = within(form).getByLabelText(copy.amountForm.amount)
    expect(amount).toHaveValue('45000')
    await userEvent.clear(amount)
    await userEvent.type(amount, '40000')
    // What it does, as it is typed.
    expect(within(form).getByText(copy.fix.owed('octubre', '$45.000', '$40.000'))).toBeInTheDocument()
    expect(within(form).getByText(copy.fix.balance('$45.000', '$40.000'))).toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText(copy.amountForm.reason), ' descuento hermano ')
    await userEvent.click(within(form).getByRole('button', { name: copy.amountForm.submit('$40.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.amountForm.done('octubre', '$45.000', '$40.000') + copy.form.remainder('$40.000'),
    )
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/adjustments',
        body: { membership_id: 'm-felipe', billing_period_id: 'p-oct', amount_clp: 5000, note: 'descuento hermano' },
      },
    ])
  })

  it('raises a paid charge: the difference owed on top (#279)', async () => {
    const paid = { id: 'p-sep', period_start: '2026-09-30', period_end: '2026-10-29', outstanding_clp: 0, voided_clp: 0, void_id: null, charged_clp: 45000 }
    const calls = stubApi({
      ledger: {
        ...LEDGER,
        open_periods: [],
        owed_clp: 0,
        balance_clp: 0,
        entries: [entry({ id: 'c-sep', kind: 'charge', billing_period_id: 'p-sep', period_start: '2026-09-30' })],
        periods: [paid],
        refundable_payments: [],
      },
      adjustment: { status: 201, body: { period: { outstanding_clp: 5000, closed: false } } },
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo septiembre/, copy.fix.charge('septiembre', null))

    // Nothing owed, nothing to void: only its amount changes.
    expect(within(fixes).queryByRole('button', { name: copy.fix.voidCharge })).not.toBeInTheDocument()
    const amount = within(fixes).getByLabelText(copy.amountForm.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '50000')
    expect(within(fixes).getByText(copy.fix.owed('septiembre', '$0', '$5.000'))).toBeInTheDocument()
    expect(within(fixes).getByText(copy.fix.balance('$0', '$5.000'))).toBeInTheDocument()
    await userEvent.type(within(fixes).getByLabelText(copy.amountForm.reason), 'matrícula')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.amountForm.submit('$50.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      copy.amountForm.done('septiembre', '$45.000', '$50.000') + copy.form.remainder('$5.000'),
    )
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([
      { membership_id: 'm-felipe', billing_period_id: 'p-sep', amount_clp: -5000, note: 'matrícula' },
    ])
  })

  it('asks for a new amount and a reason before changing it', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    // The amount it already is.
    await userEvent.click(within(fixes).getByRole('button', { name: copy.amountForm.submit('$45.000') }))
    expect((await within(fixes).findAllByRole('alert')).map((a) => a.textContent)).toEqual([
      copy.amountForm.sameAmount,
      copy.amountForm.reasonNeeded,
    ])
    await userEvent.clear(within(fixes).getByLabelText(copy.amountForm.amount))
    expect(within(fixes).getAllByRole('alert').map((a) => a.textContent)).toEqual([
      copy.amountForm.amountNeeded,
      copy.amountForm.reasonNeeded,
    ])
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('refuses a charge lower than what came in already, saying to give it back first (#279)', async () => {
    const calls = stubApi({
      ledger: {
        ...LEDGER,
        balance_clp: 25000,
        periods: [{ ...LEDGER.periods[0]!, outstanding_clp: 25000 }, LEDGER.periods[1]!],
      },
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    const amount = within(fixes).getByLabelText(copy.amountForm.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '10000')
    expect(within(fixes).getByRole('alert')).toHaveTextContent(copy.amountForm.paidMore('$20.000'))
    // Nothing below zero is shown.
    expect(within(fixes).getByText(copy.fix.owed('octubre', '$25.000', '$0'))).toBeInTheDocument()
    await userEvent.type(within(fixes).getByLabelText(copy.amountForm.reason), 'beca')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.amountForm.submit('$10.000') }))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('says so when the API refuses the change as more than is owed', async () => {
    stubApi({ adjustment: { status: 409, body: { detail: 'the adjustment exceeds what the period owes' } } })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    const amount = within(fixes).getByLabelText(copy.amountForm.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '0')
    await userEvent.type(within(fixes).getByLabelText(copy.amountForm.reason), 'beca')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.amountForm.submit('$0') }))

    expect(await within(fixes).findByRole('alert')).toHaveTextContent(copy.amountForm.refused.exceeds)
  })

  it('voids a charge made by mistake from its line, with its reason (#256)', async () => {
    const calls = stubApi({
      extra: (path, method) =>
        path === '/api/ledger/voids' && method === 'POST'
          ? { status: 201, body: { period: { outstanding_clp: 0, closed: true } } }
          : undefined,
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    await userEvent.click(within(fixes).getByRole('button', { name: copy.fix.voidCharge }))
    const form = within(fixes).getByRole('form', { name: copy.voidForm.title })
    expect(within(form).getByText(copy.fix.owed('octubre', '$45.000', '$0'))).toBeInTheDocument()
    expect(within(form).getByText(copy.fix.balance('$45.000', '$0'))).toBeInTheDocument()
    await userEvent.click(within(form).getByRole('button', { name: copy.voidForm.submit('$45.000') }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.voidForm.reasonNeeded)
    await userEvent.type(within(form).getByLabelText(copy.voidForm.reason), ' alumno de prueba ')
    await userEvent.click(within(form).getByRole('button', { name: copy.voidForm.submit('$45.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.voidForm.done('octubre', '$45.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/voids',
        body: { membership_id: 'm-felipe', billing_period_id: 'p-oct', reason: 'alumno de prueba' },
      },
    ])
  })

  it('says to refund a payment first when a void is refused for it (#256)', async () => {
    stubApi({
      extra: (path, method) =>
        path === '/api/ledger/voids' && method === 'POST'
          ? { status: 409, body: { detail: { code: 'paid', message: 'x', amount_clp: 20000 } } }
          : undefined,
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    await userEvent.click(within(fixes).getByRole('button', { name: copy.fix.voidCharge }))
    await userEvent.type(within(fixes).getByLabelText(copy.voidForm.reason), 'error')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.voidForm.submit('$45.000') }))

    expect(await within(fixes).findByRole('alert')).toHaveTextContent(copy.voidRefused.paid('$20.000'))
  })

  // Staging (#271): a lapsed plan and the one assigned after it, started the same day.
  const LAPSED: Membership = { ...MONTHLY, id: 'm-old', plan_name: 'Mensual antiguo', status: 'lapsed' }
  const NOVEMBER = { ...OCTOBER, id: 'p-old', period_start: '2026-11-01', period_end: '2026-11-30', outstanding_clp: 25000 }
  const LAPSED_LEDGER: MembershipLedger = {
    ...LEDGER,
    open_periods: [NOVEMBER],
    owed_clp: 25000,
    balance_clp: 25000,
    entries: [],
    periods: [{ id: 'p-old', period_start: '2026-11-01', period_end: '2026-11-30', outstanding_clp: 25000, voided_clp: 0, void_id: null, charged_clp: 25000 }],
    refundable_payments: [],
  }

  it('shows the active plan as current, though a lapsed one comes first (#271)', async () => {
    stubApi({
      memberships: [LAPSED, MONTHLY],
      extra: (path) => (path === '/api/ledger/memberships/m-old' ? { body: LAPSED_LEDGER } : undefined),
    })
    renderAt(PATH)

    expect(await within(await money()).findByText('Mensual adultos · vence el 30')).toBeInTheDocument()
    const debt = await screen.findByRole('region', { name: copy.earlierDebt })
    expect(within(debt).getByText(copy.earlierDebtLine('Mensual antiguo', copy.pendingMonth('noviembre')))).toBeInTheDocument()
  })

  it("voids a lapsed plan's charge from its line under Deuda anterior, which names its plan (#271)", async () => {
    const calls = stubApi({
      memberships: [MONTHLY, LAPSED],
      // Nothing to void on the plan shown: the lapsed plan's charge is still there.
      ledger: { ...LEDGER, open_periods: [], owed_clp: 0, periods: [] },
      extra: (path, method) => {
        if (path === '/api/ledger/memberships/m-old') return { body: LAPSED_LEDGER }
        if (path === '/api/ledger/voids' && method === 'POST') {
          return { status: 201, body: { period: { outstanding_clp: 0, closed: true } } }
        }
        return undefined
      },
    })
    renderAt(PATH)
    const debt = await screen.findByRole('region', { name: copy.earlierDebt })

    const line = await within(debt).findByRole('button', { name: /^Cargo noviembre/ })
    expect(line).toHaveTextContent(`Mensual antiguo · Caducado · ${copy.ledger.unpaid}`)
    await userEvent.click(line)
    const fixes = within(debt).getByRole('group', { name: copy.fix.charge('noviembre', 'Mensual antiguo · Caducado') })
    await userEvent.click(within(fixes).getByRole('button', { name: copy.fix.voidCharge }))
    expect(within(fixes).getByText(copy.fix.balance('$25.000', '$0'))).toBeInTheDocument()
    await userEvent.type(within(fixes).getByLabelText(copy.voidForm.reason), 'duplicado')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.voidForm.submit('$25.000') }))

    expect(await within(debt).findByRole('status')).toHaveTextContent(copy.voidForm.done('noviembre', '$25.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/voids',
        body: { membership_id: 'm-old', billing_period_id: 'p-old', reason: 'duplicado' },
      },
    ])
  })

  const VOIDED_OCT = { id: 'p-oct', period_start: '2026-10-30', period_end: '2026-11-29', outstanding_clp: 0, voided_clp: 45000, void_id: 'v-oct', charged_clp: 0 }
  const VOIDED_ENTRIES = [
    entry({
      id: 'void-oct',
      kind: 'adjustment',
      voids: true,
      purpose: 'void',
      billing_period_id: 'p-oct',
      period_start: '2026-10-30',
      note: 'duplicado',
      created_at: '2026-11-02T12:00:00Z',
    }),
    entry({
      id: 'c-oct',
      kind: 'charge',
      billing_period_id: 'p-oct',
      period_start: '2026-10-30',
      voided: { reason: 'duplicado', by_name: 'Ana', at: '2026-11-02T12:00:00Z' },
    }),
  ]
  const VOIDED_LEDGER: MembershipLedger = {
    ...LEDGER,
    open_periods: [],
    owed_clp: 0,
    balance_clp: 0,
    entries: VOIDED_ENTRIES,
    periods: [VOIDED_OCT],
    refundable_payments: [],
  }

  it('restores a charge voided by mistake from its line, saying what it owes again (#278)', async () => {
    const calls = stubApi({
      ledger: VOIDED_LEDGER,
      extra: (path, method) =>
        path === '/api/ledger/restores' && method === 'POST'
          ? { status: 201, body: { period: { outstanding_clp: 45000, closed: false } } }
          : undefined,
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    // Voided, it can only be restored.
    expect(within(fixes).getByRole('button', { name: copy.fix.restoreCharge, pressed: true })).toBeInTheDocument()
    expect(within(fixes).queryByRole('button', { name: copy.fix.changeAmount })).not.toBeInTheDocument()
    const form = within(fixes).getByRole('form', { name: copy.restoreForm.title })
    expect(within(form).getByText(copy.fix.owed('octubre', '$0', '$45.000'))).toBeInTheDocument()
    expect(within(form).getByText(copy.fix.balance('$0', '$45.000'))).toBeInTheDocument()
    // A reason is required.
    await userEvent.click(within(form).getByRole('button', { name: copy.restoreForm.submit }))
    expect(within(form).getByText(copy.restoreForm.reasonNeeded)).toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText(copy.restoreForm.reason), 'se anuló el cargo equivocado')
    await userEvent.click(within(form).getByRole('button', { name: copy.restoreForm.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.restoreForm.done('octubre', '$45.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/ledger/restores', body: { void_id: 'v-oct', reason: 'se anuló el cargo equivocado' } },
    ])
  })

  it("restores a lapsed plan's voided charge from its line under Otros planes (#278)", async () => {
    const lapsed: MembershipLedger = {
      ...LAPSED_LEDGER,
      open_periods: [],
      owed_clp: 0,
      balance_clp: 0,
      periods: [{ ...LAPSED_LEDGER.periods[0]!, outstanding_clp: 0, voided_clp: 25000, void_id: 'v-old', charged_clp: 0 }],
    }
    const calls = stubApi({
      memberships: [MONTHLY, LAPSED],
      extra: (path, method) => {
        if (path === '/api/ledger/memberships/m-old') return { body: lapsed }
        if (path === '/api/ledger/restores' && method === 'POST') {
          return { status: 201, body: { period: { outstanding_clp: 25000, closed: false } } }
        }
        return undefined
      },
    })
    renderAt(PATH)
    // Nothing owed there, so not "Deuda anterior".
    const others = await screen.findByRole('region', { name: copy.fix.otherPlans })
    expect(screen.queryByRole('region', { name: copy.earlierDebt })).not.toBeInTheDocument()

    const line = within(others).getByRole('button', { name: /^Cargo noviembre/ })
    expect(line).toHaveTextContent(`Mensual antiguo · Caducado · ${copy.fix.voided('$25.000')}`)
    await userEvent.click(line)
    const fixes = within(others).getByRole('group', { name: copy.fix.charge('noviembre', 'Mensual antiguo · Caducado') })
    expect(within(fixes).getByText(copy.fix.owed('noviembre', '$0', '$25.000'))).toBeInTheDocument()
    await userEvent.type(within(fixes).getByLabelText(copy.restoreForm.reason), 'se anuló el cargo equivocado')
    await userEvent.click(within(within(fixes).getByRole('form')).getByRole('button', { name: copy.restoreForm.submit }))

    expect(await within(others).findByRole('status')).toHaveTextContent(copy.restoreForm.done('noviembre', '$25.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/ledger/restores', body: { void_id: 'v-old', reason: 'se anuló el cargo equivocado' } },
    ])
  })

  it('says why a restore was refused (#278)', async () => {
    stubApi({
      ledger: VOIDED_LEDGER,
      extra: (path, method) =>
        path === '/api/ledger/restores' && method === 'POST'
          ? { status: 409, body: { detail: { code: 'restored', message: 'the void was restored already' } } }
          : undefined,
    })
    renderAt(PATH)
    const fixes = await fixLine(/^Cargo octubre/, copy.fix.charge('octubre', null))

    await userEvent.type(within(fixes).getByLabelText(copy.restoreForm.reason), 'error')
    await userEvent.click(within(within(fixes).getByRole('form')).getByRole('button', { name: copy.restoreForm.submit }))
    expect(await within(fixes).findByRole('alert')).toHaveTextContent(copy.restoreRefused.restored)
  })

  it('offers no fix on the charges of a plan voided by mistake (#278)', async () => {
    stubApi({
      memberships: [{ ...MONTHLY, status: 'cancelled', voided_at: '2026-11-08T12:00:00Z', void_reason: 'prueba' }],
      ledger: VOIDED_LEDGER,
    })
    renderAt(PATH)
    await within(await money()).findByText(copy.voidedBadge)
    const ledger = await libro()
    expect(within(ledger).getByText(copy.ledger.charge('octubre'))).toBeInTheDocument()
    expect(within(ledger).queryByRole('button')).not.toBeInTheDocument()
  })

  it('reads a restored charge as owed, saying it was voided and restored (#278)', async () => {
    stubApi({
      ledger: {
        ...LEDGER,
        entries: [
          entry({
            id: 'restore-oct',
            kind: 'adjustment',
            amount_clp: -45000,
            purpose: 'restore',
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            note: 'se anuló el cargo equivocado',
            validated_by_name: 'Martín',
            created_at: '2026-11-13T12:00:00Z',
            validated_at: '2026-11-13T12:00:00Z',
          }),
          entry({
            id: 'c-oct',
            kind: 'charge',
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            restored: {
              reason: 'se anuló el cargo equivocado',
              by_name: 'Martín',
              at: '2026-11-13T12:00:00Z',
              void: { reason: 'duplicado', by_name: 'Ana', at: '2026-11-02T12:00:00Z' },
            },
          }),
        ],
      },
    })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    const charge = within(ledger).getByText(copy.ledger.charge('octubre')).closest('li')!
    expect(charge).not.toHaveClass('member__entry--voided')
    expect(charge).toHaveTextContent(copy.ledger.voided('duplicado', 'Ana', '2 nov'))
    expect(charge).toHaveTextContent(copy.ledger.restored('se anuló el cargo equivocado', 'Martín', '13 nov'))
    expect(within(ledger).getByText(copy.ledger.restore('octubre'))).toBeInTheDocument()
  })

  it('voids a plan started by mistake, under "Corregir plan" (#256, #279)', async () => {
    const calls = stubApi({
      extra: (path, method) =>
        path === '/api/memberships/m-felipe/void' && method === 'POST'
          ? { body: { ...MONTHLY, status: 'cancelled', voided_at: '2026-11-13T12:00:00Z', void_reason: 'prueba' } }
          : undefined,
    })
    renderAt(PATH)
    const card = await money()

    const fix = await within(card).findByRole('button', { name: copy.fix.plan })
    await userEvent.click(fix)
    expect(fix).toHaveAttribute('aria-expanded', 'true')
    const choices = within(card).getByRole('group', { name: copy.fix.plan })
    await userEvent.click(within(choices).getByRole('button', { name: copy.voidPlan }))
    const form = within(card).getByRole('form', { name: copy.voidPlanForm.title })
    expect(within(form).getByText(copy.voidPlanForm.intro)).toBeInTheDocument()
    // Its unpaid October goes.
    expect(within(form).getByText(copy.fix.balance('$45.000', '$0'))).toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText(copy.voidPlanForm.reason), 'prueba')
    await userEvent.click(within(form).getByRole('button', { name: copy.voidPlanForm.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.voidPlanForm.done)
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/memberships/m-felipe/void', body: { reason: 'prueba' } },
    ])
  })

  it('opens Cobros\' wizard for the member from "Corregir plan" › "Cobro extra" (#279)', async () => {
    stubApi()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.fix.plan }))
    const choices = within(card).getByRole('group', { name: copy.fix.plan })
    expect(within(choices).getByRole('link', { name: copy.fix.extraCharge })).toHaveAttribute(
      'href',
      '/admin/pagos/cobros/nuevo?person=felipe',
    )
    // Closed again by the same button.
    await userEvent.click(within(card).getByRole('button', { name: copy.fix.plan }))
    expect(within(card).queryByRole('group', { name: copy.fix.plan })).not.toBeInTheDocument()
  })

  it('shows a voided charge struck through with why, who and when, and the void beside it (#256)', async () => {
    stubApi({
      memberships: [{ ...MONTHLY, status: 'cancelled', voided_at: '2026-11-08T12:00:00Z', void_reason: 'prueba' }],
      ledger: {
        ...LEDGER,
        open_periods: [],
        owed_clp: 0,
        entries: [
          entry({
            id: 'void-oct',
            kind: 'adjustment',
            voids: true,
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            note: 'alumno de prueba',
            validated_by_name: 'Martín',
            created_at: '2026-11-08T12:00:00Z',
            validated_at: '2026-11-08T12:00:00Z',
          }),
          entry({
            id: 'c-oct',
            kind: 'charge',
            billing_period_id: 'p-oct',
            period_start: '2026-10-30',
            voided: { reason: 'alumno de prueba', by_name: 'Martín', at: '2026-11-08T12:00:00Z' },
          }),
        ],
        periods: [{ id: 'p-oct', period_start: '2026-10-30', period_end: '2026-11-29', outstanding_clp: 0, voided_clp: 0, void_id: null, charged_clp: 45000 }],
      },
    })
    renderAt(PATH)

    const ledger = await screen.findByRole('region', { name: copy.ledger.title })
    const voided = (await within(ledger).findByText(copy.ledger.voided('alumno de prueba', 'Martín', '8 nov'))).closest('li')!
    expect(voided).toHaveClass('member__entry--voided')
    expect(within(voided).getByText(copy.ledger.charge('octubre'))).toBeInTheDocument()
    expect(within(ledger).getByText(copy.ledger.void('octubre'))).toBeInTheDocument()
    const card = await money()
    expect(within(card).getByText(copy.voidedBadge)).toBeInTheDocument()
    // Nothing left to void: no line to fix, and "Corregir plan" offers only a cobro extra.
    expect(within(ledger).queryByRole('button')).not.toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: copy.fix.plan }))
    const choices = within(card).getByRole('group', { name: copy.fix.plan })
    expect(within(choices).queryByRole('button', { name: copy.voidPlan })).not.toBeInTheDocument()
    expect(within(choices).getByRole('link', { name: copy.fix.extraCharge })).toBeInTheDocument()
  })

  it('shows a coach no Libro and nothing to fix (#256, #279)', async () => {
    stubApi({ role: 'coach' })
    renderAt(PATH)
    expect(await screen.findByRole('heading', { name: FELIPE.name })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.ledger.title })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.fix.plan })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.voidPlan })).not.toBeInTheDocument()
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

  it('refunds a payment from its Libro line, saying what it opens again (#279)', async () => {
    const calls = stubApi()
    renderAt(PATH)
    const fixes = await fixLine(/^Pago septiembre/, copy.fix.payment('septiembre'))

    expect(within(fixes).getByRole('button', { name: copy.fix.refund })).toHaveAttribute('aria-pressed', 'true')
    const form = within(fixes).getByRole('form', { name: copy.refundForm.title })
    const amount = within(form).getByLabelText(copy.refundForm.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '15000')
    expect(within(form).getByText(copy.fix.owed('septiembre', '$0', '$15.000'))).toBeInTheDocument()
    expect(within(form).getByText(copy.fix.balance('$45.000', '$60.000'))).toBeInTheDocument()
    await userEvent.click(within(form).getByRole('button', { name: copy.refundForm.submit('$15.000') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.refundForm.done('$15.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/ledger/refunds',
        body: { payment_id: 'pay-sep', amount_clp: 15000, method: 'transfer' },
      },
    ])
  })

  it('shows a refund over what the payment has left as no more than that (#279)', async () => {
    stubApi()
    renderAt(PATH)
    const fixes = await fixLine(/^Pago septiembre/, copy.fix.payment('septiembre'))

    const amount = within(fixes).getByLabelText(copy.refundForm.amount)
    await userEvent.clear(amount)
    await userEvent.type(amount, '60000')
    expect(within(fixes).getByText(copy.fix.owed('septiembre', '$0', '$45.000'))).toBeInTheDocument()
    expect(within(fixes).getByText(copy.fix.balance('$45.000', '$90.000'))).toBeInTheDocument()
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
    expect(calls.some((c) => c.path.endsWith('/corrections'))).toBe(false)
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
          can_email: false,
          emailed_at: null,
          emailed_today: false,
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

  it('emails the overdue reminder from the money card, and says when the last one went', async () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 86_400_000).toISOString()
    const overdue = {
      billing_period_id: 'p-oct',
      membership_id: 'm-felipe',
      person_id: 'felipe',
      person_name: 'Felipe Díaz',
      days_overdue: 9,
      kind: 'payment_overdue',
      rejection_note: null,
      contact_name: 'Felipe Díaz',
      whatsapp_url: null,
      reminders_sent: 0,
      reminded_at: null,
      reminder_due: true,
      can_email: true,
      emailed_at: twoDaysAgo,
      emailed_today: false,
    }
    const calls = stubApi({
      reminders: [overdue],
      extra: (path, method) =>
        path === '/api/reminders/p-oct/email' && method === 'POST'
          ? { status: 201, body: { sent_at: new Date().toISOString(), contact_name: 'Felipe Díaz' } }
          : undefined,
    })
    renderAt(PATH)
    const card = await money()
    const words = es.admin.reminders.email

    expect(await within(card).findByText(words.last('hace 2 días'))).toBeInTheDocument()
    const send = within(card).getByRole('button', { name: words.sendTo('Felipe Díaz') })
    await userEvent.dblClick(send)

    expect(await within(card).findByRole('status')).toHaveTextContent(words.sent('Felipe Díaz'))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/reminders/p-oct/email'])
    // It stays on screen, disabled, saying why (#266).
    expect(send).toBeDisabled()
    expect(send).toHaveAccessibleDescription(words.sentToday)
  })

  it('keeps the email button disabled once one went out today, saying so', async () => {
    stubApi({
      reminders: [
        {
          billing_period_id: 'p-oct',
          membership_id: 'm-felipe',
          person_id: 'felipe',
          person_name: 'Felipe Díaz',
          days_overdue: 9,
          kind: 'payment_overdue',
          rejection_note: null,
          contact_name: 'Felipe Díaz',
          whatsapp_url: null,
          reminders_sent: 0,
          reminded_at: null,
          reminder_due: true,
          can_email: true,
          emailed_at: new Date().toISOString(),
          emailed_today: true,
        },
      ],
    })
    renderAt(PATH)
    const card = await money()
    const words = es.admin.reminders.email

    expect(await within(card).findByText(words.last(words.today))).toBeInTheDocument()
    const send = within(card).getByRole('button', { name: words.sendTo('Felipe Díaz') })
    expect(send).toBeDisabled()
    expect(send).toHaveAccessibleDescription(words.sentToday)
    expect(within(card).getByText(words.sentToday)).toBeVisible()
  })

  it('keeps the email button disabled for a member with no email, saying so', async () => {
    stubApi({
      reminders: [
        {
          billing_period_id: 'p-oct',
          membership_id: 'm-felipe',
          person_id: 'felipe',
          person_name: 'Felipe Díaz',
          days_overdue: 9,
          kind: 'payment_overdue',
          rejection_note: null,
          contact_name: 'Felipe Díaz',
          whatsapp_url: null,
          reminders_sent: 0,
          reminded_at: null,
          reminder_due: true,
          can_email: false,
          emailed_at: null,
          emailed_today: false,
        },
      ],
    })
    renderAt(PATH)
    const card = await money()
    const words = es.admin.reminders.email

    const send = await within(card).findByRole('button', { name: words.sendTo('Felipe Díaz') })
    expect(send).toBeDisabled()
    expect(send).toHaveAccessibleDescription(words.noEmail)
    expect(within(card).getByText(words.noEmail)).toBeVisible()
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
    expect(within(ledger).queryByRole('button', { name: /^Ver todo el libro/ })).not.toBeInTheDocument()
  })

  it('lists the corrections under the Libro: what, period, before → after, reason, who, when (#277)', async () => {
    stubApi({
      corrections: [
        correction({ id: 'void' }),
        correction({
          id: 'discount',
          purpose: null,
          reason: 'hermano',
          actor_name: 'Martín',
          at: '2026-10-25T12:00:00Z',
          before: { outstanding_clp: 45000, balance_clp: 95000 },
          after: { outstanding_clp: 40000, balance_clp: 90000 },
        }),
        correction({
          id: 'surcharge',
          purpose: null,
          reason: 'clase extra',
          at: '2026-10-24T12:00:00Z',
          before: { outstanding_clp: 40000, balance_clp: 90000 },
          after: { outstanding_clp: 45000, balance_clp: 95000 },
        }),
        correction({ id: 'plan', plan_void: true, period_start: '2026-09-30', at: '2026-10-20T12:00:00Z' }),
      ],
    })
    renderAt(PATH)

    const fixes = await screen.findByRole('region', { name: copy.corrections.title })
    const rows = within(fixes).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      'Anuló cargo octubreduplicado · Mensual adultos · por Ana · 2 novSaldo $90.000 → $45.000$45.000 → $0',
      'Descuento octubrehermano · Mensual adultos · por Martín · 25 octSaldo $95.000 → $90.000$45.000 → $40.000',
      'Recargo octubreclase extra · Mensual adultos · por Ana · 24 octSaldo $90.000 → $95.000$40.000 → $45.000',
    ])
    await userEvent.click(within(fixes).getByRole('button', { name: copy.corrections.all(4) }))
    expect(within(fixes).getAllByRole('listitem')[3]).toHaveTextContent('Anuló plan · cargo septiembre')
    await userEvent.click(within(fixes).getByRole('button', { name: copy.corrections.fewer }))
    expect(within(fixes).getAllByRole('listitem')).toHaveLength(3)
  })

  it('lists the corrections though the plan\'s ledger fails to load (#277)', async () => {
    stubApi({
      corrections: [correction({ id: 'void' })],
      extra: (path) => (path === '/api/ledger/memberships/m-felipe' ? { status: 500, body: {} } : undefined),
    })
    renderAt(PATH)

    const fixes = await screen.findByRole('region', { name: copy.corrections.title })
    expect(within(fixes).getAllByRole('listitem')).toHaveLength(1)
    expect(screen.queryByRole('region', { name: copy.ledger.title })).not.toBeInTheDocument()
  })

  it('has no Correcciones before a first fix (#277)', async () => {
    stubApi()
    renderAt(PATH)
    await screen.findByRole('region', { name: copy.ledger.title })
    expect(screen.queryByRole('region', { name: copy.corrections.title })).not.toBeInTheDocument()
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

  it('shows no rank, promotion or log while no activity of the gym grades (#245)', async () => {
    const calls = stubApi({ grades: false })
    renderAt(PATH)

    expect(await screen.findByRole('heading', { level: 1, name: 'Felipe Díaz' })).toBeInTheDocument()
    await screen.findByRole('region', { name: copy.attendance.title })
    expect(screen.queryByRole('region', { name: copy.grading.title })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.grading.award })).not.toBeInTheDocument()
    expect(screen.queryByText(/Azul/)).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/grades') || c.path === '/api/gym/grading-scheme')).toBe(false)
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

  it('dar de baja sends the reason a chip fills, and the banner says it (#294)', async () => {
    let left: Person = FELIPE
    const calls = stubApi({
      extra: (path, method, body) => {
        if (path === '/api/people/felipe/leave' && method === 'POST') {
          left = { ...FELIPE, left_on: '2026-11-10', left_reason: (body as { left_reason?: string }).left_reason }
          return { body: left }
        }
        if (path === '/api/people/felipe' && method === 'GET') return { body: left }
        return undefined
      },
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.leave }))
    const form = screen.getByRole('form', { name: copy.leaveForm.title })
    const chips = within(form).getByRole('group', { name: copy.leftReason.chipsLabel })
    expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toEqual(copy.leftReason.chips)
    await userEvent.click(within(chips).getByRole('button', { name: 'Precio' }))
    await userEvent.click(within(chips).getByRole('button', { name: 'Lesión' }))
    expect(within(chips).getByRole('button', { name: 'Lesión' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(chips).getByRole('button', { name: 'Precio' })).toHaveAttribute('aria-pressed', 'false')
    // Pressed again, it empties what it filled.
    await userEvent.click(within(chips).getByRole('button', { name: 'Lesión' }))
    expect(within(form).getByLabelText(copy.leftReason.label)).toHaveValue('')
    await userEvent.click(within(chips).getByRole('button', { name: 'Lesión' }))
    await userEvent.click(within(form).getByRole('button', { name: copy.leaveForm.submit }))

    const banner = await screen.findByText(copy.leftBanner('10-11-2026'), { exact: false })
    expect(banner).toHaveTextContent(copy.leftBannerReason('Lesión'))
    expect(calls.filter((c) => c.path === '/api/people/felipe/leave')).toEqual([
      { method: 'POST', path: '/api/people/felipe/leave', body: { left_reason: 'Lesión' } },
    ])
  })

  it('dar de baja takes a day from years ago, not from more than 60 (#294)', async () => {
    const calls = stubApi()
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.leave }))
    const form = screen.getByRole('form', { name: copy.leaveForm.title })
    const day = within(form).getByLabelText(copy.leaveForm.on)
    // Sixty years before the gym's today, to the day.
    const min = day.getAttribute('min') ?? ''
    expect(min).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    fireEvent.change(day, { target: { value: `${Number(min.slice(0, 4)) - 1}${min.slice(4)}` } })
    await userEvent.click(within(form).getByRole('button', { name: copy.leaveForm.submit }))
    expect(within(form).getByRole('alert')).toHaveTextContent(copy.leaveForm.onNeeded)
    expect(calls.some((c) => c.path === '/api/people/felipe/leave')).toBe(false)
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

  it('eliminar says what they owe and how to clear it, and offers dar de baja (#256)', async () => {
    stubApi({
      extra: (path) =>
        path === '/api/people/felipe/deletion' ? { body: { refused: 'owes', amount_clp: 45000 } } : undefined,
    })
    renderAt(PATH)

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.remove }))
    expect(await screen.findByText(copy.removeForm.refused.owes('$45.000'))).toBeInTheDocument()
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
    await userEvent.type(within(form).getByLabelText(copy.removeForm.reason), 'era de prueba')
    await userEvent.click(submit)

    expect(await screen.findByRole('heading', { name: es.admin.students.title })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([
      { method: 'DELETE', path: '/api/people/felipe', body: { reason: 'era de prueba' } },
    ])
  })

  it('goes back to the list it was opened from after eliminar, filters kept (#250)', async () => {
    stubApi({
      extra: (path, method) => {
        if (path === '/api/people/felipe/deletion') return { body: { refused: null } }
        if (path === '/api/people/felipe' && method === 'DELETE') return { status: 204 }
        if (path === '/api/people') return { body: { items: [], total: 0 } }
        return undefined
      },
    })
    const from = '/admin/alumnos?belt=blue&q=Feli'
    const router = renderAt(from)
    await waitFor(() => expect(router.state.location.href).toBe(from))
    await router.navigate({ href: PATH })

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.remove }))
    const form = await screen.findByRole('form', { name: copy.removeForm.title })
    await userEvent.type(within(form).getByLabelText(copy.removeForm.confirm(FELIPE.name)), 'Felipe Díaz')
    await userEvent.type(within(form).getByLabelText(copy.removeForm.reason), 'era de prueba')
    await userEvent.click(within(form).getByRole('button', { name: copy.removeForm.submit }))

    await waitFor(() => expect(router.state.location.href).toBe(from))
    // Back, not the list again on top of it: no page twice in the history.
    expect(router.history.location.state.__TSR_index).toBe(0)
    expect(router.history.length).toBe(2)
  })

  it('goes to Alumnos in the gone ficha\'s place after eliminar from elsewhere (#250)', async () => {
    stubApi({
      extra: (path, method) => {
        if (path === '/api/people/felipe/deletion') return { body: { refused: null } }
        if (path === '/api/people/felipe' && method === 'DELETE') return { status: 204 }
        if (path === '/api/people') return { body: { items: [], total: 0 } }
        return undefined
      },
    })
    const router = renderAt('/admin')
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin'))
    await router.navigate({ href: PATH })

    await userEvent.click(within(await actions()).getByRole('button', { name: copy.remove }))
    const form = await screen.findByRole('form', { name: copy.removeForm.title })
    await userEvent.type(within(form).getByLabelText(copy.removeForm.confirm(FELIPE.name)), 'Felipe Díaz')
    await userEvent.type(within(form).getByLabelText(copy.removeForm.reason), 'era de prueba')
    await userEvent.click(within(form).getByRole('button', { name: copy.removeForm.submit }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos'))
    expect(router.history.length).toBe(2)
  })
})

describe('Acceso (#246)', () => {
  const access = copy.access
  const NEVER = { to: 'felipe@example.com', guardian: null, last: null }
  const SENT = { ...NEVER, last: { status: 'sent', sent_at: '2026-11-12T15:00:00Z', to: 'felipe@example.com' } }

  function welcomeApi(state: unknown, sent: unknown = SENT) {
    return (path: string, method: string): Answer | undefined => {
      if (path !== '/api/people/felipe/welcome') return undefined
      return { body: method === 'POST' ? sent : state }
    }
  }

  const section = () => screen.findByRole('region', { name: access.title })

  it('says where the link goes, and sends it from the ficha', async () => {
    const calls = stubApi({ extra: welcomeApi(NEVER) })
    renderAt(PATH)
    const s = await section()

    expect(within(s).getByText(access.to('felipe@example.com'))).toBeInTheDocument()
    expect(within(s).getByText(access.never)).toBeInTheDocument()
    await userEvent.click(within(s).getByRole('button', { name: access.send }))

    expect(await within(s).findByText(access.sent('12 de noviembre'))).toBeInTheDocument()
    expect(within(s).getByRole('button', { name: access.resend })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/people/felipe/welcome' && c.method === 'POST')).toHaveLength(1)
  })

  it("says when the welcome failed, and to whose guardian it goes", async () => {
    const failed = {
      to: 'marta@example.com',
      guardian: 'Marta Díaz',
      last: { status: 'failed', sent_at: '2026-11-12T15:00:00Z', to: 'marta@example.com' },
    }
    stubApi({ extra: welcomeApi(failed) })
    renderAt(PATH)
    const s = await section()

    expect(within(s).getByText(access.toGuardian('Marta Díaz', 'marta@example.com'))).toBeInTheDocument()
    expect(within(s).getByRole('alert')).toHaveTextContent(access.failed('12 de noviembre'))
    expect(within(s).getByRole('button', { name: access.send })).toBeInTheDocument()
  })

  it('waits for the welcome "Nuevo alumno" just asked for, until it is recorded', async () => {
    let reads = 0
    stubApi({
      extra: (path, method) => {
        if (path !== '/api/people/felipe/welcome' || method !== 'GET') return undefined
        reads += 1
        return { body: reads === 1 ? NEVER : SENT }
      },
    })
    const queryClient = createQueryClient()
    const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin/alumnos'] }))
    render(<App queryClient={queryClient} router={router} />)
    await router.navigate({
      to: '/admin/alumnos/$personId',
      params: { personId: 'felipe' },
      state: { welcomeSince: Date.now() },
    })
    const s = await section()

    expect(within(s).getByText(access.waiting)).toBeInTheDocument()
    expect(await within(s).findByText(access.sent('12 de noviembre'), {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('offers nothing to send without an email', async () => {
    stubApi({ extra: welcomeApi({ to: null, guardian: null, last: null }) })
    renderAt(PATH)
    const s = await section()

    expect(within(s).getByText(access.noEmail)).toBeInTheDocument()
    expect(within(s).queryByRole('button')).not.toBeInTheDocument()
  })

  it('says why no mail goes to a bounced address, and offers nothing to send (#104)', async () => {
    const bounced = {
      ...SENT,
      suppressed: { reason: 'bounce', detail: '550 5.1.1 User unknown', since: '2026-11-12T15:00:00Z' },
    }
    stubApi({ extra: welcomeApi(bounced) })
    renderAt(PATH)
    const s = await section()

    const alert = within(s).getByRole('alert')
    expect(alert).toHaveTextContent(access.bounced('12 de noviembre'))
    expect(alert).toHaveTextContent(access.bounceDetail('550 5.1.1 User unknown'))
    expect(within(s).queryByRole('button')).not.toBeInTheDocument()
  })

  it('says when the address complained of spam (#104)', async () => {
    const complained = {
      ...NEVER,
      suppressed: { reason: 'complaint', detail: null, since: '2026-11-12T15:00:00Z' },
    }
    stubApi({ extra: welcomeApi(complained) })
    renderAt(PATH)
    const s = await section()

    expect(within(s).getByRole('alert')).toHaveTextContent(access.complained('12 de noviembre'))
    expect(within(s).queryByRole('button')).not.toBeInTheDocument()
  })

  it('says a welcome to a since-corrected address was not sent (#104)', async () => {
    const corrected = { ...NEVER, last: { ...SENT.last, status: 'suppressed' }, suppressed: null }
    stubApi({ extra: welcomeApi(corrected) })
    renderAt(PATH)
    const s = await section()

    expect(within(s).getByText(access.suppressedLast('12 de noviembre'))).toBeInTheDocument()
    expect(within(s).getByRole('button', { name: access.send })).toBeInTheDocument()
  })

  it('is not there for a coach', async () => {
    stubApi({ role: 'coach', extra: welcomeApi(NEVER) })
    renderAt(PATH)
    await money()

    expect(screen.queryByRole('region', { name: access.title })).not.toBeInTheDocument()
  })
})

describe('the plan from the ficha (#249)', () => {
  const PLANS = [
    { id: 'plan-adults', name: 'Mensual adultos', kind: 'monthly', price_clp: 45000, anchor: 'signup', active: true },
    { id: 'plan-six', name: 'Semestral', kind: 'prepaid', price_clp: 240000, period_months: 6, active: true },
    { id: 'plan-pack', name: 'Pack 12', kind: 'credits', price_clp: 45000, credits: 12, active: true },
    { id: 'plan-old', name: 'Mensual 2025', kind: 'monthly', price_clp: 40000, anchor: 'signup', active: false },
  ]
  const QUOTE = { starts_on: '2026-11-30', period_end: '2027-05-29', amount_due_clp: 240000 }
  const assign = copy.assignForm
  const change = copy.changeForm

  /** The API with no plan running: "Asignar plan" starts one, which the ficha then reads. */
  function planless(start: Membership[] = [], to: string | null = 'felipe@example.com') {
    let members = start
    return stubApi({
      memberships: start,
      extra: (path, method, body) => {
        if (path === '/api/plans') return { body: PLANS }
        if (path === '/api/people/felipe/welcome') return { body: { to, guardian: null, last: null } }
        // A lapsed plan still owing October, billed through Nov 29: the new one starts after it (#271).
        if (path === '/api/memberships/start') {
          const lapsed = members.some((m) => m.status === 'lapsed')
          return {
            body: lapsed
              ? { starts_on: '2026-11-30', billed_through: '2026-11-29', debt_clp: 45000 }
              : { starts_on: '2026-11-10', billed_through: null, debt_clp: 0 },
          }
        }
        if (path === '/api/memberships' && method === 'GET') return { body: members }
        if (path === '/api/memberships' && method === 'POST') {
          const { plan_id } = body as { plan_id: string }
          members = [{ ...MONTHLY, plan_id, plan_name: PLANS.find((p) => p.id === plan_id)!.name }]
          return { status: 201, body: members[0] }
        }
        return undefined
      },
    })
  }

  it('gives a planless member "Asignar plan", which starts them on it with the welcome', async () => {
    const calls = planless()
    renderAt(PATH)

    await userEvent.click(await screen.findByRole('button', { name: copy.assignPlan }))
    const form = screen.getByRole('form', { name: assign.title })
    // Only plans a member can be started on: active, no drop-in.
    const select = await within(form).findByLabelText(assign.plan)
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(4))
    expect(within(select).queryByRole('option', { name: 'Mensual 2025' })).not.toBeInTheDocument()
    await userEvent.selectOptions(select, 'plan-adults')
    expect(await within(form).findByLabelText(assign.welcome)).toBeChecked()
    // A double tap starts it once.
    const submit = within(form).getByRole('button', { name: assign.submit })
    fireEvent.click(submit)
    fireEvent.click(submit)

    expect(await screen.findByText(assign.done('Mensual adultos'))).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/memberships' && c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/memberships',
        body: { person_id: 'felipe', plan_id: 'plan-adults', send_welcome: true },
      },
    ])
    // The ficha reads the plan again, and offers no second one.
    expect(within(await money()).getByText('Mensual adultos · vence el 30')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.assignPlan })).not.toBeInTheDocument()
  })

  it('keeps "Volver" to where the ficha was opened from after assigning a plan with the welcome (#250)', async () => {
    planless()
    const router = renderAt('/admin/pagos?filter=pending')
    await waitFor(() => expect(router.state.location.href).toBe('/admin/pagos?filter=pending'))
    await router.navigate({ href: PATH })

    await userEvent.click(await screen.findByRole('button', { name: copy.assignPlan }))
    const form = screen.getByRole('form', { name: assign.title })
    await userEvent.selectOptions(await within(form).findByLabelText(assign.plan), 'plan-adults')
    await userEvent.click(within(form).getByRole('button', { name: assign.submit }))
    expect(await screen.findByText(assign.done('Mensual adultos'))).toBeInTheDocument()

    expect(screen.getByRole('link', { name: 'Volver a Pagos' })).toHaveAttribute('href', '/admin/pagos?filter=pending')
    expect(router.history.length).toBe(2)
  })

  it('asks for a plan, and sends no welcome without an email or when unticked', async () => {
    const calls = planless([], null)
    renderAt(PATH)

    await userEvent.click(await screen.findByRole('button', { name: copy.assignPlan }))
    const form = screen.getByRole('form', { name: assign.title })
    await userEvent.click(within(form).getByRole('button', { name: assign.submit }))
    expect(within(form).getByRole('alert')).toHaveTextContent(assign.planNeeded)
    expect(await within(form).findByText(assign.noEmail)).toBeInTheDocument()
    expect(within(form).getByLabelText(assign.welcome)).toBeDisabled()

    await userEvent.selectOptions(await within(form).findByLabelText(assign.plan), 'plan-six')
    await userEvent.click(within(form).getByRole('button', { name: assign.submit }))

    await waitFor(() =>
      expect(calls.find((c) => c.path === '/api/memberships' && c.method === 'POST')?.body).toEqual({
        person_id: 'felipe',
        plan_id: 'plan-six',
        send_welcome: false,
      }),
    )
  })

  it('warns of a lapsed plan\'s debt, and of the day the new plan starts after it, before saving (#271)', async () => {
    const calls = planless([{ ...MONTHLY, status: 'lapsed' }])
    renderAt(PATH)

    await userEvent.click(await screen.findByRole('button', { name: copy.assignPlan }))
    const form = screen.getByRole('form', { name: assign.title })
    expect(within(form).queryByText(assign.debt('$45.000'))).not.toBeInTheDocument()
    await userEvent.selectOptions(await within(form).findByLabelText(assign.plan), 'plan-adults')

    expect(await within(form).findByText(assign.debt('$45.000'))).toBeInTheDocument()
    expect(within(form).getByText(assign.moved(shortDay('2026-11-29'), shortDay('2026-11-30')))).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/memberships/start')).toBe(true)
  })

  it('keeps a lapsed plan\'s unpaid charge on the ficha once a new plan starts', async () => {
    const lapsed: Membership = { ...MONTHLY, status: 'lapsed' }
    let members = [lapsed]
    stubApi({
      memberships: members,
      extra: (path, method, body) => {
        if (path === '/api/plans') return { body: PLANS }
        if (path === '/api/people/felipe/welcome') return { body: { to: null, guardian: null, last: null } }
        if (path === '/api/memberships' && method === 'GET') return { body: members }
        if (path === '/api/memberships' && method === 'POST') {
          const { plan_id } = body as { plan_id: string }
          const started: Membership = { ...MONTHLY, id: 'm-new', plan_id, plan_name: 'Semestral', plan_kind: 'prepaid', anchor_day: null }
          members = [started, lapsed]
          return { status: 201, body: started }
        }
        // The new plan owes nothing yet; the lapsed one keeps October (`LEDGER`).
        if (path === '/api/ledger/memberships/m-new') {
          return { body: { ...LEDGER, open_periods: [], owed_clp: 0, entries: [], periods: [], refundable_payments: [] } }
        }
        return undefined
      },
    })
    renderAt(PATH)

    // Lapsed and owing: on its own card, nothing earlier to show apart.
    expect(await within(await money()).findByText(copy.pendingMonth('octubre'))).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.earlierDebt })).not.toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: copy.assignPlan }))
    const form = screen.getByRole('form', { name: assign.title })
    await userEvent.selectOptions(await within(form).findByLabelText(assign.plan), 'plan-six')
    await userEvent.click(within(form).getByRole('button', { name: assign.submit }))

    const debt = await screen.findByRole('region', { name: copy.earlierDebt })
    expect(within(debt).getByText('$45.000', { selector: '.member__amount' })).toBeInTheDocument()
    expect(within(debt).getByText(copy.earlierDebtLine('Mensual adultos', copy.pendingMonth('octubre')))).toBeInTheDocument()
    expect(within(await money()).getByText(/^Semestral/)).toBeInTheDocument()
  })

  it('shows no "Deuda anterior" to a coach, or when the earlier plan owes nothing', async () => {
    const earlier: Membership = { ...MONTHLY, id: 'm-old', status: 'cancelled' }
    stubApi({
      role: 'coach',
      memberships: [MONTHLY, earlier],
    })
    renderAt(PATH)
    await money()
    expect(screen.queryByRole('region', { name: copy.earlierDebt })).not.toBeInTheDocument()
  })

  it('shows no "Deuda anterior" when the earlier plan owes nothing', async () => {
    const earlier: Membership = { ...MONTHLY, id: 'm-old', status: 'cancelled' }
    const calls = stubApi({
      memberships: [MONTHLY, earlier],
      extra: (path) =>
        path === '/api/ledger/memberships/m-old' ? { body: { ...LEDGER, open_periods: [], owed_clp: 0 } } : undefined,
    })
    renderAt(PATH)
    await money()
    await waitFor(() => expect(calls.some((c) => c.path === '/api/ledger/memberships/m-old')).toBe(true))
    expect(screen.queryByRole('region', { name: copy.earlierDebt })).not.toBeInTheDocument()
  })

  it('offers "Asignar plan" once the plan was cancelled', async () => {
    planless([{ ...MONTHLY, status: 'cancelled' }])
    renderAt(PATH)
    expect(await screen.findByRole('button', { name: copy.assignPlan })).toBeInTheDocument()
  })

  it('gives a coach neither "Asignar plan" nor "Cambiar plan"', async () => {
    stubApi({ role: 'coach', memberships: [] })
    renderAt(PATH)
    expect(await screen.findByText(copy.noPlan)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.assignPlan })).not.toBeInTheDocument()
  })

  it('gives a coach no "Cambiar plan" on an active member', async () => {
    stubApi({ role: 'coach' })
    renderAt(PATH)
    await money()
    expect(await screen.findByText('Mensual adultos · vence el 30')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.changePlan })).not.toBeInTheDocument()
  })

  /** An active member on "Mensual adultos"; the change answers `changed`, by default pending from the quote's day. */
  function active(changed?: Answer, membership: Membership = MONTHLY) {
    let members = [membership]
    return stubApi({
      memberships: members,
      extra: (path, method, body) => {
        if (path === '/api/plans') return { body: PLANS }
        if (path === '/api/memberships' && method === 'GET') return { body: members }
        if (path === '/api/memberships/m-felipe/plan-change' && method === 'GET') return { body: QUOTE }
        if (path === '/api/memberships/m-felipe/plan-change' && method === 'POST') {
          if (changed) return changed
          const { plan_id } = body as { plan_id: string }
          const name = PLANS.find((p) => p.id === plan_id)!.name
          members = [{ ...membership, next_plan: { plan_id, plan_name: name, starts_on: QUOTE.starts_on } }]
          return { body: members[0] }
        }
        return undefined
      },
    })
  }

  it('changes an active member to another plan, saying first what it does to this period and the next charge', async () => {
    const calls = active()
    renderAt(PATH)

    expect(screen.queryByRole('button', { name: copy.assignPlan })).not.toBeInTheDocument()
    await userEvent.click(await within(await money()).findByRole('button', { name: copy.changePlan }))
    const form = screen.getByRole('form', { name: change.title })
    const select = await within(form).findByLabelText(change.plan)
    // Another monthly or prepaid plan: not the one it is on, a pack, or one deactivated.
    await waitFor(() => expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([change.noPlan, 'Semestral']))
    await userEvent.selectOptions(select, 'plan-six')

    expect(await within(form).findByText(change.current('Mensual adultos', shortDay('2026-11-29')))).toBeInTheDocument()
    expect(within(form).getByText(change.next('Semestral', shortDay('2026-11-30'), '$240.000', shortDay('2027-05-29')))).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/memberships/m-felipe/plan-change' && c.method === 'POST')).toEqual([])

    const submit = within(form).getByRole('button', { name: change.submit })
    fireEvent.click(submit)
    fireEvent.click(submit)

    expect(await screen.findByText(change.done('Semestral', shortDay('2026-11-30')))).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/memberships/m-felipe/plan-change' && c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/memberships/m-felipe/plan-change', body: { plan_id: 'plan-six' } },
    ])
    // The card says the change is coming.
    expect(await within(await money()).findByText(copy.planChangeBooked('Semestral', shortDay('2026-11-30')))).toBeInTheDocument()
  })

  it('withdraws a pending change by staying on the plan it is on', async () => {
    const pending = { ...MONTHLY, next_plan: { plan_id: 'plan-six', plan_name: 'Semestral', starts_on: '2026-11-30' } }
    const calls = active({ body: MONTHLY }, pending)
    renderAt(PATH)

    await userEvent.click(await within(await money()).findByRole('button', { name: copy.changePlan }))
    const form = screen.getByRole('form', { name: change.title })
    await userEvent.selectOptions(await within(form).findByLabelText(change.plan), 'plan-adults')
    expect(within(form).getByText(change.withdraw('Semestral', 'Mensual adultos'))).toBeInTheDocument()
    await userEvent.click(within(form).getByRole('button', { name: change.submit }))

    expect(await screen.findByText(change.withdrawn)).toBeInTheDocument()
    expect(calls.filter((c) => c.path === '/api/memberships/m-felipe/plan-change').map((c) => [c.method, c.body])).toEqual([
      ['POST', { plan_id: 'plan-adults' }],
    ])
  })

  it('changes a frozen membership as the API allows, saying the freeze moves it', async () => {
    active(undefined, FROZEN)
    renderAt(PATH)

    await userEvent.click(await within(await money()).findByRole('button', { name: copy.changePlan }))
    const form = screen.getByRole('form', { name: change.title })
    await userEvent.selectOptions(await within(form).findByLabelText(change.plan), 'plan-six')
    expect(await within(form).findByText(change.frozen)).toBeInTheDocument()
  })

  it('says so when the API refuses the change', async () => {
    active({ status: 409, body: { detail: 'a cancelled membership cannot change plan' } })
    renderAt(PATH)

    await userEvent.click(await within(await money()).findByRole('button', { name: copy.changePlan }))
    const form = screen.getByRole('form', { name: change.title })
    await userEvent.selectOptions(await within(form).findByLabelText(change.plan), 'plan-six')
    await within(form).findByText(change.next('Semestral', shortDay('2026-11-30'), '$240.000', shortDay('2027-05-29')))
    await userEvent.click(within(form).getByRole('button', { name: change.submit }))

    expect(await within(form).findByRole('alert')).toHaveTextContent(change.refused.conflict)
  })

  it('offers no "Cambiar plan" on a pack', async () => {
    active(undefined, { ...MONTHLY, plan_kind: 'credits', anchor_day: null, plan_name: 'Pack 12' })
    renderAt(PATH)
    await within(await money()).findByRole('button', { name: copy.record })
    expect(screen.queryByRole('button', { name: copy.changePlan })).not.toBeInTheDocument()
  })
})

describe('Volver, to where the ficha was opened from (#250)', () => {
  // Opened from each of these, as their links do: a new history entry on top.
  it.each([
    ['Hoy', '/admin', 'Volver a Hoy'],
    ['Pagos with a filter', '/admin/pagos?filter=pending&q=Feli', 'Volver a Pagos'],
    ['a class roster', '/admin/clases/s1', 'Volver a la clase'],
    ['Alumnos with a belt filter', '/admin/alumnos?belt=blue&beltUp=true&q=Feli', 'Volver a Alumnos'],
  ])('goes back to %s, its filters still there', async (_from, from, label) => {
    stubApi()
    const router = renderAt(from)
    await waitFor(() => expect(router.state.location.href).toBe(from))
    await router.navigate({ href: PATH })

    expect(await screen.findByRole('heading', { name: 'Felipe Díaz' })).toBeInTheDocument()
    const back = screen.getByRole('link', { name: label })
    expect(back).toHaveAttribute('href', from)
    await userEvent.click(back)

    await waitFor(() => expect(router.state.location.href).toBe(from))
    // Back in history, not a new entry: forward returns to the ficha.
    expect(router.history.location.state.__TSR_index).toBe(0)
    expect(router.history.length).toBe(2)
  })

  it('goes to Alumnos when the ficha was opened directly', async () => {
    stubApi()
    const router = renderAt(PATH)

    const back = await screen.findByRole('link', { name: copy.back })
    expect(back).toHaveAttribute('href', '/admin/alumnos')
    await userEvent.click(back)

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos'))
    expect(router.history.length).toBe(2)
  })

  it('goes to Alumnos when what came before was not shown by the app', async () => {
    // A page the browser had before this load: a reload, or another site.
    stubApi()
    const router = renderAt(['/admin/pagos', PATH])

    await userEvent.click(await screen.findByRole('link', { name: copy.back }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos'))
  })

  it('goes to Alumnos after signing in, not back to the sign-in page', async () => {
    stubApi()
    const router = renderAt('/ingresar')
    await screen.findByRole('heading', { level: 1 })
    await router.navigate({ href: PATH })

    const back = await screen.findByRole('link', { name: copy.back })
    expect(back).toHaveAttribute('href', '/admin/alumnos')
    await userEvent.click(back)

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos'))
  })

  it('names nothing it does not know: just Volver', async () => {
    stubApi()
    const router = renderAt('/admin/alumnos/importar')
    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos/importar'))
    await router.navigate({ href: PATH })

    expect(await screen.findByRole('link', { name: es.common.back })).toHaveAttribute('href', '/admin/alumnos/importar')
  })
})

describe('a freeze the member asked for (#270)', () => {
  const freezes = es.admin.freezeRequests
  const asked = {
    id: 'fr-1',
    membership_id: 'm-felipe',
    person_id: 'felipe',
    person_name: 'Felipe Díaz',
    requested_by: 'felipe',
    requested_by_name: 'Felipe Díaz',
    plan_name: 'Mensual adultos',
    from_date: '2099-11-20',
    to_date: '2099-12-04',
    reason: 'viaje',
    note: null,
    status: 'pending',
    decision_note: null,
    decided_at: null,
    created_at: '2026-11-13T12:00:00Z',
  }

  it('waits on the plan card, and approving freezes the plan', async () => {
    let waiting = [asked]
    const calls = stubApi({
      extra: (path, method) => {
        if (path === '/api/freeze-requests') return { body: waiting }
        if (path === '/api/freeze-requests/fr-1/approve' && method === 'POST') {
          waiting = []
          return { body: { ...MONTHLY, status: 'frozen', freeze: { id: 'f1', from_date: '2099-11-20', to_date: '2099-12-04', reason: 'Viaje', started: false } } }
        }
        return undefined
      },
    })
    renderAt(PATH)
    const card = within(await money())

    expect(await card.findByText(freezes.onCard)).toBeInTheDocument()
    expect(card.getByText(freezes.dates('20 nov', '4 dic'))).toBeInTheDocument()
    expect(card.getByText('Viaje')).toBeInTheDocument()
    await userEvent.click(card.getByRole('button', { name: freezes.approveLabel('Felipe Díaz') }))
    await userEvent.click(card.getByRole('button', { name: freezes.confirmApprove }))

    expect(await card.findByText(freezes.approved('Felipe Díaz', '4 dic'))).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/freeze-requests/fr-1/approve')?.body).toEqual({})
    expect(card.queryByText(freezes.onCard)).not.toBeInTheDocument()
  })

  it('is not asked for by a coach', async () => {
    const calls = stubApi({ role: 'coach', extra: (path) => (path === '/api/freeze-requests' ? { body: [asked] } : undefined) })
    renderAt(PATH)

    await screen.findByRole('heading', { level: 1, name: 'Felipe Díaz' })
    expect(screen.queryByText(freezes.onCard)).not.toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/freeze-requests')).toBe(false)
  })
})

describe('Reactivar plan caducado (#284)', () => {
  const LAPSED: Membership = { ...MONTHLY, status: 'lapsed' }
  const QUOTE = {
    last: {
      bills_from: '2026-09-30',
      periods: [
        { period_start: '2026-09-30', period_end: '2026-10-29', due_date: '2026-09-30', amount_due_clp: 45000 },
        { period_start: '2026-10-30', period_end: '2026-11-29', due_date: '2026-10-30', amount_due_clp: 45000 },
      ],
      total_clp: 90000,
    },
    today: {
      bills_from: '2026-11-10',
      periods: [{ period_start: '2026-11-10', period_end: '2026-12-09', due_date: '2026-11-10', amount_due_clp: 45000 }],
      total_clp: 45000,
    },
  }
  const form = copy.reactivateForm

  function stubReactivation(quote: { status?: number; body: unknown } = { body: QUOTE }, ledger = LEDGER) {
    return stubApi({
      memberships: [LAPSED],
      ledger,
      extra: (path, method) => {
        if (path !== '/api/memberships/m-felipe/reactivate') return undefined
        return method === 'POST' ? { body: { ...MONTHLY, status: 'active' } } : quote
      },
    })
  }

  it('reactivates a lapsed plan from where it left off, listing what it bills before it saves', async () => {
    const calls = stubReactivation()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.reactivatePlan }))
    const opened = screen.getByRole('form', { name: form.title })
    const last = await within(opened).findByRole('radio', { name: new RegExp(form.last) })
    expect(last).toBeChecked()
    expect(within(opened).getByText(form.lastHint(2, 'septiembre', '$90.000'))).toBeInTheDocument()
    expect(within(opened).getByText(form.todayHint('10 nov', '$45.000'))).toBeInTheDocument()

    // A reason first.
    await userEvent.click(within(opened).getByRole('button', { name: form.next }))
    expect(within(opened).getByText(form.reasonNeeded)).toBeInTheDocument()
    await userEvent.type(within(opened).getByLabelText(form.reason), 'volvió')
    await userEvent.click(within(opened).getByRole('button', { name: form.next }))

    // The second step lists what it bills; nothing is saved yet.
    const confirm = screen.getByRole('form', { name: form.title })
    expect(within(confirm).getByText(form.period('septiembre', '$45.000'))).toBeInTheDocument()
    expect(within(confirm).getByText(form.period('octubre', '$45.000'))).toBeInTheDocument()
    expect(within(confirm).getByText(form.total('$90.000'))).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
    await userEvent.click(within(confirm).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(form.done('$90.000'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/memberships/m-felipe/reactivate', body: { reason: 'volvió', bill_from: 'last' } },
    ])
  })

  it('reactivates from today, and goes back to change it', async () => {
    const calls = stubReactivation()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.reactivatePlan }))
    const opened = screen.getByRole('form', { name: form.title })
    await userEvent.type(await within(opened).findByLabelText(form.reason), 'volvió')
    await userEvent.click(within(opened).getByRole('button', { name: form.next }))
    await userEvent.click(within(opened).getByRole('button', { name: form.back }))
    await userEvent.click(within(opened).getByRole('radio', { name: new RegExp(form.today) }))
    await userEvent.click(within(opened).getByRole('button', { name: form.next }))
    expect(within(opened).getByText(form.period('noviembre', '$45.000'))).toBeInTheDocument()
    await userEvent.click(within(opened).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(form.done('$45.000'))
    expect(calls.filter((c) => c.method === 'POST')[0]?.body).toEqual({ reason: 'volvió', bill_from: 'today' })
  })

  it('says what to do first while a period past grace is unpaid', async () => {
    stubReactivation({
      status: 409,
      body: { detail: { code: 'unpaid', message: 'unpaid', amount_clp: 45000, period_start: '2026-10-30' } },
    })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.reactivatePlan }))
    const group = screen.getByRole('group', { name: form.title })
    expect(await within(group).findByRole('alert')).toHaveTextContent(copy.reactivateRefused.unpaid('$45.000', 'octubre'))
    expect(within(group).queryByLabelText(form.reason)).not.toBeInTheDocument()
  })

  it('says so beside another live plan', async () => {
    stubReactivation({
      status: 409,
      body: { detail: { code: 'live_plan', message: 'live', plan_name: 'Mensual niños' } },
    })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.reactivatePlan }))
    expect(await screen.findByRole('alert')).toHaveTextContent(copy.reactivateRefused.live_plan('Mensual niños'))
  })

  it('is offered on a lapsed plan only', async () => {
    stubApi()
    renderAt(PATH)
    const card = await money()
    expect(await within(card).findByRole('button', { name: copy.record })).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.reactivatePlan })).not.toBeInTheDocument()
  })

  it('is offered, not done, once a payment settles the last debt of a lapsed plan', async () => {
    const calls = stubReactivation()
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    const payment = screen.getByRole('form', { name: copy.form.title })
    await userEvent.click(within(payment).getByRole('button', { name: copy.form.submit('$45.000') }))

    const done = await screen.findByRole('status')
    expect(done).toHaveTextContent(copy.form.recorded('$45.000'))
    expect(done).toHaveTextContent(copy.reactivateOffer)
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/ledger/payments'])
    await userEvent.click(within(done).getByRole('button', { name: copy.reactivatePlan }))
    expect(await screen.findByRole('form', { name: form.title })).toBeInTheDocument()
  })

  it('offers nothing after a payment that leaves a period of the lapsed plan owing', async () => {
    const NOVEMBER: OpenPeriod = { ...OCTOBER, id: 'p-nov', period_start: '2026-11-30', due_date: '2026-11-30' }
    stubReactivation({ body: QUOTE }, { ...LEDGER, open_periods: [OCTOBER, NOVEMBER], owed_clp: 90000 })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.record }))
    const payment = screen.getByRole('form', { name: copy.form.title })
    await userEvent.click(within(payment).getByRole('button', { name: copy.form.submit('$45.000') }))

    const done = await screen.findByRole('status')
    expect(done).toHaveTextContent(copy.form.recorded('$45.000'))
    expect(done).not.toHaveTextContent(copy.reactivateOffer)
  })
})

describe('Reactivar plan with no gap to skip (#284)', () => {
  it('offers no choice when from today bills as from where it left off', async () => {
    const same = {
      bills_from: '2026-11-30',
      periods: [{ period_start: '2026-11-30', period_end: '2026-12-29', due_date: '2026-11-30', amount_due_clp: 45000 }],
      total_clp: 45000,
    }
    stubApi({
      memberships: [{ ...MONTHLY, status: 'lapsed' }],
      extra: (path) => (path === '/api/memberships/m-felipe/reactivate' ? { body: { last: same, today: same } } : undefined),
    })
    renderAt(PATH)
    const card = await money()

    await userEvent.click(await within(card).findByRole('button', { name: copy.reactivatePlan }))
    const form = screen.getByRole('form', { name: copy.reactivateForm.title })
    expect(await within(form).findByText(copy.reactivateForm.lastHint(1, 'noviembre', '$45.000'))).toBeInTheDocument()
    expect(within(form).queryByRole('radio')).not.toBeInTheDocument()
  })
})

describe('Reactivar plan, not on a pack (#284)', () => {
  it('is not offered on a lapsed pack or trial, which can only be refused', async () => {
    stubApi({ memberships: [{ ...MONTHLY, plan_kind: 'credits', anchor_day: null, status: 'lapsed' }] })
    renderAt(PATH)
    const card = await money()
    expect(await within(card).findByRole('button', { name: copy.record })).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: copy.reactivatePlan })).not.toBeInTheDocument()
  })

  it('reads the quote again on reopen, never showing the last one', async () => {
    let total = 45000
    stubApi({
      memberships: [{ ...MONTHLY, status: 'lapsed' }],
      extra: (path) => {
        if (path !== '/api/memberships/m-felipe/reactivate') return undefined
        const bill = {
          bills_from: '2026-11-30',
          periods: [{ period_start: '2026-11-30', period_end: '2026-12-29', due_date: '2026-11-30', amount_due_clp: total }],
          total_clp: total,
        }
        return { body: { last: bill, today: bill } }
      },
    })
    renderAt(PATH)
    const card = await money()
    const button = await within(card).findByRole('button', { name: copy.reactivatePlan })

    await userEvent.click(button)
    expect(await screen.findByText(copy.reactivateForm.lastHint(1, 'noviembre', '$45.000'))).toBeInTheDocument()
    await userEvent.click(button)
    total = 40000
    // The new quote is held until the form has shown what it shows meanwhile.
    let release = () => {}
    const held = new Promise<void>((resolve) => (release = resolve))
    const answer = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(async (input, init) => {
        if (String(input).includes('/reactivate')) await held
        return answer(input, init)
      }),
    )
    await userEvent.click(button)
    // Loading, not the last quote, while the new one is read.
    expect(screen.getByText(copy.reactivateForm.loading)).toBeInTheDocument()
    expect(screen.queryByText(copy.reactivateForm.lastHint(1, 'noviembre', '$45.000'))).not.toBeInTheDocument()
    release()
    expect(await screen.findByText(copy.reactivateForm.lastHint(1, 'noviembre', '$40.000'))).toBeInTheDocument()
  })
})

describe('Historial: alumno desde y clases antes de Rakin (#293)', () => {
  const history = () => screen.findByRole('region', { name: copy.history.title })

  it('reads alumno desde from the day they first trained here, when earlier than their first plan', async () => {
    stubApi({ person: { body: { ...FELIPE, member_since: '2019-03-05' } }, grading: { current: null, events: [] } })
    renderAt(PATH)

    expect(await screen.findByText(copy.since('mar 2019'))).toBeInTheDocument()
  })

  it('keeps the first plan when it is earlier, and the record’s day with neither', async () => {
    stubApi({ person: { body: { ...FELIPE, member_since: '2025-06-01' } }, grading: { current: null, events: [] } })
    renderAt(PATH)
    expect(await screen.findByText(copy.since('mar 2024'))).toBeInTheDocument()
  })

  it('adds the classes before Rakin to the total, and says how many', async () => {
    stubApi({ attendance: { body: { last_30_days: 9, total: 504, before_rakin: 320, since_promotion: 62 } } })
    renderAt(PATH)

    const card = await screen.findByRole('region', { name: copy.attendance.title })
    expect(within(card).getByText('clases en 30 días · 504 clases (320 antes de Rakin)')).toBeInTheDocument()
  })

  it('writes the start and the classes from the ficha, in place', async () => {
    let saved: Person = FELIPE
    const calls = stubApi({
      person: undefined,
      extra: (path, method, body) => {
        if (path === '/api/people/felipe/history' && method === 'PUT') {
          saved = { ...FELIPE, ...(body as Partial<Person>) }
          return { body: saved }
        }
        if (path === '/api/people/felipe' && method === 'GET') return { body: saved }
        return undefined
      },
    })
    renderAt(PATH)

    const card = await history()
    expect(await within(card).findByText(copy.history.empty)).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: copy.history.add }))
    await userEvent.click(within(card).getByRole('button', { name: copy.history.start }))
    const form = within(card).getByRole('form', { name: copy.history.form.title })
    fireEvent.change(within(form).getByLabelText(copy.history.form.since), { target: { value: '2019-03-05' } })
    const classes = within(form).getByLabelText(copy.history.form.classes)
    await userEvent.clear(classes)
    await userEvent.type(classes, '320')
    await userEvent.click(within(form).getByRole('button', { name: copy.history.form.submit }))

    expect(await within(card).findByRole('status')).toHaveTextContent(copy.history.saved)
    expect(calls.find((c) => c.path === '/api/people/felipe/history')?.body).toEqual({
      member_since: '2019-03-05',
      prior_classes: 320,
    })
    expect(await within(card).findByText(copy.history.memberSince('5 mar 2019'))).toBeInTheDocument()
    expect(within(card).getByText(copy.history.priorClasses(320))).toBeInTheDocument()
    expect(await screen.findByText(/alumno desde mar 2019/)).toBeInTheDocument()
  })

  it('refuses a negative count before sending it', async () => {
    const calls = stubApi()
    renderAt(PATH)

    const card = await history()
    await userEvent.click(within(card).getByRole('button', { name: copy.history.add }))
    await userEvent.click(within(card).getByRole('button', { name: copy.history.start }))
    const form = within(card).getByRole('form', { name: copy.history.form.title })
    fireEvent.change(within(form).getByLabelText(copy.history.form.classes), { target: { value: '-3' } })
    await userEvent.click(within(form).getByRole('button', { name: copy.history.form.submit }))

    expect(within(form).getByRole('alert')).toHaveTextContent(copy.history.form.classesNeeded)
    expect(calls.some((c) => c.path === '/api/people/felipe/history')).toBe(false)
  })

  it('is not on a coach’s ficha', async () => {
    stubApi({ role: 'coach' })
    renderAt(PATH)

    await screen.findByRole('region', { name: copy.attendance.title })
    expect(screen.queryByRole('region', { name: copy.history.title })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.history.add })).not.toBeInTheDocument()
  })

  it('offers its choices just after "Agregar exalumno" (#294)', async () => {
    stubApi()
    const router = renderAt('/admin/alumnos')
    await router.navigate({ to: '/admin/alumnos/$personId', params: { personId: 'felipe' }, state: { offerHistory: true } })

    const card = await history()
    expect(within(card).getByRole('button', { name: copy.history.add })).toHaveAttribute('aria-expanded', 'true')
    expect(within(card).getByRole('button', { name: copy.history.start })).toBeInTheDocument()
  })
})

describe('Historial de pagos: pagos anteriores a Rakin (#295)', () => {
  const words = copy.history
  const form = words.paymentsForm
  const history = () => screen.findByRole('region', { name: words.title })
  const MARCH: HistoryPayment = {
    id: 'h-mar',
    paid_on: '2023-03-05',
    amount_clp: 25000,
    method: 'transfer',
    covers_month: '2023-03-01',
    plan_name: 'Mensual 3x semana',
    note: null,
    source: 'manual',
    import_name: null,
    created_by_name: 'Martín',
    created_at: '2026-11-14T15:00:00Z',
  }

  /** The API as a store: what is posted is read back, by year, newest first. */
  function stubHistory(initial: HistoryPayment[] = [], planFrom: string | null = null, refuse?: Answer) {
    let payments = initial
    const read = (): HistoryPayments => {
      const years = new Map<number, HistoryPayment[]>()
      for (const p of [...payments].sort((a, b) => ((b.covers_month ?? b.paid_on) > (a.covers_month ?? a.paid_on) ? 1 : -1))) {
        const year = Number((p.covers_month ?? p.paid_on).slice(0, 4))
        years.set(year, [...(years.get(year) ?? []), p])
      }
      return {
        plan_from: planFrom,
        years: [...years.entries()]
          .sort(([a], [b]) => b - a)
          .map(([year, ps]) => ({ year, count: ps.length, total_clp: ps.reduce((sum, p) => sum + p.amount_clp, 0), payments: ps })),
      }
    }
    return stubApi({
      extra: (path, method, body) => {
        if (path !== '/api/people/felipe/history/payments' && !path.startsWith('/api/people/felipe/history/payments/')) return undefined
        if (method === 'GET') return { body: read() }
        if (path.endsWith('/remove')) {
          const id = path.split('/').at(-2)
          payments = payments.filter((p) => p.id !== id)
          return { body: read() }
        }
        if (refuse) return refuse
        const sent = (body as { payments: HistoryPaymentIn[] }).payments
        payments = [
          ...payments,
          ...sent.map((p, i) => ({ ...MARCH, ...p, id: `h-${payments.length + i}`, note: null })),
        ]
        return { status: 201, body: read() }
      },
    })
  }

  async function openForm() {
    const card = await history()
    await userEvent.click(within(card).getByRole('button', { name: words.add }))
    await userEvent.click(within(card).getByRole('button', { name: words.payments }))
    return { card, form: within(card).getByRole('form', { name: form.title }) }
  }

  function fill(f: HTMLElement, from: string, to: string, amount: string) {
    fireEvent.change(within(f).getByLabelText(form.from), { target: { value: from } })
    fireEvent.change(within(f).getByLabelText(form.to), { target: { value: to } })
    fireEvent.change(within(f).getByLabelText(form.amount), { target: { value: amount } })
  }

  it('fills a row per month and saves twelve as one year with its total', async () => {
    const calls = stubHistory()
    renderAt(PATH)

    const { card, form: f } = await openForm()
    fill(f, '2024-01', '2024-12', '25000')
    fireEvent.change(within(f).getByLabelText(form.plan), { target: { value: 'Mensual 3x semana' } })
    const months = within(f).getByRole('list', { name: form.months })
    expect(within(months).getAllByRole('listitem')).toHaveLength(12)
    expect(within(f).getByText(form.total(12, '$300.000'))).toBeInTheDocument()
    // Day 5 by default; one month paid on another day, another for less.
    fireEvent.change(within(f).getByLabelText(form.rowDay('mar 2024')), { target: { value: '10' } })
    fireEvent.change(within(f).getByLabelText(form.rowAmount('abr 2024')), { target: { value: '20000' } })
    expect(within(f).getByText(form.total(12, '$295.000'))).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: form.submit(12) }))

    expect(await within(card).findByRole('status')).toHaveTextContent(form.saved(12))
    const sent = (calls.find((c) => c.method === 'POST' && c.path === '/api/people/felipe/history/payments')?.body as {
      payments: HistoryPaymentIn[]
    }).payments
    expect(sent).toHaveLength(12)
    expect(sent[0]).toEqual({
      paid_on: '2024-01-05',
      amount_clp: 25000,
      method: 'transfer',
      covers_month: '2024-01-01',
      plan_name: 'Mensual 3x semana',
    })
    expect(sent[2]!.paid_on).toBe('2024-03-10')
    expect(sent[3]!.amount_clp).toBe(20000)
    const year = within(card).getByRole('button', { name: /2024 · 12 pagos/ })
    expect(year).toHaveTextContent('$295.000')
    expect(year).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(year)
    const lines = within(card).getAllByRole('button', { name: /pagado el/ })
    expect(lines).toHaveLength(12)
    expect(lines[0]).toHaveTextContent('diciembre 2024')
    expect(lines[0]).toHaveTextContent('pagado el 5 dic 2024 · transferencia · Mensual 3x semana')
    expect(lines[0]).toHaveTextContent(words.line.typed('Martín', '14 nov'))
  })

  it('pays a short month on its last day, and never after today', () => {
    expect(paidOn('2024-02-01', 31, '2026-11-15')).toBe('2024-02-29')
    expect(paidOn('2026-11-01', 20, '2026-11-15')).toBe('2026-11-15')
    expect(monthsBetween('2023-11', '2024-02')).toEqual(['2023-11-01', '2023-12-01', '2024-01-01', '2024-02-01'])
  })

  it('takes a month off the list when it was not paid', async () => {
    const calls = stubHistory()
    renderAt(PATH)

    const { form: f } = await openForm()
    fill(f, '2024-01', '2024-03', '25000')
    await userEvent.click(within(f).getByRole('button', { name: form.removeRow('feb 2024') }))
    expect(within(f).getByText(form.total(2, '$50.000'))).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: form.submit(2) }))

    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    const sent = (calls.find((c) => c.method === 'POST')!.body as { payments: HistoryPaymentIn[] }).payments
    expect(sent.map((p) => p.covers_month)).toEqual(['2024-01-01', '2024-03-01'])
  })

  it('leaves out the months of their plan, pointing at Pagado hasta', async () => {
    stubHistory([], '2024-03-30')
    renderAt(PATH)

    const { form: f } = await openForm()
    fill(f, '2024-01', '2024-06', '25000')
    expect(within(within(f).getByRole('list', { name: form.months })).getAllByRole('listitem')).toHaveLength(3)
    expect(within(f).getByText(form.inPlan('abril 2024'))).toBeInTheDocument()
  })

  it('says when the API finds a month of their plan (covers_plan)', async () => {
    stubHistory([], null, {
      status: 422,
      body: { detail: { code: 'covers_plan', plan_from: '2024-03-30', months: ['2024-04-01'] } },
    })
    renderAt(PATH)

    const { form: f } = await openForm()
    fill(f, '2024-04', '2024-04', '25000')
    await userEvent.click(within(f).getByRole('button', { name: form.submit(1) }))
    expect(await within(f).findByRole('alert')).toHaveTextContent(form.coversPlan('30 mar 2024'))
  })

  it('warns, without refusing, of a payment equal to one already there', async () => {
    const calls = stubHistory([MARCH])
    renderAt(PATH)

    const { form: f } = await openForm()
    await waitFor(() => expect(calls.some((c) => c.path === '/api/people/felipe/history/payments')).toBe(true))
    fill(f, '2023-03', '2023-04', '25000')
    expect(within(f).getByText(form.duplicate)).toBeInTheDocument()
    expect(within(f).getByRole('status')).toHaveTextContent(form.duplicates(1))
    expect(within(f).getByRole('button', { name: form.submit(2) })).toBeEnabled()
  })

  it('refuses a form with no range or no amount before sending it', async () => {
    const calls = stubHistory()
    renderAt(PATH)

    const { form: f } = await openForm()
    await userEvent.click(within(f).getByRole('button', { name: form.submit(0) }))
    expect(within(f).getByRole('alert')).toHaveTextContent(form.rangeNeeded)
    fill(f, '2024-01', '2024-02', '')
    expect(within(f).getByRole('alert')).toHaveTextContent(form.amountNeeded)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows the years newest first, collapsed, and the older ones on asking', async () => {
    stubHistory(
      [2019, 2020, 2021, 2022].map((year) => ({
        ...MARCH,
        id: `h-${year}`,
        paid_on: `${year}-03-05`,
        covers_month: `${year}-03-01`,
      })),
    )
    renderAt(PATH)

    const card = await history()
    const years = await within(card).findAllByRole('button', { name: /· 1 pago/ })
    expect(years.map((y) => y.textContent)).toEqual(['2022 · 1 pago$25.000', '2021 · 1 pago$25.000', '2020 · 1 pago$25.000'])
    await userEvent.click(within(card).getByRole('button', { name: words.earlier(1) }))
    expect(within(card).getAllByRole('button', { name: /· 1 pago/ })).toHaveLength(4)
  })

  it('removes a line with a reason, and the source of an imported one', async () => {
    const imported: HistoryPayment = { ...MARCH, id: 'h-imp', paid_on: '2023-04-05', covers_month: '2023-04-01', source: 'import', import_name: 'pagos.xlsx', created_by_name: 'Ana' }
    const calls = stubHistory([MARCH, imported])
    renderAt(PATH)

    const card = await history()
    await userEvent.click(await within(card).findByRole('button', { name: /2023 · 2 pagos/ }))
    expect(within(card).getByText(words.line.imported('pagos.xlsx', 'Ana', '14 nov'))).toBeInTheDocument()
    await userEvent.click(within(card).getByRole('button', { name: /marzo 2023/ }))
    const removal = within(card).getByRole('form', { name: words.remove.title('marzo 2023 · $25.000') })
    await userEvent.click(within(removal).getByRole('button', { name: words.remove.submit }))
    expect(within(removal).getByRole('alert')).toHaveTextContent(words.remove.reasonNeeded)
    await userEvent.type(within(removal).getByLabelText(words.remove.reason), 'mal tipeado')
    await userEvent.click(within(removal).getByRole('button', { name: words.remove.submit }))

    expect(await within(card).findByRole('status')).toHaveTextContent(words.remove.done)
    expect(calls.find((c) => c.path === '/api/people/felipe/history/payments/h-mar/remove')?.body).toEqual({
      reason: 'mal tipeado',
    })
    expect(await within(card).findByRole('button', { name: /2023 · 1 pago/ })).toBeInTheDocument()
  })

  it('is not read on a coach’s ficha', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt(PATH)

    await screen.findByRole('region', { name: copy.attendance.title })
    expect(calls.some((c) => c.path.includes('/history/payments'))).toBe(false)
  })
})
