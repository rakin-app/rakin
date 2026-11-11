import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GymSettings } from '../api/gym'
import type { Program } from '../api/people'
import type { Plan } from '../api/plans'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings
const gym = copy.gym
const plans = copy.plans
const form = plans.form
const invalid = copy.invalid

const SETTINGS: GymSettings = {
  name: 'Academia Sur',
  slug: 'academia-sur',
  web_address: 'academia-sur.rakin.app',
  timezone: 'America/Santiago',
  theme: 'bosque',
  grace_days: 5,
  reminder_every_days: 3,
  channels: { whatsapp: true },
  bank_account: {
    bank: 'Banco de Chile',
    account_type: 'Cuenta Corriente',
    holder: 'Academia Sur SpA',
    rut: '76432109-K',
    number: '00-123-45678-09',
    email: null,
  },
  privacy: null,
}

const ADULTS: Program = { id: 'adultos', name: 'Adultos', active: true }
const KIDS: Program = { id: 'kids', name: 'Kids', active: true }
const OLD: Program = { id: 'old', name: 'Competición', active: false }

const at = { active: true, created_at: '2026-10-01T12:00:00Z' }
const MONTHLY: Plan = { ...at, id: 'mensual', kind: 'monthly', name: 'Mensual adultos', program_id: 'adultos', price_clp: 35000, anchor: 'signup' }
const TRIAL: Plan = { ...at, id: 'prueba', kind: 'trial', name: 'Clase de prueba', program_id: null, free_classes: 2, free_days: 7 }
const OLD_CREDITS: Plan = {
  ...at,
  active: false,
  id: 'pack',
  kind: 'credits',
  name: 'Pack 10',
  program_id: 'old',
  price_clp: 40000,
  credits: 10,
  credit_expiry_days: 60,
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }
type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  // Holds a membership here too (#214).
  studentPage?: boolean
  settings?: Answer
  saveSettings?: Answer
  savePlan?: Answer
}

const refused = (...errors: [string[], string][]): Answer => ({
  status: 422,
  body: { detail: errors.map(([loc, type]) => ({ loc, type, msg: type })) },
})

