import { createMemoryHistory } from '@tanstack/react-router'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { RosterMember } from '../api/attendance'
import type { ClassTag, TagHours } from '../api/classTags'
import type { ClassSession, ClassType, SessionDay } from '../api/sessions'
import { App } from '../App'
import { isoDay, shiftDay, shortDay, toDate, weekdayDay, zonedInstant } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { mondayOf, nowOrNext, validateClassesSearch } from './Classes'
import { asRole } from '../test/access'

const copy = es.admin.classes
const detail = es.admin.session

const classType = (id: string, name: string, program: string): ClassType => ({
  id,
  name,
  program_id: `p-${program}`,
  program_name: program,
  credit_cost: 1,
  kind: 'class',
  counts_as_class: true,
  active: true,
  activity_id: null,
  activity_name: null,
  created_at: '2026-11-01T12:00:00Z',
})

const FUNDAMENTALS = classType('fundamentos', 'Fundamentos', 'Adultos')
const ADVANCED = classType('avanzado', 'Avanzado', 'Adultos')
const KIDS = classType('kids', 'Kids 8 a 12', 'Kids')

// 19:00 and 07:00 in Santiago (UTC-3 in November).
const EVENING: ClassSession = {
  id: 's-evening',
  class_type_id: FUNDAMENTALS.id,
  class_type_name: FUNDAMENTALS.name,
  class_type_kind: 'class',
  program_id: FUNDAMENTALS.program_id,
  program_name: FUNDAMENTALS.program_name,
  starts_at: '2026-11-09T22:00:00Z',
  coach_id: 'coach',
  coach_name: 'Rodrigo Fuentes',
  topic: 'Guardia cerrada',
  notes: null,
  cancelled_at: null,
  created_at: '2026-11-09T22:00:00Z',
  updated_at: '2026-11-09T22:00:00Z',
  present: 12,
  duration_minutes: null,
  slot_id: null,
  slot_date: null,
  tags: [],
}

const MORNING: ClassSession = {
  ...EVENING,
  id: 's-morning',
  class_type_id: KIDS.id,
  class_type_name: KIDS.name,
  class_type_kind: 'class',
  program_id: KIDS.program_id,
  program_name: KIDS.program_name,
  starts_at: '2026-11-09T10:00:00Z',
  topic: null,
  present: 0,
}

const tag = (id: string, name: string, archived = false): ClassTag => ({
  id,
  name,
  archived,
  created_at: '2026-11-01T12:00:00Z',
})
const TAGS = [tag('strength', 'Fuerza'), tag('guard', 'Pasaje de guardia'), tag('old', 'Yoga', true)]

const hoursFor = (first: string, last: string, minutes: number): TagHours => ({
  first_day: first,
  last_day: last,
  tags: minutes ? [{ tag_id: 'guard', name: 'Pasaje de guardia', archived: false, classes: 3, minutes }] : [],
  untagged_minutes: 0,
  no_duration_classes: 0,
  no_duration: [],
})

// Chile's, as the API names them (#426).
const HOLIDAYS = [
  { date: '2026-09-18', name: 'Día de la Independencia' },
  { date: '2026-09-19', name: 'Día de las Glorias del Ejército' },
  { date: '2026-12-08', name: 'La Inmaculada Concepción' },
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }
type Stub = {
  role?: 'owner' | 'admin' | 'coach'
  classTypes?: ClassType[]
  sessions?: ClassSession[]
  start?: Answer
  update?: Answer
  // Every day's classes, each answered on its own date; without it, any date is `sessions`.
  week?: ClassSession[]
  // Who is on each class's roster.
  roster?: RosterMember[]
  // Each class type's default duration; 60 for any other.
  durations?: Record<string, number>
  hours?: TagHours
}

