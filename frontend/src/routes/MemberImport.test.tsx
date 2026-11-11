import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ImportReport, ImportRequest, RowResult, Sheet } from '../api/memberImport'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'

const copy = es.admin.import

const SHEET: Sheet = {
  headers: ['Nombre', 'Celular', 'Plan', 'Fecha de pago', 'Notas'],
  rows: [
    { number: 2, cells: ['Camila Ortiz', '9 8765 4321', 'mensual', '05/12/2026', ''] },
    { number: 3, cells: ['Benjamín Fuentes', '912340003', 'Beca 50%', '10/12/2026', 'beca'] },
    { number: 4, cells: ['Isidora Lagos', '2 2345 6789', 'Mensual', '05/12/2026', ''] },
  ],
  mapping: { name: 0, phone: 1, plan: 2, due_on: 3 },
}

const PLANS = [
  { id: 'mensual', name: 'Mensual', active: true },
  { id: 'kids', name: 'Mensual Kids', active: true },
]

const ok = (row: number, name: string): RowResult => ({
  row,
  name,
  errors: [],
  person: 'created',
  guardian: null,
  link: null,
  membership: 'created',
  ignored: [],
  missing_phone: false,
  missing_identity: false,
})

function reportFor(body: ImportRequest): ImportReport {
  const rows: RowResult[] = [
    // Already in the gym, with another email than the sheet's.
    { ...ok(2, 'Camila Ortiz'), person: 'existing', membership: 'existing', ignored: ['email'], missing_phone: true },
    body.plans['Beca 50%'] !== undefined
      ? ok(3, 'Benjamín Fuentes')
      : { ...ok(3, 'Benjamín Fuentes'), person: null, membership: null, errors: [{ field: 'plan', code: 'unknown_plan' }] },
    { ...ok(4, 'Isidora Lagos'), person: null, membership: null, errors: [{ field: 'phone', code: 'invalid_phone' }] },
  ]
  const imported = rows.filter((r) => r.errors.length === 0).length
  return {
    dry_run: body.dry_run,
    summary: {
      rows: 3,
      imported,
      refused: 3 - imported,
      people_created: imported,
      links_created: 0,
      memberships_created: imported,
      missing_phone: 1,
      missing_identity: 0,
    },
    rows,
  }
}

type Sent = ImportRequest[]

function stubApi({ role = 'owner', refuse }: { role?: string; refuse?: string } = {}): Sent {
  const sent: Sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
      if (url.pathname === '/api/me/role') return json({ role })
      if (url.pathname === '/api/plans') return json(PLANS)
      if (url.pathname === '/api/people') return json({ items: [], total: 0 })
      if (url.pathname === '/api/import/sheet') {
        expect(init?.body).toBeInstanceOf(File)
        return refuse ? json({ detail: { code: refuse } }, 422) : json(SHEET)
      }
      if (url.pathname === '/api/import/members') {
        const body = JSON.parse(String(init?.body)) as ImportRequest
        sent.push(body)
        return json(reportFor(body))
      }
      return json({ detail: 'Not Found' }, 404)
    }),
  )
  return sent
}

function renderAt(path: string) {
  const queryClient = createQueryClient()
  const router = createAppRouter({ queryClient }, createMemoryHistory({ initialEntries: [path] }))
  render(<App queryClient={queryClient} router={router} />)
}

