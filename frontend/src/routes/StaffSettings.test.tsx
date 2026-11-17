import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Permission } from '../api/me'
import { createQueryClient } from '../api/queryClient'
import type { HistoryEntry, StaffMember, Title } from '../api/staff'
import { App } from '../App'
import { isoDay } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.settings.staff
const form = copy.form

const since = '2026-10-01T12:00:00Z'
const ADMIN_PERMISSIONS: Permission[] = [
  'money_read',
  'money_write',
  'members_manage',
  'members_add',
  'attendance',
  'gym_setup',
  'team_manage',
]
const COACH_PERMISSIONS: Permission[] = ['members_add', 'attendance']

function today(): string {
  return isoDay(new Date().toISOString())
}

/** The team as `role` sees it: the owner manages everyone but themselves, an admin only
 * the coach, as the API's `manageable` says. */
function team(role: string): StaffMember[] {
  const owner = role === 'owner'
  return [
    {
      person_id: 'o',
      name: 'Martín',
      phone: '+56911111111',
      email: 'martin@example.cl',
      role: 'owner',
      since,
      account_holder: true,
      permissions: [...ADMIN_PERMISSIONS, 'expenses_read', 'expenses_write'],
      appointments: [],
      manageable: false,
    },
    {
      person_id: 'a',
      name: 'Carla',
      phone: '+56922222222',
      email: 'carla@example.cl',
      role: 'admin',
      since,
      account_holder: false,
      permissions: ADMIN_PERMISSIONS,
      appointments: [
        {
          id: 'ap-a',
          title_id: 't-admin',
          title_name: 'Administrador',
          starts_on: '2025-03-01',
          ends_on: '2027-03-01',
          public_contact: null,
          manageable: owner,
        },
      ],
      manageable: owner,
    },
    {
      person_id: 'c',
      name: 'Beto',
      phone: '+56933333333',
      email: null,
      role: 'coach',
      since,
      account_holder: false,
      permissions: COACH_PERMISSIONS,
      appointments: [
        {
          id: 'ap-c',
          title_id: 't-coach',
          title_name: 'Coach',
          starts_on: '2025-03-01',
          ends_on: null,
          public_contact: null,
          manageable: true,
        },
      ],
      manageable: true,
    },
  ]
}

function roles(role: string): Title[] {
  return [
    {
      id: 't-admin',
      name: 'Administrador',
      permissions: ADMIN_PERMISSIONS,
      public: false,
      preset: 'academia',
      holders: 1,
      manageable: role === 'owner',
    },
    { id: 't-coach', name: 'Coach', permissions: COACH_PERMISSIONS, public: true, preset: 'academia', holders: 1, manageable: true },
  ]
}

