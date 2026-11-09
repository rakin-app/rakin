import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FieldValue, PersonField } from '../api/customFields'
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

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  person?: Answer
  memberships?: Membership[]
  ledger?: MembershipLedger
  payment?: Answer
  fields?: PersonField[]
  fieldsUpdate?: Answer
}

function stubApi({
  role = 'owner',
  person,
  memberships = [MONTHLY],
  ledger = LEDGER,
  payment,
  fields = [],
  fieldsUpdate,
}: Stub = {}) {
  const calls: Call[] = []
  let current = ledger
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
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/ledger/pending') return { body: { count: 0 } }
    if (path === '/api/people/felipe') return person ?? { body: FELIPE }
    if (path === '/api/memberships' && url.searchParams.get('person_id') === 'felipe') return { body: memberships }
    if (path === '/api/ledger/memberships/m-felipe') return { body: current }
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
    expect(screen.getByText(copy.since('mar 2024'))).toBeInTheDocument()
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

  it('says when the member has no plan', async () => {
    stubApi({ memberships: [] })
    renderAt(PATH)

    expect(await screen.findByText(copy.noPlan)).toBeInTheDocument()
    expect(screen.getByText(copy.since('ene 2025'))).toBeInTheDocument()
  })

  it('says when there is no such member', async () => {
    stubApi({ person: { status: 404, body: { detail: 'person not found' } } })
    renderAt(PATH)

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.notFound)
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
    const rows = within(section).getAllByRole('term').map((term) => [term.textContent, term.nextSibling?.textContent])
    expect(rows).toEqual([
      ['Contacto de emergencia', 'Ana Díaz +56 9 8765 4321'],
      ['Categoría competencia', 'Pluma'],
      ['Peso (kg)', '72,5'],
      ['Fecha de ingreso', copy.fields.empty],
      [`Notas médicas${copy.fields.sensitive}`, 'Asma'],
    ])
  })

  it('draws nothing when no field is open to the role', async () => {
    stubApi({ role: 'coach', fields: [] })
    renderAt(PATH)

    await screen.findByRole('region', { name: es.admin.family.toggle })
    expect(screen.queryByRole('region', { name: copy.fields.title })).not.toBeInTheDocument()
  })

  it('saves only the fields that changed', async () => {
    const calls = stubApi({ fields: FIELDS })
    renderAt(PATH)

    await userEvent.click(within(await fields()).getByRole('button', { name: copy.fields.edit }))
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

    await userEvent.click(within(await fields()).getByRole('button', { name: copy.fields.edit }))
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