function stubApi({ role = 'owner', studentPage = false, settings, saveSettings, savePlan }: Stub = {}) {
  const calls: Call[] = []
  let current = SETTINGS
  let list: Plan[] = [MONTHLY, TRIAL, OLD_CREDITS]
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      const answer = route(url.pathname, method, body as Record<string, unknown>)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: Record<string, unknown>): Answer {
    if (path === '/api/me/role') {
      return {
        body: {
          role,
          person_id: 'me',
          name: 'Carla Soto',
          email: 'carla@example.cl',
          gym_name: 'Academia Sur',
          student_page: studentPage,
        },
      }
    }
    if (path === '/api/auth/logout') return { status: 204 }
    if (path === '/api/gym/settings' && method === 'GET') return settings ?? { body: current }
    if (path === '/api/gym/settings' && method === 'PATCH') {
      if (saveSettings) return saveSettings
      current = { ...current, ...(body as Partial<GymSettings>) }
      return { body: current }
    }
    if (path === '/api/programs') return { body: [ADULTS, KIDS, OLD] }
    if (path === '/api/plans' && method === 'GET') return { body: list }
    if (path === '/api/plans' && method === 'POST') {
      if (savePlan) return savePlan
      const created = { ...at, id: 'nuevo', ...body } as Plan
      list = [...list, created]
      return { status: 201, body: created }
    }
    const found = list.find((p) => path === `/api/plans/${p.id}`)
    if (found && method === 'PATCH') {
      if (savePlan) return savePlan
      const updated = { ...found, ...body } as Plan
      list = list.map((p) => (p.id === found.id ? updated : p))
      return { body: updated }
    }
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

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes', () => {
  it('is hidden from coaches, who never ask the API for it', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/gimnasio')

    expect(await screen.findByText(copy.adminsOnly)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    expect(within(nav).queryByRole('link', { name: es.nav.settings })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: copy.sectionsLabel })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/gym') || c.path.startsWith('/api/plans'))).toEqual([])
  })

  const SECTIONS = [
    [copy.sections.gym, '/admin/ajustes/gimnasio'],
    [copy.sections.plans, '/admin/ajustes/planes'],
    [copy.sections.programs, '/admin/ajustes/programas'],
    [copy.sections.schedule, '/admin/ajustes/horario'],
    [copy.sections.blocks, '/admin/ajustes/bloques'],
    [copy.sections.grading, '/admin/ajustes/graduacion'],
    [copy.sections.fields, '/admin/ajustes/campos'],
    [copy.sections.staff, '/admin/ajustes/equipo'],
    [copy.sections.joinLink, '/admin/ajustes/inscripcion'],
    [copy.sections.account, '/admin/ajustes/cuenta'],
  ]

  it('opens on a list of every section on a phone, each a way in and back', async () => {
    stubApi({ role: 'admin' })
    const router = renderAt('/admin/ajustes')

    const sections = await screen.findByRole('navigation', { name: copy.sectionsLabel })
    const links = within(sections).getAllByRole('link')
    expect(links.map((l) => [l.querySelector('.list-row__title')?.textContent, l.getAttribute('href')])).toEqual(SECTIONS)
    expect(links[1]).toHaveTextContent(copy.descriptions.plans)
    expect(screen.getByRole('heading', { level: 1, name: copy.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/ajustes')
    await waitFor(() => expect(document.title).toBe(`${copy.title} · Academia Sur`))

    await userEvent.click(links[1]!)
    expect(await screen.findByRole('region', { name: plans.title })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: copy.sections.plans })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: copy.sectionsLabel })).not.toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe(`${copy.sections.plans} · Academia Sur`))

    await userEvent.click(screen.getByRole('link', { name: copy.backLabel }))
    expect(await screen.findByRole('navigation', { name: copy.sectionsLabel })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/ajustes')
  })

  it('opens on Gimnasio on a desktop, with a tab per section', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches: true, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
    )
    stubApi({ role: 'admin' })
    const router = renderAt('/admin/ajustes')

    const sections = await screen.findByRole('navigation', { name: copy.sectionsLabel })
    expect(within(sections).getAllByRole('link').map((l) => [l.textContent, l.getAttribute('href')])).toEqual(SECTIONS)
    expect(await screen.findByRole('form', { name: gym.formLabel })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: copy.title })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: copy.backLabel })).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/ajustes/gimnasio')
    expect(within(sections).getByRole('link', { name: copy.sections.gym })).toHaveAttribute('aria-current', 'page')

    await userEvent.click(within(sections).getByRole('link', { name: copy.sections.plans }))
    expect(await screen.findByRole('region', { name: plans.title })).toBeInTheDocument()
  })

  it('has Cuenta: who is signed in, and Cerrar sesión', async () => {
    const calls = stubApi({ role: 'admin' })
    const router = renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    expect(await within(account).findByText('Carla Soto')).toBeInTheDocument()
    expect(within(account).getByText('carla@example.cl')).toBeInTheDocument()
    await userEvent.click(within(account).getByRole('button', { name: es.signOut.label }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/ingresar'))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true)
  })

  it('has "Mi página" in Cuenta for an owner who also trains, the way to it on a phone (#214)', async () => {
    stubApi({ studentPage: true })
    const router = renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    await userEvent.click(await within(account).findByRole('link', { name: es.nav.myPage }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/me'))
  })

  it('has no "Mi página" in Cuenta for an owner who does not train', async () => {
    stubApi()
    renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    await within(account).findByText('Carla Soto')
    expect(within(account).queryByRole('link', { name: es.nav.myPage })).not.toBeInTheDocument()
  })

  it('tells an admin whose role was taken away that the section is not theirs', async () => {
    stubApi({ settings: { status: 403, body: { detail: 'forbidden' } } })
    renderAt('/admin/ajustes/gimnasio')

    expect(await screen.findByText(copy.adminsOnly)).toBeInTheDocument()
  })
})

describe('Ajustes: Gimnasio', () => {
  it('shows the settings and saves only what changed', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    expect(within(settings).getByLabelText(gym.slug)).toHaveValue('academia-sur.rakin.app')
    expect(within(settings).getByLabelText(gym.timezone)).toHaveValue('America/Santiago')
    expect(within(settings).getByLabelText(gym.rut)).toHaveValue('76.432.109-K')
    const name = within(settings).getByLabelText(gym.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'Academia Sur Ñuñoa')
    const grace = within(settings).getByLabelText(gym.graceDays)
    await userEvent.clear(grace)
    await userEvent.type(grace, '7')
    await userEvent.click(within(settings).getByLabelText(gym.whatsapp))
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('status')).toHaveTextContent(gym.saved)
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/gym/settings',
        body: { name: 'Academia Sur Ñuñoa', grace_days: 7, channels: { whatsapp: false } },
      },
    ])
  })

  it('sends the bank account whole, and clears it once every field is empty', async () => {
    const calls = stubApi({ settings: { body: { ...SETTINGS, bank_account: null } } })
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    await userEvent.type(within(settings).getByLabelText(gym.bankName), 'BancoEstado')
    await userEvent.selectOptions(within(settings).getByLabelText(gym.accountType), 'Cuenta RUT')
    await userEvent.type(within(settings).getByLabelText(gym.holder), 'Rodrigo Fuentes')
    await userEvent.type(within(settings).getByLabelText(gym.rut), '12.345.678-5')
    await userEvent.type(within(settings).getByLabelText(gym.number), '12345678')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))
    await within(settings).findByRole('status')

    for (const label of [gym.bankName, gym.holder, gym.rut, gym.number]) {
      await userEvent.clear(within(settings).getByLabelText(label))
    }
    await userEvent.selectOptions(within(settings).getByLabelText(gym.accountType), '')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))
    await within(settings).findByRole('status')

    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      {
        bank_account: {
          bank: 'BancoEstado',
          account_type: 'Cuenta RUT',
          holder: 'Rodrigo Fuentes',
          rut: '12.345.678-5',
          number: '12345678',
          email: null,
        },
      },
      { bank_account: null },
    ])
  })

  it("puts the API's refusals under the fields they name", async () => {
    stubApi({
      saveSettings: refused(
        [['body', 'grace_days'], 'less_than_equal'],
        [['body', 'bank_account', 'rut'], 'value_error'],
        [['body', 'bank_account', 'bank'], 'string_too_short'],
      ),
    })
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    const grace = within(settings).getByLabelText(gym.graceDays)
    await userEvent.clear(grace)
    await userEvent.type(grace, '90')
    await userEvent.clear(within(settings).getByLabelText(gym.bankName))
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('alert')).toHaveTextContent(gym.invalid)
    expect(grace).toHaveAttribute('aria-invalid', 'true')
    expect(grace).toHaveAccessibleDescription(`${gym.graceDaysHint} ${gym.range.grace_days}`)
    expect(within(settings).getByLabelText(gym.rut)).toHaveAccessibleDescription(gym.value['bank_account.rut'])
    expect(within(settings).getByLabelText(gym.bankName)).toHaveAccessibleDescription(invalid.required)
    expect(within(settings).getByLabelText(gym.name)).toHaveAttribute('aria-invalid', 'false')
  })

  it('says so when the save fails for another reason', async () => {
    stubApi({ saveSettings: { status: 500, body: { detail: 'boom' } } })
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    await userEvent.type(within(settings).getByLabelText(gym.name), ' 2')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('alert')).toHaveTextContent(gym.failed)
  })
})