const HISTORY: HistoryEntry[] = [
  { id: 'h2', person_id: 'c', person_name: 'Beto', title_name: 'Coach', starts_on: '2025-03-01', ends_on: null },
  { id: 'h1', person_id: 'c', person_name: 'Beto', title_name: 'Ayudante', starts_on: '2025-03-01', ends_on: '2025-03-01' },
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({
  role = 'owner',
  invite,
  answers = {},
  pending = false,
}: { role?: string; invite?: Answer; answers?: Record<string, Answer>; pending?: boolean } = {}) {
  const calls: Call[] = []
  let staff = team(role)
  let titles = roles(role)
  let setupPending = pending
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Record<string, unknown>
      calls.push({ method, path: url.pathname, body })
      const answer = answers[`${method} ${url.pathname}`] ?? route(url.pathname, method, body)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: Record<string, unknown>): Answer {
    if (path === '/api/me/role') return { body: asRole(role) }
    if (path === '/api/staff' && method === 'GET') return { body: staff }
    if (path === '/api/staff/history') return { body: HISTORY }
    if (path === '/api/titles' && method === 'GET') return { body: { titles, setup_pending: setupPending } }
    if (path === '/api/titles/setup') {
      setupPending = false
      return { body: { titles, setup_pending: false } }
    }
    if (path === '/api/staff' && method === 'POST') {
      if (invite) return invite
      const created = { ...team(role)[2]!, ...body, person_id: 'nuevo', appointments: [] } as StaffMember
      staff = [...staff, created]
      return { status: 201, body: created }
    }
    if (path === '/api/staff/c/appointments/ap-c/end') {
      staff = staff.filter((s) => s.person_id !== 'c')
      return { status: 204 }
    }
    if (path === '/api/staff/c/appointments/ap-c' && method === 'PATCH') return { status: 204 }
    if (path === '/api/staff/c/appointments' && method === 'POST') return { status: 201, body: staff[2] }
    if (path === '/api/titles' && method === 'POST') {
      const created: Title = {
        id: 't-new',
        name: String(body.name),
        permissions: body.permissions as Permission[],
        public: Boolean(body.public),
        preset: null,
        holders: 0,
        manageable: true,
      }
      titles = [...titles, created]
      return { status: 201, body: created }
    }
    const title = titles.find((t) => path === `/api/titles/${t.id}`)
    if (title && method === 'PATCH') return { body: { ...title, ...body } }
    if (path === '/api/titles/presets') return { status: 201, body: [titles[0]] }
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

async function people() {
  return within(await section()).findByRole('region', { name: copy.people.title })
}

async function cargos() {
  return within(await section()).findByRole('region', { name: copy.titles.title })
}

/** A row the signed-in role may act on: a button, named by its text. */
async function rowButton(region: HTMLElement, name: string) {
  return within(region).findByRole('button', { name: new RegExp(`^${name}`) })
}

/** Opens a person's row, and answers the panel it opens to. */
async function open(name: string) {
  const region = await people()
  await userEvent.click(await rowButton(region, name))
  return within(region).getByRole('group', { name })
}

async function openInvite() {
  const region = await section()
  await userEvent.click(within(region).getByRole('button', { name: copy.add }))
  return within(region).getByRole('form', { name: form.title })
}

const posts = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Equipo, Personas', () => {
  it('lists each person with their roles, and the titular with no actions', async () => {
    stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await people()
    const owner = await within(region).findByRole('listitem', { name: 'Martín' })
    expect(owner).toHaveTextContent(copy.people.titular)
    expect(within(owner).queryByRole('button')).not.toBeInTheDocument()
    // The roles held, and when the term ends.
    const carla = await rowButton(region, 'Carla')
    expect(carla).toHaveTextContent('Administrador')
    expect(carla).toHaveTextContent(copy.people.until('mar 2027'))

    const panel = await open('Carla')
    expect(panel).toHaveTextContent('+56 9 2222 2222 · carla@example.cl')
    // What they may do, in words, "Registrar pagos" saying "Ver ingresos" too.
    expect(panel).toHaveTextContent(copy.panel.can)
    expect(panel).toHaveTextContent('Registrar pagos, Gestionar alumnos, Tomar asistencia')
    expect(panel).not.toHaveTextContent('Ver ingresos')
    await userEvent.click(within(panel).getByRole('button', { name: copy.panel.close }))
    expect(within(region).queryByRole('group', { name: 'Carla' })).not.toBeInTheDocument()
  })

  it('ends an appointment only once confirmed', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const beto = await open('Beto')
    const coach = within(beto).getByRole('group', { name: 'Coach' })
    await userEvent.click(within(coach).getByRole('button', { name: copy.panel.end }))
    const confirm = within(coach).getByRole('group', { name: copy.panel.confirmEnd('Coach', 'Beto') })
    await userEvent.click(within(confirm).getByRole('button', { name: copy.cancel }))
    expect(posts(calls)).toEqual([])

    await userEvent.click(within(coach).getByRole('button', { name: copy.panel.end }))
    await userEvent.click(within(coach).getByRole('button', { name: copy.panel.confirm }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.panel.ended('Coach', 'Beto'))
    expect(within(await people()).queryByRole('button', { name: /^Beto/ })).not.toBeInTheDocument()
    expect(posts(calls)).toEqual([{ method: 'POST', path: '/api/staff/c/appointments/ap-c/end', body: undefined }])
  })

  it('corrects the dates of an appointment', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const coach = within(await open('Beto')).getByRole('group', { name: 'Coach' })
    expect(within(coach).queryByRole('button', { name: copy.panel.saveDates })).not.toBeInTheDocument()
    fireEvent.change(within(coach).getByLabelText(copy.panel.from), { target: { value: '2025-02-15' } })
    fireEvent.change(within(coach).getByLabelText(copy.panel.until), { target: { value: '2027-02-15' } })
    await userEvent.click(within(coach).getByRole('button', { name: copy.panel.saveDates }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.panel.datesSaved('Coach'))
    expect(posts(calls)).toEqual([
      {
        method: 'PATCH',
        path: '/api/staff/c/appointments/ap-c',
        body: { starts_on: '2025-02-15', ends_on: '2027-02-15' },
      },
    ])
  })

  it('says so when a new appointment overlaps one they hold', async () => {
    const calls = stubApi({ answers: { 'POST /api/staff/c/appointments': { status: 409, body: { detail: 'x' } } } })
    renderAt('/admin/ajustes/equipo')

    const add = within(await open('Beto')).getByRole('form', { name: copy.panel.add })
    expect(within(add).getByLabelText(copy.panel.from)).toHaveValue(today())
    await userEvent.selectOptions(within(add).getByLabelText(copy.panel.role), 'Coach')
    await userEvent.click(within(add).getByRole('button', { name: copy.panel.appoint }))

    expect(await within(add).findByText(copy.panel.overlaps)).toBeInTheDocument()
    expect(posts(calls)).toEqual([
      { method: 'POST', path: '/api/staff/c/appointments', body: { title_id: 't-coach', starts_on: today() } },
    ])
  })

  it('lets an admin open only the coach, and give only the roles they may', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/equipo')

    const region = await people()
    expect(within(await within(region).findByRole('listitem', { name: 'Carla' })).queryByRole('button')).not.toBeInTheDocument()
    const add = within(await open('Beto')).getByRole('form', { name: copy.panel.add })
    const options = within(within(add).getByLabelText(copy.panel.role)).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Coach'])
  })
})

