import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FieldDefinition } from '../api/customFields'
import type { Person } from '../api/member'
import type { MemberRow } from '../api/people'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { isMinor } from './NewMember'

const copy = es.admin.newMember

const CREATED: Person = {
  id: 'new',
  phone: '+56987654321',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  name: 'Camila Rojas',
  email: null,
  rut: null,
  dob: null,
  left_on: null,
  created_at: '2026-11-10T12:00:00Z',
}

const MARTA: MemberRow = {
  id: 'marta',
  name: 'Marta Vera',
  phone: '+56911112222',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  rut: null,
  membership: null,
  guardian: null,
  dependents: 0,
  left_on: null,
}

const TALLA: FieldDefinition = {
  key: 'talla',
  label: 'Talla',
  type: 'enum',
  options: ['S', 'M', 'L'],
  sensitive: false,
  visible_to: 'staff',
  archived: false,
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi(enrolled: Answer = { status: 201, body: CREATED }) {
  const calls: Call[] = []
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
    if (path === '/api/me/role') return { body: { role: 'owner', person_id: 'me' } }
    if (path === '/api/sessions') return { body: { date: '2026-11-10', timezone: 'America/Santiago', sessions: [] } }
    if (path === '/api/ledger/pending') return { body: { count: 0 } }
    if (path === '/api/custom-fields') return { body: [TALLA] }
    if (path === '/api/plans') {
      return {
        body: [
          { id: 'plan-adults', name: 'Mensual adultos', kind: 'monthly', active: true },
          { id: 'plan-dropin', name: 'Clase suelta', kind: 'dropin', active: true },
          { id: 'plan-old', name: 'Plan 2024', kind: 'monthly', active: false },
        ],
      }
    }
    if (path === '/api/people' && method === 'GET') return { body: { items: [MARTA], total: 1 } }
    if (path === '/api/people/enrol' && method === 'POST') return enrolled
    if (path === '/api/people/new') return { body: CREATED }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const form = () => screen.findByRole('form', { name: copy.title })
const enrolments = (calls: Call[]) => calls.filter((c) => c.path === '/api/people/enrol').map((c) => c.body)

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('isMinor', () => {
  it('is under 18 on the day, a 29 February birthday coming of age on the 28th', () => {
    expect(isMinor('2008-11-11', '2026-11-10')).toBe(true)
    expect(isMinor('2008-11-10', '2026-11-10')).toBe(false)
    expect(isMinor('2008-02-29', '2026-02-28')).toBe(false)
    expect(isMinor('2008-02-29', '2026-02-27')).toBe(true)
  })
})

describe('Nuevo alumno', () => {
  it('saves a member with a plan and opens their ficha', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.lastName), 'Rojas')
    await userEvent.type(within(f).getByLabelText(copy.phone), '9 8765 4321')
    await userEvent.type(within(f).getByLabelText(copy.rut), '7.654.321-6')
    await userEvent.selectOptions(await within(f).findByLabelText('Talla'), 'M')
    const plan = within(f).getByLabelText(copy.plan)
    // A drop-in is a single class and a deactivated plan takes no one new.
    expect(within(plan).queryByRole('option', { name: 'Clase suelta' })).not.toBeInTheDocument()
    expect(within(plan).queryByRole('option', { name: 'Plan 2024' })).not.toBeInTheDocument()
    await userEvent.selectOptions(plan, 'plan-adults')
    await userEvent.click(within(f).getByRole('checkbox', { name: copy.welcome }))
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/alumnos/new'))
    expect(enrolments(calls)).toEqual([
      {
        name: 'Camila Rojas',
        phone: '9 8765 4321',
        rut: '7.654.321-6',
        fields: { talla: 'M' },
        membership: { plan_id: 'plan-adults' },
        send_welcome: true,
      },
    ])
  })

  it('keeps the welcome off without a plan', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    expect(within(f).getByRole('checkbox', { name: copy.welcome })).toBeDisabled()
    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.email), 'camila@example.com')
    await userEvent.type(within(f).getByLabelText(copy.phone), '987654321')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    await waitFor(() =>
      expect(enrolments(calls)).toEqual([
        { name: 'Camila', email: 'camila@example.com', phone: '987654321', send_welcome: false },
      ]),
    )
  })

  it('asks a minor for a guardian, and takes one already in the gym', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Tomás')
    await userEvent.type(within(f).getByLabelText(copy.dob), '2016-05-04')
    expect(within(f).getByText(copy.guardianMinor)).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))
    expect(within(f).getByText(copy.needed.guardian)).toBeInTheDocument()
    expect(enrolments(calls)).toEqual([])

    await userEvent.click(within(f).getByRole('button', { name: copy.guardianExisting }))
    await userEvent.type(within(f).getByRole('searchbox', { name: copy.guardianSearch }), 'Marta')
    await userEvent.click(await within(f).findByRole('button', { name: copy.guardianPickLabel('Marta Vera') }))
    expect(within(f).getByText(copy.guardianPicked('Marta Vera'))).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    await waitFor(() =>
      expect(enrolments(calls)).toEqual([
        { name: 'Tomás', dob: '2016-05-04', guardian: { person_id: 'marta' }, send_welcome: false },
      ]),
    )
  })

  it('takes a new guardian by RUT or email, with their phone', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Tomás')
    await userEvent.click(within(f).getByRole('button', { name: copy.guardianNew }))
    await userEvent.type(within(f).getByLabelText(copy.guardianName), 'Marta Vera')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))
    expect(within(f).getByText(copy.needed.guardianIdentity)).toBeInTheDocument()
    expect(within(f).getByText(copy.needed.guardianPhone)).toBeInTheDocument()

    await userEvent.type(within(f).getByLabelText(copy.guardianRut), '11.111.111-1')
    await userEvent.type(within(f).getByLabelText(copy.guardianPhone), '+56 9 1111 2222')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    await waitFor(() =>
      expect(enrolments(calls)).toEqual([
        {
          name: 'Tomás',
          guardian: { name: 'Marta Vera', rut: '11.111.111-1', phone: '+56 9 1111 2222' },
          send_welcome: false,
        },
      ]),
    )
  })

  it('needs a RUT or an email, and a phone, when there is no guardian', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.phone), '22 345 6789')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    expect(within(f).getByText(copy.needed.identity)).toBeInTheDocument()
    expect(within(f).getByText(copy.needed.phone)).toBeInTheDocument()
    expect(enrolments(calls)).toEqual([])
  })

  it('saves someone with no phone when "No tiene WhatsApp" is ticked', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.rut), '7.654.321-6')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))
    expect(within(f).getByText(copy.needed.phone)).toBeInTheDocument()

    await userEvent.click(within(f).getByRole('checkbox', { name: copy.noWhatsapp }))
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    await waitFor(() =>
      expect(enrolments(calls)).toEqual([
        { name: 'Camila', rut: '7.654.321-6', no_whatsapp: true, send_welcome: false },
      ]),
    )
  })

  it('marks the field the API refused, under the field, rather than a generic error (#211)', async () => {
    const refusal = (loc: string[]) => ({ type: 'value_error', loc: ['body', ...loc], msg: 'Value error' })
    stubApi({
      status: 422,
      body: {
        detail: [
          refusal(['rut']),
          { type: 'date_past', loc: ['body', 'dob'], msg: 'Date should be in the past' },
          refusal(['guardian', 'function-after[_identified(), NewGuardian]', 'email']),
          // The other branch of the union says nothing about what was typed.
          { type: 'extra_forbidden', loc: ['body', 'guardian', 'ExistingGuardian', 'rut'], msg: 'Extra inputs' },
        ],
      },
    })
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.rut), '12.345.678-0')
    await userEvent.type(within(f).getByLabelText(copy.phone), '987654321')
    await userEvent.click(within(f).getByRole('button', { name: copy.guardianNew }))
    await userEvent.type(within(f).getByLabelText(copy.guardianName), 'Marta Vera')
    await userEvent.type(within(f).getByLabelText(copy.guardianEmail), 'marta@example')
    await userEvent.type(within(f).getByLabelText(copy.guardianPhone), '+56 9 1111 2222')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    expect(await within(f).findByText(copy.refused.rut)).toBeInTheDocument()
    expect(within(f).getByLabelText(copy.rut)).toHaveAttribute('aria-invalid', 'true')
    expect(within(f).getByText(copy.refused.dob)).toBeInTheDocument()
    expect(within(f).getByLabelText(copy.guardianEmail)).toHaveAttribute('aria-invalid', 'true')
    expect(within(f).getByLabelText(copy.guardianRut)).toHaveAttribute('aria-invalid', 'false')
    expect(within(f).getByLabelText(copy.email)).toHaveAttribute('aria-invalid', 'false')
    expect(within(f).getByText(copy.refused.fields)).toBeInTheDocument()
    expect(within(f).queryByText(copy.refused.invalid)).not.toBeInTheDocument()
  })

  it('keeps the general message for a 422 that names no field it shows', async () => {
    stubApi({ status: 422, body: { detail: [{ type: 'value_error', loc: ['body'], msg: 'Value error' }] } })
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.rut), '7.654.321-6')
    await userEvent.type(within(f).getByLabelText(copy.phone), '987654321')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    expect(await within(f).findByText(copy.refused.invalid)).toBeInTheDocument()
  })

  it('names who already has the RUT, with a link to their ficha', async () => {
    stubApi({ status: 409, body: { detail: { code: 'rut_in_gym', person_id: 'camila' } } })
    renderAt('/admin/alumnos/nuevo')
    const f = await form()

    await userEvent.type(within(f).getByLabelText(copy.firstName), 'Camila')
    await userEvent.type(within(f).getByLabelText(copy.rut), '7.654.321-6')
    await userEvent.type(within(f).getByLabelText(copy.phone), '987654321')
    await userEvent.click(within(f).getByRole('button', { name: copy.submit }))

    const alert = await within(f).findByText(copy.duplicate.rut_in_gym, { exact: false })
    expect(within(alert).getByRole('link', { name: copy.duplicate.open })).toHaveAttribute(
      'href',
      '/admin/alumnos/camila',
    )
  })
})
