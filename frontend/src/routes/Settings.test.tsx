import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
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
  timezone: 'America/Santiago',
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
  settings?: Answer
  saveSettings?: Answer
  savePlan?: Answer
}

const refused = (...errors: [string[], string][]): Answer => ({
  status: 422,
  body: { detail: errors.map(([loc, type]) => ({ loc, type, msg: type })) },
})

function stubApi({ role = 'owner', settings, saveSettings, savePlan }: Stub = {}) {
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
    if (path === '/api/me/role') return { body: { role } }
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

  it('opens on Gimnasio, with a tab per section', async () => {
    stubApi({ role: 'admin' })
    const router = renderAt('/admin/ajustes')

    const sections = await screen.findByRole('navigation', { name: copy.sectionsLabel })
    expect(within(sections).getAllByRole('link').map((l) => [l.textContent, l.getAttribute('href')])).toEqual([
      [copy.sections.gym, '/admin/ajustes/gimnasio'],
      [copy.sections.plans, '/admin/ajustes/planes'],
    ])
    expect(await screen.findByRole('form', { name: gym.formLabel })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/ajustes/gimnasio')
    expect(within(sections).getByRole('link', { name: copy.sections.gym })).toHaveAttribute('aria-current', 'page')

    await userEvent.click(within(sections).getByRole('link', { name: copy.sections.plans }))
    expect(await screen.findByRole('region', { name: plans.title })).toBeInTheDocument()
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
    expect(within(settings).getByLabelText(gym.slug)).toHaveValue('academia-sur')
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

describe('Ajustes: Planes', () => {
  it('lists every plan with its kind, terms and program', async () => {
    stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Mensual adultos')
    expect(rows[0]).toHaveTextContent(plans.row(plans.kinds.monthly, plans.row('$35.000 al mes', plans.anchors.signup)))
    expect(await within(rows[0]!).findByText('Adultos')).toBeInTheDocument()
    expect(rows[1]).toHaveTextContent(plans.row(plans.kinds.trial, 'Gratis · 2 clases · 7 días'))
    expect(rows[1]).toHaveTextContent(plans.anyProgram)
    expect(rows[2]).toHaveTextContent(plans.inactive)
    expect(rows[2]).toHaveTextContent(plans.row(plans.kinds.credits, '$40.000 por 10 clases · vencen en 60 días'))
    expect(within(rows[2]!).getByRole('button', { name: plans.reactivate })).toBeInTheDocument()
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
    await userEvent.click(within(trial).getByRole('button', { name: plans.edit }))
    const edit = within(section).getByRole('form', { name: form.edit('Clase de prueba') })
    // The kind is set on create.
    expect(within(edit).getByLabelText(form.kind)).toBeDisabled()
    await userEvent.clear(within(edit).getByLabelText(form.freeDays))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.saved('Clase de prueba'))
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      { method: 'PATCH', path: '/api/plans/prueba', body: { free_days: null } },
    ])
    expect(await within(section).findByText(plans.row(plans.kinds.trial, 'Gratis · 2 clases'))).toBeInTheDocument()
  })

  it('closes an edit that changed nothing without asking the API', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const monthly = (await within(section).findAllByRole('listitem'))[0]!
    await userEvent.click(within(monthly).getByRole('button', { name: plans.edit }))
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
    await userEvent.click(within(trial).getByRole('button', { name: plans.edit }))
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
    await userEvent.click(within(pack).getByRole('button', { name: plans.edit }))
    const edit = within(section).getByRole('form', { name: form.edit('Pack 10') })
    const program = within(edit).getByLabelText(form.program)
    expect(program).toHaveValue('old')
    expect(within(program).getByRole('option', { name: form.inactiveProgram('Competición') })).toBeInTheDocument()
  })

  it('deactivates a plan and reactivates it', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const monthly = (await within(section).findAllByRole('listitem'))[0]!
    await userEvent.click(within(monthly).getByRole('button', { name: plans.deactivate }))
    expect(await within(section).findByRole('status')).toHaveTextContent(plans.deactivated('Mensual adultos'))
    await userEvent.click(await within(monthly).findByRole('button', { name: plans.reactivate }))
    expect(await within(section).findByRole('status')).toHaveTextContent(plans.reactivated('Mensual adultos'))

    expect(calls.filter((c) => c.method === 'PATCH').map((c) => [c.path, c.body])).toEqual([
      ['/api/plans/mensual', { active: false }],
      ['/api/plans/mensual', { active: true }],
    ])
  })
})
