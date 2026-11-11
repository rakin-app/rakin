import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { StaffMember } from '../api/staff'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.staff
const form = copy.form

const since = '2026-10-01T12:00:00Z'
const OWNER: StaffMember = { person_id: 'o', name: 'Martín', phone: '+56911111111', email: 'martin@example.cl', role: 'owner', since }
const ADMIN: StaffMember = { person_id: 'a', name: 'Carla', phone: '+56922222222', email: 'carla@example.cl', role: 'admin', since }
const COACH: StaffMember = { person_id: 'c', name: 'Beto', phone: '+56933333333', email: null, role: 'coach', since }

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ role = 'owner', invite }: { role?: string; invite?: Answer } = {}) {
  const calls: Call[] = []
  let staff = [OWNER, ADMIN, COACH]
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Record<string, unknown>
      calls.push({ method, path: url.pathname, body })
      const answer = route(url.pathname, method, body)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: Record<string, unknown>): Answer {
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/staff' && method === 'GET') return { body: staff }
    if (path === '/api/staff' && method === 'POST') {
      if (invite) return invite
      const created = { ...body, person_id: 'nuevo', since } as StaffMember
      staff = [...staff, created]
      return { status: 201, body: created }
    }
    const member = staff.find((s) => path === `/api/staff/${s.person_id}`)
    if (member && method === 'PATCH') {
      const updated = { ...member, ...body }
      staff = staff.map((s) => (s.person_id === member.person_id ? updated : s))
      return { body: updated }
    }
    if (member && method === 'DELETE') {
      staff = staff.filter((s) => s.person_id !== member.person_id)
      return { status: 204 }
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

async function section() {
  return screen.findByRole('region', { name: copy.title })
}

async function row(name: string) {
  return within(await section()).findByRole('listitem', { name })
}

/** A member the signed-in role may act on: their row is a button, named by its text. */
async function rowButton(name: string) {
  return within(await section()).findByRole('button', { name: new RegExp(`^${name}`) })
}

/** Opens a member's row, and answers the panel it opens to. */
async function open(name: string) {
  await userEvent.click(await rowButton(name))
  return within(await section()).getByRole('group', { name })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Equipo', () => {
  it('lists the staff with their roles, and the owner with no actions', async () => {
    stubApi()
    renderAt('/admin/ajustes/equipo')

    const owner = await row('Martín')
    expect(owner).toHaveTextContent(copy.roles.owner!)
    expect(within(owner).queryByRole('button')).not.toBeInTheDocument()
    // Phones as they read, not as stored.
    const admin = await rowButton('Carla')
    expect(admin).toHaveTextContent('+56 9 2222 2222 · carla@example.cl')
    // No Editar / Quitar pair on the row: its actions are behind it.
    expect(within(await section()).queryByRole('button', { name: copy.revoke })).not.toBeInTheDocument()

    const carla = await open('Carla')
    expect(within(carla).getByRole('button', { name: copy.makeCoach })).toBeInTheDocument()
    expect(within(carla).getByRole('button', { name: copy.revoke })).toBeInTheDocument()
    await userEvent.click(within(carla).getByRole('button', { name: copy.close }))
    expect(within(await section()).queryByRole('group', { name: 'Carla' })).not.toBeInTheDocument()

    // One open at a time.
    expect(within(await open('Beto')).getByRole('button', { name: copy.makeAdmin })).toBeInTheDocument()
  })

  it('invites a coach by name, phone and email', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await section()
    await userEvent.click(within(region).getByRole('button', { name: copy.add }))
    const invite = within(region).getByRole('form', { name: form.title })
    await userEvent.type(within(invite).getByLabelText(form.name), 'Pedro')
    await userEvent.type(within(invite).getByLabelText(form.phone), '9 4444 4444')
    await userEvent.type(within(invite).getByLabelText(form.email), 'pedro@example.cl')
    expect(within(invite).getByLabelText(form.role)).toHaveValue('coach')
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(region).findByRole('status')).toHaveTextContent(copy.invited('Pedro', 'pedro@example.cl'))
    expect(await rowButton('Pedro')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/staff',
        body: { name: 'Pedro', phone: '9 4444 4444', email: 'pedro@example.cl', role: 'coach' },
      },
    ])
  })

  it('says so when the person is already on the staff', async () => {
    stubApi({
      invite: { status: 409, body: { detail: { code: 'already_staff', person_id: 'c' } } },
    })
    renderAt('/admin/ajustes/equipo')

    const region = await section()
    await userEvent.click(within(region).getByRole('button', { name: copy.add }))
    const invite = within(region).getByRole('form', { name: form.title })
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(invite).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(within(invite).getByLabelText(form.email)).toHaveAccessibleDescription(
      `${form.emailHint} ${copy.alreadyStaff}`,
    )
  })

  it('says so when the email is another person of the gym', async () => {
    stubApi({
      invite: { status: 409, body: { detail: { code: 'email_in_gym', person_id: 'c' } } },
    })
    renderAt('/admin/ajustes/equipo')

    const region = await section()
    await userEvent.click(within(region).getByRole('button', { name: copy.add }))
    const invite = within(region).getByRole('form', { name: form.title })
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(invite).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(within(invite).getByLabelText(form.email)).toHaveAccessibleDescription(
      `${form.emailHint} ${copy.emailTaken}`,
    )
  })

  it('maps a refused email to its field', async () => {
    stubApi({
      invite: { status: 422, body: { detail: [{ loc: ['body', 'email'], type: 'value_error', msg: 'x' }] } },
    })
    renderAt('/admin/ajustes/equipo')

    const region = await section()
    await userEvent.click(within(region).getByRole('button', { name: copy.add }))
    const invite = within(region).getByRole('form', { name: form.title })
    await userEvent.type(within(invite).getByLabelText(form.email), 'nope')
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(invite).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(within(invite).getByLabelText(form.email)).toHaveAccessibleDescription(
      `${form.emailHint} ${copy.value.email}`,
    )
  })

  it('makes a coach an admin', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    await userEvent.click(within(await open('Beto')).getByRole('button', { name: copy.makeAdmin }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.roleChanged('Beto', copy.roles.admin!))
    // The panel closes on the change; the row now reads the new role.
    expect(await rowButton('Beto')).toHaveTextContent(copy.roles.admin!)
    expect(within(await open('Beto')).getByRole('button', { name: copy.makeCoach })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/staff/c', body: { role: 'admin' } },
    ])
  })

  it('revokes only once confirmed', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const beto = await open('Beto')
    await userEvent.click(within(beto).getByRole('button', { name: copy.revoke }))
    const confirm = within(beto).getByRole('group', { name: copy.confirmRevoke('Beto') })
    await userEvent.click(within(confirm).getByRole('button', { name: copy.cancel }))
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([])

    await userEvent.click(within(beto).getByRole('button', { name: copy.revoke }))
    await userEvent.click(within(beto).getByRole('button', { name: copy.confirm }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.revoked('Beto'))
    expect(within(await section()).queryByRole('button', { name: /^Beto/ })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([
      { method: 'DELETE', path: '/api/staff/c', body: undefined },
    ])
  })

  it('lets an admin manage coaches only, and invite only coaches', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/equipo')

    expect(within(await row('Carla')).queryByRole('button')).not.toBeInTheDocument()
    const beto = await open('Beto')
    expect(within(beto).getByRole('button', { name: copy.revoke })).toBeInTheDocument()
    expect(within(beto).queryByRole('button', { name: copy.makeAdmin })).not.toBeInTheDocument()

    const region = await section()
    await userEvent.click(within(region).getByRole('button', { name: copy.add }))
    const roleSelect = within(region).getByLabelText(form.role)
    expect(within(roleSelect).getAllByRole('option').map((o) => o.textContent)).toEqual([copy.roles.coach])
    expect(roleSelect).toHaveAccessibleDescription(form.adminOnlyHint)
  })

  it('is a tab of Ajustes, which a coach is not shown', async () => {
    stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/equipo')

    expect(await screen.findByText(es.admin.settings.adminsOnly)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.title })).not.toBeInTheDocument()
  })
})