describe('Ajustes: Gimnasio, datos de privacidad', () => {
  it('sends the privacy details whole, the address optional', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    expect(within(settings).queryByRole('link', { name: gym.privacyView })).not.toBeInTheDocument()
    await userEvent.type(within(settings).getByLabelText(gym.privacyLegalName), 'Academia Sur SpA')
    await userEvent.type(within(settings).getByLabelText(gym.privacyRut), '76.432.109-K')
    await userEvent.type(within(settings).getByLabelText(gym.privacyEmail), 'privacidad@academiasur.cl')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('status')).toHaveTextContent(gym.saved)
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      {
        privacy: {
          legal_name: 'Academia Sur SpA',
          rut: '76.432.109-K',
          email: 'privacidad@academiasur.cl',
          address: null,
        },
      },
    ])
    expect(within(settings).getByRole('link', { name: gym.privacyView })).toHaveAttribute('href', '/privacidad')
  })

  it('shows the details set, and puts their refusals under their fields', async () => {
    const privacy = { legal_name: 'Academia Sur SpA', rut: '76432109-K', email: 'a@b.cl', address: 'Av. Siempre Viva 742', updated_on: '2026-11-10' }
    stubApi({
      settings: { body: { ...SETTINGS, privacy } },
      saveSettings: refused([['body', 'privacy', 'email'], 'value_error']),
    })
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    expect(within(settings).getByLabelText(gym.privacyRut)).toHaveValue('76.432.109-K')
    expect(within(settings).getByLabelText(gym.privacyAddress)).toHaveValue('Av. Siempre Viva 742')
    const email = within(settings).getByLabelText(gym.privacyEmail)
    await userEvent.clear(email)
    await userEvent.type(email, 'nada')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('alert')).toHaveTextContent(gym.invalid)
    expect(email).toHaveAccessibleDescription(gym.value['privacy.email'])
  })
})

