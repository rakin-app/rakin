import { createMemoryHistory } from '@tanstack/react-router'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Roster, RosterMember } from '../api/attendance'
import { createQueryClient } from '../api/queryClient'
import type { ClassSession } from '../api/sessions'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.session.attendance

const SESSION: ClassSession = {
  id: 's1',
  class_type_id: 'fundamentos',
  class_type_name: 'Fundamentos',
  program_id: 'adultos',
  program_name: 'Adultos',
  starts_at: '2026-11-09T22:00:00Z',
  coach_id: 'coach',
  coach_name: 'Rodrigo Fuentes',
  topic: null,
  notes: null,
  cancelled_at: null,
  created_at: '2026-11-09T22:00:00Z',
  updated_at: '2026-11-09T22:00:00Z',
  present: 1,
  duration_minutes: null,
  slot_id: null,
  slot_date: null,
}

const member = (id: string, name: string, over: Partial<RosterMember> = {}): RosterMember => ({
  membership_id: `m-${id}`,
  person_id: id,
  name,
  rut: null,
  plan_name: 'Mensual adultos',
  plan_kind: 'monthly',
  status: 'active',
  credits_remaining: null,
  overdue: false,
  days_absent: 2,
  // A regular of the class type, unless a test says otherwise.
  regular: true,
  rank: null,
  present: false,
  ...over,
})

const ANTONIA = member('antonia', 'Antonia Rojas', {
  present: true,
  rank: { rank_key: 'blue', rank_label: 'Azul', sub_rank: '0', sub_rank_label: 'Sin grados', awarded_on: '2025-01-01' },
})
const FELIPE = member('felipe', 'Felipe Díaz', { overdue: true })
const PAULA = member('paula', 'Paula Contreras', { plan_name: 'Pack 12 clases', plan_kind: 'credits', credits_remaining: 4 })
const IGNACIO = member('ignacio', 'Ignacio Vera', { days_absent: 16, status: 'lapsed' })

const TRIAL_PLAN = { id: 'trial', name: 'Clase de prueba', kind: 'trial', active: true }
const MONTHLY_PLAN = { id: 'monthly', name: 'Mensual adultos', kind: 'monthly', active: true }

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }
type Stub = {
  members?: RosterMember[]
  plans?: unknown[]
  // `offline` throws as fetch does without signal.
  change?: Answer | 'offline'
  person?: Answer
  trial?: Answer
  // A save waits for this before it is answered.
  hold?: Promise<void>
}