describe('Ajustes: Equipo, Invitar', () => {
  it('invites someone to the roles ticked, from today', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const invite = await openInvite()
    await userEvent.type(within(invite).getByLabelText(form.name), 'Pedro')
    await userEvent.type(within(invite).getByLabelText(form.phone), '9 4444 4444')
    await userEvent.type(within(invite).getByLabelText(form.email), 'pedro@example.cl')
    expect(within(invite).getByLabelText(form.from)).toHaveValue(today())
    // At least one role.
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))
    expect(await within(invite).findByRole('alert')).toHaveTextContent(form.rolesNeeded)
    expect(posts(calls)).toEqual([])

    await userEvent.click(within(invite).getByRole('checkbox', { name: 'Coach' }))
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.invited('Pedro', 'pedro@example.cl'))
    expect(posts(calls)).toEqual([
      {
        method: 'POST',
        path: '/api/staff',
        body: {
          name: 'Pedro',
          phone: '9 4444 4444',
          email: 'pedro@example.cl',
          title_ids: ['t-coach'],
          starts_on: today(),
        },
      },
    ])
  })

  it('offers an admin only the roles they may give', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/equipo')

    const invite = await openInvite()
    expect(within(invite).getAllByRole('checkbox').map((c) => c.closest('label')?.textContent)).toEqual(['Coach'])
  })

  it('invites once for a double tap on Enviar invitación (#204)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const invite = await openInvite()
    await userEvent.type(within(invite).getByLabelText(form.name), 'Pedro')
    await userEvent.type(within(invite).getByLabelText(form.email), 'pedro@example.cl')
    await userEvent.click(within(invite).getByRole('checkbox', { name: 'Coach' }))
    // Both taps before the button re-renders disabled, as a thumb does on a phone.
    const submit = within(invite).getByRole('button', { name: copy.submit })
    fireEvent.click(submit)
    fireEvent.click(submit)

    expect(await screen.findByRole('status')).toHaveTextContent(copy.invited('Pedro', 'pedro@example.cl'))
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
  })

  it.each([
    ['already_staff', copy.alreadyStaff],
    ['email_in_gym', copy.emailTaken],
  ])('says so on a 409 %s', async (code, message) => {
    stubApi({ invite: { status: 409, body: { detail: { code, person_id: 'c' } } } })
    renderAt('/admin/ajustes/equipo')

    const invite = await openInvite()
    await userEvent.click(within(invite).getByRole('checkbox', { name: 'Coach' }))
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(invite).findByText(copy.invalid)).toBeInTheDocument()
    expect(within(invite).getByLabelText(form.email)).toHaveAccessibleDescription(`${form.emailHint} ${message}`)
  })

  it('maps a refused email to its field', async () => {
    stubApi({
      invite: { status: 422, body: { detail: [{ loc: ['body', 'email'], type: 'value_error', msg: 'x' }] } },
    })
    renderAt('/admin/ajustes/equipo')

    const invite = await openInvite()
    await userEvent.type(within(invite).getByLabelText(form.email), 'nope')
    await userEvent.click(within(invite).getByRole('checkbox', { name: 'Coach' }))
    await userEvent.click(within(invite).getByRole('button', { name: copy.submit }))

    expect(await within(invite).findByText(copy.invalid)).toBeInTheDocument()
    expect(within(invite).getByLabelText(form.email)).toHaveAccessibleDescription(`${form.emailHint} ${copy.value.email}`)
  })
})

