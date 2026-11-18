import { createMemoryHistory } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RecentImport } from '../api/memberImport'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { shortDay } from '../format'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.import
const form = copy.undoForm

const BAD: RecentImport = {
  id: 'imp-1',
  at: '2026-11-14T15:00:00Z',
  by: 'Ana Rojas',
  file_name: 'pagos_meta.xlsx',
  tabs: ['alumnos', 'pagos', 'grados'],
  counts: {
    alumnos: { rows: 40, people_created: 3, history_set: 12 },
    pagos: { payments_created: 240, amount_clp: 6_000_000 },
    grados: { grades_created: 18 },
  },
  undone: null,
}

const UNDONE: RecentImport = {
  ...BAD,
  id: 'imp-0',
  file_name: null,
  at: '2026-11-10T15:00:00Z',
  undone: {
    at: '2026-11-11T12:00:00Z',
    by: 'Ana Rojas',
    reason: 'columna corrida',
    payments: 1,
    grades: 0,
    people: 0,
    kept: 0,
  },
}

type Undo = { id: string; reason: string }

function stubApi({ role = 'owner', refuse }: { role?: string; refuse?: string } = {}): Undo[] {
  const undone: Undo[] = []
  let recent = [BAD, UNDONE]
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
      if (url.pathname === '/api/me/role') return json(asRole(role))
      if (url.pathname === '/api/import/recent') return json(recent)
      if (url.pathname === '/api/import/imp-1/undo') {
        if (init?.method !== 'POST') return json({ payments: 240, grades: 18, people: 12, kept: 2 })
        if (refuse) return json({ detail: { code: refuse } }, 409)
        const { reason } = JSON.parse(String(init.body)) as { reason: string }
        undone.push({ id: 'imp-1', reason })
        recent = [{ ...BAD, undone: { at: '2026-11-16T12:00:00Z', by: 'Ana Rojas', reason, ...counts } }, UNDONE]
        return new Response(null, { status: 204 })
      }
      return json({ detail: 'Not Found' }, 404)
    }),
  )
  return undone
}

const counts = { payments: 240, grades: 18, people: 12, kept: 2 }

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Importaciones recientes', () => {
  it('lists the recent imports, newest first, with what each wrote and its undo', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')

    const list = await screen.findByRole('list', { name: copy.recentTitle })
    const [bad, undone] = within(list).getAllByRole('listitem')
    expect(within(bad!).getByText('pagos_meta.xlsx')).toBeInTheDocument()
    expect(within(bad!).getByText(copy.recentWho('Ana Rojas', shortDay(BAD.at)))).toBeInTheDocument()
    expect(within(bad!).getByText(copy.recentCounts(3, 12, 240, 18))).toBeInTheDocument()
    expect(within(bad!).getByRole('button', { name: copy.undo })).toBeInTheDocument()
    // Undone once, it offers no second undo.
    expect(within(undone!).getByText(copy.unnamedFile)).toBeInTheDocument()
    expect(
      within(undone!).getByText(copy.undone(shortDay(UNDONE.undone!.at), 'Ana Rojas', 'columna corrida')),
    ).toBeInTheDocument()
    expect(within(undone!).queryByRole('button', { name: copy.undo })).toBeNull()
  })

  it('offers an admin no undo', async () => {
    stubApi({ role: 'admin' })
    renderAt('/admin/alumnos/importar')

    expect(await screen.findByRole('list', { name: copy.recentTitle })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: copy.undo })).toBeNull()
  })

  it('says what goes, asks a reason, then undoes', async () => {
    const undone = stubApi()
    renderAt('/admin/alumnos/importar')
    await userEvent.click(await screen.findByRole('button', { name: copy.undo }))

    const undo = await screen.findByRole('form', { name: form.title })
    // It takes focus, so a phone scrolls to it below the fold (#419).
    expect(undo).toHaveFocus()
    expect(await within(undo).findByText(form.removes(240, 18, 12))).toBeInTheDocument()
    expect(undo).toHaveFocus()
    expect(within(undo).getByText(form.kept(2))).toBeInTheDocument()
    expect(within(undo).getByText(form.stays)).toBeInTheDocument()

    await userEvent.click(within(undo).getByRole('button', { name: form.submit }))
    expect(within(undo).getByText(form.reasonNeeded)).toBeInTheDocument()
    expect(undone).toEqual([])

    await userEvent.type(within(undo).getByLabelText(form.reason), 'columna corrida')
    await userEvent.click(within(undo).getByRole('button', { name: form.submit }))
    expect(await screen.findByText(copy.undoDone)).toBeInTheDocument()
    expect(undone).toEqual([{ id: 'imp-1', reason: 'columna corrida' }])
    expect(screen.queryByRole('form', { name: form.title })).toBeNull()
    expect(screen.queryByRole('button', { name: copy.undo })).toBeNull()
  })

  it('says so when the import was undone meanwhile', async () => {
    stubApi({ refuse: 'undone' })
    renderAt('/admin/alumnos/importar')
    await userEvent.click(await screen.findByRole('button', { name: copy.undo }))
    const undo = await screen.findByRole('form', { name: form.title })
    await userEvent.type(within(undo).getByLabelText(form.reason), 'x')
    await userEvent.click(within(undo).getByRole('button', { name: form.submit }))

    expect(await within(undo).findByText(form.alreadyUndone)).toBeInTheDocument()
  })
})
