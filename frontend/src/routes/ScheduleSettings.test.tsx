import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClosedDay, ScheduleSlot } from '../api/schedule'
import { createQueryClient } from '../api/queryClient'
import type { ClassType } from '../api/sessions'
import { App } from '../App'
import { isoDay } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.schedule
const form = copy.form

const FUNDAMENTALS: ClassType = {
  id: 'fundamentos',
  name: 'Fundamentos',
  program_id: 'adultos',
  program_name: 'Adultos',
  credit_cost: 1,
  kind: 'class',
  counts_as_class: true,
  active: true,
  created_at: '2026-01-01T12:00:00Z',
}

const STAFF = [
  { person_id: 'owner', name: 'Carla Soto', phone: null, email: null, role: 'owner', since: '2026-01-01' },
  { person_id: 'coach', name: 'Rodrigo Fuentes', phone: null, email: null, role: 'coach', since: '2026-01-01' },
]

const slot = (id: string, extra: Partial<ScheduleSlot> = {}): ScheduleSlot => ({
  id,
  class_type_id: FUNDAMENTALS.id,
  class_type_name: FUNDAMENTALS.name,
  program_id: 'adultos',
  program_name: 'Adultos',
  class_type_active: true,
  weekdays: [1, 3, 5],
  start_time: '19:00:00',
  duration_minutes: 90,
  coach_id: 'coach',
  coach_name: 'Rodrigo Fuentes',
  topic: null,
  valid_from: '2026-01-05',
  valid_to: null,
  created_at: '2026-01-01T12:00:00Z',
  updated_at: '2026-01-01T12:00:00Z',
  ...extra,
})

const RUNNING = slot('running', { topic: 'Guardia' })
// Ended long ago: the timetable as it was, not shown.
const ENDED = slot('ended', { weekdays: [2], valid_to: '2026-01-31' })