function stubApi({ members = [ANTONIA, FELIPE, PAULA, IGNACIO], plans = [TRIAL_PLAN, MONTHLY_PLAN], ...answers }: Stub = {}) {
  const calls: Call[] = []
  let roster: RosterMember[] = members
  const stub = { ...answers }
  const answer = (): Roster => ({
    session_id: SESSION.id,
    present: roster.filter((m) => m.present).length,
    members: roster,
  })
  const apply = ({ mark, unmark }: { mark: string[]; unmark: string[] }) => {
    roster = roster.map((m) =>
      mark.includes(m.membership_id) ? { ...m, present: true } : unmark.includes(m.membership_id) ? { ...m, present: false } : m,
    )
  }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      if (method === 'PATCH' && url.pathname === '/api/sessions/s1/attendance') {
        if (stub.change === 'offline') throw new TypeError('Failed to fetch')
        if (stub.hold) await stub.hold
      }
      const reply = route(url.pathname, method, body)
      return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: unknown): Answer {
    if (path === '/api/me/role') return { body: { role: 'coach', person_id: 'coach' } }
    if (path === '/api/sessions' && method === 'GET') {
      return { body: { date: '2026-11-09', timezone: 'America/Santiago', sessions: [SESSION] } }
    }
    if (path === '/api/sessions/s1') return { body: SESSION }
    if (path === '/api/sessions/s1/roster') return { body: answer() }
    if (path === '/api/plans') return { body: plans }
    if (path === '/api/sessions/s1/attendance' && method === 'PATCH') {
      if (stub.change && stub.change !== 'offline') return stub.change
      apply(body as { mark: string[]; unmark: string[] })
      return { body: answer() }
    }
    if (path === '/api/people' && method === 'POST') {
      return stub.person ?? { status: 201, body: { id: 'camila' } }
    }
    if (path === '/api/sessions/s1/trials' && method === 'POST') {
      if (stub.trial) return stub.trial
      roster = [...roster, member('camila', 'Camila Ortiz', { plan_kind: 'trial', status: 'trial', present: true })]
      return { status: 201, body: answer() }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return {
    calls,
    // The signal comes back: the change goes through from now on.
    online() {
      delete stub.change
    },
    // How the next changes are answered.
    answer(change: Answer | 'offline') {
      stub.change = change
    },
  }
}

function renderClass() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin/clases/s1'] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function rosterList() {
  return within(await screen.findByRole('list', { name: copy.title }))
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Asistencia', () => {
  it('lists the roster by name, with who is present, the count and the overdue dot', async () => {
    stubApi()
    renderClass()

    const list = await rosterList()
    const rows = list.getAllByRole('button')
    expect(rows.map((r) => r.getAttribute('aria-pressed'))).toEqual(['true', 'false', 'false', 'false'])
    expect(rows[0]).toHaveTextContent('Antonia RojasAzul · Sin grados · Mensual adultos')
    expect(within(rows[1]!).getByRole('img', { name: copy.overdue })).toBeInTheDocument()
    expect(within(rows[0]!).queryByRole('img', { name: copy.overdue })).not.toBeInTheDocument()
    expect(rows[2]).toHaveTextContent('Pack 12 clases · quedan 4')
    expect(rows[3]).toHaveTextContent('Mensual adultos · Vencido · 16 d sin venir')
    expect(screen.getByText(copy.count(1, 4))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.save(1) })).toBeDisabled()
  })

  it('lists regulars first, the others under "Otros alumnos", one tap away', async () => {
    const others = [member('rosa', 'Rosa Soto', { regular: false }), member('tomas', 'Tomás Pérez', { regular: false })]
    stubApi({ members: [ANTONIA, FELIPE, ...others] })
    renderClass()

    const list = await rosterList()
    expect(list.getAllByRole('button').map((r) => r.getAttribute('aria-pressed'))).toEqual(['true', 'false'])
    // The count is of the regulars.
    expect(screen.getByText(copy.count(1, 2))).toBeInTheDocument()
    expect(screen.queryByText('Rosa Soto')).not.toBeInTheDocument()

    const open = screen.getByRole('button', { name: copy.others(2, 0) })
    expect(open).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(open)

    const rest = within(screen.getByRole('list', { name: copy.othersLabel }))
    await userEvent.click(rest.getByRole('button', { name: /Rosa Soto/ }))
    expect(rest.getByRole('button', { name: /Rosa Soto/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: copy.others(2, 1) })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.save(2) })).toBeEnabled()
  })

  it('finds anyone on the roster by name or RUT as it is typed', async () => {
    const rosa = member('rosa', 'Rosa Núñez', { regular: false, rut: '12345678-5' })
    stubApi({ members: [ANTONIA, FELIPE, rosa] })
    renderClass()

    const search = await screen.findByRole('searchbox', { name: copy.search })
    await userEvent.type(search, 'nu')
    // The others open on a search: a non-regular is found without opening them.
    expect(screen.getByRole('button', { name: /Rosa Núñez/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Antonia Rojas/ })).not.toBeInTheDocument()

    await userEvent.clear(search)
    await userEvent.type(search, '12.345')
    expect(screen.getByRole('button', { name: /Rosa Núñez/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Felipe Díaz/ })).not.toBeInTheDocument()

    await userEvent.clear(search)
    await userEvent.type(search, 'zz')
    expect(screen.getByText(copy.noMatches)).toBeInTheDocument()
  })

  it('lists everyone as one when the class type has no regulars yet', async () => {
    stubApi({ members: [FELIPE, PAULA].map((m) => ({ ...m, regular: false })) })
    renderClass()

    expect((await rosterList()).getAllByRole('button')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /^Otros alumnos/ })).not.toBeInTheDocument()
  })

  it('has "Guardar asistencia" as its one primary button', async () => {
    stubApi()
    renderClass()

    await rosterList()
    const primaries = document.querySelectorAll('.button--primary')
    expect([...primaries].map((b) => b.textContent)).toEqual([copy.save(1)])
  })

  it("draws a rank's belt, compact, in place of its name when the scheme colours it", async () => {
    const rank = { ...ANTONIA.rank!, belt: { colors: ['#1f4fa3'], stripes: 0, max_stripes: 4 } }
    stubApi({ members: [{ ...ANTONIA, rank }, FELIPE] })
    renderClass()

    const [antonia] = (await rosterList()).getAllByRole('button')
    // No stripes yet: the rank alone.
    expect(within(antonia!).getByRole('img', { name: 'Azul' })).toHaveClass('belt--compact')
    expect(antonia).toHaveTextContent('Antonia RojasMensual adultos')
    expect(antonia).toHaveAccessibleName(expect.stringContaining('Azul'))
  })

  it('counts each tap and saves what changed', async () => {
    const api = stubApi()
    renderClass()

    const list = await rosterList()
    await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
    await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
    await userEvent.click(list.getByRole('button', { name: /Antonia Rojas/ }))
    expect(screen.getByText(copy.count(2, 4))).toBeInTheDocument()
    // Tapped twice: back as saved, nothing to send.
    await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
    await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.saved)
    expect(writes(api.calls)).toEqual([
      { method: 'PATCH', path: '/api/sessions/s1/attendance', body: { mark: ['m-felipe', 'm-paula'], unmark: ['m-antonia'] } },
    ])
    expect(list.getByRole('button', { name: /Felipe Díaz/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: copy.done })).toBeDisabled()
  })

  it('keeps a change made without signal on the phone and sends it when the signal is back', async () => {
    const api = stubApi({ change: 'offline' })
    renderClass()

    const list = await rosterList()
    await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

    expect(await screen.findByText(copy.queued)).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('rakin:attendance:s1')!)).toEqual({ mark: ['m-felipe'], unmark: [] })
    expect(list.getByRole('button', { name: /Felipe Díaz/ })).toHaveAttribute('aria-pressed', 'true')

    api.online()
    act(() => {
      window.dispatchEvent(new Event('online'))
    })

    expect(await screen.findByText(copy.saved)).toBeInTheDocument()
    expect(screen.queryByText(copy.queued)).not.toBeInTheDocument()
    expect(localStorage.getItem('rakin:attendance:s1')).toBeNull()
    expect(writes(api.calls).map((c) => c.body)).toEqual([
      { mark: ['m-felipe'], unmark: [] },
      { mark: ['m-felipe'], unmark: [] },
    ])
  })

  it('sends what an earlier visit left on the phone', async () => {
    localStorage.setItem('rakin:attendance:s1', JSON.stringify({ mark: ['m-paula'], unmark: ['m-antonia'] }))
    const api = stubApi()
    renderClass()

    expect(await screen.findByText(copy.saved)).toBeInTheDocument()
    expect(writes(api.calls)).toEqual([
      { method: 'PATCH', path: '/api/sessions/s1/attendance', body: { mark: ['m-paula'], unmark: ['m-antonia'] } },
    ])
    const list = await rosterList()
    expect(list.getByRole('button', { name: /Paula Contreras/ })).toHaveAttribute('aria-pressed', 'true')
    expect(list.getByRole('button', { name: /Antonia Rojas/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('drops a queued change the API refuses, instead of resending it forever', async () => {
    localStorage.setItem('rakin:attendance:s1', JSON.stringify({ mark: ['m-paula'], unmark: [] }))
    const api = stubApi({ change: { status: 422, body: { detail: [{ type: 'cancelled_membership' }] } } })
    renderClass()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.dropped)
    expect(localStorage.getItem('rakin:attendance:s1')).toBeNull()
    const list = await rosterList()
    expect(list.getByRole('button', { name: /Paula Contreras/ })).toHaveAttribute('aria-pressed', 'false')
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(writes(api.calls)).toHaveLength(1)
  })

  it('keeps a queued change the server fails to save, and sends it on the next flush', async () => {
    localStorage.setItem('rakin:attendance:s1', JSON.stringify({ mark: ['m-paula'], unmark: [] }))
    const api = stubApi({ change: { status: 503, body: 'Service Unavailable' } })
    renderClass()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.failed)
    expect(JSON.parse(localStorage.getItem('rakin:attendance:s1')!)).toEqual({ mark: ['m-paula'], unmark: [] })
    const list = await rosterList()
    expect(list.getByRole('button', { name: /Paula Contreras/ })).toHaveAttribute('aria-pressed', 'true')

    api.online()
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(await screen.findByText(copy.saved)).toBeInTheDocument()
    expect(localStorage.getItem('rakin:attendance:s1')).toBeNull()
    expect(writes(api.calls)).toHaveLength(2)
  })

  it('keeps the queue when a save by hand meets a server error', async () => {
    const api = stubApi({ change: 'offline' })
    renderClass()

    const list = await rosterList()
    await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))
    expect(await screen.findByText(copy.queued)).toBeInTheDocument()
    api.answer({ status: 500, body: {} })
    await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(3) }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.failed)
    expect(JSON.parse(localStorage.getItem('rakin:attendance:s1')!)).toEqual({
      mark: ['m-felipe', 'm-paula'],
      unmark: [],
    })
    expect(screen.getByText(copy.queued)).toBeInTheDocument()
  })

  it('keeps on the phone the taps made after a save without signal', async () => {
    stubApi({ change: 'offline' })
    renderClass()

    const list = await rosterList()
    await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))
    expect(await screen.findByText(copy.queued)).toBeInTheDocument()
    await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
    await userEvent.click(list.getByRole('button', { name: /Antonia Rojas/ }))

    expect(JSON.parse(localStorage.getItem('rakin:attendance:s1')!)).toEqual({
      mark: ['m-felipe', 'm-paula'],
      unmark: ['m-antonia'],
    })
  })

  it('does not resend while a save is still on its way', async () => {
    localStorage.setItem('rakin:attendance:s1', JSON.stringify({ mark: ['m-paula'], unmark: [] }))
    let release = () => {}
    const api = stubApi({ hold: new Promise<void>((resolve) => (release = resolve)) })
    renderClass()

    await rosterList()
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(writes(api.calls)).toHaveLength(1)
    await act(async () => release())

    expect(await screen.findByText(copy.saved)).toBeInTheDocument()
    expect(writes(api.calls)).toHaveLength(1)
  })

  it('says so when the API refuses the change, and keeps nothing queued', async () => {
    stubApi({ change: { status: 422, body: { detail: [] } } })
    renderClass()

    const list = await rosterList()
    await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
    await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.failed)
    expect(localStorage.getItem('rakin:attendance:s1')).toBeNull()
  })

  describe('what Guardar did, beside the button', () => {
    // The sticky bar the button sits in, which stays in view at the foot of the screen.
    const bar = (button: HTMLElement) => within(button.parentElement!)

    it('goes busy while sending, then says saved with the way back, until the next tap', async () => {
      let release = () => {}
      stubApi({ hold: new Promise<void>((resolve) => (release = resolve)) })
      renderClass()

      const list = await rosterList()
      await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
      await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

      const busy = await screen.findByRole('button', { name: copy.working })
      expect(busy).toBeDisabled()
      expect(busy).toHaveAttribute('aria-busy', 'true')
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      await act(async () => release())

      const done = await screen.findByRole('button', { name: copy.done })
      expect(done).toBeDisabled()
      expect(done).toHaveAttribute('aria-busy', 'false')
      expect(bar(done).getByRole('status')).toHaveTextContent(copy.saved)
      expect(bar(done).getByRole('link', { name: copy.back })).toHaveAttribute('href', '/admin/clases')

      await userEvent.click(list.getByRole('button', { name: /Paula Contreras/ }))
      expect(screen.getByRole('button', { name: copy.save(3) })).toBeEnabled()
      expect(screen.queryByRole('button', { name: copy.done })).not.toBeInTheDocument()
      expect(screen.queryByRole('link', { name: copy.back })).not.toBeInTheDocument()
      expect(screen.queryByText(copy.saved)).not.toBeInTheDocument()
    })

    it('says a change without signal waits on the phone, not that it was saved', async () => {
      stubApi({ change: 'offline' })
      renderClass()

      const list = await rosterList()
      await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
      await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

      const queued = await screen.findByText(copy.queued)
      const button = screen.getByRole('button', { name: copy.save(2) })
      expect(bar(button).getByText(copy.queued)).toBe(queued)
      expect(screen.queryByRole('button', { name: copy.done })).not.toBeInTheDocument()
      expect(screen.queryByRole('link', { name: copy.back })).not.toBeInTheDocument()
    })

    it('shows a failed save next to the button, which stays ready to retry', async () => {
      stubApi({ change: { status: 500, body: {} } })
      renderClass()

      const list = await rosterList()
      await userEvent.click(list.getByRole('button', { name: /Felipe Díaz/ }))
      await userEvent.click(screen.getByRole('button', { name: copy.save(2) }))

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(copy.failed)
      const button = screen.getByRole('button', { name: copy.save(2) })
      expect(bar(button).getByRole('alert')).toBe(alert)
      expect(button).toBeEnabled()
      expect(screen.queryByRole('link', { name: copy.back })).not.toBeInTheDocument()
    })
  })

  it('says when nobody has a plan for the class', async () => {
    stubApi({ members: [] })
    renderClass()

    expect(await screen.findByText(copy.empty)).toBeInTheDocument()
    expect(screen.getByText(copy.count(0, 0))).toBeInTheDocument()
  })
})

