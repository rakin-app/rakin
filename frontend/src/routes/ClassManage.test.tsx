import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../api/blockKinds'
import { createQueryClient } from '../api/queryClient'
import { queuePlan, type SessionBlock } from '../api/sessionBlocks'
import type { ClassSession, ClassType } from '../api/sessions'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.session

const classType = (id: string, name: string, kind: ClassType['kind'] = 'class'): ClassType => ({
  id,
  name,
  program_id: 'adultos',
  program_name: 'Adultos',
  credit_cost: 1,
  kind,
  counts_as_class: kind === 'class',
  active: true,
  created_at: '2026-11-01T12:00:00Z',
})

const FUNDAMENTALS = classType('fundamentos', 'Fundamentos')
const OPEN_MAT = classType('open-mat', 'Open mat', 'open_mat')

// 19:00 in Santiago, UTC-3 in November; long begun.
const SESSION: ClassSession = {
  id: 's1',
  class_type_id: FUNDAMENTALS.id,
  class_type_name: FUNDAMENTALS.name,
  program_id: 'adultos',
  program_name: 'Adultos',
  starts_at: '2026-11-09T22:00:00Z',
  coach_id: 'coach',
  coach_name: 'Rodrigo Fuentes',
  topic: 'Guardia',
  notes: 'Faltó calentamiento.',
  cancelled_at: null,
  created_at: '2026-11-09T22:00:00Z',
  updated_at: '2026-11-09T22:00:00Z',
  present: 12,
  duration_minutes: null,
  slot_id: null,
  slot_date: null,
  tags: [],
}

const kind = (id: string, name: string, is_sparring = false): BlockKind => ({
  id,
  name,
  is_sparring,
  position: 0,
  archived: false,
  created_at: '2026-11-01T12:00:00Z',
})
const TECHNIQUE = kind('technique', 'Técnica')
const DRILLING = kind('drilling', 'Drilling')
const SPARRING = kind('sparring', 'Sparring', true)

const BLOCKS: SessionBlock[] = [
  {
    id: 'b1',
    position: 0,
    block_kind_id: TECHNIQUE.id,
    block_kind_name: TECHNIQUE.name,
    is_sparring: false,
    planned_seconds: 1200,
    actual_seconds: 1200,
    rounds_planned: null,
    rounds_completed: null,
    round_seconds: null,
    rest_seconds: null,
  },
  {
    id: 'b2',
    position: 1,
    block_kind_id: SPARRING.id,
    block_kind_name: SPARRING.name,
    is_sparring: true,
    planned_seconds: 1500,
    actual_seconds: null,
    rounds_planned: 5,
    rounds_completed: null,
    round_seconds: 300,
    rest_seconds: 60,
  },
]

