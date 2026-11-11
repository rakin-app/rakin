import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ageOn, type JoinRequest } from '../api/join'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.joinRequests

const ANA: JoinRequest = {
  id: 'r1',
  first_name: 'Ana',
  last_name: 'Pérez',
  rut: '7654321-6',
  phone: '+56987654321',
  email: 'ana@example.cl',
  dob: '1990-05-20',
  no_whatsapp: false,
  guardian: null,
  program_id: 'kids',
  program_name: 'Kids',
  created_at: '2026-11-09T15:00:00Z',
  rut_in_gym: { id: 'p9', name: 'Ana Antigua' },
  email_in_gym: null,
  ignored_email: 'ana@example.cl',
}

const JUAN: JoinRequest = {
  ...ANA,
  id: 'r2',
  first_name: 'Juan',
  rut: '12345678-5',
  phone: null,
  email: null,
  dob: '2016-03-01',
  guardian: { name: 'Marta Pérez', phone: '+56912345678', email: 'marta@example.cl' },
  no_whatsapp: true,
  program_id: null,
  program_name: null,
  rut_in_gym: null,
  ignored_email: null,
}

// No RUT: found by their email.
const LUCIA: JoinRequest = {
  ...ANA,
  id: 'r3',
  first_name: 'Lucía',
  rut: null,
  phone: null,
  email: 'lucia@example.cl',
  no_whatsapp: true,
  rut_in_gym: null,
  email_in_gym: { id: 'p7', name: 'Lucía Antigua' },
  ignored_email: null,
}

const PLANS = [
  { id: 'adultos', name: 'Mensual adultos', kind: 'monthly', program_id: null, active: true },
  { id: 'kids-plan', name: 'Mensual kids', kind: 'monthly', program_id: 'kids', active: true },
  { id: 'old', name: 'Antiguo', kind: 'monthly', program_id: null, active: false },
  { id: 'suelta', name: 'Clase suelta', kind: 'dropin', program_id: null, active: true },
]

type Call = { method: string; path: string; body: unknown }