describe('Ajustes: Planes', () => {
  it('lists every plan with its kind, terms and program', async () => {
    stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Mensual adultos')
    expect(rows[0]).toHaveTextContent(plans.row(plans.kinds.monthly, plans.row('$35.000 al mes', plans.anchors.signup)))
    await waitFor(() => expect(rows[0]).toHaveTextContent('Adultos'))
    expect(rows[1]).toHaveTextContent(plans.row(plans.kinds.trial, 'Gratis · 2 clases · 7 días'))
    expect(rows[1]).toHaveTextContent(plans.anyProgram)
    expect(rows[2]).toHaveTextContent(plans.inactive)
    expect(rows[2]).toHaveTextContent(plans.row(plans.kinds.credits, '$40.000 por 10 clases · vencen en 60 días'))
    // A row is the way into its plan: no Editar or Desactivar beside it (#177).
    for (const row of rows) expect(within(row).getAllByRole('button')).toHaveLength(1)
    expect(within(section).queryByRole('button', { name: plans.reactivate })).not.toBeInTheDocument()
  })

  it('creates a plan of the kind chosen, with its own parameters and program', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.selectOptions(within(create).getByLabelText(form.kind), plans.kinds.credits)
    // The kind's own parameters only.
    expect(within(create).queryByLabelText(form.anchor)).not.toBeInTheDocument()
    // Active programs only.
    const program = within(create).getByLabelText(form.program)
    expect(within(program).getAllByRole('option').map((o) => o.textContent)).toEqual([plans.anyProgram, 'Adultos', 'Kids'])
    await userEvent.selectOptions(program, 'Kids')
    await userEvent.type(within(create).getByLabelText(form.name), 'Pack 8 kids')
    await userEvent.type(within(create).getByLabelText(form.price), '32.000')
    await userEvent.type(within(create).getByLabelText(form.credits), '8')
    await userEvent.type(within(create).getByLabelText(form.creditExpiryDays), '45')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.created('Pack 8 kids'))
    expect(await within(section).findByText('Pack 8 kids')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/plans',
        body: {
          kind: 'credits',
          name: 'Pack 8 kids',
          program_id: 'kids',
          price_clp: 32000,
          credits: 8,
          credit_expiry_days: 45,
        },
      },
    ])
  })

  it("puts a create's refusals under the fields they name, past the kind", async () => {
    stubApi({
      savePlan: refused(
        [['body', 'monthly', 'price_clp'], 'int_parsing'],
        [['body', 'monthly', 'name'], 'string_too_short'],
        [['body', 'program_id'], 'inactive_program'],
      ),
    })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.selectOptions(within(create).getByLabelText(form.program), 'Adultos')
    await userEvent.type(within(create).getByLabelText(form.price), 'treinta mil')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(create).findByRole('alert')).toHaveTextContent(form.invalid)
    expect(within(create).getByLabelText(form.price)).toHaveAccessibleDescription(invalid.integer)
    expect(within(create).getByLabelText(form.name)).toHaveAccessibleDescription(invalid.required)
    expect(within(create).getByLabelText(form.program)).toHaveAccessibleDescription(form.value.inactive_program)
  })

  it('edits a plan, sending only what changed; a trial limit left empty is cleared', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const trial = (await within(section).findAllByRole('listitem'))[1]!
    await userEvent.click(within(trial).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Clase de prueba') })
    // The kind is set on create.
    expect(within(edit).getByLabelText(form.kind)).toBeDisabled()
    await userEvent.clear(within(edit).getByLabelText(form.freeDays))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.saved('Clase de prueba'))
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/plans/prueba', body: { free_days: null } },
    ])
    await waitFor(() =>
      expect((within(section).getAllByRole('listitem'))[1]).toHaveTextContent(
        `${plans.row(plans.kinds.trial, 'Gratis · 2 clases')} · ${plans.anyProgram}`,
      ),
    )
  })

  it('closes an edit that changed nothing without asking the API', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const monthly = (await within(section).findAllByRole('listitem'))[0]!
    await userEvent.click(within(monthly).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(within(section).queryByRole('form')).not.toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([])
  })

  it("clears a create's refusals when the kind changes", async () => {
    stubApi({ savePlan: refused([['body', 'monthly', 'price_clp'], 'missing']) })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))
    expect(await within(create).findByRole('alert')).toHaveTextContent(form.invalid)
    expect(within(create).getByLabelText(form.price)).toHaveAttribute('aria-invalid', 'true')

    await userEvent.selectOptions(within(create).getByLabelText(form.kind), plans.kinds.dropin)

    expect(within(create).queryByRole('alert')).not.toBeInTheDocument()
    expect(within(create).getByLabelText(form.price)).toHaveAttribute('aria-invalid', 'false')
  })

  it('says a trial needs a limit when the API refuses one with none', async () => {
    stubApi({ savePlan: refused([['body'], 'value_error']) })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const trial = (await within(section).findAllByRole('listitem'))[1]!
    await userEvent.click(within(trial).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Clase de prueba') })
    await userEvent.clear(within(edit).getByLabelText(form.freeClasses))
    await userEvent.clear(within(edit).getByLabelText(form.freeDays))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(edit).findByRole('alert')).toHaveTextContent(form.trialLimit)
  })

  it('keeps an inactive program a plan already has among its choices', async () => {
    stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const pack = (await within(section).findAllByRole('listitem'))[2]!
    await userEvent.click(within(pack).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Pack 10') })
    const program = within(edit).getByLabelText(form.program)
    expect(program).toHaveValue('old')
    expect(within(program).getByRole('option', { name: form.inactiveProgram('Competición') })).toBeInTheDocument()
  })

  it('deactivates a plan and reactivates it', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const open = async () =>
      userEvent.click(within((await within(section).findAllByRole('listitem'))[0]!).getByRole('button'))
    // Deactivating is in the plan's edit view, not on its row.
    await open()
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    await userEvent.click(within(edit).getByRole('button', { name: plans.deactivate }))
    expect(await within(section).findByRole('status')).toHaveTextContent(plans.deactivated('Mensual adultos'))
    expect(within(section).queryByRole('form')).not.toBeInTheDocument()
    await open()
    await userEvent.click(within(section).getByRole('button', { name: plans.reactivate }))
    expect(await within(section).findByRole('status')).toHaveTextContent(plans.reactivated('Mensual adultos'))

    expect(calls.filter((c) => c.method === 'PATCH').map((c) => [c.path, c.body])).toEqual([
      ['/api/plans/mensual', { active: false }],
      ['/api/plans/mensual', { active: true }],
    ])
  })
})
