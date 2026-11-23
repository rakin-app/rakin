import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Activity } from '../api/activities'
import type { GymSettings } from '../api/gym'
import type { Program } from '../api/people'
import type { AnchorMoves, Plan, PlanMembership } from '../api/plans'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { STATUS_URL } from '../config'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { DEFAULT_VOCABULARY, wearVocabulary } from '../i18n/vocabulary'
import { asRole } from '../test/access'

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
  logo: null,
  grace_days: 5,
  reminder_every_days: 3,
  channels: { whatsapp: true },
  summary_email: true,
  bank_account: {
    bank: 'Banco de Chile',
    account_type: 'Cuenta Corriente',
    holder: 'Academia Sur SpA',
    rut: '76432109-K',
    number: '00-123-45678-09',
    email: null,
  },
  privacy: null,
  vocabulary: DEFAULT_VOCABULARY,
}

const ADULTS: Program = { id: 'adultos', name: 'Adultos', active: true }
const KIDS: Program = { id: 'kids', name: 'Kids', active: true }
const OLD: Program = { id: 'old', name: 'Competición', active: false }

const at = { active: true, created_at: '2026-10-01T12:00:00Z' }
const MONTHLY: Plan = { ...at, id: 'mensual', kind: 'monthly', name: 'Mensual adultos', program_id: 'adultos', price_clp: 35000, anchor: 'signup' }
// The member on it a change to the 1st would move (#547), as `GET .../anchor-moves` quotes it.
const ON_MONTHLY: AnchorMoves = {
  moves: [
  {
    membership_id: 'm-ana',
    person_id: 'p-ana',
    name: 'Ana Rojas',
    status: 'active',
    from_day: 12,
    to_day: 1,
    starts_on: '2026-12-12',
    ends_on: '2026-12-31',
    amount_due_clp: 22580,
    next_starts_on: '2027-01-01',
    next_amount_clp: 35000,
  },
  ],
  withdrawn: [],
}
const TRIAL: Plan = { ...at, id: 'prueba', kind: 'trial', name: 'Clase de prueba', program_id: null, free_classes: 2, free_days: 7 }
const SEASON: Plan = {
  ...at,
  id: 'temporada',
  kind: 'fixed_period',
  name: 'Temporada 2027',
  program_id: 'adultos',
  price_clp: 300000,
  period_start: '2027-03-01',
  period_end: '2027-12-31',
}
const ON_SEASON: PlanMembership[] = [
  { membership_id: 'm-ana', person_id: 'ana', name: 'Ana Rojas', status: 'active', next_plan_name: null },
  { membership_id: 'm-luis', person_id: 'luis', name: 'Luis Pérez', status: 'frozen', next_plan_name: null },
]
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
  // The plans listed, in order; by default a monthly plan, a trial and an old pack.
  plans?: Plan[]
  // What the gym teaches (#245); by default BJJ, which grades.
  activities?: Activity[]
  // An answer to every change of an activity, in place of the stub's own.
  changeActivity?: Answer
  // A monthly plan's anchor change quoted (#547); by default one member it would move.
  anchorQuote?: AnchorMoves
  // Every read of the plans after the first never answers (#558): what the list shows
  // after a save is the save's own answer.
  holdPlans?: boolean
}

const BJJ: Activity = {
  id: 'bjj',
  name: 'BJJ',
  uses_grades: true,
  class_types: 2,
  created_at: '2026-10-01T12:00:00Z',
}

const refused = (...errors: [string[], string][]): Answer => ({
  status: 422,
  body: { detail: errors.map(([loc, type]) => ({ loc, type, msg: type })) },
})

