import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Family } from '../api/family'
import type { MemberRow } from '../api/people'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.family

const CAMILA: MemberRow = {
  id: 'camila',
  name: 'Camila Ortiz',
  phone: '+56987654321',
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  rut: null,
  membership: null,
  guardian: null,
  dependents: 1,
  left_on: null,
  owes: false,
}
const MATEO: MemberRow = {
  id: 'mateo',
  name: 'Mateo Ortiz',
  phone: null,
  no_whatsapp: false,
  missing_phone: false,
  missing_rut: false,
  rut: null,
  membership: null,
  guardian: { id: 'camila', name: 'Camila Ortiz' },
  dependents: 0,
  left_on: null,
  owes: false,
}
const DIEGO: MemberRow = { ...MATEO, id: 'diego', name: 'Diego Soto', guardian: null }

type Call = { method: string; path: string; body: unknown }
type Answer = { status?: number; body?: unknown }

/** A tiny API: the member list and each person's family, which the calls change. */
function stubApi(families: Record<string, Family>, refuse?: Answer) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (method !== 'GET') calls.push({ method, path: url.pathname, body })
      const answer = route(url, method, body)
      return new Response(answer.body === undefined ? null : JSON.stringify(answer.body), {
        status: answer.status ?? 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  function route(url: URL, method: string, body: { person_id?: string; name?: string } | undefined): Answer {
    if (url.pathname === '/api/people') {
      const q = url.searchParams.get('q')
      const items = q ? [CAMILA, MATEO, DIEGO].filter((r) => r.name.includes(q)) : [CAMILA, MATEO]
      return { body: { items, total: items.length } }
    }
    if (url.pathname === '/api/plans') return { body: [] }
    const family = /^\/api\/people\/([^/]+)\/family$/.exec(url.pathname)
    if (family) return { body: families[family[1]!] }
    const dependents = /^\/api\/people\/([^/]+)\/dependents(?:\/([^/]+))?$/.exec(url.pathname)
    if (dependents) {
      if (refuse) return refuse
      const own = families[dependents[1]!]!
      if (method === 'DELETE') {
        own.dependents = own.dependents.filter((d) => d.id !== dependents[2])
        return { status: 204 }
      }
      const added = body?.person_id
        ? { id: body.person_id, name: 'Diego Soto' }
        : { id: 'new', name: body?.name ?? '' }
      own.dependents = [...own.dependents, added]
      return { status: 201, body: own }
    }
    return { status: 404, body: { detail: 'Not Found' } }
  }

  return calls
}

function renderStudents() {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: ['/admin/alumnos'] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function openFamily(name: string) {
  await userEvent.click(await screen.findByRole('button', { name: copy.toggleLabel(name) }))
}

// The forms that add someone open behind "Agregar a alguien a cargo" (#179).
async function openAdding() {
  await userEvent.click(await screen.findByRole('button', { name: copy.addTitle }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Familia', () => {
  it('shows each row’s guardian or how many they pay for', async () => {
    stubApi({})
    renderStudents()

    expect(await screen.findByText(es.admin.students.guardianOf('Camila Ortiz'))).toBeInTheDocument()
    expect(screen.getByText(es.admin.students.dependentsCount(1))).toBeInTheDocument()
  })

  it('controls a panel that is there, hidden, while closed', async () => {
    stubApi({ camila: { guardian: null, dependents: [] } })
    renderStudents()
    const toggle = await screen.findByRole('button', { name: copy.toggleLabel('Camila Ortiz') })
    const panel = document.getElementById(toggle.getAttribute('aria-controls')!)

    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(panel).not.toBeNull()
    expect(panel).not.toBeVisible()
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(panel).toBeVisible()
  })

  it('keeps the forms that add someone closed until asked for', async () => {
    stubApi({ camila: { guardian: null, dependents: [] } })
    renderStudents()
    await openFamily('Camila Ortiz')

    await openAdding()
    expect(screen.getByLabelText(copy.name)).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: copy.linkSearch })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.close }))
    expect(screen.queryByLabelText(copy.name)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.addTitle })).toBeInTheDocument()
  })

  it('adds a new dependent with no phone', async () => {
    const calls = stubApi({ camila: { guardian: null, dependents: [{ id: 'mateo', name: 'Mateo Ortiz' }] } })
    renderStudents()
    await openFamily('Camila Ortiz')

    expect(await screen.findByText('Mateo Ortiz', { selector: '.family__person span' })).toBeInTheDocument()
    await openAdding()
    await userEvent.type(screen.getByLabelText(copy.name), 'Sofía Ortiz')
    await userEvent.type(screen.getByLabelText(copy.rut), '23.456.789-0')
    await userEvent.click(screen.getByRole('button', { name: copy.add }))

    await waitFor(() =>
      expect(calls).toEqual([
        { method: 'POST', path: '/api/people/camila/dependents', body: { name: 'Sofía Ortiz', rut: '23.456.789-0' } },
      ]),
    )
    expect(await screen.findByText('Sofía Ortiz')).toBeInTheDocument()
    expect(screen.getByLabelText(copy.name)).toHaveValue('')
  })

  it('links someone already in the gym', async () => {
    const calls = stubApi({ camila: { guardian: null, dependents: [] } })
    renderStudents()
    await openFamily('Camila Ortiz')
    await openAdding()

    await userEvent.type(await screen.findByRole('searchbox', { name: copy.linkSearch }), 'Ortiz')
    // Mateo already has a guardian, and Camila is the guardian: neither is offered.
    expect(await screen.findByText(copy.noMatches)).toBeInTheDocument()

    await userEvent.clear(screen.getByRole('searchbox', { name: copy.linkSearch }))
    await userEvent.type(screen.getByRole('searchbox', { name: copy.linkSearch }), 'Diego')
    await userEvent.click(await screen.findByRole('button', { name: copy.linkLabel('Diego Soto') }))

    await waitFor(() =>
      expect(calls).toEqual([{ method: 'POST', path: '/api/people/camila/dependents', body: { person_id: 'diego' } }]),
    )
  })

  it('unlinks a dependent from their guardian’s side or their own', async () => {
    const families = {
      camila: { guardian: null, dependents: [{ id: 'mateo', name: 'Mateo Ortiz' }] },
      mateo: { guardian: { id: 'camila', name: 'Camila Ortiz' }, dependents: [] },
    }
    const calls = stubApi(families)
    renderStudents()
    await openFamily('Mateo Ortiz')

    // A dependent cannot have dependents of their own: no form to add any.
    const panel = await screen.findByRole('heading', { name: copy.guardian })
    expect(screen.queryByRole('button', { name: copy.add })).not.toBeInTheDocument()
    await userEvent.click(within(panel.parentElement!).getByRole('button', { name: copy.unlinkLabel('Camila Ortiz') }))
    // It asks first (#241): nothing goes until it is confirmed, and Cancelar takes it back.
    await userEvent.click(screen.getByRole('button', { name: copy.unlinkCancel }))
    await userEvent.click(within(panel.parentElement!).getByRole('button', { name: copy.unlinkLabel('Camila Ortiz') }))
    const asking = screen.getByRole('group', { name: copy.unlinkLabel('Camila Ortiz') })
    expect(asking).toHaveTextContent(copy.unlinkConfirm('Camila Ortiz'))
    expect(calls).toEqual([])
    await userEvent.click(within(asking).getByRole('button', { name: copy.unlink }))

    await waitFor(() => expect(calls).toEqual([{ method: 'DELETE', path: '/api/people/camila/dependents/mateo', body: undefined }]))
  })

  it('says why a link was refused and keeps what was typed', async () => {
    stubApi({ camila: { guardian: null, dependents: [] } }, { status: 409, body: { detail: { code: 'one_level' } } })
    renderStudents()
    await openFamily('Camila Ortiz')
    await openAdding()

    await userEvent.type(await screen.findByLabelText(copy.name), 'Abuela')
    await userEvent.click(screen.getByRole('button', { name: copy.add }))

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refused.one_level)
    expect(screen.getByLabelText(copy.name)).toHaveValue('Abuela')
  })
})