const STAFF = [
  { person_id: 'owner', name: 'Carla Soto', phone: null, email: null, role: 'owner', since: '2026-01-01' },
  { person_id: 'coach', name: 'Rodrigo Fuentes', phone: null, email: null, role: 'coach', since: '2026-01-01' },
  { person_id: 'other', name: 'Tomás Vidal', phone: null, email: null, role: 'coach', since: '2026-01-01' },
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({
  role = 'owner',
  me = 'owner',
  session = SESSION,
  blocks = BLOCKS,
  update,
  replace,
}: {
  role?: 'owner' | 'admin' | 'coach'
  me?: string
  session?: ClassSession
  blocks?: SessionBlock[]
  update?: Answer
  // How a plan sent is answered, if not taken.
  replace?: Answer
} = {}) {
  const calls: Call[] = []
  let current = session
  let plan = blocks
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      const reply = route(url.pathname, method, body)
      return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
        status: reply.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: unknown): Answer {
    if (path === '/api/me/role') return { body: { role, person_id: me } }
    if (path === '/api/sessions' && method === 'GET') {
      return { body: { date: '2026-11-10', timezone: 'America/Santiago', sessions: [current] } }
    }
    if (path === '/api/sessions/s1' && method === 'GET') return { body: current }
    if (path === '/api/sessions/s1' && method === 'PATCH') {
      if (update) return update
      const changes = body as Partial<ClassSession>
      const type = [FUNDAMENTALS, OPEN_MAT].find((c) => c.id === changes.class_type_id)
      const coach = STAFF.find((p) => p.person_id === changes.coach_id)
      current = {
        ...current,
        ...changes,
        ...(type && { class_type_name: type.name }),
        ...(coach && { coach_name: coach.name }),
      }
      return { body: current }
    }
    if (path === '/api/sessions/s1/cancel') {
      if (current.present > 0) return { status: 409, body: { detail: 'attendance was taken' } }
      current = { ...current, cancelled_at: '2026-11-10T12:00:00Z' }
      return { body: current }
    }
    if (path === '/api/sessions/s1/reactivate') {
      current = { ...current, cancelled_at: null }
      return { body: current }
    }
    if (path === '/api/sessions/s1' && method === 'DELETE') return { status: 204 }
    if (path === '/api/schedule/slot1' && method === 'PATCH') return { body: { id: 'slot2' } }
    if (path === '/api/sessions/s1/roster') return { body: { session_id: 's1', present: 0, members: [] } }
    if (path === '/api/sessions/s1/blocks' && method === 'GET') {
      return { body: { session_id: 's1', class_kind: 'class', blocks: plan } }
    }
    if (path === '/api/sessions/s1/blocks' && method === 'PUT') {
      if (replace) return replace
      const sent = (body as { blocks: Record<string, unknown>[] }).blocks
      plan = sent.map((b, position) => {
        const k = [TECHNIQUE, DRILLING, SPARRING].find((x) => x.id === b.block_kind_id)!
        return {
          ...(b as unknown as SessionBlock),
          position,
          block_kind_name: k.name,
          is_sparring: k.is_sparring,
          planned_seconds: (b.planned_seconds as number | null) ?? 0,
          actual_seconds: null,
          rounds_completed: null,
        }
      })
      return { body: { session_id: 's1', class_kind: 'class', blocks: plan } }
    }
    const actual = /^\/api\/sessions\/s1\/blocks\/([^/]+)\/actual$/.exec(path)
    if (actual && method === 'PUT') {
      plan = plan.map((b) => (b.id === actual[1] ? { ...b, ...(body as object) } : b))
      return { body: plan.find((b) => b.id === actual[1]) }
    }
    if (path === '/api/block-kinds') return { body: [TECHNIQUE, DRILLING, SPARRING] }
    if (path === '/api/class-types') return { body: [FUNDAMENTALS, OPEN_MAT] }
    if (path === '/api/staff') return { body: STAFF }
    if (path === '/api/plans') return { body: [] }
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

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Editar clase', () => {
  it("moves the class in the gym's timezone and changes its type and coach, sending what changed", async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    const day = within(form).getByLabelText(copy.edit.day)
    const time = within(form).getByLabelText(copy.edit.time)
    expect(day).toHaveValue('2026-11-09')
    expect(time).toHaveValue('19:00')
    await userEvent.clear(day)
    await userEvent.type(day, '2026-11-08')
    await userEvent.clear(time)
    await userEvent.type(time, '07:30')
    await userEvent.selectOptions(within(form).getByLabelText(copy.edit.classType), 'Open mat')
    await within(form).findByRole('option', { name: 'Tomás Vidal' })
    await userEvent.selectOptions(within(form).getByLabelText(copy.edit.coach), 'Tomás Vidal')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.edit.saved)
    expect(writes(calls)).toEqual([
      {
        method: 'PATCH',
        path: '/api/sessions/s1',
        // 07:30 in Santiago is 10:30 UTC.
        body: { starts_at: '2026-11-08T10:30:00.000Z', class_type_id: OPEN_MAT.id, coach_id: 'other' },
      },
    ])
    expect(screen.getByRole('heading', { level: 1, name: 'Open mat' })).toBeInTheDocument()
    expect(screen.getByText(copy.coach('Tomás Vidal'))).toBeInTheDocument()
    expect(screen.getByText(copy.eyebrow('Adultos', '8 nov 07:30'))).toBeInTheDocument()
  })

  it('sets and clears a duration for this class alone', async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    // A one-off class has no scope to choose.
    expect(within(form).queryByRole('radio')).not.toBeInTheDocument()
    await userEvent.type(within(form).getByLabelText(copy.edit.duration), '90')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.edit.saved)
    expect(writes(calls)).toEqual([{ method: 'PATCH', path: '/api/sessions/s1', body: { duration_minutes: 90 } }])
  })

  it('refuses a duration out of range before sending it', async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    await userEvent.type(within(form).getByLabelText(copy.edit.duration), '0')
    expect(within(form).getByRole('alert')).toHaveTextContent(copy.edit.badDuration)
    expect(within(form).getByRole('button', { name: copy.edit.submit })).toBeDisabled()
    expect(writes(calls)).toEqual([])
  })

  it('changes this class alone, or its schedule from its date on', async () => {
    const scheduled = { ...SESSION, duration_minutes: 90, slot_id: 'slot1', slot_date: '2026-11-09' }
    const calls = stubApi({ session: scheduled })
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    let form = await screen.findByRole('form', { name: copy.edit.label })
    expect(within(form).getByRole('radio', { name: copy.edit.scope.one })).toBeChecked()
    await userEvent.click(within(form).getByRole('radio', { name: copy.edit.scope.series }))
    // The day is the schedule's weekdays, not this form's.
    expect(within(form).queryByLabelText(copy.edit.day)).not.toBeInTheDocument()
    expect(within(form).getByText(copy.edit.scope.seriesHint)).toBeInTheDocument()
    const time = within(form).getByLabelText(copy.edit.time)
    await userEvent.clear(time)
    await userEvent.type(time, '20:00')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.edit.saved)

    await userEvent.click(screen.getByRole('button', { name: copy.edit.open }))
    form = await screen.findByRole('form', { name: copy.edit.label })
    await userEvent.clear(within(form).getByLabelText(copy.edit.duration))
    await userEvent.type(within(form).getByLabelText(copy.edit.duration), '60')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))
    await screen.findByRole('status')

    expect(writes(calls)).toEqual([
      {
        method: 'PATCH',
        path: '/api/schedule/slot1',
        body: { start_time: '20:00', from_date: '2026-11-09' },
      },
      { method: 'PATCH', path: '/api/sessions/s1', body: { duration_minutes: 60 } },
    ])
  })

  it("keeps this class's own coach out of a series change of its duration", async () => {
    // A substitute coach for this class alone; the schedule's is someone else.
    const scheduled = {
      ...SESSION,
      coach_id: 'other',
      coach_name: 'Tomás Vidal',
      duration_minutes: 90,
      slot_id: 'slot1',
      slot_date: '2026-11-09',
    }
    const calls = stubApi({ session: scheduled })
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    await userEvent.click(within(form).getByRole('radio', { name: copy.edit.scope.series }))
    const duration = within(form).getByLabelText(copy.edit.duration)
    await userEvent.clear(duration)
    await userEvent.type(duration, '75')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.edit.saved)

    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/schedule/slot1', body: { duration_minutes: 75, from_date: '2026-11-09' } },
    ])
  })

  it('sends nothing when nothing changed', async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))
    expect(screen.queryByRole('form', { name: copy.edit.label })).not.toBeInTheDocument()
    expect(writes(calls)).toEqual([])
  })

  it('says why a class with blocks cannot become an open mat', async () => {
    const detail = [{ type: 'open_mat_plan', loc: ['body', 'class_type_id'], msg: 'x' }]
    stubApi({ update: { status: 422, body: { detail } } })
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.edit.open }))
    const form = await screen.findByRole('form', { name: copy.edit.label })
    await userEvent.selectOptions(within(form).getByLabelText(copy.edit.classType), 'Open mat')
    await userEvent.click(within(form).getByRole('button', { name: copy.edit.submit }))
    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.edit.openMatPlan)
  })

  it("is not offered to a coach, who writes their own class's topic and no one else's", async () => {
    stubApi({ role: 'coach', me: 'coach' })
    renderAt('/admin/clases/s1')
    expect(await screen.findByRole('form', { name: copy.form.label })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.edit.open })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: copy.manage.title })).not.toBeInTheDocument()
  })

  it("shows another coach the class's topic and notes to read", async () => {
    stubApi({ role: 'coach', me: 'other' })
    renderAt('/admin/clases/s1')
    const topic = await screen.findByRole('region', { name: copy.form.label })
    expect(topic).toHaveTextContent('Guardia')
    expect(topic).toHaveTextContent('Faltó calentamiento.')
    expect(screen.queryByRole('form', { name: copy.form.label })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: copy.record.title })).not.toBeInTheDocument()
  })
})