function stubApi({
  role = 'coach',
  classTypes = [FUNDAMENTALS, ADVANCED, KIDS],
  sessions = [MORNING, EVENING],
  start,
  update,
  week,
  roster = [],
  durations = {},
  hours = hoursFor('2026-11-01', '2026-11-30', 270),
}: Stub = {}) {
  const calls: Call[] = []
  let day: SessionDay = { date: '2026-11-09', timezone: 'America/Santiago', sessions }
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      const answer = route(url.pathname, method, body, url.searchParams.get('date'), url.searchParams)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: unknown, date: string | null, query: URLSearchParams): Answer {
    // The class's own coach, unless told otherwise.
    if (path === '/api/me/role') return { body: { ...asRole(role), person_id: 'coach' } }
    if (path === '/api/class-types') return { body: classTypes }
    if (path === '/api/sessions' && method === 'GET' && week) {
      const on = date ?? isoDay(new Date().toISOString(), 'America/Santiago')
      return { body: { ...day, date: on, sessions: week.filter((s) => isoDay(s.starts_at, 'America/Santiago') === on) } }
    }
    if (path === '/api/sessions' && method === 'GET' && date) {
      return { body: { ...day, date, holidays: HOLIDAYS.filter((h) => h.date === date) } }
    }
    if (path === '/api/sessions' && method === 'GET') return { body: day }
    if (path === '/api/sessions/range') {
      const from = query.get('from')!
      const to = query.get('to')!
      const all = week ?? day.sessions
      const within = all.filter((s) => {
        const on = isoDay(s.starts_at, 'America/Santiago')
        return from <= on && on <= to
      })
      const holidays = HOLIDAYS.filter((h) => from <= h.date && h.date <= to)
      return { body: { from, to, timezone: 'America/Santiago', sessions: within, holidays } }
    }
    if (path === '/api/sessions/duration') {
      const id = query.get('class_type_id')!
      return { body: { class_type_id: id, duration_minutes: durations[id] ?? 60 } }
    }
    if (path === '/api/sessions' && method === 'POST') {
      if (start) return start
      const sent = body as { class_type_id: string; duration_minutes?: number }
      const type = classTypes.find((c) => c.id === sent.class_type_id)!
      const created: ClassSession = {
        ...EVENING,
        duration_minutes: sent.duration_minutes ?? 60,
        id: 's-new',
        class_type_id: type.id,
        class_type_name: type.name,
        program_id: type.program_id,
        program_name: type.program_name,
        topic: null,
      }
      day = { ...day, sessions: [...day.sessions, created] }
      return { status: 201, body: created }
    }
    // The roster has its own tests (SessionDetail.test.tsx).
    const rostered = [...day.sessions, ...(week ?? [])].find((s) => path === `/api/sessions/${s.id}/roster`)
    if (rostered) {
      return { body: { session_id: rostered.id, present: roster.filter((m) => m.present).length, members: roster } }
    }
    if (path === '/api/plans') return { body: [] }
    if (path === '/api/class-tags') return { body: TAGS }
    if (path === '/api/class-tags/hours') return { body: hours }
    const found = day.sessions.find((s) => path === `/api/sessions/${s.id}`)
    if (found && method === 'GET') return { body: found }
    if (found && method === 'PATCH') {
      if (update) return update
      const { topic, notes, tag_ids } = body as { topic: string; notes: string; tag_ids: string[] }
      const updated = {
        ...found,
        topic: topic.trim() || null,
        notes: notes.trim() || null,
        tags: TAGS.filter((each) => tag_ids.includes(each.id)),
        updated_at: '2026-11-09T23:30:00Z',
      }
      day = { ...day, sessions: day.sessions.map((s) => (s.id === found.id ? updated : s)) }
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

/** "Crear clase" is a button until it is wanted (#358): open its form. */
async function openStart() {
  await userEvent.click(await screen.findByRole('button', { name: copy.start.title }))
  return screen.findByRole('form', { name: copy.start.title })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('Clases', () => {
  it("lists today's sessions earliest first, in the gym's time, each leading to its page", async () => {
    stubApi()
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    expect(await within(today).findByText(copy.today.count(2))).toBeInTheDocument()
    const rows = within(today).getAllByRole('link')
    expect(rows.map((row) => row.getAttribute('href'))).toEqual(['/admin/clases/s-morning', '/admin/clases/s-evening'])
    expect(rows[0]).toHaveTextContent(copy.today.row('07:00', 'Kids 8 a 12'))
    expect(rows[0]).toHaveTextContent(copy.today.detail('Kids', 'Rodrigo Fuentes'))
    expect(rows[0]).toHaveTextContent(copy.today.noTopic)
    expect(rows[1]).toHaveTextContent(copy.today.row('19:00', 'Fundamentos'))
    expect(rows[1]).toHaveTextContent('Guardia cerrada')
  })

  it('shows how long a class lasts, and walks to the next day and back', async () => {
    const calls = stubApi({ sessions: [{ ...EVENING, duration_minutes: 90 }] })
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    expect(await within(today).findByRole('link')).toHaveTextContent(copy.today.row('19:00–20:30', 'Fundamentos'))

    const tomorrow = shiftDay(isoDay(new Date().toISOString(), 'America/Santiago'), 1)
    const days = within(today).getByRole('group', { name: copy.days.label })
    await userEvent.click(within(days).getByRole('button', { name: copy.days.next }))
    const next = await screen.findByRole('region', { name: weekdayDay(toDate(tomorrow)) })
    expect(calls.map((c) => c.path)).toContain(`/api/sessions?date=${tomorrow}`)

    await userEvent.click(within(next).getByRole('button', { name: copy.days.today }))
    expect(await screen.findByRole('region', { name: copy.today.title })).toBeInTheDocument()
  })

  it('keeps the day in the URL: a reload finds it, back steps through it, "Hoy" clears it (#426)', async () => {
    const calls = stubApi()
    const today = isoDay(new Date().toISOString(), 'America/Santiago')
    const past = shiftDay(today, -20)
    const router = renderAt(`/admin/clases?day=${past}`)

    const shown = await screen.findByRole('region', { name: weekdayDay(toDate(past)) })
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain(`/api/sessions?date=${past}`))
    const days = within(shown).getByRole('group', { name: copy.days.label })
    await userEvent.click(within(days).getByRole('button', { name: copy.days.previous }))
    await userEvent.click(within(screen.getByRole('group', { name: copy.days.label })).getByRole('button', { name: copy.days.previous }))
    expect(router.state.location.search).toEqual({ day: shiftDay(past, -2) })

    act(() => router.history.back())
    act(() => router.history.back())
    expect(await screen.findByRole('region', { name: weekdayDay(toDate(past)) })).toBeInTheDocument()

    await userEvent.click(within(screen.getByRole('region', { name: weekdayDay(toDate(past)) })).getByRole('button', { name: copy.days.today }))
    expect(router.state.location.search).toEqual({})
    expect(await screen.findByRole('region', { name: copy.today.title })).toBeInTheDocument()
  })

  it('jumps to the date typed (#426)', async () => {
    stubApi()
    const router = renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    fireEvent.change(within(today).getByLabelText(copy.days.jump), { target: { value: '2026-10-03' } })
    expect(router.state.location.search).toEqual({ day: '2026-10-03' })
    expect(await screen.findByRole('region', { name: weekdayDay(toDate('2026-10-03')) })).toBeInTheDocument()
  })

  it('names a public holiday after the day (#426)', async () => {
    stubApi()
    renderAt('/admin/clases?day=2026-12-08')

    expect(
      await screen.findByRole('region', { name: copy.days.holiday(weekdayDay(toDate('2026-12-08')), 'La Inmaculada Concepción') }),
    ).toBeInTheDocument()
  })

  it('takes only a real day and the first of a month from the URL', () => {
    expect(validateClassesSearch({ day: '2026-11-04', month: '2026-11-01' })).toEqual({ day: '2026-11-04', month: '2026-11-01' })
    expect(validateClassesSearch({ day: '2026-02-30', month: '2026-11-04' })).toEqual({ day: undefined, month: undefined })
    expect(validateClassesSearch({ day: 'ayer', month: 202611 })).toEqual({ day: undefined, month: undefined })
  })

  it('shows how many came on each class of the day', async () => {
    stubApi()
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    const [morning, evening] = await within(today).findAllByRole('link')
    expect(morning).not.toHaveTextContent(copy.today.present(0))
    expect(evening).toHaveTextContent(copy.today.present(12))
  })

  it('flags a class no one is marked at', async () => {
    stubApi()
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    const [morning, evening] = await within(today).findAllByRole('link')
    expect(morning).toHaveTextContent(copy.today.unmarked)
    expect(evening).not.toHaveTextContent(copy.today.unmarked)
  })

  it('does not flag a class that has not started yet', async () => {
    const later: ClassSession = {
      ...MORNING,
      id: 's-later',
      starts_at: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
    }
    stubApi({ sessions: [later] })
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    const [row] = await within(today).findAllByRole('link')
    expect(row).not.toHaveTextContent(copy.today.unmarked)
  })

  // 09:00 in Santiago on Monday the 9th: the 07:00 class is over, the 19:00 one is next.
  it('puts the class on now, else the next one, first: its attendance and its timer (#358)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-09T12:00:00Z'))
    stubApi()
    renderAt('/admin/clases')

    const eyebrow = await screen.findByText(copy.now.next)
    const card = eyebrow.closest('section')!
    expect(card).toHaveTextContent(copy.today.row('19:00', 'Fundamentos'))
    expect(card).toHaveTextContent(copy.today.detail('Adultos', 'Rodrigo Fuentes'))
    expect(within(card).getByRole('link', { name: copy.now.takeLabel(copy.today.row('19:00', 'Fundamentos')) })).toHaveAttribute(
      'href',
      '/admin/clases/s-evening',
    )
    // The class's own coach runs its timer.
    expect(within(card).getByRole('link', { name: detail.timer.open })).toHaveAttribute('href', '/admin/clases/s-evening/timer')
    // Ahead of "Crear clase" and the day's list.
    const start = screen.getByRole('button', { name: copy.start.title })
    const today = screen.getByRole('region', { name: copy.today.title })
    expect(card.compareDocumentPosition(start) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(card.compareDocumentPosition(today) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('moves on to the class on now as the minutes pass, the page left open', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    // 18:59 in Santiago: the 19:00 class is next.
    vi.setSystemTime(new Date('2026-11-09T21:59:00Z'))
    stubApi()
    renderAt('/admin/clases')

    const card = (await screen.findByText(copy.now.next)).closest('section')!
    expect(card).toHaveTextContent(copy.today.row('19:00', 'Fundamentos'))

    // A minute on, with nothing else re-rendering the page.
    await act(async () => {
      vi.advanceTimersByTime(60_000)
    })
    expect(await screen.findByText(copy.now.on)).toBeInTheDocument()
    expect(screen.queryByText(copy.now.next)).not.toBeInTheDocument()
  })

  it('has no such card once the day’s classes are over', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    // 23:00 in Santiago.
    vi.setSystemTime(new Date('2026-11-10T02:00:00Z'))
    stubApi()
    renderAt('/admin/clases')

    await screen.findByRole('region', { name: copy.today.title })
    expect(screen.queryByText(copy.now.next)).not.toBeInTheDocument()
    expect(screen.queryByText(copy.now.on)).not.toBeInTheDocument()
  })

  it('keeps "Crear clase" a button until it is wanted (#358)', async () => {
    stubApi()
    renderAt('/admin/clases')

    const start = await screen.findByRole('button', { name: copy.start.title })
    expect(start).toHaveAttribute('aria-expanded', 'false')
    // Nothing to point at while closed.
    expect(start).not.toHaveAttribute('aria-controls')
    expect(screen.queryByRole('form', { name: copy.start.title })).not.toBeInTheDocument()
    await userEvent.click(start)
    const form = await screen.findByRole('form', { name: copy.start.title })
    await userEvent.click(screen.getByRole('button', { name: copy.start.close }))
    expect(form).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.start.title })).toBeInTheDocument()
  })

  it('cuts a row short on a desktop, its full text in its title', async () => {
    stubApi()
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    const [, evening] = await within(today).findAllByRole('link')
    expect(evening).toHaveAttribute(
      'title',
      [copy.today.row('19:00', 'Fundamentos'), copy.today.detail('Adultos', 'Rodrigo Fuentes'), 'Guardia cerrada'].join(' · '),
    )
  })

  it('says when there are no classes yet today', async () => {
    stubApi({ sessions: [] })
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    expect(await within(today).findByText(copy.today.empty)).toBeInTheDocument()
  })

  it('starts a class of the type chosen and opens it', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/clases')

    const form = await openStart()
    const select = within(form).getByLabelText(copy.start.classType)
    // By program: the select groups the class types under each.
    expect(within(select).getAllByRole('group').map((g) => g.getAttribute('label'))).toEqual(['Adultos', 'Kids'])
    await userEvent.selectOptions(select, 'Avanzado')
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Avanzado' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/clases/s-new')
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/sessions', body: { class_type_id: 'avanzado', duration_minutes: 60 } },
    ])
  })

  it("prefills the class's duration with its type's, and keeps one typed", async () => {
    const calls = stubApi({ durations: { fundamentos: 90, kids: 45 } })
    renderAt('/admin/clases')

    const form = await openStart()
    const duration = within(form).getByLabelText(copy.start.duration)
    await vi.waitFor(() => expect(duration).toHaveValue(90))
    await userEvent.selectOptions(within(form).getByLabelText(copy.start.classType), 'Kids 8 a 12')
    await vi.waitFor(() => expect(duration).toHaveValue(45))
    await userEvent.clear(duration)
    await userEvent.type(duration, '2000')
    expect(within(form).getByRole('alert')).toHaveTextContent(copy.start.badDuration)
    expect(within(form).getByRole('button', { name: copy.start.submit })).toBeDisabled()
    await userEvent.clear(duration)
    await userEvent.type(duration, '50')
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Kids 8 a 12' })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/sessions', body: { class_type_id: 'kids', duration_minutes: 50 } },
    ])
  })

  it('registers a class that already happened on the day and time chosen (#407)', async () => {
    const calls = stubApi({ durations: { avanzado: 75 } })
    renderAt('/admin/clases')
    const today = isoDay(new Date().toISOString(), 'America/Santiago')
    const earlier = shiftDay(today, -3)

    const form = await openStart()
    const day = within(form).getByLabelText(copy.start.day)
    expect(day).toHaveValue(today)
    expect(day).toHaveAttribute('max', today)
    await userEvent.selectOptions(within(form).getByLabelText(copy.start.classType), 'Avanzado')
    fireEvent.change(day, { target: { value: earlier } })
    // An earlier day's time is chosen, never the clock's by accident.
    const time = within(form).getByLabelText(copy.start.time)
    expect(time).toHaveValue('')
    expect(time).toHaveAccessibleDescription(copy.start.chooseTime)
    expect(within(form).getByRole('button', { name: copy.start.submit })).toBeDisabled()
    fireEvent.change(time, { target: { value: '07:30' } })
    expect(within(form).queryByText(copy.start.chooseTime)).not.toBeInTheDocument()
    expect(within(form).getByRole('button', { name: copy.start.submit })).toBeEnabled()
    expect(within(form).getByText(copy.start.pastDay)).toBeInTheDocument()
    // The type's duration as of that day.
    await vi.waitFor(() =>
      expect(calls.some((c) => c.path === `/api/sessions/duration?class_type_id=avanzado&date=${earlier}`)).toBe(true),
    )
    await vi.waitFor(() => expect(within(form).getByLabelText(copy.start.duration)).toHaveValue(75))
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Avanzado' })).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/sessions',
        body: {
          class_type_id: 'avanzado',
          duration_minutes: 75,
          starts_at: zonedInstant(earlier, '07:30', 'America/Santiago'),
        },
      },
    ])
  })

  it('starts on the day shown, and refuses a day yet to come', async () => {
    const calls = stubApi()
    renderAt('/admin/clases')
    const today = isoDay(new Date().toISOString(), 'America/Santiago')

    await userEvent.click(await screen.findByRole('button', { name: copy.days.previous }))
    const form = await openStart()
    const day = within(form).getByLabelText(copy.start.day)
    expect(day).toHaveValue(shiftDay(today, -1))
    expect(within(form).getByLabelText(copy.start.time)).toHaveValue('')
    expect(within(form).getByText(copy.start.chooseTime)).toBeInTheDocument()
    // Back on today, the time is now again, as it always was.
    fireEvent.change(day, { target: { value: today } })
    expect(within(form).getByLabelText(copy.start.time)).not.toHaveValue('')
    fireEvent.change(day, { target: { value: shiftDay(today, 1) } })
    expect(within(form).getByRole('alert')).toHaveTextContent(copy.start.futureDay)
    expect(within(form).getByRole('button', { name: copy.start.submit })).toBeDisabled()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([])
  })

  it('says so when a class cannot be started', async () => {
    stubApi({ start: { status: 422, body: { detail: [] } } })
    renderAt('/admin/clases')

    const form = await openStart()
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.start.failed)
  })

  it('says when the gym has no class types to start', async () => {
    stubApi({ classTypes: [] })
    renderAt('/admin/clases')

    await userEvent.click(await screen.findByRole('button', { name: copy.start.title }))
    const start = await screen.findByRole('region', { name: copy.start.title })
    expect(await within(start).findByText(copy.start.noClassTypes)).toBeInTheDocument()
    expect(within(start).queryByRole('button', { name: copy.start.submit })).not.toBeInTheDocument()
  })
})

