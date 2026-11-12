import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GradingScheme } from '../api/grading'
import type { MemberPage, MemberRow, Plan, Program } from '../api/people'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { validateStudentsSearch } from './Students'

const copy = es.admin.students

const CAMILA: MemberRow = {
  id: 'p1',
  name: 'Camila Rojas',
  phone: '+56987654321',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  rut: '7654321-6',
  membership: { id: 'm1', status: 'active', plan_id: 'plan-adults', plan_name: 'Mensual adultos' },
  guardian: null,
  dependents: 0,
  left_on: null,
}
const DIEGO: MemberRow = {
  id: 'p2',
  name: 'Diego Soto',
  phone: null,
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  rut: null,
  membership: null,
  guardian: null,
  dependents: 0,
  left_on: null,
}
const PLANS: Plan[] = [
  { id: 'plan-adults', name: 'Mensual adultos', active: true },
  { id: 'plan-old', name: 'Plan 2024', active: false },
]
const PROGRAMS: Program[] = [
  { id: 'program-kids', name: 'Kids', active: true },
  { id: 'program-old', name: 'Competición', active: false },
]

const rank = (key: string, label: string) => ({ key, label, sub_ranks: [] })
const BJJ: GradingScheme = {
  ranks: [rank('white', 'Blanca'), rank('blue', 'Azul'), rank('black', 'Negra')],
  kids_ladder: [rank('grey', 'Gris'), rank('yellow', 'Amarilla')],
  goal_metric: null,
}

type Answer = { status?: number; body: unknown }

// Answers by path, and records every /api/people query it was asked.
function stubApi(
  people: (params: URLSearchParams) => Answer,
  plans: Answer = { body: PLANS },
  programs: Answer = { body: PROGRAMS },
  // Who is signed in; unanswered, as if the role never loaded.
  role?: 'owner' | 'admin' | 'coach',
  // The gym's grading scheme; unanswered, as a gym that does not grade.
  scheme?: GradingScheme,
  // Whether an activity of the gym grades (#245): by default, when it has a scheme.
  grades = scheme !== undefined,
) {
  const asked: URLSearchParams[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), 'http://localhost')
      let answer: Answer
      if (url.pathname === '/api/people') {
        asked.push(url.searchParams)
        answer = people(url.searchParams)
      } else if (url.pathname === '/api/plans') {
        answer = plans
      } else if (url.pathname === '/api/programs') {
        answer = programs
      } else if (url.pathname === '/api/gym/grading-scheme' && scheme) {
        answer = { body: scheme }
      } else if (url.pathname === '/api/me/role' && (role || grades)) {
        answer = { body: { role: role ?? 'admin', person_id: 'me', uses_grades: grades } }
      } else {
        answer = { status: 404, body: { detail: 'Not Found' } }
      }
      return new Response(JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return asked
}

function page(items: MemberRow[], total = items.length): Answer {
  return { body: { items, total } satisfies MemberPage }
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
  return router
}