describe('Cancelar y eliminar', () => {
  it('refuses to cancel a class with attendance and points to deleting it', async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.manage.cancel }))
    const asked = screen.getByRole('group', { name: copy.manage.cancel })
    expect(asked).toHaveTextContent(copy.manage.hasAttendance)
    expect(within(asked).queryByRole('button', { name: copy.manage.cancelYes })).not.toBeInTheDocument()
    expect(writes(calls)).toEqual([])
  })

  it('cancels a class after asking, hides its attendance, and reactivates it', async () => {
    const calls = stubApi({ session: { ...SESSION, present: 0 } })
    renderAt('/admin/clases/s1')

    expect(await screen.findByRole('heading', { name: copy.attendance.title })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.manage.cancel }))
    expect(screen.getByRole('group', { name: copy.manage.cancel })).toHaveTextContent(copy.manage.cancelConfirm)
    await userEvent.click(screen.getByRole('button', { name: copy.manage.cancelYes }))

    expect(await screen.findByText(copy.cancelled.note)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: copy.attendance.title })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: copy.timer.open })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: copy.record.title })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: copy.manage.reactivate }))
    expect(await screen.findByRole('heading', { name: copy.attendance.title })).toBeInTheDocument()
    expect(writes(calls).map((c) => `${c.method} ${c.path}`)).toEqual([
      'POST /api/sessions/s1/cancel',
      'POST /api/sessions/s1/reactivate',
    ])
  })

  it('says what deleting takes, then deletes and goes back to Clases', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/clases/s1')

    await screen.findByRole('heading', { name: copy.record.title })
    await userEvent.click(screen.getByRole('button', { name: copy.manage.delete }))
    const asked = screen.getByRole('group', { name: copy.manage.delete })
    expect(asked).toHaveTextContent('¿Eliminar esta clase? Se borran 12 asistencias y el registro del timer.')
    expect(asked).toHaveTextContent(copy.manage.credits)
    await userEvent.click(within(asked).getByRole('button', { name: copy.manage.deleteYes }))

    expect(await screen.findByRole('heading', { name: es.admin.classes.title })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/clases')
    expect(writes(calls)).toEqual([{ method: 'DELETE', path: '/api/sessions/s1', body: undefined }])
  })

  it('agrees the verb with what deleting takes (#213)', () => {
    expect(copy.manage.deleteConfirm(1, false)).toBe('¿Eliminar esta clase? Se borra 1 asistencia. No se puede deshacer.')
    expect(copy.manage.deleteConfirm(0, true)).toBe(
      '¿Eliminar esta clase? Se borra el registro del timer. No se puede deshacer.',
    )
    expect(copy.manage.deleteConfirm(1, true)).toBe(
      '¿Eliminar esta clase? Se borran 1 asistencia y el registro del timer. No se puede deshacer.',
    )
  })

  it('says a class with nothing taken has nothing to lose', async () => {
    stubApi({ session: { ...SESSION, present: 0 }, blocks: [] })
    renderAt('/admin/clases/s1')
    await screen.findByText(copy.record.empty)
    await userEvent.click(screen.getByRole('button', { name: copy.manage.delete }))
    const asked = screen.getByRole('group', { name: copy.manage.delete })
    expect(asked).toHaveTextContent(copy.manage.deleteConfirm(0, false))
    expect(asked).not.toHaveTextContent(copy.manage.credits)
  })

  it('marks a cancelled class on the day, in place of Sin asistencia', async () => {
    stubApi({ session: { ...SESSION, present: 0, cancelled_at: '2026-11-10T12:00:00Z' } })
    renderAt('/admin/clases')
    const row = await screen.findByRole('link', { name: /Fundamentos/ })
    expect(row).toHaveTextContent(es.admin.classes.today.cancelled)
    expect(row).not.toHaveTextContent(es.admin.classes.today.unmarked)
  })
})