function stubApi({
  role = 'owner',
  requests = [ANA, JUAN],
  approve,
}: {
  role?: string
  requests?: JoinRequest[]
  approve?: { status: number; body: unknown }
} = {}) {
  const calls: Call[] = []
  let queue = requests
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname, body })
      let answer: { status?: number; body?: unknown } = { status: 404, body: { detail: 'Not Found' } }
      if (url.pathname === '/api/me/role') answer = { body: { role, person_id: 'me' } }
      if (url.pathname === '/api/plans') answer = { body: PLANS }
      if (url.pathname === '/api/join-requests') answer = { body: { items: queue, total: queue.length } }
      const approved = /^\/api\/join-requests\/(\w+)\/approve$/.exec(url.pathname)
      if (approved && approve) answer = approve
      else if (approved) {
        queue = queue.filter((r) => r.id !== approved[1])
        answer = { body: { person_id: 'nuevo', membership_id: body.plan_id ? 'm1' : null } }
      }
      const rejected = /^\/api\/join-requests\/(\w+)$/.exec(url.pathname)
      if (rejected && method === 'DELETE') {
        queue = queue.filter((r) => r.id !== rejected[1])
        answer = { status: 204 }
      }
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function row(name: string) {
  return screen.findByRole('listitem', { name })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Solicitudes', () => {
  it('lists the requests in Alumnos, with a warning for a RUT or email already here', async () => {
    stubApi()
    renderAt('/admin/alumnos')

    expect(await screen.findByRole('heading', { name: copy.title(2) })).toBeInTheDocument()
    const ana = await row('Ana Pérez')
    expect(within(ana).getByText(`${es.common.rut('7654321-6')} · ${copy.age(ageOn(ANA.dob, new Date().toISOString().slice(0, 10))!)}`)).toBeInTheDocument()
    expect(within(ana).getByText(copy.program('Kids'))).toBeInTheDocument()
    expect(within(ana).getByRole('link', { name: copy.rutInGym('Ana Antigua') })).toHaveAttribute(
      'href',
      '/admin/alumnos/p9',
    )
    expect(within(ana).getByText(copy.ignoredEmail('ana@example.cl'))).toBeInTheDocument()
    const juan = await row('Juan Pérez')
    expect(within(juan).getByText(/Apoderado: Marta Pérez/)).toHaveTextContent(copy.noWhatsapp)
    expect(within(juan).queryByText(/no se usará/)).not.toBeInTheDocument()
  })

  it('warns of an email already here on a request with no RUT', async () => {
    stubApi({ requests: [LUCIA] })
    renderAt('/admin/alumnos')

    const lucia = await row('Lucía Pérez')
    expect(within(lucia).getByText(`lucia@example.cl · ${copy.noWhatsapp}`)).toBeInTheDocument()
    expect(within(lucia).getByRole('link', { name: copy.emailInGym('Lucía Antigua') })).toHaveAttribute(
      'href',
      '/admin/alumnos/p7',
    )
  })

  it('says to approve with no plan someone who is a member already', async () => {
    stubApi({ approve: { status: 409, body: { detail: { code: 'has_membership', field: 'plan_id' } } } })
    renderAt('/admin/alumnos')

    const ana = await row('Ana Pérez')
    const select = await within(ana).findByLabelText(copy.plan)
    await within(select).findByRole('option', { name: 'Mensual kids' })
    await userEvent.selectOptions(select, 'kids-plan')
    await userEvent.click(within(ana).getByRole('button', { name: copy.approveLabel('Ana Pérez') }))

    expect(await within(ana).findByRole('alert')).toHaveTextContent(copy.hasMembership)
  })

  it('says to reactivate someone dado de baja before approving them on a plan', async () => {
    stubApi({ approve: { status: 409, body: { detail: { code: 'has_left' } } } })
    renderAt('/admin/alumnos')

    const ana = await row('Ana Pérez')
    const select = await within(ana).findByLabelText(copy.plan)
    await within(select).findByRole('option', { name: 'Mensual kids' })
    await userEvent.selectOptions(select, 'kids-plan')
    await userEvent.click(within(ana).getByRole('button', { name: copy.approveLabel('Ana Pérez') }))

    expect(await within(ana).findByRole('alert')).toHaveTextContent(copy.hasLeft)
  })

  it('shows on Hoy for a coach, who approves with no plan', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt('/admin')

    const ana = await row('Ana Pérez')
    expect(within(ana).queryByLabelText(copy.plan)).not.toBeInTheDocument()
    expect(within(ana).getByText(copy.coachHint)).toBeInTheDocument()
    await userEvent.click(within(ana).getByRole('button', { name: copy.approveLabel('Ana Pérez') }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.approved('Ana Pérez'))
    expect(calls.find((c) => c.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/join-requests/r1/approve',
      body: {},
    })
    expect(calls.some((c) => c.path === '/api/plans')).toBe(false)
  })

  it('lets an owner give a plan, the request’s program first', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos')

    const ana = await row('Ana Pérez')
    const select = await within(ana).findByLabelText(copy.plan)
    await within(select).findByRole('option', { name: 'Mensual kids' })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      copy.noPlan,
      'Mensual kids',
      'Mensual adultos',
    ])
    await userEvent.selectOptions(select, 'kids-plan')
    await userEvent.click(within(ana).getByRole('button', { name: copy.approveLabel('Ana Pérez') }))

    await screen.findByRole('status')
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ plan_id: 'kids-plan' })
  })

  it('rejects once confirmed', async () => {
    const calls = stubApi()
    renderAt('/admin/alumnos')

    const juan = await row('Juan Pérez')
    await userEvent.click(within(juan).getByRole('button', { name: copy.rejectLabel('Juan Pérez') }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(juan).getByRole('button', { name: copy.confirm }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.rejected('Juan Pérez'))
    expect(calls.find((c) => c.method === 'DELETE')?.path).toBe('/api/join-requests/r2')
    expect(screen.queryByRole('listitem', { name: 'Juan Pérez' })).not.toBeInTheDocument()
  })

  it('shows nothing while the queue is empty', async () => {
    const calls = stubApi({ requests: [] })
    renderAt('/admin/alumnos')

    await vi.waitFor(() => expect(calls.some((c) => c.path === '/api/join-requests')).toBe(true))
    expect(screen.queryByRole('heading', { name: copy.title(0) })).not.toBeInTheDocument()
  })
})