const list = () => screen.findByRole('list', { name: copy.title })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Alumnos', () => {
  it('offers "Nuevo alumno" beside the import to an owner or admin, never a coach', async () => {
    stubApi(() => page([CAMILA]), undefined, undefined, 'admin')
    renderAt('/admin/alumnos')
    expect(await screen.findByRole('link', { name: copy.newLink })).toHaveAttribute('href', '/admin/alumnos/nuevo')
    expect(screen.getByRole('link', { name: copy.importLink })).toBeInTheDocument()
  })

  it('hides "Nuevo alumno" from a coach', async () => {
    stubApi(() => page([CAMILA]), undefined, undefined, 'coach')
    renderAt('/admin/alumnos')
    await list()
    expect(screen.queryByRole('link', { name: copy.newLink })).not.toBeInTheDocument()
  })

  it('"Dados de baja" lists who left the gym, and since when', async () => {
    const gone: MemberRow = { ...DIEGO, left_on: '2026-10-31' }
    const asked = stubApi((params) => page(params.get('left') === 'only' ? [gone] : [CAMILA]))
    const router = renderAt('/admin/alumnos')
    await list()

    await userEvent.click(screen.getByRole('button', { name: copy.left }))

    expect(await screen.findByText(copy.leftOn('31-10-2026'))).toBeInTheDocument()
    expect(asked.map((params) => params.get('left'))).toEqual([null, 'only'])
    expect(router.state.location.search).toEqual({ left: true })
    expect(screen.getByRole('button', { name: copy.left })).toHaveAttribute('aria-pressed', 'true')
  })

  it('"Falta teléfono" lists who the gym cannot reach yet, and flags them', async () => {
    const unreachable: MemberRow = { ...DIEGO, missing_phone: true }
    const sinWhatsapp: MemberRow = { ...CAMILA, phone: null, no_whatsapp: true }
    const asked = stubApi((params) =>
      page(params.get('missing_phone') === 'true' ? [unreachable] : [sinWhatsapp, unreachable]),
    )
    const router = renderAt('/admin/alumnos')
    const members = await list()
    expect(within(members).getByText(copy.noWhatsapp)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: copy.missingPhone }))

    await waitFor(() => expect(asked.map((params) => params.get('missing_phone'))).toEqual([null, 'true']))
    expect(router.state.location.search).toEqual({ missingPhone: true })
    expect(screen.getByRole('button', { name: copy.missingPhone })).toHaveAttribute('aria-pressed', 'true')
    expect(await within(await list()).findByText(copy.missingPhone)).toBeInTheDocument()
  })

  it('"Falta RUT" lists who has neither a RUT nor an email, and flags them', async () => {
    const keyless: MemberRow = { ...DIEGO, missing_rut: true }
    const asked = stubApi((params) => page(params.get('missing_rut') === 'true' ? [keyless] : [CAMILA, keyless]))
    const router = renderAt('/admin/alumnos')
    await list()

    await userEvent.click(screen.getByRole('button', { name: copy.missingRut }))

    await waitFor(() => expect(asked.map((params) => params.get('missing_rut'))).toEqual([null, 'true']))
    expect(router.state.location.search).toEqual({ missingRut: true })
    expect(await within(await list()).findByText(copy.missingRut)).toBeInTheDocument()
  })

  it('"Sin venir 14 d" lists who is away, as Hoy\'s "Ver los N" opens it', async () => {
    const asked = stubApi((params) => page(params.get('away') === 'true' ? [DIEGO] : [CAMILA, DIEGO]))
    renderAt('/admin/alumnos?away=true')

    expect(await within(await list()).findByText('Diego Soto')).toBeInTheDocument()
    expect(asked.map((params) => params.get('away'))).toEqual(['true'])
    expect(screen.getByRole('button', { name: copy.away })).toHaveAttribute('aria-pressed', 'true')
  })

  it('lists members with their phone, RUT, status and plan', async () => {
    stubApi(() => page([CAMILA, DIEGO]))
    renderAt('/admin/alumnos')

    const rows = within(await list()).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      `Camila Rojas+56 9 8765 43217.654.321-6ActivoMensual adultos${es.admin.family.toggle}`,
      `Diego Soto${copy.noPlan}${es.admin.family.toggle}`,
    ])
    expect(screen.getByText(copy.count(2))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.clearFilters })).not.toBeInTheDocument()
  })

  it("links each member's name to their detail", async () => {
    stubApi(() => page([CAMILA]))
    renderAt('/admin/alumnos')
    await list()

    expect(screen.getByRole('link', { name: 'Camila Rojas' })).toHaveAttribute('href', '/admin/alumnos/p1')
  })

  it('searches by what is typed, once typing pauses', async () => {
    const asked = stubApi((params) => page(params.get('q') === '9 8765' ? [CAMILA] : [CAMILA, DIEGO]))
    const router = renderAt('/admin/alumnos')
    await list()

    await userEvent.type(screen.getByRole('searchbox', { name: copy.searchLabel }), '9 8765')

    await waitFor(() => expect(within(screen.getByRole('list', { name: copy.title })).getAllByRole('listitem')).toHaveLength(1))
    expect(asked.map((params) => params.get('q'))).toEqual([null, '9 8765'])
    expect(router.state.location.search).toEqual({ q: '9 8765' })
  })

  it('filters by status, several at once', async () => {
    const asked = stubApi(() => page([CAMILA]))
    const router = renderAt('/admin/alumnos')
    await list()
    const statuses = screen.getByRole('group', { name: copy.statusLabel })

    await userEvent.click(within(statuses).getByRole('button', { name: copy.status.lapsed }))
    await userEvent.click(within(statuses).getByRole('button', { name: copy.status.trial }))

    await waitFor(() => expect(asked.at(-1)?.getAll('status')).toEqual(['trial', 'lapsed']))
    expect(within(statuses).getByRole('button', { name: copy.status.lapsed })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(statuses).getByRole('button', { name: copy.status.active })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(router.state.location.search).toEqual({ status: ['trial', 'lapsed'] })

    await userEvent.click(within(statuses).getByRole('button', { name: copy.status.lapsed }))
    await waitFor(() => expect(asked.at(-1)?.getAll('status')).toEqual(['trial']))
  })

  it('filters by plan, inactive plans marked', async () => {
    const asked = stubApi(() => page([CAMILA]))
    renderAt('/admin/alumnos')
    const select = await screen.findByRole('combobox', { name: copy.planLabel })

    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      copy.allPlans,
      'Mensual adultos',
      copy.inactivePlan('Plan 2024'),
    ])
    await userEvent.selectOptions(select, 'plan-old')

    await waitFor(() => expect(asked.at(-1)?.getAll('plan_id')).toEqual(['plan-old']))
  })

  it('works without the plan filter when plans cannot be read', async () => {
    stubApi(() => page([CAMILA]), { status: 404, body: { detail: 'Not Found' } }, { body: [] })
    renderAt('/admin/alumnos')

    await list()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('filters by program, inactive programs marked', async () => {
    const asked = stubApi(() => page([CAMILA]))
    renderAt('/admin/alumnos')
    const select = await screen.findByRole('combobox', { name: copy.programLabel })

    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      copy.allPrograms,
      'Kids',
      copy.inactiveProgram('Competición'),
    ])
    await userEvent.selectOptions(select, 'program-kids')

    await waitFor(() => expect(asked.at(-1)?.getAll('program_id')).toEqual(['program-kids']))
    expect(asked.at(-1)?.getAll('plan_id')).toEqual([])
  })

  it('has no program filter while the gym has no programs', async () => {
    stubApi(() => page([CAMILA]), undefined, { body: [] })
    renderAt('/admin/alumnos')

    await screen.findByRole('combobox', { name: copy.planLabel })
    expect(screen.queryByRole('combobox', { name: copy.programLabel })).not.toBeInTheDocument()
  })

  it('offers no belt filter while no activity of the gym grades, whatever its scheme', async () => {
    const asked = stubApi(() => page([CAMILA]), undefined, undefined, 'admin', BJJ, false)
    renderAt('/admin/alumnos')
    await list()
    expect(screen.queryByRole('combobox', { name: copy.rankLabel })).not.toBeInTheDocument()
    expect(asked).toHaveLength(1)
  })

  it('filters by belt, exactly or "o superior", adults and kids apart', async () => {
    const asked = stubApi(() => page([CAMILA]), undefined, undefined, undefined, BJJ)
    const router = renderAt('/admin/alumnos')
    const select = await screen.findByRole('combobox', { name: copy.rankLabel })

    const groups = within(select).getAllByRole('group')
    expect(groups.map((g) => g.getAttribute('label'))).toEqual(['Adultos', 'Kids'])
    // The top of a ladder "o superior" is that belt alone: offered once.
    expect(within(groups[0]!).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Blanca',
      'Blanca o superior',
      'Azul',
      'Azul o superior',
      'Negra',
    ])
    expect(within(groups[1]!).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Gris',
      'Gris o superior',
      'Amarilla',
    ])

    await userEvent.selectOptions(select, 'Azul o superior')
    await waitFor(() => expect(asked.at(-1)?.get('rank_min')).toBe('blue'))
    expect(asked.at(-1)?.getAll('rank')).toEqual([])
    expect(router.state.location.search).toEqual({ belt: 'blue', beltUp: true })

    await userEvent.selectOptions(select, 'Azul')
    await waitFor(() => expect(asked.at(-1)?.getAll('rank')).toEqual(['blue']))
    expect(asked.at(-1)?.get('rank_min')).toBeNull()
    expect(router.state.location.search).toEqual({ belt: 'blue' })

    // Back to the unfiltered list, already in the cache.
    await userEvent.selectOptions(select, copy.allRanks)
    await waitFor(() => expect(router.state.location.search).toEqual({}))
  })

  it('has no belt filter while the gym does not grade', async () => {
    const none: GradingScheme = { ranks: [], kids_ladder: [], goal_metric: null }
    stubApi(() => page([CAMILA]), undefined, undefined, undefined, none)
    renderAt('/admin/alumnos')

    await screen.findByRole('combobox', { name: copy.programLabel })
    expect(screen.queryByRole('combobox', { name: copy.rankLabel })).not.toBeInTheDocument()
  })

  it('opens with the belt in the URL', async () => {
    const asked = stubApi(() => page([CAMILA]), undefined, undefined, undefined, BJJ)
    renderAt('/admin/alumnos?belt=%22grey%22&beltUp=true')

    expect(await screen.findByRole('combobox', { name: copy.rankLabel })).toHaveDisplayValue('Gris o superior')
    expect(asked[0]?.get('rank_min')).toBe('grey')
    expect(screen.getByRole('button', { name: copy.clearFilters })).toBeInTheDocument()
  })

  it('opens with the filters in the URL and clears them all', async () => {
    const asked = stubApi((params) => page(params.toString().includes('q=') ? [] : [CAMILA]))
    const router = renderAt(
      '/admin/alumnos?q=%22nadie%22&status=%5B%22frozen%22%5D&plan=%22plan-adults%22&program=%22program-kids%22',
    )

    expect(await screen.findByText(copy.noMatches)).toBeInTheDocument()
    const first = asked[0]!
    expect([first.get('q'), first.getAll('status'), first.getAll('plan_id'), first.getAll('program_id')]).toEqual([
      'nadie',
      ['frozen'],
      ['plan-adults'],
      ['program-kids'],
    ])
    expect(screen.getByRole('searchbox')).toHaveValue('nadie')

    await userEvent.click(screen.getByRole('button', { name: copy.clearFilters }))

    await list()
    expect(router.state.location.search).toEqual({})
    expect(screen.getByRole('searchbox')).toHaveValue('')
  })

  it('says so when the gym has no members yet', async () => {
    stubApi(() => page([]))
    renderAt('/admin/alumnos')
    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
  })

  it('loads the next page on demand', async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ ...DIEGO, id: `p${i}`, name: `Alumno ${i}` }))
    const asked = stubApi((params) => (params.get('offset') === '0' ? page(many, 51) : page([CAMILA], 51)))
    renderAt('/admin/alumnos')
    await list()

    await userEvent.click(screen.getByRole('button', { name: copy.more }))

    await waitFor(() => expect(within(screen.getByRole('list', { name: copy.title })).getAllByRole('listitem')).toHaveLength(51))
    expect(asked.map((params) => params.get('offset'))).toEqual(['0', '50'])
    expect(screen.queryByRole('button', { name: copy.more })).not.toBeInTheDocument()
  })

  it('offers a retry when the list fails to load', async () => {
    let fail = true
    stubApi(() => (fail ? { status: 403, body: { detail: 'no' } } : page([CAMILA])))
    renderAt('/admin/alumnos')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.error)
    fail = false
    await userEvent.click(screen.getByRole('button', { name: copy.retry }))

    await list()
  })
})

describe('validateStudentsSearch', () => {
  it('keeps known values and drops the rest', () => {
    expect(validateStudentsSearch({ q: 'ana', status: ['frozen', 'gone', 3], plan: 'x', program: 'y' })).toEqual({
      q: 'ana',
      status: ['frozen'],
      plan: 'x',
      program: 'y',
    })
    expect(validateStudentsSearch({ q: '  ', status: 'trial', plan: 7, program: '' })).toEqual({
      q: undefined,
      status: ['trial'],
      plan: undefined,
      program: undefined,
    })
    // "o superior" means nothing without a belt.
    expect(validateStudentsSearch({ belt: 'blue', beltUp: 'true' })).toMatchObject({ belt: 'blue', beltUp: true })
    expect(validateStudentsSearch({ belt: '', beltUp: true })).toMatchObject({ belt: undefined, beltUp: undefined })
    expect(validateStudentsSearch({})).toEqual({
      q: undefined,
      status: undefined,
      plan: undefined,
      program: undefined,
    })
  })
})