describe('Clase', () => {
  it('shows what the class is, when it started and who teaches it', async () => {
    stubApi()
    renderAt('/admin/clases/s-evening')

    expect(await screen.findByRole('heading', { level: 1, name: 'Fundamentos' })).toBeInTheDocument()
    // Not today: the day too.
    expect(await screen.findByText(detail.eyebrow('Adultos', '9 nov 19:00'))).toBeInTheDocument()
    expect(screen.getByText(detail.coach('Rodrigo Fuentes'))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: detail.back })).toHaveAttribute('href', '/admin/clases')
  })

  it('writes the topic and notes after class', async () => {
    const calls = stubApi()
    renderAt('/admin/clases/s-evening')

    const form = await screen.findByRole('form', { name: detail.form.label })
    const topic = within(form).getByLabelText(detail.form.topic)
    expect(topic).toHaveValue('Guardia cerrada')
    await userEvent.clear(topic)
    await userEvent.type(topic, ' Pasaje de rodilla ')
    await userEvent.type(within(form).getByLabelText(detail.form.notes), 'Faltó calentamiento.')
    await userEvent.click(within(form).getByRole('button', { name: detail.form.submit }))

    expect(await within(form).findByRole('status')).toHaveTextContent(detail.form.saved)
    // As stored: trimmed.
    expect(topic).toHaveValue('Pasaje de rodilla')
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/sessions/s-evening',
        body: { topic: ' Pasaje de rodilla ', notes: 'Faltó calentamiento.', tag_ids: [] },
      },
    ])

    // "Guardado" until the next edit.
    await userEvent.type(topic, '!')
    expect(within(form).queryByRole('status')).not.toBeInTheDocument()
  })

  it('tags the class from the gym’s tags, an archived one only while it is on', async () => {
    const calls = stubApi({ sessions: [{ ...EVENING, tags: [{ id: 'old', name: 'Yoga', archived: true }] }] })
    renderAt('/admin/clases/s-evening')

    const form = await screen.findByRole('form', { name: detail.form.label })
    const picker = within(await within(form).findByRole('group', { name: detail.form.tags }))
    expect(picker.getAllByRole('button').map((b) => b.textContent)).toEqual([
      'Fuerza',
      'Pasaje de guardia',
      `Yoga (${es.tagHours.archived})`,
    ])
    expect(picker.getByRole('button', { name: /^Yoga/ })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(picker.getByRole('button', { name: 'Pasaje de guardia' }))
    await userEvent.click(picker.getByRole('button', { name: /^Yoga/ }))
    await userEvent.click(within(form).getByRole('button', { name: detail.form.submit }))

    expect(await within(form).findByRole('status')).toHaveTextContent(detail.form.saved)
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { topic: 'Guardia cerrada', notes: '', tag_ids: ['guard'] },
    ])
    // Taken off, an archived tag is gone from the choices.
    expect(picker.queryByRole('button', { name: /^Yoga/ })).not.toBeInTheDocument()
  })

  it('shows another coach the class’s tags', async () => {
    stubApi({ sessions: [{ ...EVENING, coach_id: 'other', tags: [TAGS[1]!] }] })
    renderAt('/admin/clases/s-evening')

    const view = await screen.findByRole('region', { name: detail.form.label })
    expect(within(view).getByRole('list', { name: detail.form.tags })).toHaveTextContent('Pasaje de guardia')
  })

  it('says so when the topic cannot be saved', async () => {
    stubApi({ update: { status: 500, body: { detail: 'boom' } } })
    renderAt('/admin/clases/s-evening')

    const form = await screen.findByRole('form', { name: detail.form.label })
    await userEvent.click(within(form).getByRole('button', { name: detail.form.submit }))

    expect(await within(form).findByRole('alert')).toHaveTextContent(detail.form.failed)
  })

  it('says when there is no such class', async () => {
    stubApi()
    renderAt('/admin/clases/nope')

    expect(await screen.findByRole('alert')).toHaveTextContent(detail.notFound)
  })
})