describe('Alumno de prueba', () => {
  async function addGuest(name: string, who: string, phone: string) {
    await userEvent.click(await screen.findByRole('button', { name: copy.guest.open }))
    const form = within(screen.getByRole('form', { name: copy.guest.label }))
    await userEvent.type(form.getByLabelText(copy.guest.name), name)
    await userEvent.type(form.getByLabelText(copy.guest.who), who)
    await userEvent.type(form.getByLabelText(copy.guest.phone), phone)
    await userEvent.click(form.getByRole('button', { name: copy.guest.submit }))
  }

  it('adds someone by RUT, with their phone, on the trial plan, present at the class', async () => {
    const api = stubApi()
    renderClass()

    await addGuest('Camila Ortiz', '7.654.321-6', '9 1234 5678')

    expect(await screen.findByText(copy.guest.done('Camila Ortiz'))).toBeInTheDocument()
    const list = await rosterList()
    expect(list.getByRole('button', { name: /Camila Ortiz/ })).toHaveAttribute('aria-pressed', 'true')
    expect(writes(api.calls)).toEqual([
      {
        method: 'POST',
        path: '/api/people',
        body: { name: 'Camila Ortiz', rut: '7.654.321-6', phone: '9 1234 5678' },
      },
      { method: 'POST', path: '/api/sessions/s1/trials', body: { person_id: 'camila', plan_id: 'trial' } },
    ])
  })

  it('marks someone already a member instead', async () => {
    const api = stubApi({
      person: { status: 409, body: { detail: { code: 'email_in_gym', person_id: 'felipe' } } },
      trial: { status: 409, body: { detail: { code: 'already_member', membership_id: 'm-felipe' } } },
    })
    renderClass()

    await addGuest('Felipe', 'felipe@example.cl', '9 8765 4321')

    expect(await screen.findByText(copy.guest.member('Felipe'))).toBeInTheDocument()
    expect(writes(api.calls).map((c) => [c.path, c.body])).toEqual([
      ['/api/people', { name: 'Felipe', email: 'felipe@example.cl', phone: '9 8765 4321' }],
      ['/api/sessions/s1/trials', { person_id: 'felipe', plan_id: 'trial' }],
      ['/api/sessions/s1/attendance', { mark: ['m-felipe'], unmark: [] }],
    ])
    const list = await rosterList()
    expect(list.getByRole('button', { name: /Felipe Díaz/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('sends someone dado de baja to Reactivar instead of a trial', async () => {
    stubApi({
      person: { status: 409, body: { detail: { code: 'rut_in_gym', person_id: 'felipe' } } },
      trial: { status: 409, body: { detail: { code: 'has_left' } } },
    })
    renderClass()

    await addGuest('Felipe', '7.654.321-6', '9 8765 4321')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.guest.hasLeft)
  })

  it('asks to check what the API refuses', async () => {
    stubApi({ person: { status: 422, body: { detail: [] } } })
    renderClass()

    await addGuest('Camila Ortiz', '7.654.321-6', '12')

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.guest.invalid)
  })

  it('needs a trial plan', async () => {
    stubApi({ plans: [MONTHLY_PLAN] })
    renderClass()

    await userEvent.click(await screen.findByRole('button', { name: copy.guest.open }))
    const form = within(screen.getByRole('form', { name: copy.guest.label }))
    expect(await form.findByText(copy.guest.noPlans)).toBeInTheDocument()
    expect(form.queryByRole('button', { name: copy.guest.submit })).not.toBeInTheDocument()
  })
})
