import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import type { Requirement } from '../api/requirements'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.settings.requirements
const form = copy.form
const PATH = '/admin/ajustes/requisitos'

const WAIVER: Requirement = {
  id: 'r-waiver',
  name: 'Deslinde firmado',
  valid_months: null,
  sensitive: false,
  visible_to: 'staff',
  active: true,
}
const MEDICAL: Requirement = {
  id: 'r-medical',
  name: 'Certificado médico',
  valid_months: 12,
  sensitive: true,
  visible_to: 'owner',
  active: true,
}

type Call = { method: string; path: string; body: unknown }

function stubApi({ role = 'owner', initial = [WAIVER, MEDICAL] }: { role?: 'owner' | 'admin'; initial?: Requirement[] } = {}) {
  const calls: Call[] = []
  let list = initial
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Record<string, unknown>
      calls.push({ method, path: url.pathname, body })
      const path = url.pathname
      if (path === '/api/me/role') return Response.json({ role })
      if (path === '/api/requirements' && method === 'GET') return Response.json(list)
      if (path === '/api/requirements' && method === 'POST') {
        const created = { id: 'r-new', sensitive: false, visible_to: 'staff', active: true, ...body } as Requirement
        list = [...list, created]
        return Response.json(created, { status: 201 })
      }
      if (path === '/api/requirements/order' && method === 'PUT') {
        list = (body.ids as string[]).map((id) => list.find((r) => r.id === id)!)
        return Response.json(list)
      }
      const found = list.find((r) => path === `/api/requirements/${r.id}`)
      if (found && method === 'PATCH') {
        const updated = { ...found, ...body }
        list = list.map((r) => (r.id === found.id ? updated : r))
        return Response.json(updated)
      }
      return Response.json({ detail: 'Not Found' }, { status: 404 })
    }),
  )
  return calls
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET')
const section = () => screen.findByRole('region', { name: copy.title })

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Requisitos (#349)', () => {
  it('suggests some when the gym has none', async () => {
    stubApi({ initial: [] })
    renderAt(PATH)

    const list = await section()
    expect(await within(list).findByText(copy.empty)).toBeInTheDocument()
    for (const example of copy.examples) expect(within(list).getByText(example)).toBeInTheDocument()
  })

  it('lists each with how long it lasts and, for the owner, who sees it', async () => {
    stubApi()
    renderAt(PATH)

    const list = await section()
    expect(await within(list).findByText(copy.row(copy.once, copy.visibleTo.staff))).toBeInTheDocument()
    expect(within(list).getByText(copy.row(copy.months(12), copy.visibleTo.owner))).toBeInTheDocument()
    expect(within(list).getByText(copy.sensitive)).toBeInTheDocument()
  })

  it('adds one that lasts a number of months', async () => {
    const calls = stubApi()
    renderAt(PATH)

    const list = await section()
    await userEvent.click(await within(list).findByRole('button', { name: copy.add }))
    const create = within(list).getByRole('form', { name: form.create })
    await userEvent.type(within(create).getByLabelText(form.name), 'Prueba de natación')
    await userEvent.type(within(create).getByLabelText(form.validMonths), '24')
    await userEvent.click(within(create).getByRole('button', { name: form.submit }))

    expect(await within(list).findByText(copy.created('Prueba de natación'))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      {
        method: 'POST',
        path: '/api/requirements',
        body: { name: 'Prueba de natación', valid_months: 24, sensitive: false, visible_to: 'staff' },
      },
    ])
  })

  it('makes one done once by clearing its months, and never sends who sees it as an admin', async () => {
    const calls = stubApi({ role: 'admin', initial: [{ ...WAIVER, valid_months: 6 }] })
    renderAt(PATH)

    const list = await section()
    await userEvent.click(await within(list).findByRole('button', { name: /^Deslinde firmado/ }))
    const edit = within(list).getByRole('form', { name: form.edit('Deslinde firmado') })
    expect(within(edit).queryByLabelText(form.visibleTo)).not.toBeInTheDocument()
    await userEvent.clear(within(edit).getByLabelText(form.validMonths))
    await userEvent.click(within(edit).getByRole('button', { name: form.submit }))

    expect(await within(list).findByText(copy.saved('Deslinde firmado'))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'PATCH', path: '/api/requirements/r-waiver', body: { valid_months: null } },
    ])
  })

  it('reorders and deactivates', async () => {
    const calls = stubApi()
    renderAt(PATH)

    const list = await section()
    await userEvent.click(await within(list).findByRole('button', { name: copy.down('Deslinde firmado') }))
    await userEvent.click(within(list).getByRole('button', { name: /^Certificado médico/ }))
    const edit = within(list).getByRole('form', { name: form.edit('Certificado médico') })
    await userEvent.click(within(edit).getByRole('button', { name: copy.archive }))

    expect(await within(list).findByText(copy.archivedDone('Certificado médico'))).toBeInTheDocument()
    expect(writes(calls)).toEqual([
      { method: 'PUT', path: '/api/requirements/order', body: { ids: ['r-medical', 'r-waiver'] } },
      { method: 'PATCH', path: '/api/requirements/r-medical', body: { active: false } },
    ])
    expect(within(list).getByText(copy.archived)).toBeInTheDocument()
  })
})
