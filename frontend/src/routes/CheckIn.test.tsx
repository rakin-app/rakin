import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { warning, type Arrival, type Candidate, type Door } from '../api/checkIn'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.checkIn

const person = (id: string, name: string, extra: Partial<Candidate> = {}): Candidate => ({
  membership_id: `m-${id}`,
  person_id: `p-${id}`,
  name,
  rut: null,
  plan_name: 'Bono 10 entradas',
  plan_kind: 'credits',
  status: 'active',
  credits_remaining: 6,
  overdue: false,
  checked_in_at: null,
  ...extra,
})

const PAULA = person('paula', 'Paula Contreras')
const TOMAS = person('tomas', 'Tomás Pérez', { status: 'lapsed', plan_kind: 'monthly', credits_remaining: null })
const ANA = person('ana', 'Ana Rojas', { credits_remaining: 0, overdue: true })

const DOOR: Door = {
  class_type_id: 'ct-libre',
  name: 'Acceso libre',
  program_id: 'p-adultos',
  program_name: 'Adultos',
  credit_cost: 1,
  date: '2026-11-16',
  timezone: 'America/Santiago',
  session_id: null,
  cancelled: false,
  arrivals: [],
}

type Call = { method: string; path: string; body: unknown }

function stubApi({ doors = [DOOR], people = [PAULA, TOMAS, ANA] }: { doors?: Door[]; people?: Candidate[] } = {}) {
  const calls: Call[] = []
  let day = doors
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const body: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
      calls.push({ method, path: url.pathname, body })
      const answer = (status: number, json: unknown) =>
        new Response(JSON.stringify(json), { status, headers: { 'Content-Type': 'application/json' } })
      const path = url.pathname
      const arrivals = () => day[0]?.arrivals ?? []
      const withArrivals = (next: Arrival[]): Door[] =>
        day.map((d, i) => (i === 0 ? { ...d, session_id: 's-day', arrivals: next } : d))
      if (path === '/api/me/role') return answer(200, { role: 'coach', person_id: 'coach' })
      if (path === '/api/check-in' && method === 'GET') return answer(200, day)
      if (path === '/api/check-in/ct-libre/search') {
        const q = (url.searchParams.get('q') ?? '').toLowerCase()
        const found = people
          .filter((p) => p.name.toLowerCase().includes(q))
          .map((p) => ({ ...p, checked_in_at: arrivals().find((a) => a.membership_id === p.membership_id)?.marked_at ?? null }))
        return answer(200, found)
      }
      if (path === '/api/check-in/ct-libre' && method === 'POST') {
        const id = (body as { membership_id: string }).membership_id
        const who = people.find((p) => p.membership_id === id)!
        const arrival: Arrival = { ...who, marked_at: '2026-11-16T22:40:00Z', credits_consumed: 1 }
        day = withArrivals([arrival, ...arrivals()])
        return answer(200, day[0])
      }
      const undone = /^\/api\/check-in\/ct-libre\/(.+)$/.exec(path)
      if (undone && method === 'DELETE') {
        day = withArrivals(arrivals().filter((a) => a.membership_id !== undone[1]))
        return answer(200, day[0])
      }
      return answer(404, { detail: 'Not Found' })
    }),
  )
  return calls
}

function renderEntrada() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin/entrada'] }))
  render(<App queryClient={queryClient} router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Entrada', () => {
  it('checks someone in with a search and a tap, then clears the box for the next one', async () => {
    const calls = stubApi()
    renderEntrada()

    const box = await screen.findByRole('searchbox', { name: copy.search.label('Acceso libre') })
    expect(box).toHaveFocus()
    await userEvent.type(box, 'paula')
    await userEvent.click(await screen.findByRole('button', { name: copy.search.enterLabel('Paula Contreras') }))

    expect(calls).toContainEqual({ method: 'POST', path: '/api/check-in/ct-libre', body: { membership_id: 'm-paula' } })
    const today = await screen.findByRole('list', { name: copy.today.title })
    // 22:40 UTC is 19:40 in Santiago.
    expect(within(today).getByText('19:40')).toBeInTheDocument()
    expect(within(today).getByText('Paula Contreras')).toBeInTheDocument()
    expect(screen.getByText(copy.today.count(1))).toBeInTheDocument()
    expect(box).toHaveValue('')
    expect(box).toHaveFocus()
  })

  it('checks in the one person a search finds on Enter', async () => {
    const calls = stubApi()
    renderEntrada()

    const box = await screen.findByRole('searchbox', { name: copy.search.label('Acceso libre') })
    await userEvent.type(box, 'tomás')
    await screen.findByRole('button', { name: copy.search.enterLabel('Tomás Pérez') })
    await userEvent.type(box, '{Enter}')

    await screen.findByRole('list', { name: copy.today.title })
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/check-in/ct-libre', body: { membership_id: 'm-tomas' } },
    ])
  })

  it('warns of a lapsed plan, a spent pack and a payment past due, and still lets them in', async () => {
    stubApi()
    renderEntrada()

    const box = await screen.findByRole('searchbox', { name: copy.search.label('Acceso libre') })
    await userEvent.type(box, 'r')
    const results = await screen.findByRole('list', { name: copy.search.results })
    expect(within(results).getByText(copy.warning.lapsed)).toBeInTheDocument()
    expect(within(results).getByText(copy.warning.noCredits)).toBeInTheDocument()
    expect(within(results).getByText(copy.overdue)).toBeInTheDocument()
    for (const name of ['Paula Contreras', 'Tomás Pérez', 'Ana Rojas']) {
      expect(within(results).getByRole('button', { name: copy.search.enterLabel(name) })).toBeEnabled()
    }
  })

  it('says when someone came in already, and undoes an arrival', async () => {
    const calls = stubApi()
    renderEntrada()

    const box = await screen.findByRole('searchbox', { name: copy.search.label('Acceso libre') })
    await userEvent.type(box, 'paula')
    await userEvent.click(await screen.findByRole('button', { name: copy.search.enterLabel('Paula Contreras') }))
    await userEvent.type(box, 'paula')
    expect(await screen.findByText(copy.search.already('19:40'))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: copy.today.undoLabel('Paula Contreras') }))
    expect(await screen.findByText(copy.today.empty)).toBeInTheDocument()
    expect(calls).toContainEqual({ method: 'DELETE', path: '/api/check-in/ct-libre/m-paula', body: undefined })
  })

  it('says so for a gym with no open access', async () => {
    stubApi({ doors: [] })
    renderEntrada()

    expect(await screen.findByText(copy.none)).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
  })

  it('refuses no one, and never asks for a pack a free entry does not spend', () => {
    expect(warning(PAULA, 1)).toBeNull()
    expect(warning({ ...PAULA, credits_remaining: 1 }, 2)).toBe('noCredits')
    expect(warning({ ...PAULA, credits_remaining: 0 }, 0)).toBeNull()
    expect(warning(TOMAS, 1)).toBe('lapsed')
    expect(warning({ ...PAULA, status: 'frozen' }, 1)).toBe('frozen')
    expect(warning({ ...PAULA, plan_kind: 'trial', credits_remaining: 0 }, 0)).toBe('noCredits')
  })
})