describe('Ajustes: Equipo, Cargos', () => {
  it('creates a role with what its permissions imply', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await cargos()
    await userEvent.click(within(region).getByRole('button', { name: copy.titles.add }))
    const draft = within(region).getByRole('form', { name: copy.titles.form.title })
    await userEvent.type(within(draft).getByLabelText(copy.titles.form.name), 'Tesorera')
    await userEvent.click(within(draft).getByRole('checkbox', { name: new RegExp(`^${copy.titles.form.public}`) }))
    await userEvent.click(within(draft).getByRole('checkbox', { name: new RegExp(`^${copy.permissions.money_write}`) }))
    // Registrar pagos brings Ver ingresos, which stays while it does.
    const read = within(draft).getByRole('checkbox', { name: new RegExp(`^${copy.permissions.money_read}`) })
    expect(read).toBeChecked()
    expect(read).toBeDisabled()
    await userEvent.click(within(draft).getByRole('button', { name: copy.titles.save }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.titles.created('Tesorera'))
    expect(posts(calls)).toEqual([
      { method: 'POST', path: '/api/titles', body: { name: 'Tesorera', permissions: ['money_read', 'money_write'], public: true } },
    ])
  })

  it('says what an edit widens for its holders before saving it', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await cargos()
    await userEvent.click(await rowButton(region, 'Coach'))
    const coach = within(region).getByRole('form', { name: 'Coach' })
    await userEvent.click(within(coach).getByRole('checkbox', { name: new RegExp(`^${copy.permissions.expenses_read}`) }))
    await userEvent.click(within(coach).getByRole('button', { name: copy.titles.save }))

    expect(within(coach).getByText(copy.titles.widens(copy.titles.holders(1), 'ver gastos'))).toBeInTheDocument()
    expect(posts(calls)).toEqual([])
    await userEvent.click(within(coach).getByRole('button', { name: copy.titles.widensConfirm }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.titles.saved('Coach'))
    expect(posts(calls)).toEqual([
      {
        method: 'PATCH',
        path: '/api/titles/t-coach',
        body: { name: 'Coach', permissions: ['expenses_read', 'members_add', 'attendance'], public: true },
      },
    ])
  })

  it('disables a permission the editor lacks, and opens only the roles they may change', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/equipo')

    const region = await cargos()
    const administrador = await within(region).findByRole('listitem', { name: 'Administrador' })
    expect(within(administrador).queryByRole('button')).not.toBeInTheDocument()
    await userEvent.click(await rowButton(region, 'Coach'))
    const coach = within(region).getByRole('form', { name: 'Coach' })
    const expenses = within(coach).getByRole('checkbox', { name: new RegExp(`^${copy.permissions.expenses_read}`) })
    expect(expenses).toBeDisabled()
    expect(expenses.closest('label')).toHaveTextContent(copy.titles.form.notYours)
  })

  it('says why a role somebody holds is not archived', async () => {
    stubApi({ answers: { 'POST /api/titles/t-coach/archive': { status: 409, body: { detail: 'x' } } } })
    renderAt('/admin/ajustes/equipo')

    const region = await cargos()
    await userEvent.click(await rowButton(region, 'Coach'))
    const coach = within(region).getByRole('form', { name: 'Coach' })
    await userEvent.click(within(coach).getByRole('button', { name: copy.titles.archive }))
    await userEvent.click(within(coach).getByRole('button', { name: copy.titles.confirm }))

    expect(await within(coach).findByText(copy.titles.held)).toBeInTheDocument()
  })

  it('adds a preset', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await cargos()
    await userEvent.click(within(region).getByRole('button', { name: copy.titles.addPreset }))
    const picker = within(region).getByRole('group', { name: copy.titles.addPreset })
    await userEvent.click(within(picker).getByRole('button', { name: copy.setup.choose(copy.presets.club_federado!) }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.titles.presetAdded(1))
    expect(posts(calls)).toEqual([{ method: 'POST', path: '/api/titles/presets', body: { preset: 'club_federado' } }])
  })
})

