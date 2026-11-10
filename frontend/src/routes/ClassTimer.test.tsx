import { createMemoryHistory } from '@tanstack/react-router'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../api/blockKinds'
import { createQueryClient } from '../api/queryClient'
import type { SessionBlock, SuggestedBlock } from '../api/sessionBlocks'
import type { ClassSession } from '../api/sessions'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { savedRun, saveRun, startRun } from './timerEngine'

const copy = es.admin.timer
const running = copy.running

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
  created_at: '2026-11-09T22:00:00Z',
  updated_at: '2026-11-09T22:00:00Z',
  present: 1,
}

const kind = (id: string, name: string, position: number, extra: Partial<BlockKind> = {}): BlockKind => ({
  id,
  name,
  is_sparring: false,
  position,
  archived: false,
  created_at: '2026-11-10T12:00:00Z',
  ...extra,
})

const KINDS = [
  kind('warmup', 'Calentamiento', 0),
  kind('technique', 'Técnica', 1),
  kind('sparring', 'Sparring', 2, { is_sparring: true }),
]

const LAST_CLASS: SuggestedBlock[] = [
  {
    block_kind_id: 'warmup',
    block_kind_name: 'Calentamiento',
    is_sparring: false,
    planned_seconds: 600,
    rounds_planned: null,
    round_seconds: null,
    rest_seconds: null,
  },
  {
    block_kind_id: 'sparring',
    block_kind_name: 'Sparring',
    is_sparring: true,
    planned_seconds: 1800,
    rounds_planned: 6,
    round_seconds: 300,
    rest_seconds: 60,
  },
]

type Call = { method: string; path: string; body: unknown }
type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  me?: string
  plan?: SessionBlock[]
  suggested?: SuggestedBlock[]
  classKind?: 'class' | 'open_mat'
  // Writes throw as fetch does without signal.
  offline?: boolean
}

function stubApi({ role = 'coach', me = 'coach', plan = [], suggested = LAST_CLASS, classKind = 'class', ...rest }: Stub = {}) {
  const calls: Call[] = []
  const state = { offline: rest.offline ?? false }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      if (method !== 'GET' && state.offline) throw new TypeError('Failed to fetch')
      calls.push({ method, path: url.pathname, body })
      const reply = route(url.pathname, method, body)
      return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: unknown): { status?: number; body?: unknown } {
    if (path === '/api/me/role') return { body: { role, person_id: me } }
    if (path === '/api/sessions' && method === 'GET') {
      return { body: { date: '2026-11-09', timezone: 'America/Santiago', sessions: [SESSION] } }
    }
    if (path === '/api/sessions/s1') return { body: SESSION }
    if (path === '/api/sessions/s1/roster') return { body: { session_id: 's1', present: 0, members: [] } }
    if (path === '/api/plans') return { body: [] }
    if (path === '/api/block-kinds') return { body: KINDS }
    if (path === '/api/sessions/s1/blocks' && method === 'GET') {
      return { body: { session_id: 's1', class_kind: classKind, blocks: plan } }
    }
    if (path === '/api/sessions/s1/blocks/suggested') {
      return { body: { session_id: 's1', from_session_id: suggested.length ? 's0' : null, blocks: suggested } }
    }
    if (path === '/api/sessions/s1/blocks' && method === 'PUT') {
      return { body: { session_id: 's1', class_kind: classKind, blocks: (body as { blocks: unknown[] }).blocks } }
    }
    if (/^\/api\/sessions\/s1\/blocks\/[^/]+\/actual$/.test(path) && method === 'PUT') return { body: {} }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return {
    calls,
    online() {
      state.offline = false
      window.dispatchEvent(new Event('online'))
    },
  }
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

// The clock the timer reads; moved by hand, while its real interval keeps ticking.
let clockNow = 1_700_000_000_000
const later = (ms: number) => {
  clockNow += ms
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  return render(<App queryClient={queryClient} router={router} />)
}

beforeEach(() => {
  localStorage.clear()
  clockNow = 1_700_000_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => clockNow)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function startClass() {
  const view = renderAt('/admin/clases/s1/timer')
  const editor = await screen.findByRole('form', { name: copy.editor.title })
  await userEvent.click(within(editor).getByRole('button', { name: copy.editor.start }))
  await screen.findByRole('timer', { name: running.countdown })
  return view
}

describe('who runs the timer', () => {
  it.each([
    ['the class coach', 'coach', 'coach'],
    ['an owner', 'owner', 'someone'],
    ['an admin', 'admin', 'someone'],
  ] as const)('shows "Iniciar clase" on the session to %s', async (_who, role, me) => {
    stubApi({ role, me })
    renderAt('/admin/clases/s1')
    expect(await screen.findByRole('link', { name: es.admin.session.timer.open })).toHaveAttribute(
      'href',
      '/admin/clases/s1/timer',
    )
  })

  it('hides it from another coach, and refuses them the timer', async () => {
    stubApi({ role: 'coach', me: 'other-coach' })
    renderAt('/admin/clases/s1')
    expect(await screen.findByText('Rodrigo Fuentes', { exact: false })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: es.admin.session.timer.open })).not.toBeInTheDocument()
  })

  it('refuses the timer itself to another coach', async () => {
    const api = stubApi({ role: 'coach', me: 'other-coach' })
    renderAt('/admin/clases/s1/timer')
    expect(await screen.findByText(copy.notAllowed)).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: copy.editor.title })).not.toBeInTheDocument()
    expect(writes(api.calls)).toEqual([])
  })
})

