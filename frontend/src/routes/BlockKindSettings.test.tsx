import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../api/blockKinds'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.blocks
const form = copy.form

const kind = (id: string, name: string, position: number, extra: Partial<BlockKind> = {}): BlockKind => ({
  id,
  name,
  is_sparring: false,
  position,
  archived: false,
  created_at: '2026-11-10T12:00:00Z',
  ...extra,
})

const DEFAULTS = [
  kind('warmup', 'Calentamiento', 0),
  kind('technique', 'Técnica', 1),
  kind('sparring', 'Sparring', 2, { is_sparring: true }),
  kind('old', 'Yoga', 3, { archived: true }),
]

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ role = 'owner', save, remove }: { role?: string; save?: Answer; remove?: Answer } = {}) {
  const calls: Call[] = []
  let kinds = [...DEFAULTS]
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
    if (path === '/api/block-kinds' && method === 'GET') return { body: kinds }
    if (path === '/api/block-kinds' && method === 'POST') {
      if (save) return save
      const created = kind('nuevo', String(body['name']), kinds.length, { is_sparring: Boolean(body['is_sparring']) })
      kinds = [...kinds.filter((k) => !k.archived), created, ...kinds.filter((k) => k.archived)]
      return { status: 201, body: created }
    }
    if (path === '/api/block-kinds/order' && method === 'PUT') {
      const ids = body['ids'] as string[]
      kinds = ids.map((id, position) => ({ ...kinds.find((k) => k.id === id)!, position }))
      return { body: kinds }
    }
    const found = kinds.find((k) => path === `/api/block-kinds/${k.id}`)
    if (found && method === 'PATCH') {
      if (save) return save
      const updated = { ...found, ...body }
      kinds = kinds.map((k) => (k.id === found.id ? updated : k))
      return { body: updated }
    }
    if (found && method === 'DELETE') {
      if (remove) return remove
      kinds = kinds.filter((k) => k.id !== found.id)
      return { status: 204 }
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

async function row(name: string) {
  const section = await screen.findByRole('region', { name: copy.title })
  return within(section).getByText(name).closest('li')!
}

/** Opens a kind's edit form: its row is the button (#177). */
async function open(name: string) {
  await userEvent.click(within(await row(name)).getByRole('button', { name: new RegExp(`^${name}`) }))
}

const IN_USE = { status: 409, body: { detail: { code: 'block_kind_in_use', blocks: 3 } } }

describe('Ajustes: Bloques', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists the kinds in order, sparring and archived ones tagged', async () => {
    stubApi()
    renderAt('/admin/ajustes/bloques')

    const section = await screen.findByRole('region', { name: copy.title })
    const rows = within(section).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByText(/./, { selector: '.list-row__title' }).textContent)).toEqual([
      'Calentamiento',
      'Técnica',
      `Sparring${copy.sparring}`,
      `Yoga${copy.archived}`,
    ])
    expect(within(rows[0]!).getByRole('button', { name: copy.up('Calentamiento') })).toBeDisabled()
    expect(within(rows[2]!).getByRole('button', { name: copy.down('Sparring') })).toBeDisabled()
    // An archived kind keeps its place at the end, and the row holds no Editar or Desactivar (#177).
    expect(within(rows[3]!).queryByRole('button', { name: copy.up('Yoga') })).not.toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: copy.edit })).not.toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: copy.archive })).not.toBeInTheDocument()
    await open('Yoga')
    const edit = screen.getByRole('form', { name: form.edit('Yoga') })
    expect(within(edit).getByRole('button', { name: copy.restore })).toBeInTheDocument()
  })

  it('creates a sparring kind', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/bloques')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.name), 'Lucha de pie')
    await userEvent.click(within(create).getByRole('checkbox', { name: form.sparring }))
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.created('Lucha de pie'))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Lucha de pie', is_sparring: true })
    expect(await row('Lucha de pie')).toHaveTextContent(copy.sparring)
  })

  it('renames a kind, sending only the name, and says when the name is taken', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/bloques')

    await open('Técnica')
    const edit = screen.getByRole('form', { name: form.edit('Técnica') })
    const name = within(edit).getByLabelText(form.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'Técnica de guardia')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.saved('Técnica de guardia'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => [c.path, c.body])).toEqual([
      ['/api/block-kinds/technique', { name: 'Técnica de guardia' }],
    ])
  })

  it('refuses inline a name taken, and a sparring change on a kind in use', async () => {
    stubApi({ save: { status: 409, body: { detail: 'the gym already has a block kind by this name' } } })
    renderAt('/admin/ajustes/bloques')

    await open('Técnica')
    let edit = screen.getByRole('form', { name: form.edit('Técnica') })
    await userEvent.clear(within(edit).getByLabelText(form.name))
    await userEvent.type(within(edit).getByLabelText(form.name), 'Sparring')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))
    expect(await within(edit).findByText(form.taken)).toBeInTheDocument()
    vi.unstubAllGlobals()

    stubApi({ save: IN_USE })
    await userEvent.click(within(edit).getByRole('button', { name: form.cancel }))
    await open('Técnica')
    edit = screen.getByRole('form', { name: form.edit('Técnica') })
    await userEvent.click(within(edit).getByRole('checkbox', { name: form.sparring }))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))
    expect(await within(edit).findByRole('alert')).toHaveTextContent(form.sparringInUse(3))
  })

  it('moves a kind up, sending every kind in the new order', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/bloques')

    await userEvent.click(await screen.findByRole('button', { name: copy.up('Sparring') }))

    const put = await vi.waitFor(() => {
      const found = calls.find((c) => c.method === 'PUT')
      expect(found).toBeDefined()
      return found!
    })
    expect(put).toEqual({
      method: 'PUT',
      path: '/api/block-kinds/order',
      body: { ids: ['warmup', 'sparring', 'technique', 'old'] },
    })
    const section = await screen.findByRole('region', { name: copy.title })
    await vi.waitFor(() =>
      expect(within(section).getAllByRole('listitem')[1]).toHaveTextContent('Sparring'),
    )
  })

  it('deletes an unused kind', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/bloques')

    await open('Calentamiento')
    const edit = screen.getByRole('form', { name: form.edit('Calentamiento') })
    await userEvent.click(within(edit).getByRole('button', { name: copy.delete }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.deleted('Calentamiento'))
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api/block-kinds/warmup'])
    expect(screen.queryByText('Calentamiento')).not.toBeInTheDocument()
  })

  it('tells to archive a kind in use instead, and archives it', async () => {
    const calls = stubApi({ remove: IN_USE })
    renderAt('/admin/ajustes/bloques')

    await open('Técnica')
    const edit = screen.getByRole('form', { name: form.edit('Técnica') })
    await userEvent.click(within(edit).getByRole('button', { name: copy.delete }))
    expect(await within(edit).findByRole('alert')).toHaveTextContent(copy.inUse(3))

    await userEvent.click(within(edit).getByRole('button', { name: copy.archive }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.archivedDone('Técnica'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ archived: true }])
  })

  it('is for owners and admins', async () => {
    stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/bloques')
    expect(await screen.findByText(es.admin.settings.adminsOnly)).toBeInTheDocument()
  })
})