describe('Registro del timer', () => {
  it('lists what each block ran', async () => {
    stubApi({ role: 'coach', me: 'coach' })
    renderAt('/admin/clases/s1')
    const list = await screen.findByRole('list', { name: copy.record.title })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Técnica20 min',
      `Sparring${es.admin.timer.done.notRun}`,
    ])
  })

  it("lets the class's coach correct it: a kind, minutes, rounds done, a block added and one removed", async () => {
    const extra: SessionBlock = { ...BLOCKS[0]!, id: 'b3', position: 2 }
    const calls = stubApi({ role: 'coach', me: 'coach', blocks: [...BLOCKS, extra] })
    renderAt('/admin/clases/s1')

    await userEvent.click(await screen.findByRole('button', { name: copy.record.edit }))
    const form = screen.getByRole('form', { name: copy.record.label })
    const first = within(form).getByRole('group', { name: copy.record.block(1) })
    await userEvent.selectOptions(within(first).getByLabelText(copy.record.kind), 'Drilling')
    await userEvent.clear(within(first).getByLabelText(copy.record.minutes))
    await userEvent.type(within(first).getByLabelText(copy.record.minutes), '15')

    const second = within(form).getByRole('group', { name: copy.record.block(2) })
    await userEvent.clear(within(second).getByLabelText(copy.record.completed))
    await userEvent.type(within(second).getByLabelText(copy.record.completed), '3')
    await userEvent.clear(within(second).getByLabelText(copy.record.minutes))
    // More than three rounds and part of a fourth: refused before it is sent.
    await userEvent.type(within(second).getByLabelText(copy.record.minutes), '21')
    await userEvent.click(within(form).getByRole('button', { name: copy.record.submit }))
    expect(within(form).getByRole('alert')).toHaveTextContent(copy.record.invalid)
    expect(within(second).getByLabelText(copy.record.minutes)).toHaveAttribute('aria-invalid', 'true')
    await userEvent.clear(within(second).getByLabelText(copy.record.minutes))
    await userEvent.type(within(second).getByLabelText(copy.record.minutes), '15')

    await userEvent.click(within(form).getByRole('button', { name: copy.record.remove(3) }))
    await userEvent.click(within(form).getByRole('button', { name: copy.record.add }))
    const added = within(form).getByRole('group', { name: copy.record.block(3) })
    await userEvent.type(within(added).getByLabelText(copy.record.minutes), '5')
    await userEvent.click(within(form).getByRole('button', { name: copy.record.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.record.saved)
    const sent = writes(calls)
    expect(sent.map((c) => `${c.method} ${c.path}`)).toEqual([
      'PUT /api/sessions/s1/blocks',
      'PUT /api/sessions/s1/blocks/b1/actual',
      'PUT /api/sessions/s1/blocks/b2/actual',
      expect.stringMatching(/^PUT \/api\/sessions\/s1\/blocks\/[0-9a-f-]{36}\/actual$/),
    ])
    const planned = (sent[0]!.body as { blocks: Record<string, unknown>[] }).blocks
    expect(planned).toEqual([
      {
        id: 'b1',
        block_kind_id: DRILLING.id,
        planned_seconds: 1200,
        rounds_planned: null,
        round_seconds: null,
        rest_seconds: null,
      },
      {
        id: 'b2',
        block_kind_id: SPARRING.id,
        planned_seconds: null,
        rounds_planned: 5,
        round_seconds: 300,
        rest_seconds: 60,
      },
      expect.objectContaining({ block_kind_id: TECHNIQUE.id, planned_seconds: 300, rounds_planned: null }),
    ])
    expect(sent[1]!.body).toEqual({ actual_seconds: 900, rounds_completed: null })
    expect(sent[2]!.body).toEqual({ actual_seconds: 900, rounds_completed: 3 })
    expect(sent[3]!.body).toEqual({ actual_seconds: 300, rounds_completed: null })
    // The record as it now stands.
    const list = screen.getByRole('list', { name: copy.record.title })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Drilling15 min',
      'Sparring3 de 5 rondas · 15 min',
      'Técnica5 min',
    ])
  })

  it('waits while the timer on this phone has blocks to send', async () => {
    // A server error keeps it on the phone, for the next try.
    queuePlan('s1', [])
    stubApi({ role: 'coach', me: 'coach', replace: { status: 500, body: { detail: 'boom' } } })
    renderAt('/admin/clases/s1')
    expect(await screen.findByText(copy.record.pending)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.record.edit })).not.toBeInTheDocument()
  })
})