const today = () => isoDay(new Date().toISOString(), 'America/Santiago')

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ save, closed = [] }: { save?: Answer; closed?: ClosedDay[] } = {}) {
  const calls: Call[] = []
  let slots = [RUNNING, ENDED]
  let days = [...closed]
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
    if (path === '/api/me/role') return { body: { role: 'owner' } }
    if (path === '/api/sessions') return { body: { date: today(), timezone: 'America/Santiago', sessions: [] } }
    if (path === '/api/class-types') return { body: [FUNDAMENTALS] }
    if (path === '/api/staff') return { body: STAFF }
    if (path === '/api/schedule' && method === 'GET') return { body: slots }
    if (path === '/api/schedule' && method === 'POST') {
      if (save) return save
      const made = slot('new', { ...(body as Partial<ScheduleSlot>), start_time: `${String(body['start_time'])}:00` })
      slots = [...slots, made]
      return { status: 201, body: made }
    }
    if (path === '/api/schedule/running' && method === 'PATCH') {
      if (save) return save
      return { body: { ...RUNNING, ...body } }
    }
    if (path === '/api/schedule/running' && method === 'DELETE') {
      slots = slots.filter((s) => s.id !== 'running')
      return { status: 204 }
    }
    if (path === '/api/closed-days' && method === 'GET') return { body: days }
    const closedDay = /^\/api\/closed-days\/(.+)$/.exec(path)
    if (closedDay && method === 'PUT') {
      const day = { day: closedDay[1]!, label: (body['label'] as string) || null }
      days = [...days, day]
      return { body: day }
    }
    if (closedDay && method === 'DELETE') {
      days = days.filter((d) => d.day !== closedDay[1])
      return { status: 204 }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function section() {
  return screen.findByRole('region', { name: copy.title })
}

/** The slot's row, the button that opens its form. */
async function slotRow() {
  return within(await section()).findByRole('button', { name: /^Lun · Mié · Vie/ })
}

describe('Ajustes: Horario', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the slots still running, with their days, times and coach', async () => {
    stubApi()
    renderAt('/admin/ajustes/horario')

    const rows = within(await section()).getAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(within(rows[0]!).getByText(copy.row('Lun · Mié · Vie', '19:00–20:30', 'Fundamentos'))).toBeInTheDocument()
    expect(rows[0]).toHaveTextContent(copy.detail('Adultos', 'Rodrigo Fuentes', 'Guardia'))
    expect(rows[0]).toHaveTextContent(copy.validity(null, null))
    // The row opens the slot; no Editar / Eliminar pair on it.
    expect(within(rows[0]!).queryByRole('button', { name: copy.edit })).not.toBeInTheDocument()
    expect(within(rows[0]!).queryByRole('button', { name: copy.delete })).not.toBeInTheDocument()
  })

  it('creates a slot from today, on the days ticked', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/horario')

    await userEvent.click(within(await section()).getByRole('button', { name: copy.add }))
    const create = await screen.findByRole('form', { name: form.create })
    await within(create).findByRole('option', { name: 'Fundamentos' })
    await within(create).findByRole('option', { name: 'Rodrigo Fuentes' })
    // No day yet: refused before anything is sent.
    expect(within(create).getByText(form.noDays)).toBeInTheDocument()
    await userEvent.click(within(create).getByRole('checkbox', { name: 'Mar' }))
    await userEvent.click(within(create).getByRole('checkbox', { name: 'Jue' }))
    const time = within(create).getByLabelText(form.time)
    await userEvent.clear(time)
    await userEvent.type(time, '07:00')
    await userEvent.selectOptions(within(create).getByLabelText(form.coach), 'Rodrigo Fuentes')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.created('Fundamentos'))
    expect(writes(calls)).toEqual([
      {
        method: 'POST',
        path: '/api/schedule',
        body: {
          class_type_id: 'fundamentos',
          weekdays: [2, 4],
          start_time: '07:00',
          duration_minutes: 60,
          coach_id: 'coach',
          topic: null,
          valid_to: null,
          valid_from: today(),
        },
      },
    ])
  })

  it('changes a slot from a date on, sending only what changed', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/horario')

    await userEvent.click(await slotRow())
    const edit = await screen.findByRole('form', { name: form.edit('Fundamentos') })
    expect(within(edit).getByLabelText(form.fromDate)).toHaveValue(today())
    await userEvent.click(within(edit).getByRole('checkbox', { name: 'Vie' }))
    const from = within(edit).getByLabelText(form.fromDate)
    await userEvent.clear(from)
    await userEvent.type(from, '2099-01-05')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.saved('Fundamentos'))
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/schedule/running', body: { weekdays: [1, 3], from_date: '2099-01-05' } },
    ])
  })

  it('says why a change after the slot ended is refused', async () => {
    const detail = [{ type: 'after_valid_to', loc: ['body', 'from_date'], msg: 'x' }]
    stubApi({ save: { status: 422, body: { detail } } })
    renderAt('/admin/ajustes/horario')

    await userEvent.click(await slotRow())
    const edit = await screen.findByRole('form', { name: form.edit('Fundamentos') })
    await userEvent.click(within(edit).getByRole('checkbox', { name: 'Sáb' }))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))
    expect(await within(edit).findByRole('alert')).toHaveTextContent(form.afterEnd)
  })

  it('deletes a slot after asking', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/horario')

    // Eliminar is in the slot's form, and asks first.
    await userEvent.click(await slotRow())
    const edit = await screen.findByRole('form', { name: form.edit('Fundamentos') })
    await userEvent.click(within(edit).getByRole('button', { name: copy.delete }))
    expect(screen.getByText(copy.deleteConfirm)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.deleteYes }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.deleted('Fundamentos'))
    expect(writes(calls)).toEqual([{ method: 'DELETE', path: '/api/schedule/running', body: undefined }])
    expect(await within(await section()).findByText(copy.empty)).toBeInTheDocument()
  })

  it('closes a day and reopens it', async () => {
    const calls = stubApi({ closed: [{ day: '2099-09-18', label: 'Fiestas Patrias' }] })
    renderAt('/admin/ajustes/horario')

    const closed = await screen.findByRole('region', { name: copy.closed.title })
    expect(await within(closed).findByText('Fiestas Patrias')).toBeInTheDocument()
    const add = within(closed).getByRole('form', { name: copy.closed.add })
    await userEvent.type(within(add).getByLabelText(copy.closed.day), '2099-12-25')
    await userEvent.type(within(add).getByLabelText(copy.closed.label), 'Navidad')
    await userEvent.click(within(add).getByRole('button', { name: copy.closed.add }))
    expect(await within(closed).findByText('Navidad')).toBeInTheDocument()

    const first = within(closed).getByText('Fiestas Patrias').closest('li')!
    await userEvent.click(within(first).getByRole('button', { name: copy.closed.reopen }))
    expect(await within(closed).findByRole('status')).toBeInTheDocument()

    expect(writes(calls)).toEqual([
      { method: 'PUT', path: '/api/closed-days/2099-12-25', body: { label: 'Navidad' } },
      { method: 'DELETE', path: '/api/closed-days/2099-09-18', body: undefined },
    ])
  })
})