function stubApi({
  role = 'owner',
  studentPage = false,
  settings,
  saveSettings,
  savePlan,
  plans: listed = [MONTHLY, TRIAL, OLD_CREDITS],
  activities = [BJJ],
  changeActivity,
  anchorQuote = ON_MONTHLY,
  holdPlans = false,
}: Stub = {}) {
  const calls: Call[] = []
  let current = SETTINGS
  let taught = activities
  let list: Plan[] = listed
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      const plansRead = calls.filter((c) => c.method === 'GET' && c.path === '/api/plans').length
      if (holdPlans && method === 'GET' && url.pathname === '/api/plans' && plansRead > 1) {
        return new Promise<Response>(() => {})
      }
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
          ...asRole(role),
          person_id: 'me',
          name: 'Carla Soto',
          email: 'carla@example.cl',
          gym_name: 'Academia Sur',
          student_page: studentPage,
          theme: current.theme,
          uses_grades: taught.some((a) => a.uses_grades),
          vocabulary: current.vocabulary,
        },
      }
    }
    if (path === '/api/activities' && method === 'GET') return { body: taught }
    if (path === '/api/activities' && method === 'POST') {
      if (changeActivity) return changeActivity
      const made = { id: `a-${taught.length}`, class_types: 0, created_at: '2026-11-12T12:00:00Z', ...body } as Activity
      taught = [...taught, made].sort((a, b) => a.name.localeCompare(b.name))
      return { status: 201, body: made }
    }
    const activity = taught.find((a) => path === `/api/activities/${a.id}`)
    if (activity && changeActivity) return changeActivity
    if (activity && method === 'PATCH') {
      const changed = { ...activity, ...body } as Activity
      taught = taught.map((a) => (a.id === activity.id ? changed : a))
      return { body: changed }
    }
    if (activity && method === 'DELETE') {
      taught = taught.filter((a) => a.id !== activity.id)
      return { status: 204 }
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
    if (path === `/api/plans/${SEASON.id}/memberships`) return { body: ON_SEASON }
    if (path === `/api/plans/${MONTHLY.id}/anchor-moves`) return { body: anchorQuote }
    if (path === `/api/plans/${SEASON.id}/next-period` && method === 'POST') {
      if (savePlan) return savePlan
      const { membership_ids: moved, ...fields } = body as { membership_ids: string[] }
      const created = { ...SEASON, id: 'temporada-2028', ...fields } as Plan
      list = [...list, created]
      return { status: 201, body: { plan: created, moved: moved.length } }
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
  localStorage.clear()
  wearVocabulary(null)
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
    [copy.sections.tags, '/admin/ajustes/etiquetas'],
    [copy.sections.blocks, '/admin/ajustes/bloques'],
    [copy.sections.grading, '/admin/ajustes/graduacion'],
    [copy.sections.fields, '/admin/ajustes/campos'],
    [copy.sections.requirements, '/admin/ajustes/requisitos'],
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

  // One back pattern across the admin app (#360): the chevron button, named by where it goes (#250).
  it.each([
    ['another section', '/admin/ajustes/planes', es.common.backTo(es.common.places.settings)],
    ['Pagos', '/admin/pagos', es.common.backTo(es.common.places.payments)],
    ['a ficha', '/admin/alumnos/felipe', es.common.backTo(es.common.places.member)],
  ])('on a phone, coming from %s, the way back says where it goes', async (_from, from, label) => {
    stubApi({ role: 'admin' })
    const router = renderAt(from)
    await waitFor(() => expect(router.state.location.pathname).toBe(from))
    await router.navigate({ href: '/admin/ajustes/cuenta' })

    const back = await screen.findByRole('link', { name: label })
    expect(back).toHaveClass('button--icon')
    expect(back).toHaveAttribute('href', from)
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

  it('fades the tab row where more tabs follow, under an arrow that scrolls (#418)', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches: true, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
    )
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes')
    const sections = await screen.findByRole('navigation', { name: copy.sectionsLabel })
    expect(sections).not.toHaveAttribute('data-more-end')

    // jsdom lays nothing out: twelve tabs needing 1070px in a row 953px wide, at 1280.
    Object.defineProperty(sections, 'clientWidth', { configurable: true, value: 953 })
    Object.defineProperty(sections, 'scrollWidth', { configurable: true, value: 1070 })
    fireEvent.scroll(sections)
    expect(sections).toHaveAttribute('data-more-end')
    expect(sections).not.toHaveAttribute('data-more-start')

    // A mouse cannot swipe, and macOS hides the scrollbar: an arrow over the faded edge scrolls.
    expect(screen.queryByRole('button', { name: copy.tabsBack })).not.toBeInTheDocument()
    const scrollBy = vi.fn()
    sections.scrollBy = scrollBy
    await userEvent.click(screen.getByRole('button', { name: copy.tabsMore }))
    expect(scrollBy).toHaveBeenCalledWith(expect.objectContaining({ left: expect.any(Number) }))
    expect(scrollBy.mock.calls[0]?.[0].left).toBeGreaterThan(0)

    sections.scrollLeft = 117
    fireEvent.scroll(sections)
    expect(screen.getByRole('button', { name: copy.tabsBack })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.tabsMore })).not.toBeInTheDocument()
  })

  it('has Cuenta: who is signed in, and Cerrar sesión', async () => {
    const calls = stubApi({ role: 'admin' })
    // Taps a coach left unsaved on a roster (#416): not the next person's on this phone.
    localStorage.setItem('rakin:attendance-taps:s1', JSON.stringify({ at: Date.now(), change: { mark: ['m-1'], unmark: [] } }))
    const router = renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    expect(await within(account).findByText('Carla Soto')).toBeInTheDocument()
    expect(within(account).getByText('carla@example.cl')).toBeInTheDocument()
    await userEvent.click(within(account).getByRole('button', { name: es.signOut.label }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/ingresar'))
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true)
    expect(localStorage.getItem('rakin:attendance-taps:s1')).toBeNull()
  })

  it('has "Mi página" in Cuenta for an owner who also trains, the way to it on a phone (#214)', async () => {
    stubApi({ studentPage: true })
    const router = renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    await userEvent.click(await within(account).findByRole('link', { name: es.nav.myPage }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/me'))
  })

  it('has "Estado del servicio" in Cuenta, the public status page in a new tab (#519)', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/cuenta')

    const account = await screen.findByRole('region', { name: copy.account.title })
    const status = await within(account).findByRole('link', { name: new RegExp(es.nav.status) })
    expect(status).toHaveAttribute('href', STATUS_URL)
    expect(status).toHaveAttribute('target', '_blank')
    expect(status).toHaveTextContent(es.nav.statusLine)
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
  it("saves the gym's words with the page, and every screen reads them at once (#344)", async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    const nav = screen.getByRole('navigation', { name: es.nav.label })
    expect(within(nav).getByRole('link', { name: 'Alumnos' })).toBeInTheDocument()
    expect(within(settings).getByLabelText(gym.vocabulary.place)).toHaveValue('academia')
    await userEvent.selectOptions(within(settings).getByLabelText(gym.vocabulary.place), 'Club')
    await userEvent.selectOptions(within(settings).getByLabelText(gym.vocabulary.members), 'Socios')
    await userEvent.selectOptions(within(settings).getByLabelText(gym.vocabulary.coach), 'Entrenador')
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByText(gym.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { vocabulary: { place: 'club', members: 'socios', coach: 'entrenador' } },
    ])
    expect(within(nav).getByRole('link', { name: 'Socios' })).toBeInTheDocument()
    expect(within(settings).getByLabelText('Nombre del club')).toHaveValue('Academia Sur')
  })

  it("offers another activity's words in one tap, saved with the page (#344)", async () => {
    const judo: Activity = {
      ...BJJ,
      id: 'judo',
      name: 'Judo',
      preset: 'judo',
      words: { place: 'dojo', members: 'alumnos', coach: 'sensei' },
    }
    const calls = stubApi({ activities: [{ ...BJJ, preset: 'bjj', words: DEFAULT_VOCABULARY }, judo] })
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    const suggest = await within(settings).findByRole('button', { name: gym.vocabulary.suggest('Judo') })
    // BJJ's words are the gym's already.
    expect(within(settings).queryByRole('button', { name: gym.vocabulary.suggest('BJJ') })).not.toBeInTheDocument()
    await userEvent.click(suggest)

    expect(within(settings).getByLabelText(gym.vocabulary.place)).toHaveValue('dojo')
    expect(within(settings).getByLabelText(gym.vocabulary.coach)).toHaveValue('sensei')
    expect(within(settings).getByText(gym.vocabulary.suggested)).toBeInTheDocument()
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByText(gym.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { vocabulary: { place: 'dojo', members: 'alumnos', coach: 'sensei' } },
    ])
  })

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
    // Resumen del mes by email (#507): on until the titular turns it off.
    const summaryEmail = within(settings).getByLabelText(gym.summaryEmail)
    expect(summaryEmail).toBeChecked()
    await userEvent.click(summaryEmail)
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByRole('status')).toHaveTextContent(gym.saved)
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/gym/settings',
        body: {
          name: 'Academia Sur Ñuñoa',
          grace_days: 7,
          channels: { whatsapp: false },
          summary_email: false,
        },
      },
    ])
  })

  it('picks the theme from a preview of each, and Guardar keeps it (#199, #241)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    const bosque = within(settings).getByRole('radio', { name: new RegExp(gym.themes.bosque) })
    expect(bosque).toBeChecked()
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('bosque'))
    // Each preview wears its own theme, whatever the page wears.
    expect(bosque.nextElementSibling).toHaveAttribute('data-theme', 'bosque')

    await userEvent.click(within(settings).getByRole('radio', { name: new RegExp(gym.themes.volcan) }))
    // Picked, not yet saved: every screen wears it at once, and nothing is remembered.
    expect(document.documentElement.dataset.theme).toBe('volcan')
    expect(localStorage.getItem('rakin.theme')).not.toBe('volcan')
    expect(within(settings).getByText(gym.themePreview(gym.themes.volcan, gym.themes.bosque))).toBeInTheDocument()
    await userEvent.click(within(settings).getByRole('button', { name: gym.submit }))

    expect(await within(settings).findByText(gym.saved)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ theme: 'volcan' }])
    expect(within(settings).queryByText(gym.themePreview(gym.themes.volcan, gym.themes.bosque))).not.toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem('rakin.theme')).toBe('volcan'))
    // Saved: leaving Gimnasio keeps it on.
    await userEvent.click(screen.getByRole('link', { name: copy.backLabel }))
    await screen.findByRole('navigation', { name: copy.sectionsLabel })
    expect(document.documentElement.dataset.theme).toBe('volcan')
  })

  it('puts the saved theme back on Cancelar, or on leaving without saving (#241)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/gimnasio')

    const settings = await screen.findByRole('form', { name: gym.formLabel })
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('bosque'))
    const oceano = within(settings).getByRole('radio', { name: new RegExp(gym.themes.oceano) })

    await userEvent.click(oceano)
    expect(document.documentElement.dataset.theme).toBe('oceano')
    await userEvent.click(within(settings).getByRole('button', { name: gym.themeCancel }))
    expect(document.documentElement.dataset.theme).toBe('bosque')
    expect(within(settings).getByRole('radio', { name: new RegExp(gym.themes.bosque) })).toBeChecked()

    await userEvent.click(oceano)
    expect(document.documentElement.dataset.theme).toBe('oceano')
    await userEvent.click(screen.getByRole('link', { name: copy.backLabel }))
    await screen.findByRole('navigation', { name: copy.sectionsLabel })
    expect(document.documentElement.dataset.theme).toBe('bosque')
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([])
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
    // Focus is on the first field refused, not left on the page (#362).
    expect(settings.querySelector('[aria-invalid="true"]')).toHaveFocus()
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