describe('the blocks before the class', () => {
  it('starts from the last class of the type', async () => {
    stubApi()
    renderAt('/admin/clases/s1/timer')
    const editor = await screen.findByRole('form', { name: copy.editor.title })
    const first = within(editor).getByRole('group', { name: copy.editor.label(1) })
    expect(within(first).getByLabelText(copy.editor.kind)).toHaveValue('warmup')
    expect(within(first).getByLabelText(copy.editor.minutes)).toHaveValue('10')
    const second = within(editor).getByRole('group', { name: copy.editor.label(2) })
    expect(within(second).getByLabelText(copy.editor.rounds)).toHaveValue('6')
    expect(within(second).getByLabelText(copy.editor.roundMinutes)).toHaveValue('5')
    expect(within(second).getByLabelText(copy.editor.restSeconds)).toHaveValue('60')
    expect(within(editor).getByText(copy.editor.total(copy.minutes(2400)))).toBeInTheDocument()
  })

  it('adds, reorders and removes blocks, and refuses a block without its minutes', async () => {
    const api = stubApi({ suggested: [] })
    renderAt('/admin/clases/s1/timer')
    const editor = await screen.findByRole('form', { name: copy.editor.title })
    expect(within(editor).getByRole('button', { name: copy.editor.start })).toBeDisabled()

    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.add }))
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.add }))
    const second = within(editor).getByRole('group', { name: copy.editor.label(2) })
    await userEvent.selectOptions(within(second).getByLabelText(copy.editor.kind), 'technique')
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.up(2) }))
    expect(within(within(editor).getByRole('group', { name: copy.editor.label(1) })).getByLabelText(copy.editor.kind)).toHaveValue(
      'technique',
    )
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.remove(2) }))
    const only = within(editor).getByRole('group', { name: copy.editor.label(1) })
    await userEvent.clear(within(only).getByLabelText(copy.editor.minutes))

    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.start }))
    expect(within(editor).getByRole('alert')).toHaveTextContent(copy.editor.invalid)
    expect(within(only).getByLabelText(copy.editor.minutes)).toHaveAttribute('aria-invalid', 'true')
    expect(writes(api.calls)).toEqual([])
  })

  it('gives an open mat one block of rounds, and nothing to add', async () => {
    const api = stubApi({ classKind: 'open_mat', suggested: [] })
    renderAt('/admin/clases/s1/timer')
    const editor = await screen.findByRole('form', { name: copy.editor.title })
    expect(within(editor).getAllByRole('group')).toHaveLength(1)
    expect(within(editor).getByLabelText(copy.editor.rounds)).toHaveValue('6')
    expect(within(editor).queryByRole('button', { name: copy.editor.add })).not.toBeInTheDocument()
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.start }))

    expect(await screen.findByText(running.round('Sparring', 1, 6))).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: running.edit })).not.toBeInTheDocument()
    await waitFor(() => expect(writes(api.calls)).toHaveLength(1))
    const blocks = (writes(api.calls)[0]!.body as { blocks: Record<string, unknown>[] }).blocks
    expect(blocks).toEqual([
      expect.objectContaining({ block_kind_id: 'sparring', rounds_planned: 6, round_seconds: 300, rest_seconds: 60 }),
    ])
  })
})

