import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { RosterMember } from '../api/attendance'
import type { ClassTag, TagHours } from '../api/classTags'
import type { ClassSession, ClassType, SessionDay } from '../api/sessions'
import { App } from '../App'
import { isoDay, shiftDay, toDate, weekdayDay } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { mondayOf } from './Classes'

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
})

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
}

function stubApi({
  role = 'coach',
  classTypes = [FUNDAMENTALS, ADVANCED, KIDS],
  sessions = [MORNING, EVENING],
  start,
  update,
  week,
  roster = [],
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
      const answer = route(url.pathname, method, body, url.searchParams.get('date'))
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: unknown, date: string | null): Answer {
    // The class's own coach, unless told otherwise.
    if (path === '/api/me/role') return { body: { role, person_id: 'coach' } }
    if (path === '/api/class-types') return { body: classTypes }
    if (path === '/api/sessions' && method === 'GET' && week) {
      const on = date ?? isoDay(new Date().toISOString(), 'America/Santiago')
      return { body: { ...day, date: on, sessions: week.filter((s) => isoDay(s.starts_at, 'America/Santiago') === on) } }
    }
    if (path === '/api/sessions' && method === 'GET') return { body: day }
    if (path === '/api/sessions' && method === 'POST') {
      if (start) return start
      const type = classTypes.find((c) => c.id === (body as { class_type_id: string }).class_type_id)!
      const created: ClassSession = {
        ...EVENING,
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
    if (path === '/api/class-tags/hours') return { body: hoursFor('2026-11-01', '2026-11-30', 270) }
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

afterEach(() => {
  vi.unstubAllGlobals()
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
    const days = within(today).getByRole('navigation', { name: copy.days.label })
    await userEvent.click(within(days).getByRole('button', { name: copy.days.next }))
    const next = await screen.findByRole('region', { name: weekdayDay(toDate(tomorrow)) })
    expect(calls.map((c) => c.path)).toContain(`/api/sessions?date=${tomorrow}`)

    await userEvent.click(within(next).getByRole('button', { name: copy.days.today }))
    expect(await screen.findByRole('region', { name: copy.today.title })).toBeInTheDocument()
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

  it('says when there are no classes yet today', async () => {
    stubApi({ sessions: [] })
    renderAt('/admin/clases')

    const today = await screen.findByRole('region', { name: copy.today.title })
    expect(await within(today).findByText(copy.today.empty)).toBeInTheDocument()
  })

  it('starts a class of the type chosen and opens it', async () => {
    const calls = stubApi()
    const router = renderAt('/admin/clases')

    const form = await screen.findByRole('form', { name: copy.start.title })
    const select = within(form).getByLabelText(copy.start.classType)
    // By program: the select groups the class types under each.
    expect(within(select).getAllByRole('group').map((g) => g.getAttribute('label'))).toEqual(['Adultos', 'Kids'])
    await userEvent.selectOptions(select, 'Avanzado')
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Avanzado' })).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/admin/clases/s-new')
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/sessions', body: { class_type_id: 'avanzado' } },
    ])
  })

  it('says so when a class cannot be started', async () => {
    stubApi({ start: { status: 422, body: { detail: [] } } })
    renderAt('/admin/clases')

    const form = await screen.findByRole('form', { name: copy.start.title })
    await userEvent.click(within(form).getByRole('button', { name: copy.start.submit }))

    expect(await within(form).findByRole('alert')).toHaveTextContent(copy.start.failed)
  })

  it('says when the gym has no class types to start', async () => {
    stubApi({ classTypes: [] })
    renderAt('/admin/clases')

    const start = await screen.findByRole('region', { name: copy.start.title })
    expect(await within(start).findByText(copy.start.noClassTypes)).toBeInTheDocument()
    expect(within(start).queryByRole('button')).not.toBeInTheDocument()
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
})

describe('Clases on a desktop', () => {
  const wide = (matches: boolean) =>
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
    )

  it('finds the Monday of the week', () => {
    expect(mondayOf('2026-11-10')).toBe('2026-11-09')
    expect(mondayOf('2026-11-09')).toBe('2026-11-09')
    expect(mondayOf('2026-11-15')).toBe('2026-11-09')
  })

  it('shows the week beside the day, and who came to the class picked in it', async () => {
    wide(true)
    const today = isoDay(new Date().toISOString(), 'America/Santiago')
    const monday = mondayOf(today)
    const days = Array.from({ length: 7 }, (_, i) => shiftDay(monday, i))
    // Today's at midnight has begun, whatever the hour the test runs at.
    const begun: ClassSession = { ...EVENING, id: 's-begun', starts_at: onDay(today, '00:00'), present: 2 }
    // Yet to start, unless the test runs in the week's last minute.
    const sunday: ClassSession = { ...MORNING, id: 's-sunday', starts_at: onDay(days[6]!, '23:59') }
    const calls = stubApi({
      week: [begun, sunday],
      roster: [onRoster('ana', 'Ana Soto', true), onRoster('beto', 'Beto Díaz', true, false), onRoster('caro', 'Caro Vera', false)],
    })
    renderAt('/admin/clases')

    const week = await screen.findByRole('region', { name: copy.week.title })
    for (const day of days) {
      expect(within(week).getByRole('heading', { name: weekdayDay(toDate(day)) })).toBeInTheDocument()
      const asked = day === today ? '/api/sessions' : `/api/sessions?date=${day}`
      // Once the gym's timezone is in: a device in another zone has its own today until then.
      await vi.waitFor(() => expect(calls.map((c) => c.path)).toContain(asked))
    }

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

  it('never asks for the week on a phone', async () => {
    wide(false)
    const calls = stubApi()
    renderAt('/admin/clases')

    await screen.findByRole('region', { name: copy.today.title })
    expect(screen.queryByRole('region', { name: copy.week.title })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/sessions?date='))).toEqual([])
  })

  it('totals the gym’s hours per tag for a month or a year', async () => {
    const calls = stubApi()
    renderAt('/admin/clases')

    const card = within(await screen.findByRole('region', { name: es.tagHours.gym }))
    expect(await card.findByText('4,5 h · 3 clases')).toBeInTheDocument()
    const today = isoDay(new Date().toISOString(), 'America/Santiago')
    const month = Number(today.slice(5, 7))
    const year = Number(today.slice(0, 4))
    expect(calls.some((c) => c.path === `/api/class-tags/hours?year=${year}&month=${month}`)).toBe(true)

    await userEvent.click(card.getByRole('button', { name: es.tagHours.previous(es.tagHours.month) }))
    const before = month === 1 ? `year=${year - 1}&month=12` : `year=${year}&month=${month - 1}`
    expect(calls.some((c) => c.path === `/api/class-tags/hours?${before}`)).toBe(true)
    await userEvent.click(card.getByRole('button', { name: es.tagHours.year }))
    expect(card.getByText(String(month === 1 ? year - 1 : year))).toBeInTheDocument()
  })
})
