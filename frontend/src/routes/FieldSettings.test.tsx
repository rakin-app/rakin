import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FieldDefinition } from '../api/customFields'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.fields
const form = copy.form

const BELT: FieldDefinition = {
  key: 'talla',
  label: 'Talla de kimono',
  type: 'enum',
  options: ['A1', 'A2', 'A3'],
  sensitive: false,
  visible_to: 'staff',
  archived: false,
}
const HEALTH: FieldDefinition = {
  key: 'salud',
  label: 'Condición médica',
  type: 'text',
  options: null,
  sensitive: true,
  visible_to: 'admin',
  archived: false,
}
const OLD: FieldDefinition = {
  key: 'apodo',
  label: 'Apodo',
  type: 'text',
  options: null,
  sensitive: false,
  visible_to: 'staff',
  archived: true,
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({ role = 'owner', save }: { role?: 'owner' | 'admin' | 'coach'; save?: Answer } = {}) {
  const calls: Call[] = []
  let list: FieldDefinition[] = [BELT, HEALTH, OLD]
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw
      calls.push({ method, path: url.pathname, body })
      const answer = route(url.pathname, method, body as Record<string, unknown>)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: Record<string, unknown>): Answer {
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/custom-fields' && method === 'GET') return { body: list }
    if (path === '/api/custom-fields' && method === 'POST') {
      if (save) return save
      const created = { key: 'nuevo', options: null, sensitive: false, visible_to: 'staff', archived: false, ...body }
      list = [...list, created as FieldDefinition]
      return { status: 201, body: created }
    }
    if (path === '/api/custom-fields/order' && method === 'PUT') {
      if (save) return save
      const keys = body.keys as string[]
      list = keys.map((key) => list.find((f) => f.key === key)!)
      return { body: list }
    }
    const found = list.find((f) => path === `/api/custom-fields/${f.key}`)
    if (found && method === 'PATCH') {
      if (save) return save
      const updated = { ...found, ...body }
      list = list.map((f) => (f.key === found.key ? updated : f))
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

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Campos', () => {
  it('is hidden from coaches, who never ask the API for it', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/campos')

    expect(await screen.findByText(es.admin.settings.adminsOnly)).toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/custom-fields'))).toEqual([])
  })

  it('lists the fields in order, with their type, options and who sees them, for the owner', async () => {
    stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    const items = within(section).getAllByRole('listitem')
    expect(items.map((item) => within(item).getByText((_, el) => el?.className === 'settings__plan-name').textContent)).toEqual([
      'Talla de kimono',
      `Condición médica${copy.sensitive}`,
      `Apodo${copy.archived}`,
    ])
    expect(within(items[0]!).getByText(copy.row(copy.row(copy.types.enum, 'A1, A2, A3'), copy.visibleTo.staff))).toBeInTheDocument()
    expect(within(items[1]!).getByText(copy.row(copy.types.text, copy.visibleTo.admin))).toBeInTheDocument()
    expect(within(items[0]!).getByRole('button', { name: copy.up('Talla de kimono') })).toBeDisabled()
    expect(within(items[2]!).getByRole('button', { name: copy.down('Apodo') })).toBeDisabled()
    expect(within(items[2]!).getByRole('button', { name: copy.restore })).toBeInTheDocument()
  })

  it('shows an admin neither who sees a field nor the controls that set it', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    expect(within(section).getAllByText(copy.types.text, { selector: '.settings__detail' })).toHaveLength(2)
    expect(within(section).queryByText(copy.visibleTo.admin, { exact: false })).not.toBeInTheDocument()

    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    expect(within(create).queryByLabelText(form.sensitive)).not.toBeInTheDocument()
    expect(within(create).queryByLabelText(form.visibleTo)).not.toBeInTheDocument()
  })

  it('creates an enum field with its options, one per line; an admin sends no visibility', async () => {
    const calls = stubApi({ role: 'admin' })
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.label), 'Turno')
    await userEvent.selectOptions(within(create).getByLabelText(form.type), 'enum')
    await userEvent.type(within(create).getByLabelText(form.options), 'Mañana{enter}{enter} Tarde {enter}Noche')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(copy.created('Turno'))
    expect(writes(calls)).toEqual([
      { method: 'POST', path: '/api/custom-fields', body: { label: 'Turno', type: 'enum', options: ['Mañana', 'Tarde', 'Noche'] } },
    ])
  })

  it('lets the owner mark a new field sensitive, which narrows it to the owner', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.label), 'RUT apoderado')
    expect(within(create).getByLabelText(form.visibleTo)).toHaveValue('staff')
    await userEvent.click(within(create).getByLabelText(form.sensitive))
    expect(within(create).getByLabelText(form.visibleTo)).toHaveValue('owner')
    await userEvent.selectOptions(within(create).getByLabelText(form.visibleTo), 'admin')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(copy.created('RUT apoderado'))
    expect(writes(calls)).toEqual([
      {
        method: 'POST',
        path: '/api/custom-fields',
        body: { label: 'RUT apoderado', type: 'text', sensitive: true, visible_to: 'admin' },
      },
    ])
  })

  it('edits a field, sending only what changed, with its type fixed', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    const [belt] = within(section).getAllByRole('listitem')
    await userEvent.click(within(belt!).getByRole('button', { name: copy.edit }))
    const edit = within(section).getByRole('form', { name: form.edit('Talla de kimono') })
    expect(within(edit).getByLabelText(form.type)).toBeDisabled()
    const options = within(edit).getByLabelText(form.options)
    expect(options).toHaveValue('A1\nA2\nA3')
    await userEvent.type(options, '{enter}A4')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(copy.saved('Talla de kimono'))
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/custom-fields/talla', body: { options: ['A1', 'A2', 'A3', 'A4'] } },
    ])
  })

  it('closes an edit that changed nothing but whitespace without asking the API', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    const [, health] = within(section).getAllByRole('listitem')
    await userEvent.click(within(health!).getByRole('button', { name: copy.edit }))
    const edit = within(section).getByRole('form', { name: form.edit('Condición médica') })
    // Whitespace around the label is trimmed by the API, so it is no change.
    await userEvent.type(within(edit).getByLabelText(form.label), '  ')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(within(section).queryByRole('form')).not.toBeInTheDocument()
    expect(writes(calls)).toEqual([])
  })

  it('says which options are in use when removing them is refused', async () => {
    stubApi({ save: { status: 409, body: { detail: { code: 'option_in_use', options: { A1: 3, A2: 1 } } } } })
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    const [belt] = within(section).getAllByRole('listitem')
    await userEvent.click(within(belt!).getByRole('button', { name: copy.edit }))
    const edit = within(section).getByRole('form', { name: form.edit('Talla de kimono') })
    const options = within(edit).getByLabelText(form.options)
    await userEvent.clear(options)
    await userEvent.type(options, 'A3')
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(edit).findByRole('alert')).toHaveTextContent(form.inUse({ A1: 3, A2: 1 }))
  })

  it("puts the API's refusals under the label and the options", async () => {
    stubApi({
      save: {
        status: 422,
        body: {
          detail: [
            { loc: ['body', 'label'], type: 'string_too_short', msg: '' },
            { loc: ['body', 'options'], type: 'too_short', msg: '' },
          ],
        },
      },
    })
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', { name: form.create })
    await userEvent.selectOptions(within(create).getByLabelText(form.type), 'enum')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(create).findByText(form.invalid)).toBeInTheDocument()
    expect(within(create).getByLabelText(form.label)).toHaveAccessibleDescription(es.admin.settings.invalid.required)
    expect(within(create).getByLabelText(form.options)).toHaveAccessibleDescription(
      `${form.optionsHint} ${form.optionsRequired}`,
    )
  })

  it('moves a field down, sending every key in the new order', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.down('Talla de kimono') }))

    expect(await within(section).findByRole('button', { name: copy.up('Talla de kimono') })).toBeEnabled()
    expect(writes(calls)).toEqual([
      { method: 'PUT', path: '/api/custom-fields/order', body: { keys: ['salud', 'talla', 'apodo'] } },
    ])
    const labels = within(section)
      .getAllByRole('listitem')
      .map((item) => item.querySelector('.settings__plan-name')?.firstChild?.textContent)
    expect(labels).toEqual(['Condición médica', 'Talla de kimono', 'Apodo'])
  })

  it('says so when a reorder is refused', async () => {
    stubApi({ save: { status: 422, body: { detail: 'keys must list every field once' } } })
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.up('Apodo') }))

    expect(await within(section).findByText(copy.reorderFailed)).toBeInTheDocument()
  })

  it('archives a field and restores it', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/campos')

    const section = await screen.findByRole('region', { name: copy.title })
    const [belt] = within(section).getAllByRole('listitem')
    await userEvent.click(within(belt!).getByRole('button', { name: copy.archive }))
    expect(await within(section).findByRole('status')).toHaveTextContent(copy.archivedDone('Talla de kimono'))

    const [archived] = within(section).getAllByRole('listitem')
    await userEvent.click(await within(archived!).findByRole('button', { name: copy.restore }))
    expect(await within(section).findByText(copy.restored('Talla de kimono'))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/custom-fields/talla', body: { archived: true } },
      { method: 'PATCH', path: '/api/custom-fields/talla', body: { archived: false } },
    ])
  })
})