const activities = gym.activities

describe('Ajustes: Gimnasio, actividades', () => {
  // Once the gym's activities are in, and the way to add one under them.
  const panel = async () => {
    const group = await screen.findByRole('group', { name: activities.title })
    await within(group).findByRole('combobox', { name: activities.add })
    return group
  }
  const sectionLinks = async () =>
    within(await screen.findByRole('navigation', { name: copy.sectionsLabel }))
      .getAllByRole('link')
      .map((l) => l.getAttribute('href'))

  it('lists what the gym teaches, with whether each grades', async () => {
    stubApi({ activities: [BJJ, { ...BJJ, id: 'ballet', name: 'Ballet', uses_grades: false, class_types: 0 }] })
    renderAt('/admin/ajustes/gimnasio')

    const list = within(await panel()).getAllByRole('listitem')
    expect(list.map((item) => within(item).getByRole('checkbox', { name: activities.usesGrades }))).toHaveLength(2)
    expect(list[0]).toHaveTextContent('BJJ')
    expect(list[0]).toHaveTextContent(activities.classTypes(2))
    expect(within(list[0]!).getByRole('checkbox')).toBeChecked()
    expect(within(list[1]!).getByRole('checkbox')).not.toBeChecked()
  })

  it('says so when the gym has none yet', async () => {
    stubApi({ activities: [] })
    renderAt('/admin/ajustes/gimnasio')
    expect(await within(await panel()).findByText(activities.none)).toBeInTheDocument()
  })

  it('adds a preset with its own "Usa grados", or another by name, saved on their own', async () => {
    const calls = stubApi({ activities: [] })
    renderAt('/admin/ajustes/gimnasio')
    const group = await panel()

    const adding = within(group).getByRole('group', { name: activities.add })
    await userEvent.selectOptions(within(group).getByRole('combobox', { name: activities.add }), 'Judo')
    expect(within(adding).getByRole('checkbox', { name: activities.usesGrades })).toBeChecked()
    await userEvent.click(within(group).getByRole('button', { name: activities.addSubmit }))
    expect(await within(group).findByText(activities.added('Judo'))).toBeInTheDocument()

    await userEvent.selectOptions(within(group).getByRole('combobox', { name: activities.add }), 'Piano')
    expect(within(adding).getByRole('checkbox', { name: activities.usesGrades })).not.toBeChecked()
    await userEvent.click(within(group).getByRole('button', { name: activities.addSubmit }))
    await within(group).findByText(activities.added('Piano'))

    await userEvent.selectOptions(within(group).getByRole('combobox', { name: activities.add }), activities.other)
    await userEvent.type(within(group).getByRole('textbox', { name: activities.name }), 'Parkour{Enter}')
    await within(group).findByText(activities.added('Parkour'))

    expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/activities').map((c) => c.body)).toEqual([
      { name: 'Judo', uses_grades: true, preset: 'judo' },
      { name: 'Piano', uses_grades: false, preset: 'piano' },
      { name: 'Parkour', uses_grades: false },
    ])
    // Enter added the activity; it did not save the Gimnasio form.
    expect(calls.some((c) => c.method === 'PATCH' && c.path === '/api/gym/settings')).toBe(false)
    // A preset added is offered no more.
    const offered = within(within(group).getByRole('combobox', { name: activities.add })).getAllByRole('option')
    expect(offered.map((o) => o.textContent)).not.toContain('Judo')
  })

  it('says a name is taken', async () => {
    stubApi({ activities: [], changeActivity: { status: 409, body: { detail: 'taken' } } })
    renderAt('/admin/ajustes/gimnasio')
    const group = await panel()
    await userEvent.selectOptions(within(group).getByRole('combobox', { name: activities.add }), activities.other)
    await userEvent.type(within(group).getByRole('textbox', { name: activities.name }), 'bjj')
    await userEvent.click(within(group).getByRole('button', { name: activities.addSubmit }))
    expect(await within(group).findByText(activities.taken)).toBeInTheDocument()
  })

  it('turns grades on and off, renames and removes, and Graduación follows', async () => {
    // On a desktop, where the sections are tabs over Gimnasio.
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches: true, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
    )
    const calls = stubApi()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderAt('/admin/ajustes/gimnasio')
    const group = await panel()

    await userEvent.click(within(group).getByRole('checkbox', { name: activities.usesGrades }))
    expect(await within(group).findByText(activities.gradesOff('BJJ'))).toBeInTheDocument()
    await waitFor(async () => expect(await sectionLinks()).not.toContain('/admin/ajustes/graduacion'))

    await userEvent.click(within(group).getByRole('checkbox', { name: activities.usesGrades }))
    await within(group).findByText(activities.gradesOn('BJJ'))
    await waitFor(async () => expect(await sectionLinks()).toContain('/admin/ajustes/graduacion'))

    await userEvent.click(within(group).getByRole('button', { name: activities.rename }))
    const name = within(group).getByRole('textbox', { name: activities.renameLabel('BJJ') })
    await userEvent.clear(name)
    await userEvent.type(name, 'Jiu-jitsu{Enter}')
    await within(group).findByText(activities.renamed('Jiu-jitsu'))

    await userEvent.click(within(group).getByRole('button', { name: activities.removeLabel('Jiu-jitsu') }))
    await within(group).findByText(activities.removed('Jiu-jitsu'))
    expect(window.confirm).toHaveBeenCalledWith(activities.removeConfirm('Jiu-jitsu', 2))
    expect(within(group).getByText(activities.none)).toBeInTheDocument()

    expect(calls.filter((c) => c.path === '/api/activities/bjj').map((c) => [c.method, c.body])).toEqual([
      ['PATCH', { uses_grades: false }],
      ['PATCH', { uses_grades: true }],
      ['PATCH', { name: 'Jiu-jitsu' }],
      ['DELETE', undefined],
    ])
    expect(calls.some((c) => c.method === 'PATCH' && c.path === '/api/gym/settings')).toBe(false)
  })

  it('keeps an activity when the removal is not confirmed', async () => {
    const calls = stubApi()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderAt('/admin/ajustes/gimnasio')
    await userEvent.click(within(await panel()).getByRole('button', { name: activities.removeLabel('BJJ') }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('says so when a change fails', async () => {
    stubApi({ changeActivity: { status: 500, body: {} } })
    renderAt('/admin/ajustes/gimnasio')
    const group = await panel()
    await userEvent.click(within(group).getByRole('checkbox', { name: activities.usesGrades }))
    expect(await within(group).findByText(activities.failed)).toBeInTheDocument()
  })
})

describe('Ajustes: Graduación, with no activity that grades', () => {
  it('is not among the sections, on a phone or a desktop', async () => {
    stubApi({ activities: [{ ...BJJ, uses_grades: false }] })
    renderAt('/admin/ajustes')
    const sections = await screen.findByRole('navigation', { name: copy.sectionsLabel })
    await waitFor(() => expect(within(sections).getAllByRole('link')).toHaveLength(11))
    expect(within(sections).queryByRole('link', { name: new RegExp(copy.sections.grading) })).not.toBeInTheDocument()
  })

  it('says where to turn grades on, and asks nothing of the scheme', async () => {
    const calls = stubApi({ activities: [] })
    renderAt('/admin/ajustes/graduacion')
    expect(await screen.findByText(copy.grading.off)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: copy.grading.turnOn })).toHaveAttribute(
      'href',
      '/admin/ajustes/gimnasio#actividades',
    )
    expect(calls.some((c) => c.path.startsWith('/api/gym/grading-scheme'))).toBe(false)
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
          // No matrícula (#355).
          enrolment_fee_clp: null,
        },
      },
    ])
  })

  it('creates a plan with a matrícula, lists it, and an edit takes it off (#355)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.name), 'Mensual kids')
    await userEvent.type(within(create).getByLabelText(form.price), '36.000')
    const fee = within(create).getByLabelText(form.enrolmentFee)
    expect(fee).toHaveAccessibleDescription(form.enrolmentHint)
    await userEvent.type(fee, '25.000')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.created('Mensual kids'))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([
      {
        kind: 'monthly',
        name: 'Mensual kids',
        program_id: null,
        price_clp: 36000,
        anchor: 'signup',
        enrolment_fee_clp: 25000,
      },
    ])
    const row = (await within(section).findAllByRole('listitem')).find((r) => r.textContent?.includes('Mensual kids'))!
    expect(row).toHaveTextContent(
      plans.row(plans.kinds.monthly, plans.row(plans.row('$36.000 al mes', plans.anchors.signup), 'matrícula $25.000')),
    )

    await userEvent.click(within(row).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual kids') })
    await userEvent.clear(within(edit).getByLabelText(form.enrolmentFee))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.saved('Mensual kids'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ enrolment_fee_clp: null }])
  })

  it('offers to move the members on a monthly plan to its new anchor, and says what it bills (#547)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    await userEvent.click(within(rows[0]!).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    // Nothing to offer until the anchor changes.
    expect(within(edit).queryByText(form.anchorMove.legend)).not.toBeInTheDocument()
    await userEvent.selectOptions(within(edit).getByLabelText(form.anchor), plans.anchors.first)

    const offer = await within(edit).findByRole('checkbox', { name: form.anchorMove.offer(1, 'first') })
    // Unticked, the form says they keep their day before it is saved.
    expect(within(edit).getByText(form.anchorMove.declined('first'))).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/plans/mensual/anchor-moves?anchor=first')).toBe(true)
    await userEvent.click(offer)
    expect(within(edit).getByText(form.anchorMove.proration)).toBeInTheDocument()
    expect(within(edit).getByText(/Ana Rojas/)).toHaveTextContent(
      `Ana Rojas · ${form.anchorMove.line('12 dic', '31 dic', '$22.580', '1 ene', '$35.000')}`,
    )
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.savedMoved('Mensual adultos', 1))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { anchor: 'first', move_members: true },
    ])
  })

  it("shows a save in the plan's row with the notice, before the list is read again (#558)", async () => {
    const calls = stubApi({ holdPlans: true })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    await userEvent.click(within(rows[0]!).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    await userEvent.selectOptions(within(edit).getByLabelText(form.anchor), plans.anchors.first)
    await userEvent.click(await within(edit).findByRole('checkbox', { name: form.anchorMove.offer(1, 'first') }))
    await userEvent.clear(within(edit).getByLabelText(form.price))
    await userEvent.type(within(edit).getByLabelText(form.price), '38.000')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.savedMoved('Mensual adultos', 1))
    expect(within(section).getAllByRole('listitem')[0]).toHaveTextContent(
      plans.row(plans.kinds.monthly, plans.row('$38.000 al mes', plans.anchors.first)),
    )
    // The list was asked for again, and has not answered.
    expect(calls.filter((c) => c.method === 'GET' && c.path === '/api/plans')).toHaveLength(2)
  })

  it('changes the anchor alone when the owner leaves the members on their day (#547)', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    await userEvent.click(within(rows[0]!).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    await userEvent.selectOptions(within(edit).getByLabelText(form.anchor), plans.anchors.first)
    await within(edit).findByRole('checkbox', { name: form.anchorMove.offer(1, 'first') })
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.saved('Mensual adultos'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ anchor: 'first' }])
  })

  it('says a pending move is withdrawn when the anchor changes back, ticked or not (#547)', async () => {
    const calls = stubApi({
      anchorQuote: {
        moves: [],
        withdrawn: [
          { membership_id: 'm-ana', person_id: 'p-ana', name: 'Ana Rojas', status: 'active', pending_day: 1, stays_on: 12 },
        ],
      },
    })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    const rows = await within(section).findAllByRole('listitem')
    await userEvent.click(within(rows[0]!).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Mensual adultos') })
    await userEvent.selectOptions(within(edit).getByLabelText(form.anchor), plans.anchors.first)

    expect(await within(edit).findByText(/Ana Rojas/)).toHaveTextContent(
      `Ana Rojas · ${form.anchorMove.withdrawn(1, 12)}`,
    )
    // Nobody to move, so no offer, and no "nadie cambia" beside the withdrawal.
    expect(within(edit).queryByRole('checkbox')).not.toBeInTheDocument()
    expect(within(edit).queryByText(form.anchorMove.none)).not.toBeInTheDocument()
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.saved('Mensual adultos'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ anchor: 'first' }])
  })

  it('asks no matrícula of a drop-in or a trial (#355)', async () => {
    stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    for (const kind of ['dropin', 'trial'] as const) {
      await userEvent.selectOptions(within(create).getByLabelText(form.kind), plans.kinds[kind])
      expect(within(create).queryByLabelText(form.enrolmentFee)).not.toBeInTheDocument()
    }
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

  it('creates a fixed-period plan with its two dates, and lists it with them', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.selectOptions(within(create).getByLabelText(form.kind), plans.kinds.fixed_period)
    expect(within(create).queryByLabelText(form.periodMonths)).not.toBeInTheDocument()
    await userEvent.type(within(create).getByLabelText(form.name), 'Temporada 2027')
    await userEvent.type(within(create).getByLabelText(form.price), '300.000')
    await userEvent.type(within(create).getByLabelText(form.periodStart), '2027-03-01')
    await userEvent.type(within(create).getByLabelText(form.periodEnd), '2027-12-31')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.created('Temporada 2027'))
    const row = (await within(section).findAllByRole('listitem')).at(-1)!
    expect(row).toHaveTextContent(plans.row(plans.kinds.fixed_period, plans.summary.fixed_period('$300.000', '1 mar 2027', '31 dic 2027')))
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.body)).toEqual([
      {
        kind: 'fixed_period',
        name: 'Temporada 2027',
        program_id: null,
        price_clp: 300000,
        period_start: '2027-03-01',
        period_end: '2027-12-31',
        enrolment_fee_clp: null,
      },
    ])
  })

  it('puts a period ending before it starts under Hasta', async () => {
    stubApi({ savePlan: refused([['body', 'fixed_period', 'period_end'], 'period_order']) })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within(section).getByRole('button', { name: plans.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.selectOptions(within(create).getByLabelText(form.kind), plans.kinds.fixed_period)
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(create).findByRole('alert')).toHaveTextContent(form.invalid)
    expect(within(create).getByLabelText(form.periodEnd)).toHaveAccessibleDescription(
      `${form.periodHint} ${form.value.period_order}`,
    )
  })

  it('copies a fixed-period plan for its next period and moves the members ticked', async () => {
    const calls = stubApi({ plans: [SEASON] })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within((await within(section).findAllByRole('listitem'))[0]!).getByRole('button'))
    const edit = within(section).getByRole('form', { name: form.edit('Temporada 2027') })
    await userEvent.click(within(edit).getByRole('button', { name: plans.nextPeriod.open }))

    const next = within(section).getByRole('form', { name: plans.nextPeriod.title('Temporada 2027') })
    // A year on, to begin with.
    expect(within(next).getByLabelText(form.name)).toHaveValue('Temporada 2028')
    expect(within(next).getByLabelText(form.price)).toHaveValue('300000')
    expect(within(next).getByLabelText(form.periodStart)).toHaveValue('2028-03-01')
    expect(within(next).getByLabelText(form.periodEnd)).toHaveValue('2028-12-31')
    const ana = await within(next).findByRole('checkbox', { name: 'Ana Rojas' })
    const luis = within(next).getByRole('checkbox', { name: `Luis Pérez · ${plans.nextPeriod.frozen}` })
    expect(ana).toBeChecked()
    expect(luis).toBeChecked()
    await userEvent.click(luis)
    await userEvent.clear(within(next).getByLabelText(form.price))
    await userEvent.type(within(next).getByLabelText(form.price), '320.000')
    await userEvent.click(within(next).getByRole('button', { name: plans.nextPeriod.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(plans.nextPeriod.done('Temporada 2028', 1))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/plans/temporada/next-period',
        body: {
          name: 'Temporada 2028',
          price_clp: 320000,
          period_start: '2028-03-01',
          period_end: '2028-12-31',
          membership_ids: ['m-ana'],
        },
      },
    ])
  })

  it('says when the next period does not start after this one', async () => {
    stubApi({ plans: [SEASON], savePlan: refused([['body', 'period_start'], 'after_period']) })
    renderAt('/admin/ajustes/planes')

    const section = await screen.findByRole('region', { name: plans.title })
    await userEvent.click(within((await within(section).findAllByRole('listitem'))[0]!).getByRole('button'))
    await userEvent.click(within(section).getByRole('button', { name: plans.nextPeriod.open }))
    const next = within(section).getByRole('form', { name: plans.nextPeriod.title('Temporada 2027') })
    await within(next).findByRole('checkbox', { name: 'Ana Rojas' })
    await userEvent.click(within(next).getByRole('button', { name: plans.nextPeriod.submit }))

    expect(await within(next).findByRole('alert')).toHaveTextContent(form.invalid)
    expect(within(next).getByLabelText(form.periodStart)).toHaveAccessibleDescription(
      plans.nextPeriod.afterPeriod('31 dic 2027'),
    )
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
