import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Program } from '../api/people'
import type { ClassType } from '../api/sessions'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const settings = es.admin.settings
const copy = settings.programs
const form = copy.classTypeForm

const ADULTS: Program = { id: 'adultos', name: 'Adultos', active: true }
const KIDS: Program = { id: 'kids', name: 'Kids', active: true }
const OLD: Program = { id: 'old', name: 'Competición', active: false }

const at = { active: true, created_at: '2026-10-01T12:00:00Z', kind: 'class', counts_as_class: true } as const
const FUNDAMENTOS: ClassType = {
  ...at,
  id: 'fund',
  name: 'Fundamentos',
  program_id: 'adultos',
  program_name: 'Adultos',
  credit_cost: 1,
}
const OPEN_MAT: ClassType = {
  ...at,
  id: 'open',
  name: 'Open mat',
  program_id: 'adultos',
  program_name: 'Adultos',
  credit_cost: 0,
  kind: 'open_mat',
  counts_as_class: false,
}
const SPARRING: ClassType = {
  ...at,
  active: false,
  id: 'spar',
  name: 'Sparring',
  program_id: 'old',
  program_name: 'Competición',
  credit_cost: 2,
}

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

function stubApi({
  role = 'owner',
  saveProgram,
  saveClassType,
}: { role?: string; saveProgram?: Answer; saveClassType?: Answer } = {}) {
  const calls: Call[] = []
  let programs = [ADULTS, KIDS, OLD]
  let classTypes = [FUNDAMENTOS, OPEN_MAT, SPARRING]
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const raw = init?.body
      const body = (typeof raw === 'string' ? JSON.parse(raw) : raw) as Record<string, unknown>
      calls.push({ method, path: `${url.pathname}${url.search}`, body })
      const answer = route(url.pathname, method, body)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(path: string, method: string, body: Record<string, unknown>): Answer {
    if (path === '/api/me/role') return { body: { role } }
    if (path === '/api/programs' && method === 'GET') return { body: programs }
    if (path === '/api/programs' && method === 'POST') {
      if (saveProgram) return saveProgram
      const created = { id: 'nuevo', active: true, ...body } as Program
      programs = [...programs, created]
      return { status: 201, body: created }
    }
    const program = programs.find((p) => path === `/api/programs/${p.id}`)
    if (program && method === 'PATCH') {
      if (saveProgram) return saveProgram
      const updated = { ...program, ...body }
      programs = programs.map((p) => (p.id === program.id ? updated : p))
      return { body: updated }
    }
    if (path === '/api/class-types' && method === 'GET') return { body: classTypes }
    if (path === '/api/class-types' && method === 'POST') {
      if (saveClassType) return saveClassType
      const created = {
        ...at,
        id: 'nueva',
        program_name: '',
        ...body,
      } as ClassType
      classTypes = [...classTypes, created]
      return { status: 201, body: created }
    }
    const classType = classTypes.find((c) => path === `/api/class-types/${c.id}`)
    if (classType && method === 'PATCH') {
      if (saveClassType) return saveClassType
      const updated = { ...classType, ...body }
      classTypes = classTypes.map((c) => (c.id === classType.id ? updated : c))
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

async function programCard(name: string) {
  const section = await screen.findByRole('region', { name: copy.title })
  const heading = await within(section).findByRole('heading', {
    name: new RegExp(`^${name}`),
  })
  return heading.closest('li')!
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Ajustes: Programas y clases', () => {
  it('lists each program with its class types, their credit cost and whether they count as a class', async () => {
    stubApi()
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    const types = within(adults).getByRole('list', {
      name: copy.classTypesLabel('Adultos'),
    })
    const rows = within(types).getAllByRole('listitem')
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining(`Fundamentos${copy.credits(1)}`),
      expect.stringContaining(`Open mat${copy.openMat} · ${copy.credits(0)} · ${copy.notCounted}`),
    ])
    expect(within(await programCard('Kids')).getByText(copy.noClassTypes)).toBeInTheDocument()

    const old = await programCard('Competición')
    expect(old).toHaveTextContent(copy.inactive)
    // The program's own, and its inactive class type's.
    expect(within(old).getAllByRole('button', { name: copy.reactivate })).toHaveLength(2)
    expect(within(old).getByText('Sparring').closest('li')).toHaveTextContent(copy.inactive)
    // A deactivated program takes no new class types.
    expect(within(old).queryByRole('button', { name: copy.addClassType })).not.toBeInTheDocument()
  })

  it('creates a program', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const section = await screen.findByRole('region', { name: copy.title })
    await userEvent.click(within(section).getByRole('button', { name: copy.add }))
    const create = within(section).getByRole('form', {
      name: copy.programForm.create,
    })
    await userEvent.type(within(create).getByLabelText(copy.programForm.name), 'Competición kids')
    await userEvent.click(within(create).getByRole('button', { name: copy.submit }))

    expect(await within(section).findByRole('status')).toHaveTextContent(copy.programCreated('Competición kids'))
    expect(await programCard('Competición kids')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/programs',
        body: { name: 'Competición kids' },
      },
    ])
  })

  it('shows a name already taken under the name', async () => {
    stubApi({
      saveProgram: {
        status: 409,
        body: { detail: 'the gym already has a program by this name' },
      },
    })
    renderAt('/admin/ajustes/programas')

    const kids = await programCard('Kids')
    await userEvent.click(within(kids).getByRole('button', { name: copy.rename }))
    const rename = within(kids).getByRole('form', {
      name: copy.programForm.rename('Kids'),
    })
    const name = within(rename).getByLabelText(copy.programForm.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'adultos')
    await userEvent.click(within(rename).getByRole('button', { name: copy.submit }))

    expect(await within(rename).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(name).toHaveAccessibleDescription(copy.programTaken)
  })

  it('renames a program, and closes a rename that changed nothing without asking the API', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    let kids = await programCard('Kids')
    await userEvent.click(within(kids).getByRole('button', { name: copy.rename }))
    await userEvent.click(within(kids).getByRole('button', { name: copy.submit }))
    expect(within(kids).queryByRole('form')).not.toBeInTheDocument()

    await userEvent.click(within(kids).getByRole('button', { name: copy.rename }))
    const name = within(kids).getByLabelText(copy.programForm.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'Infantil')
    await userEvent.click(within(kids).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.programRenamed('Infantil'))
    kids = await programCard('Infantil')
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/programs/kids',
        body: { name: 'Infantil' },
      },
    ])
  })

  it('deactivates a program and reactivates it', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const kids = await programCard('Kids')
    await userEvent.click(within(kids).getByRole('button', { name: copy.deactivate }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.programDeactivated('Kids'))
    await userEvent.click(await within(kids).findByRole('button', { name: copy.reactivate }))
    expect(await screen.findByRole('status')).toHaveTextContent(copy.programReactivated('Kids'))

    expect(calls.filter((c) => c.method === 'PATCH').map((c) => [c.path, c.body])).toEqual([
      ['/api/programs/kids', { active: false }],
      ['/api/programs/kids', { active: true }],
    ])
  })

  it('creates a class type in a program, with its credit cost', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const kids = await programCard('Kids')
    await userEvent.click(within(kids).getByRole('button', { name: copy.addClassType }))
    const create = within(kids).getByRole('form', {
      name: form.create('Kids'),
    })
    // Active programs only, this one chosen.
    const program = within(create).getByLabelText(form.program)
    expect(program).toHaveValue('kids')
    expect(
      within(program)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Adultos', 'Kids'])
    await userEvent.type(within(create).getByLabelText(form.name), 'Kids 4-6')
    const cost = within(create).getByLabelText(form.creditCost)
    await userEvent.clear(cost)
    await userEvent.type(cost, '2')
    await userEvent.click(within(create).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.classTypeCreated('Kids 4-6'))
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      {
        method: 'POST',
        path: '/api/class-types',
        body: { name: 'Kids 4-6', program_id: 'kids', credit_cost: 2, kind: 'class', counts_as_class: true },
      },
    ])
  })

  it('creates an open mat, which does not count as a class unless told', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    await userEvent.click(within(adults).getByRole('button', { name: copy.addClassType }))
    const create = within(adults).getByRole('form', { name: form.create('Adultos') })
    const counts = within(create).getByRole('checkbox', { name: form.countsAsClass })
    expect(counts).toBeChecked()
    await userEvent.type(within(create).getByLabelText(form.name), 'Open mat sábado')
    await userEvent.selectOptions(within(create).getByLabelText(form.kind), form.kinds.open_mat)
    expect(counts).not.toBeChecked()
    await userEvent.click(within(create).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.classTypeCreated('Open mat sábado'))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      name: 'Open mat sábado',
      program_id: 'adultos',
      credit_cost: 1,
      kind: 'open_mat',
      counts_as_class: false,
    })
  })

  it('makes an open mat count as a class, sending only that', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    const row = within(adults).getByText('Open mat').closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: copy.edit }))
    const edit = within(adults).getByRole('form', { name: form.edit('Open mat') })
    expect(within(edit).getByLabelText(form.kind)).toHaveValue('open_mat')
    await userEvent.click(within(edit).getByRole('checkbox', { name: form.countsAsClass }))
    await userEvent.click(within(edit).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.classTypeSaved('Open mat'))
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => [c.path, c.body])).toEqual([
      ['/api/class-types/open', { counts_as_class: true }],
    ])
    const saved = within(await programCard('Adultos')).getByText('Open mat').closest('li')!
    expect(saved).not.toHaveTextContent(copy.notCounted)
  })

  it("puts a class type's refusals inline: an inactive program, a cost out of range, a name taken", async () => {
    stubApi({
      saveClassType: {
        status: 422,
        body: {
          detail: [
            { loc: ['body', 'program_id'], type: 'inactive_program', msg: '' },
            { loc: ['body', 'credit_cost'], type: 'less_than_equal', msg: '' },
          ],
        },
      },
    })
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    await userEvent.click(within(adults).getByRole('button', { name: copy.addClassType }))
    const create = within(adults).getByRole('form', {
      name: form.create('Adultos'),
    })
    await userEvent.type(within(create).getByLabelText(form.name), 'Competición')
    await userEvent.type(within(create).getByLabelText(form.creditCost), '00')
    await userEvent.click(within(create).getByRole('button', { name: copy.submit }))

    expect(await within(create).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(within(create).getByLabelText(form.program)).toHaveAccessibleDescription(copy.value.inactive_program)
    expect(within(create).getByLabelText(form.creditCost)).toHaveAccessibleDescription(
      `${form.creditCostHint} ${copy.range.credit_cost}`,
    )
  })

  it('says a class type name is taken in its program', async () => {
    stubApi({ saveClassType: { status: 409, body: { detail: 'taken' } } })
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    const fundamentos = within(adults).getByText('Fundamentos').closest('li')!
    await userEvent.click(within(fundamentos).getByRole('button', { name: copy.edit }))
    const edit = within(adults).getByRole('form', {
      name: form.edit('Fundamentos'),
    })
    const name = within(edit).getByLabelText(form.name)
    await userEvent.clear(name)
    await userEvent.type(name, 'Open mat')
    await userEvent.click(within(edit).getByRole('button', { name: copy.submit }))

    expect(await within(edit).findByRole('alert')).toHaveTextContent(copy.invalid)
    expect(name).toHaveAccessibleDescription(copy.classTypeTaken)
  })

  it('edits a class type, sending only what changed, and moves it to another program', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    const open = within(adults).getByText('Open mat').closest('li')!
    await userEvent.click(within(open).getByRole('button', { name: copy.edit }))
    const edit = within(adults).getByRole('form', {
      name: form.edit('Open mat'),
    })
    await userEvent.selectOptions(within(edit).getByLabelText(form.program), 'Kids')
    await userEvent.click(within(edit).getByRole('button', { name: copy.submit }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.classTypeSaved('Open mat'))
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/class-types/open',
        body: { program_id: 'kids' },
      },
    ])
    expect(await within(await programCard('Kids')).findByText('Open mat')).toBeInTheDocument()
  })

  it("keeps a class type's inactive program among its choices", async () => {
    stubApi()
    renderAt('/admin/ajustes/programas')

    const old = await programCard('Competición')
    await userEvent.click(within(old).getByRole('button', { name: copy.edit }))
    const program = within(old).getByLabelText(form.program)
    expect(program).toHaveValue('old')
    expect(
      within(program).getByRole('option', {
        name: form.inactiveProgram('Competición'),
      }),
    ).toBeInTheDocument()
  })

  it('deactivates a class type', async () => {
    const calls = stubApi()
    renderAt('/admin/ajustes/programas')

    const adults = await programCard('Adultos')
    const fundamentos = within(adults).getByText('Fundamentos').closest('li')!
    await userEvent.click(within(fundamentos).getByRole('button', { name: copy.deactivate }))

    expect(await screen.findByRole('status')).toHaveTextContent(copy.classTypeDeactivated('Fundamentos'))
    expect(await within(fundamentos).findByText(copy.inactive)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'PATCH')).toEqual([
      {
        method: 'PATCH',
        path: '/api/class-types/fund',
        body: { active: false },
      },
    ])
  })

  it('is hidden from coaches', async () => {
    const calls = stubApi({ role: 'coach' })
    renderAt('/admin/ajustes/programas')

    expect(await screen.findByText(settings.adminsOnly)).toBeInTheDocument()
    expect(calls.filter((c) => c.path.startsWith('/api/programs') || c.path.startsWith('/api/class-types'))).toEqual([])
  })
})