describe('Ajustes: Equipo, first-run and Historial', () => {
  it('asks a new gym how its team is organised, once', async () => {
    const calls = stubApi({ pending: true })
    renderAt('/admin/ajustes/equipo')

    const setup = await within(await section()).findByRole('region', { name: copy.setup.title })
    await userEvent.click(within(setup).getByRole('button', { name: copy.setup.none }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.setup.chosen)
    expect(within(await section()).queryByRole('region', { name: copy.setup.title })).not.toBeInTheDocument()
    expect(posts(calls)).toEqual([{ method: 'POST', path: '/api/titles/setup', body: { preset: null } }])
  })

  it('is not asked of a gym that has chosen', async () => {
    stubApi()
    renderAt('/admin/ajustes/equipo')

    await people()
    expect(within(await section()).queryByRole('region', { name: copy.setup.title })).not.toBeInTheDocument()
  })

  it('lists the history, newest first, only once opened', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/equipo')

    const region = await section()
    await people()
    expect(calls.some((c) => c.path === '/api/staff/history')).toBe(false)
    const summary = within(region).getByText(copy.history.title)
    await userEvent.click(summary)
    summary.closest('details')!.open = true
    fireEvent(summary.closest('details')!, new Event('toggle'))

    expect(await within(region).findByText('Beto · Coach')).toBeInTheDocument()
    expect(within(region).getByText(`1 mar 2025, ${copy.history.never}`)).toBeInTheDocument()
  })

  it('is a tab of Ajustes, which a coach is not shown', async () => {
    stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/equipo')

    expect(await screen.findByText(es.admin.settings.adminsOnly)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.title })).not.toBeInTheDocument()
  })
})