async function chooseFile() {
  const file = new File(['Nombre,Celular\n'], 'alumnos.csv', { type: 'text/csv' })
  await userEvent.upload(await screen.findByLabelText(copy.choose), file)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Importar alumnos', () => {
  it('reads the sheet and offers the suggested mapping', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByText(copy.fileSummary('alumnos.csv', 3))).toBeInTheDocument()
    expect(screen.getByLabelText('Nombre')).toHaveValue('name')
    expect(screen.getByLabelText('Celular')).toHaveValue('phone')
    expect(screen.getByLabelText('Notas')).toHaveValue('')
    expect(screen.getByText(copy.sample('beca'))).toBeInTheDocument()
  })

  it('matches plan values by name and lets the admin choose for the rest', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    // "mensual" and "Mensual" are one value, matched to the plan of that name.
    expect(await screen.findByLabelText('mensual')).toHaveValue('mensual')
    expect(screen.queryByLabelText('Mensual')).toBeNull()
    expect(screen.getByLabelText('Beca 50%')).toHaveValue('')
  })

  it('dry-runs, shows each refused row, then imports', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.click(await screen.findByRole('button', { name: copy.check }))

    expect(await screen.findByText(copy.summary(1, 2))).toBeInTheDocument()
    const errors = screen.getByRole('list', { name: copy.errorsTitle })
    expect(within(errors).getByText(copy.rowLabel(3, 'Benjamín Fuentes'))).toBeInTheDocument()
    expect(
      within(errors).getByText(copy.fieldError(copy.fields.phone, copy.error.invalid_phone)),
    ).toBeInTheDocument()
    expect(sent).toEqual([
      { rows: SHEET.rows, mapping: SHEET.mapping, plans: { mensual: 'mensual' }, dry_run: true },
    ])
    // Imported anyway: a warning, not an error.
    const missing = screen.getByRole('list', { name: copy.missingPhoneTitle(1) })
    expect(within(missing).getByText(copy.rowLabel(2, 'Camila Ortiz'))).toBeInTheDocument()
    const kept = screen.getByRole('list', { name: copy.keptTitle })
    expect(within(kept).getByText(copy.kept([copy.fields.email]))).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: copy.apply(1) }))
    expect(await screen.findByText(copy.doneSummary('alumnos.csv', 1, 2))).toBeInTheDocument()
    expect(sent[1]?.dry_run).toBe(false)
    expect(screen.getByRole('link', { name: copy.toStudents })).toHaveAttribute('href', '/admin/alumnos')
  })

  it('imports once for a double tap on Importar (#203)', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.click(await screen.findByRole('button', { name: copy.check }))
    await screen.findByText(copy.summary(1, 2))

    const apply = screen.getByRole('button', { name: copy.apply(1) })
    fireEvent.click(apply)
    fireEvent.click(apply)

    expect(await screen.findByText(copy.doneSummary('alumnos.csv', 1, 2))).toBeInTheDocument()
    expect(sent.filter((body) => !body.dry_run)).toHaveLength(1)
  })

  it('sends the plan the admin chose and a remapped column', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.selectOptions(await screen.findByLabelText('Beca 50%'), 'mensual')
    await userEvent.selectOptions(screen.getByLabelText('Notas'), 'email')
    await userEvent.click(screen.getByRole('button', { name: copy.check }))

    expect(await screen.findByText(copy.summary(2, 1))).toBeInTheDocument()
    expect(sent[0]?.plans).toEqual({ mensual: 'mensual', 'Beca 50%': 'mensual' })
    expect(sent[0]?.mapping).toEqual({ name: 0, phone: 1, email: 4, plan: 2, due_on: 3 })
  })

  it('sends "Sin plan" as no plan, for a matched value and an unmatched one', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.selectOptions(await screen.findByLabelText('mensual'), copy.noPlan)
    await userEvent.selectOptions(screen.getByLabelText('Beca 50%'), copy.noPlan)
    await userEvent.click(screen.getByRole('button', { name: copy.check }))

    await waitFor(() => expect(sent[0]?.plans).toEqual({ mensual: null, 'Beca 50%': null }))
  })

  it('leaves an unchosen value out, for the API to report', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    expect(await screen.findByLabelText('Beca 50%')).toHaveDisplayValue(copy.pickPlan)
    await userEvent.click(screen.getByRole('button', { name: copy.check }))

    await waitFor(() => expect(sent[0]?.plans).toEqual({ mensual: 'mensual' }))
  })

  it('moves a field to the column it is picked for', async () => {
    const sent = stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.selectOptions(await screen.findByLabelText('Notas'), 'name')

    expect(screen.getByLabelText('Nombre')).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    await waitFor(() => expect(sent[0]?.mapping).toEqual({ name: 4, phone: 1, plan: 2, due_on: 3 }))
  })

  it('needs a name column before it checks', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.selectOptions(await screen.findByLabelText('Nombre'), '')

    expect(screen.getByText(copy.nameRequired)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.check })).toBeDisabled()
  })

  it('says why a file was refused', async () => {
    stubApi({ refuse: 'unreadable' })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByRole('alert')).toHaveTextContent(copy.refused.unreadable)
  })
})

describe('Alumnos', () => {
  it('links an owner to the import', async () => {
    stubApi()
    renderAt('/admin/alumnos')
    expect(await screen.findByRole('link', { name: es.admin.students.importLink })).toHaveAttribute(
      'href',
      '/admin/alumnos/importar',
    )
  })

  it('does not show a coach the import', async () => {
    stubApi({ role: 'coach' })
    renderAt('/admin/alumnos')
    expect(await screen.findByText(es.admin.students.empty)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: es.admin.students.importLink })).toBeNull()
  })
})