const onDay = (day: string, time: string) => new Date(`${day}T${time}:00-03:00`).toISOString()

const onRoster = (id: string, name: string, present: boolean, regular = true): RosterMember => ({
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
  regular,
  rank: null,
  present,
  unmet_requirements: [],
})

describe('Clases on a desktop', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  const wide = (matches: boolean) =>
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
    )

  it('finds the class on now, else the next one, never a cancelled one', () => {
    const at = (iso: string, extra: Partial<ClassSession> = {}): ClassSession => ({ ...EVENING, id: iso, starts_at: iso, ...extra })
    const nine = at('2026-11-09T12:00:00Z', { duration_minutes: 90 })
    const noon = at('2026-11-09T15:00:00Z')
    const evening = at('2026-11-09T22:00:00Z')
    const now = (iso: string) => new Date(iso)

    expect(nowOrNext([nine, noon, evening], now('2026-11-09T13:00:00Z'))).toEqual({ session: nine, on: true })
    expect(nowOrNext([evening, nine, noon], now('2026-11-09T13:31:00Z'))).toEqual({ session: noon, on: false })
    // No duration: on for its first hour.
    expect(nowOrNext([noon, evening], now('2026-11-09T15:59:00Z'))).toEqual({ session: noon, on: true })
    expect(nowOrNext([noon, evening], now('2026-11-09T16:00:00Z'))).toEqual({ session: evening, on: false })
    expect(nowOrNext([{ ...evening, cancelled_at: '2026-11-09T10:00:00Z' }], now('2026-11-09T12:00:00Z'))).toBeNull()
    expect(nowOrNext([nine, noon], now('2026-11-09T23:00:00Z'))).toBeNull()
    // The open-access day is the door's (#348), never the class now.
    const door = at('2026-11-09T11:00:00Z', { class_type_kind: 'open_access' })
    expect(nowOrNext([door, noon], now('2026-11-09T11:30:00Z'))).toEqual({ session: noon, on: false })
  })

  it('finds the Monday of the week', () => {
    expect(mondayOf('2026-11-10')).toBe('2026-11-09')
    expect(mondayOf('2026-11-09')).toBe('2026-11-09')
    expect(mondayOf('2026-11-15')).toBe('2026-11-09')
  })

  // The clock pinned (#330): at 22:00 on a Sunday in Santiago it is already Monday in UTC,
  // the next week on a runner in UTC until the gym's timezone is in.
  it.each([
    ['on a Sunday evening, Monday already in UTC', '2026-11-16T01:00:00Z', '2026-11-15'],
    ['at midday', '2026-11-11T15:00:00Z', '2026-11-11'],
  ])('shows the week beside the day, and who came to the class picked in it, %s', async (_, now, today) => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(now))
    wide(true)
    const monday = mondayOf(today)
    const days = Array.from({ length: 7 }, (_, i) => shiftDay(monday, i))
    // Today's at midnight has begun.
    const begun: ClassSession = { ...EVENING, id: 's-begun', starts_at: onDay(today, '00:00'), present: 2 }
    // Yet to start.
    const sunday: ClassSession = { ...MORNING, id: 's-sunday', starts_at: onDay(days[6]!, '23:59') }
    const calls = stubApi({
      week: [begun, sunday],
      roster: [onRoster('ana', 'Ana Soto', true), onRoster('beto', 'Beto Díaz', true, false), onRoster('caro', 'Caro Vera', false)],
    })
    renderAt('/admin/clases')

    const week = await screen.findByRole('region', { name: copy.week.title })
    // Once the gym's timezone is in: a device in another zone has its own week until then.
    for (const day of days) {
      expect(await within(week).findByRole('heading', { name: weekdayDay(toDate(day)) })).toBeInTheDocument()
    }
    // The whole week in one request (#426), not one a day.
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain(`/api/sessions/range?from=${monday}&to=${days[6]}`))
    expect(calls.filter((c) => c.path.startsWith('/api/sessions?date='))).toEqual([])

    // Today's class that has begun is picked to start with: two came, and two are regulars.
    await screen.findByText(copy.week.present(2, 2))
    const picked = screen.getByRole('region', { name: copy.week.picked })
    const present = within(picked).getByRole('list', { name: copy.week.presentLabel })
    expect(within(present).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Ana Soto', 'Beto Díaz'])
    expect(within(picked).getByRole('link', { name: copy.week.take })).toHaveAttribute('href', '/admin/clases/s-begun')

    const later = within(week).getByRole('button', { name: new RegExp(copy.today.row('23:59', 'Kids 8 a 12')) })
    await userEvent.click(later)
    expect(later).toHaveAttribute('aria-pressed', 'true')
    expect(await screen.findByText(copy.week.upcoming)).toBeInTheDocument()
  })

  // 19:30 in Santiago: the 19:00 class is on, and it is the one picked in the week.
  it('shows the class on now once, picked in the week, with one "Tomar asistencia" (#416)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-09T22:30:00Z'))
    wide(true)
    stubApi({ week: [MORNING, EVENING], roster: [onRoster('ana', 'Ana Soto', true)] })
    renderAt('/admin/clases')

    await screen.findByText(copy.week.present(1, 1))
    const picked = screen.getByRole('region', { name: copy.week.picked })
    const name = copy.today.row('19:00', 'Fundamentos')
    expect(within(picked).getByText(copy.now.on)).toBeInTheDocument()
    expect(within(picked).getByRole('link', { name: detail.timer.open })).toHaveAttribute('href', '/admin/clases/s-evening/timer')
    // Once on the page: the left column drops its card.
    const takes = screen.getAllByRole('link', { name: copy.now.takeLabel(name) })
    expect(takes).toHaveLength(1)
    expect(picked).toContainElement(takes[0]!)
    expect(screen.queryByRole('region', { name })).not.toBeInTheDocument()
    expect(screen.getAllByText(copy.now.on)).toHaveLength(1)

    // Another class picked, the class now is the left column's card again.
    const week = screen.getByRole('region', { name: copy.week.title })
    await userEvent.click(within(week).getByRole('button', { name: new RegExp(copy.today.row('07:00', 'Kids 8 a 12')) }))
    const card = (await screen.findByText(copy.now.on)).closest('section')!
    expect(within(card).getByRole('link', { name: copy.now.takeLabel(name) })).toHaveAttribute('href', '/admin/clases/s-evening')
    expect(within(screen.getByRole('region', { name: copy.week.picked })).getByRole('link', { name: copy.week.take })).toBeInTheDocument()
  })

  it('has one date navigator at 1280, the week, and lists each class once (#567)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T15:00:00Z'))
    wide(true)
    const calls = stubApi({ week: [{ ...MORNING, starts_at: onDay('2026-11-11', '07:00') }] })
    renderAt('/admin/clases')

    const week = await screen.findByRole('region', { name: copy.week.title })
    expect(screen.getAllByRole('group', { name: /^Cambiar de (día|semana|mes)$/ })).toEqual([
      within(week).getByRole('group', { name: copy.week.label }),
    ])
    expect(screen.getAllByLabelText(copy.days.jump)).toHaveLength(1)
    // No day list beside the week: today's class is the week's alone.
    expect(screen.queryByRole('region', { name: copy.today.title })).not.toBeInTheDocument()
    expect(await within(week).findAllByRole('button', { name: new RegExp(copy.today.row('07:00', 'Kids 8 a 12')) })).toHaveLength(1)
    expect(calls.filter((c) => c.path.startsWith('/api/sessions/range'))).not.toEqual([])
  })

  it('never asks for the week on a phone', async () => {
    wide(false)
    const calls = stubApi()
    renderAt('/admin/clases')

    await screen.findByRole('region', { name: copy.today.title })
    expect(screen.queryByRole('region', { name: copy.week.title })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/sessions?date='))).toEqual([])
    expect(calls.filter((c) => c.path.startsWith('/api/sessions/range'))).toEqual([])
  })

  it('walks the week back and on, the day moving with it (#426)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T15:00:00Z'))
    wide(true)
    const calls = stubApi({ week: [] })
    const router = renderAt('/admin/clases')

    const week = await screen.findByRole('region', { name: copy.week.title })
    const arrows = within(week).getByRole('group', { name: copy.week.label })
    await userEvent.click(within(arrows).getByRole('button', { name: copy.week.previous }))
    expect(router.state.location.search).toEqual({ day: '2026-11-04' })
    expect(await within(arrows).findByRole('heading', { name: copy.week.range(shortDay('2026-11-02'), shortDay('2026-11-08')) })).toBeInTheDocument()
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain('/api/sessions/range?from=2026-11-02&to=2026-11-08'))
    // Off today's week, "Hoy" is back beside "Ir a fecha".
    expect(within(week).getByRole('button', { name: copy.days.today })).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('group', { name: copy.week.label })).getByRole('button', { name: copy.week.next }))
    // Back on today's week, today is no day in the URL.
    expect(router.state.location.search).toEqual({})
  })

  it('shows the month beside the day, each day a tap that keeps it (#426)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    // Wednesday 11 November, midday in Santiago.
    vi.setSystemTime(new Date('2026-11-11T15:00:00Z'))
    wide(true)
    const cancelled: ClassSession = { ...EVENING, id: 's-cancelled', starts_at: onDay('2026-11-04', '19:00'), cancelled_at: '2026-11-04T12:00:00Z', present: 0 }
    const unmarked: ClassSession = { ...MORNING, id: 's-unmarked', starts_at: onDay('2026-11-04', '07:00') }
    const marked: ClassSession = { ...EVENING, id: 's-marked', starts_at: onDay('2026-11-04', '20:00') }
    const door: ClassSession = { ...MORNING, id: 's-door', class_type_kind: 'open_access', starts_at: onDay('2026-11-04', '06:00') }
    const calls = stubApi({ week: [cancelled, unmarked, marked, door] })
    const router = renderAt('/admin/clases')

    const week = await screen.findByRole('region', { name: copy.week.title })
    await userEvent.click(within(week).getByRole('button', { name: copy.view.month }))
    expect(router.state.location.search).toEqual({ month: '2026-11-01' })
    const month = await screen.findByRole('region', { name: copy.month.title('2026-11-01') })
    // Six weeks, Monday 26 October to Sunday 6 December.
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain('/api/sessions/range?from=2026-10-26&to=2026-12-06'))
    // The door's day is no class; a cancelled one is said apart.
    const fourth = await within(month).findByRole('button', { name: copy.month.cell('miércoles', '2026-11-04', 2, 1, 1) })
    expect(within(month).getByRole('button', { name: copy.month.cell('miércoles', '2026-11-11', 0, 0, 0) })).toHaveAttribute('aria-current', 'date')
    expect(within(month).getAllByRole('button', { name: /^(lunes|martes|miércoles|jueves|viernes|sábado|domingo) / })).toHaveLength(42)

    await userEvent.click(fourth)
    expect(router.state.location.search).toEqual({ day: '2026-11-04', month: '2026-11-01' })
    expect(await screen.findByRole('region', { name: weekdayDay(toDate('2026-11-04')) })).toBeInTheDocument()
    expect(fourth).toHaveAttribute('aria-pressed', 'true')

    // Another month leaves the day where it is.
    await userEvent.click(within(month).getByRole('button', { name: copy.month.previous }))
    expect(router.state.location.search).toEqual({ day: '2026-11-04', month: '2026-10-01' })
    expect(await screen.findByRole('region', { name: copy.month.title('2026-10-01') })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: weekdayDay(toDate('2026-11-04')) })).toBeInTheDocument()

    // "Hoy" is today's day and week again.
    await userEvent.click(within(screen.getByRole('region', { name: copy.month.title('2026-10-01') })).getByRole('button', { name: copy.days.today }))
    expect(router.state.location.search).toEqual({})
    expect(await screen.findByRole('region', { name: copy.week.title })).toBeInTheDocument()
  })

  it('marks a public holiday in the month in red only, its name in the day and its title, and in the week (#426, #457)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-16T15:00:00Z'))
    wide(true)
    stubApi({ week: [] })
    renderAt('/admin/clases?month=2026-09-01')

    const month = await screen.findByRole('region', { name: copy.month.title('2026-09-01') })
    const independence = await within(month).findByRole('button', {
      name: copy.month.cell('viernes', '2026-09-18', 0, 0, 0, 'Día de la Independencia'),
    })
    expect(independence).toHaveClass('month__day--holiday')
    // Not by its red alone: the day's name and its title name it; the cell has room for the number only (#457).
    expect(independence).toHaveAttribute('title', 'Día de la Independencia')
    expect(independence).not.toHaveTextContent('Independencia')
    for (const cell of within(month).getAllByRole('button', { name: /^(lunes|martes|miércoles|jueves|viernes|sábado|domingo) / })) {
      expect(cell.textContent).not.toMatch(/Día|Glorias|Independencia/)
    }
    expect(within(month).getByRole('button', { name: copy.month.cell('jueves', '2026-09-17', 0, 0, 0) })).not.toHaveClass(
      'month__day--holiday',
    )

    // The week names it in its day's heading.
    await userEvent.click(within(month).getByRole('button', { name: copy.view.week }))
    const week = await screen.findByRole('region', { name: copy.week.title })
    expect(
      await within(week).findByRole('heading', { name: copy.days.holiday(weekdayDay(toDate('2026-09-19')), 'Día de las Glorias del Ejército') }),
    ).toBeInTheDocument()
  })

  it('shows the month in place of the day on a phone, a day tapped leaving it (#426)', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T15:00:00Z'))
    wide(false)
    stubApi({ week: [] })
    const router = renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    await userEvent.click(within(today).getByRole('button', { name: copy.view.month }))
    const month = await screen.findByRole('region', { name: copy.month.title('2026-11-01') })
    expect(screen.queryByRole('region', { name: copy.today.title })).not.toBeInTheDocument()
    await userEvent.click(await within(month).findByRole('button', { name: copy.month.cell('lunes', '2026-11-02', 0, 0, 0) }))
    expect(router.state.location.search).toEqual({ day: '2026-11-02' })
    expect(await screen.findByRole('region', { name: weekdayDay(toDate('2026-11-02')) })).toBeInTheDocument()

    // Back is the month again.
    act(() => router.history.back())
    expect(await screen.findByRole('region', { name: copy.month.title('2026-11-01') })).toBeInTheDocument()
  })

  // At 22:00 on the year's last day in Santiago it is already next year in UTC (#330).
  it.each([
    ['on the year’s last evening, next year already in UTC', '2027-01-01T01:00:00Z', 2026, 12],
    ['at midday', '2026-11-11T15:00:00Z', 2026, 11],
  ])('totals the gym’s hours per tag for a month or a year, %s', async (_, now, year, month) => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(now))
    const calls = stubApi()
    renderAt('/admin/clases')

    const card = within(await screen.findByRole('region', { name: es.tagHours.gym }))
    // Once the gym's timezone is in.
    await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain(`/api/class-tags/hours?year=${year}&month=${month}`))
    expect(await card.findByText('4,5 h · 3 clases')).toBeInTheDocument()

    await userEvent.click(card.getByRole('button', { name: es.tagHours.previous(es.tagHours.month) }))
    const before = month === 1 ? `year=${year - 1}&month=12` : `year=${year}&month=${month - 1}`
    expect(calls.some((c) => c.path === `/api/class-tags/hours?${before}`)).toBe(true)
    await userEvent.click(card.getByRole('button', { name: es.tagHours.year }))
    expect(card.getByText(String(month === 1 ? year - 1 : year))).toBeInTheDocument()
    expect(card.queryByText(es.tagHours.noDuration(1))).not.toBeInTheDocument()
  })

  it('says which classes have no duration and add no hours, each leading to its page', async () => {
    // November's hours, in November in UTC too: the card opens on the gym's month (#330).
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-11T15:00:00Z'))
    stubApi({
      hours: {
        ...hoursFor('2026-11-01', '2026-11-30', 0),
        tags: [{ tag_id: 'guard', name: 'Guardia', archived: false, classes: 1, minutes: 0 }],
        no_duration_classes: 1,
        no_duration: [{ session_id: EVENING.id, starts_at: EVENING.starts_at, class_type_name: 'Fundamentos' }],
      },
    })
    const router = renderAt('/admin/clases')

    const card = within(await screen.findByRole('region', { name: es.tagHours.gym }))
    expect(await card.findByText('1 clase sin duración, no suma horas')).toBeInTheDocument()
    await userEvent.click(card.getByRole('link', { name: '9 nov · Fundamentos' }))
    expect(router.state.location.pathname).toBe('/admin/clases/s-evening')
  })
})