describe('the running class', () => {
  it('sends the plan on start, counts down, and records each block as it finishes', async () => {
    const api = stubApi()
    await startClass()
    expect(screen.getByRole('timer')).toHaveTextContent('10:00')
    expect(screen.getByText('Calentamiento')).toBeInTheDocument()
    expect(screen.getByText(running.next(copy.roundsSummary('Sparring', 6, '5 min', '1 min')))).toBeInTheDocument()

    await waitFor(() => expect(writes(api.calls)).toHaveLength(1))
    const plan = writes(api.calls)[0]!
    expect(plan.path).toBe('/api/sessions/s1/blocks')
    const sent = (plan.body as { blocks: { id: string; block_kind_id: string; planned_seconds: number | null }[] }).blocks
    expect(sent.map((b) => [b.block_kind_id, b.planned_seconds])).toEqual([
      ['warmup', 600],
      ['sparring', null],
    ])

    act(() => later(10 * 60_000 + 2_000))
    expect(await screen.findByText(running.round('Sparring', 1, 6))).toBeInTheDocument()
    await waitFor(() => expect(writes(api.calls)).toHaveLength(2))
    expect(writes(api.calls)[1]).toEqual({
      method: 'PUT',
      path: `/api/sessions/s1/blocks/${sent[0]!.id}/actual`,
      body: { actual_seconds: 600, rounds_completed: null },
    })
    expect(screen.getByRole('timer')).toHaveTextContent('4:58')
    expect(screen.getByText(running.next(running.nextRest('1 min')))).toBeInTheDocument()
  })

  it('pauses, adds a minute and skips', async () => {
    stubApi()
    await startClass()
    act(() => later(60_000))
    await userEvent.click(screen.getByRole('button', { name: running.pause }))
    expect(screen.getByText(running.paused)).toBeInTheDocument()
    act(() => later(5 * 60_000))
    await waitFor(() => expect(screen.getByRole('timer')).toHaveTextContent('9:00'))

    await userEvent.click(screen.getByRole('button', { name: running.resume }))
    await userEvent.click(screen.getByRole('button', { name: running.addMinute }))
    expect(screen.getByRole('timer')).toHaveTextContent('10:00')

    await userEvent.click(screen.getByRole('button', { name: running.skip }))
    expect(screen.getByText(running.round('Sparring', 1, 6))).toBeInTheDocument()
    expect(screen.getByRole('button', { name: running.skipRound })).toBeInTheDocument()
  })

  it('finds the class where it is after a reload, from the clock', async () => {
    stubApi()
    const view = await startClass()
    expect(savedRun('s1')).not.toBeNull()
    view.unmount()
    // Away 15 min 30 s: warm-up done, round 1 done, half its rest gone.
    later(15 * 60_000 + 30_000)
    renderAt('/admin/clases/s1/timer')
    expect(await screen.findByRole('timer')).toHaveTextContent('0:30')
    expect(screen.getByText(running.rest(2, 6))).toBeInTheDocument()
  })

  it('keeps what ran on the phone without signal, and sends it when the signal comes back', async () => {
    const api = stubApi({ offline: true })
    await startClass()
    act(() => later(10 * 60_000 + 1_000))
    expect(await screen.findByText(running.round('Sparring', 1, 6))).toBeInTheDocument()
    expect(writes(api.calls)).toEqual([])
    expect(await screen.findByText(copy.sync.pending, {}, { timeout: 4000 })).toBeInTheDocument()

    api.online()
    await waitFor(() => expect(writes(api.calls)).toHaveLength(2))
    expect(writes(api.calls).map((c) => c.path)).toEqual([
      '/api/sessions/s1/blocks',
      expect.stringMatching(/\/actual$/),
    ])
    await waitFor(() => expect(screen.queryByText(copy.sync.pending)).not.toBeInTheDocument())
    expect(localStorage.getItem('rakin:timer-sync:s1')).toBeNull()
  })

  it('records what ran when the class is ended early, and shows it', async () => {
    const api = stubApi()
    await startClass()
    // Round 3 started at 22:00 (two rounds of 5 min, each with its minute of rest), and is
    // half way through: 2 rounds done, 150 s of the third.
    act(() => later(22 * 60_000 + 150_000))
    expect(await screen.findByText(running.round('Sparring', 3, 6))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: running.end }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: running.endYes }))

    expect(await screen.findByText(copy.done.title)).toBeInTheDocument()
    expect(screen.getByText(copy.done.rounds(2, 6, copy.minutes(750)))).toBeInTheDocument()
    await waitFor(() => expect(writes(api.calls)).toHaveLength(3))
    expect(writes(api.calls)[2]!.body).toEqual({ actual_seconds: 750, rounds_completed: 2 })

    await userEvent.click(screen.getByRole('button', { name: copy.done.back }))
    expect(await screen.findByRole('link', { name: es.admin.session.timer.open })).toBeInTheDocument()
    expect(savedRun('s1')).toBeNull()
  })

  it('changes the blocks still to come while the class runs', async () => {
    const api = stubApi()
    await startClass()
    await userEvent.click(screen.getByRole('button', { name: running.edit }))
    const editor = await screen.findByRole('form', { name: copy.editor.title })
    // Only the sparring block is still to come.
    expect(within(editor).getAllByRole('group')).toHaveLength(1)
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.add }))
    await userEvent.click(within(editor).getByRole('button', { name: copy.editor.save }))

    expect(screen.queryByRole('form', { name: copy.editor.title })).not.toBeInTheDocument()
    expect(screen.getByText(running.position(1, 3))).toBeInTheDocument()
    await waitFor(() => expect(writes(api.calls)).toHaveLength(2))
    const blocks = (writes(api.calls)[1]!.body as { blocks: unknown[] }).blocks
    expect(blocks).toHaveLength(3)
  })

  it('says "Volver al timer" on the session while one runs', async () => {
    stubApi()
    saveRun(
      's1',
      startRun(
        [
          {
            id: 'b1',
            kindId: 'warmup',
            kindName: 'Calentamiento',
            sparring: false,
            seconds: 600,
            rounds: null,
            roundSeconds: null,
            restSeconds: null,
          },
        ],
        clockNow,
      ),
    )
    renderAt('/admin/clases/s1')
    expect(await screen.findByRole('link', { name: es.admin.session.timer.resume })).toBeInTheDocument()
  })
})
