import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ClassTag } from '../api/classTags'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.tags
const form = copy.form

const tag = (id: string, name: string, archived = false): ClassTag => ({
  id,
  name,
  archived,
  created_at: '2026-11-11T12:00:00Z',
})

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ role = 'owner', save }: { role?: string | null; save?: Answer } = {}) {
  const calls: Call[] = []
  let tags = [tag('strength', 'Fuerza'), tag('guard', 'Pasaje de guardia'), tag('old', 'Yoga', true)]
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
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/class-tags' && method === 'GET') return { body: tags }
    if (path === '/api/class-tags' && method === 'POST') {
      if (save) return save
      const created = tag('nuevo', String(body['name']).trim())
      tags = [...tags, created]
      return { status: 201, body: created }
    }
    const found = tags.find((each) => path === `/api/class-tags/${each.id}`)
    if (found && method === 'PATCH') {
      if (save) return save
      const updated = { ...found, ...body }
      tags = tags.map((each) => (each.id === found.id ? updated : each))
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
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

async function open(name: string) {
  const section = await screen.findByRole('region', { name: copy.title })
  const row = within(section).getByText(name).closest('li')!
  await userEvent.click(within(row).getByRole('button', { name: new RegExp(`^${name}`) }))
}

describe('Ajustes: Etiquetas', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the tags by name, archived ones marked and last', async () => {
    stubApi()
    renderAt('/admin/ajustes/etiquetas')

    const section = await screen.findByRole('region', { name: copy.title })
    const rows = within(section).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByText(/./, { selector: '.list-row__title' }).textContent)).toEqual([
      'Fuerza',
      'Pasaje de guardia',
      `Yoga${copy.archived}`,
    ])
  })

  it('creates a tag', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/etiquetas')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.name), 'Fuerza de dedos')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.created('Fuerza de dedos'))
    expect(writes(calls)).toEqual([{ method: 'POST', path: '/api/class-tags', body: { name: 'Fuerza de dedos' } }])
  })

  it('renames a tag, and says so when the name is taken', async () => {
    const calls = stubApi({ save: { status: 409, body: { detail: 'taken' } } })
    renderAt('/admin/ajustes/etiquetas')

    await open('Fuerza')
    const edit = screen.getByRole('form', { name: form.edit('Fuerza') })
    const name = within(edit).getByLabelText(form.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'pasaje de guardia')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(edit).findByText(form.taken)).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/class-tags/strength', body: { name: 'pasaje de guardia' } },
    ])
  })

  it('archives a tag and reactivates an archived one', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/etiquetas')

    await open('Fuerza')
    const edit = screen.getByRole('form', { name: form.edit('Fuerza') })
    expect(within(edit).getByText(copy.archiveHint)).toBeInTheDocument()
    await userEvent.click(within(edit).getByRole('button', { name: copy.archive }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.archivedDone('Fuerza'))

    await open('Yoga')
    await userEvent.click(
      within(screen.getByRole('form', { name: form.edit('Yoga') })).getByRole('button', { name: copy.restore }),
    )
    expect(await screen.findByRole('status')).toHaveTextContent(copy.restored('Yoga'))
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/class-tags/strength', body: { archived: true } },
      { method: 'PATCH', path: '/api/class-tags/old', body: { archived: false } },
    ])
  })

  it('is the owner’s or an admin’s', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/etiquetas')

    expect(await screen.findByText(es.admin.settings.adminsOnly)).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/class-tags')).toBe(false)
  })
})
