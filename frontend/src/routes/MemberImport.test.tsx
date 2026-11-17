import { createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GradeReport, ImportReport, ImportRequest, PaymentReport, RowResult, Sheet } from '../api/memberImport'
import { createQueryClient } from '../api/queryClient'
import { App } from '../App'
import { es } from '../i18n/es'
import { createAppRouter } from '../router'
import { asRole } from '../test/access'

const copy = es.admin.import

const SHEET: Sheet = {
  headers: ['Nombre', 'Celular', 'Plan', 'Fecha de pago', 'Notas'],
  rows: [
    { number: 2, cells: ['Camila Ortiz', '9 8765 4321', 'mensual', '05/12/2026', ''] },
    { number: 3, cells: ['Benjamín Fuentes', '912340003', 'Beca 50%', '10/12/2026', 'beca'] },
    { number: 4, cells: ['Isidora Lagos', '2 2345 6789', 'Mensual', '05/12/2026', ''] },
  ],
  mapping: { name: 0, phone: 1, plan: 2, due_on: 3 },
  file: { name: 'alumnos.csv', sha256: 'a'.repeat(64) },
  pagos: null,
  grados: null,
  grados_ignored: false,
}

// A workbook with a Pagos tab (#298), headers as a gym's own notebook has them.
const PAYMENTS_BOOK: Sheet = {
  ...SHEET,
  pagos: {
    headers: ['Alumno', 'Fecha', 'Valor', 'Mes'],
    rows: [
      { number: 2, cells: ['Camila Ortiz', '05-03-2024', '$25.000', '03-2024'] },
      { number: 3, cells: ['Camila Ortiz', '05-04-2024', '25000', '04-2024'] },
      { number: 4, cells: ['Nadie', '05-04-2024', '0', '04-2024'] },
    ],
    mapping: { name: 0, paid_on: 1, amount_clp: 2, covers_month: 3 },
  },
}

function paymentsFor(body: ImportRequest): PaymentReport | null {
  if (!body.pagos) return null
  return {
    summary: { rows: 3, imported: 2, refused: 1, payments_created: 1, amount_clp: 25_000 },
    rows: [
      { row: 2, name: 'Camila Ortiz', errors: [], payment: 'existing' },
      { row: 3, name: 'Camila Ortiz', errors: [], payment: 'created' },
      {
        row: 4,
        name: 'Nadie',
        errors: [
          { field: 'name', code: 'unknown_person' },
          { field: 'amount_clp', code: 'invalid_amount' },
        ],
        payment: null,
      },
    ],
  }
}

// A workbook with a Grados tab (#299): the scheme says "Café", the sheet "Marrón".
const BOOK: Sheet = {
  ...SHEET,
  grados: {
    headers: ['Nombre', 'Grado', 'Rayas', 'Fecha'],
    rows: [
      { number: 2, cells: ['Camila Ortiz', 'Azul', '2', '12-08-2023'] },
      { number: 3, cells: ['Camila Ortiz', 'Marrón', '', '01-03-2025'] },
      { number: 4, cells: ['Nadie', 'azul', '', '01-03-2025'] },
    ],
    mapping: { name: 0, rank: 1, sub_rank: 2, awarded_on: 3 },
  },
}

const SCHEME = {
  ranks: [
    { key: 'white', label: 'Blanca', sub_ranks: [] },
    { key: 'blue', label: 'Azul', sub_ranks: [] },
    { key: 'brown', label: 'Café', sub_ranks: [] },
  ],
  kids_ladder: [],
  goal_metric: null,
}

function gradesFor(body: ImportRequest): GradeReport | null {
  if (!body.grados) return null
  return {
    summary: { rows: 3, imported: 2, refused: 1, grades_created: 1 },
    rows: [
      { row: 2, name: 'Camila Ortiz', errors: [], grade: 'existing' },
      body.grados.ranks['Marrón']
        ? { row: 3, name: 'Camila Ortiz', errors: [], grade: 'created' }
        : { row: 3, name: 'Camila Ortiz', errors: [{ field: 'rank', code: 'unknown_rank' }], grade: null },
      { row: 4, name: 'Nadie', errors: [{ field: 'name', code: 'unknown_person' }], grade: null },
    ],
  }
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
  history: false,
  former: false,
})

// More rows for a test's report: a former student's, say.
let extraRows: RowResult[] = []

function reportFor(body: ImportRequest): ImportReport {
  const rows: RowResult[] = [
    // Already in the gym, with another email than the sheet's.
    { ...ok(2, 'Camila Ortiz'), person: 'existing', membership: 'existing', ignored: ['email'], missing_phone: true },
    body.plans['Beca 50%'] !== undefined
      ? ok(3, 'Benjamín Fuentes')
      : { ...ok(3, 'Benjamín Fuentes'), person: null, membership: null, errors: [{ field: 'plan', code: 'unknown_plan' }] },
    { ...ok(4, 'Isidora Lagos'), person: null, membership: null, errors: [{ field: 'phone', code: 'invalid_phone' }] },
    ...extraRows,
  ]
  const imported = rows.filter((r) => r.errors.length === 0).length
  return {
    dry_run: body.dry_run,
    import_id: null,
    summary: {
      rows: rows.length,
      imported,
      refused: rows.length - imported,
      people_created: imported,
      links_created: 0,
      memberships_created: imported,
      missing_phone: 1,
      missing_identity: 0,
      history_set: rows.filter((r) => r.history).length,
      former_created: rows.filter((r) => r.former && r.person === 'created').length,
    },
    rows,
    pagos: paymentsFor(body),
    grados: gradesFor(body),
  }
}

type Sent = ImportRequest[]

// The names the sheets were uploaded with, and the tab a CSV was said to be.
let uploadedAs: (string | null)[] = []
let uploadedTabs: (string | null)[] = []
// Whether an activity of the gym grades (#245, #352), as `/api/me/role` answers now.
let grading = true

function stubApi({
  role = 'owner',
  refuse,
  sheet = SHEET,
  grades = true,
  plans = PLANS,
}: { role?: string; refuse?: string; sheet?: Sheet; grades?: boolean; plans?: unknown[] } = {}): Sent {
  grading = grades
  const sent: Sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
      if (url.pathname === '/api/me/role') return json({ ...asRole(role), uses_grades: grading })
      if (url.pathname === '/api/plans') return json(plans)
      if (url.pathname === '/api/people') return json({ items: [], total: 0 })
      if (url.pathname === '/api/gym/grading-scheme') return json(SCHEME)
      if (url.pathname === '/api/import/sheet') {
        expect(init?.body).toBeInstanceOf(File)
        uploadedAs.push(url.searchParams.get('name'))
        uploadedTabs.push(url.searchParams.get('tab'))
        return refuse ? json({ detail: { code: refuse } }, 422) : json(sheet)
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
  return queryClient
}

async function chooseFile() {
  const file = new File(['Nombre,Celular\n'], 'alumnos.csv', { type: 'text/csv' })
  await userEvent.upload(await screen.findByLabelText(copy.choose), file)
}

afterEach(() => {
  vi.unstubAllGlobals()
  extraRows = []
  uploadedAs = []
  uploadedTabs = []
})

describe('Importar alumnos', () => {
  it('reads the sheet and offers the suggested mapping', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByText(copy.fileSummary('alumnos.csv', 3, []))).toBeInTheDocument()
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
      { rows: SHEET.rows, mapping: SHEET.mapping, plans: { mensual: 'mensual' }, dry_run: true, file: SHEET.file },
    ])
    // The file's name goes up with it, and its hash comes back for the import's record.
    expect(uploadedAs).toEqual(['alumnos.csv'])
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

  it('charges the matrícula of the plans that have one only when ticked (#355)', async () => {
    const sent = stubApi({ plans: [PLANS[0], { ...PLANS[1], kind: 'monthly', enrolment_fee_clp: 25000 }] })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    const enrolment = await screen.findByLabelText(copy.enrolment)
    expect(enrolment).not.toBeChecked()
    expect(screen.getByText(copy.enrolmentHint)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    expect(await screen.findByText(copy.summary(1, 2))).toBeInTheDocument()
    expect(sent[0]).not.toHaveProperty('charge_enrolment')

    await userEvent.click(screen.getByRole('button', { name: copy.back }))
    await userEvent.click(await screen.findByLabelText(copy.enrolment))
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    expect(await screen.findByText(copy.summary(1, 2))).toBeInTheDocument()
    expect(sent[1]?.charge_enrolment).toBe(true)
  })

  it('asks nothing of a matrícula when no plan has one (#355)', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByRole('button', { name: copy.check })).toBeInTheDocument()
    expect(screen.queryByLabelText(copy.enrolment)).not.toBeInTheDocument()
  })

  it('offers the template to download', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')

    const template = await screen.findByRole('link', { name: copy.template })
    expect(template).toHaveAttribute('href', '/api/import/template.xlsx')
    expect(template).toHaveAttribute('download')
  })

  it('names the history columns in Spanish', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    const notas = await screen.findByLabelText('Notas')
    for (const label of ['Alumno desde', 'Fecha de baja', 'Motivo de baja', 'Clases antes de Rakin']) {
      expect(within(notas).getByRole('option', { name: label })).toBeInTheDocument()
    }
  })

  it('reports a former student imported with no plan, and the history it filled', async () => {
    extraRows = [
      { ...ok(5, 'Joaquín Vera'), membership: null, ignored: ['plan'], history: true, former: true },
      { ...ok(6, 'Ana Paz'), person: 'existing', membership: null, ignored: ['left_on'], history: false },
      {
        ...ok(7, 'Ema Paz'),
        person: null,
        membership: null,
        errors: [{ field: 'left_on', code: 'left_before_start' }],
      },
    ]
    stubApi()
    renderAt('/admin/alumnos/importar')
    await chooseFile()
    await userEvent.click(await screen.findByRole('button', { name: copy.check }))

    expect(await screen.findByText(copy.history(1, 1))).toBeInTheDocument()
    const former = screen.getByRole('list', { name: copy.formerTitle(1) })
    expect(within(former).getByText(copy.rowLabel(5, 'Joaquín Vera'))).toBeInTheDocument()
    expect(within(former).getByText(copy.formerKept([copy.fields.plan]))).toBeInTheDocument()
    // Someone already here keeps their record, and is never given a baja.
    const kept = screen.getByRole('list', { name: copy.keptTitle })
    expect(within(kept).queryByText(copy.rowLabel(5, 'Joaquín Vera'))).toBeNull()
    expect(within(kept).getByText(copy.kept([copy.fields.left_on]))).toBeInTheDocument()
    const errors = screen.getByRole('list', { name: copy.errorsTitle })
    expect(
      within(errors).getByText(copy.fieldError(copy.fields.left_on, copy.error.left_before_start)),
    ).toBeInTheDocument()
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

  it('maps a workbook\'s Grados tab on a step of its own, its ranks by label until chosen (#299)', async () => {
    const sent = stubApi({ sheet: BOOK })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByText(copy.fileSummary('alumnos.csv', 3, [{ tab: copy.tabs.grados, rows: 3 }]))).toBeInTheDocument()
    const grados = screen.getByRole('region', { name: copy.tabMappingTitle(copy.tabs.grados) })
    expect(within(grados).getByLabelText('Rayas')).toHaveValue('sub_rank')
    expect(within(grados).getByLabelText('Fecha')).toHaveValue('awarded_on')
    const ranks = screen.getByRole('region', { name: copy.ranksTitle })
    // "Azul" and "azul" are one value, matched to the rank of that label.
    expect(await within(ranks).findByLabelText('Azul')).toHaveValue('blue')
    expect(within(ranks).getByLabelText('Marrón')).toHaveValue('')

    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    const report = await screen.findByRole('region', { name: copy.gradesTitle })
    expect(within(report).getByText(copy.gradesSummary(1, 1, 2))).toBeInTheDocument()
    // One was already there: its note is not updated either.
    expect(within(report).getByText(copy.gradesExistingHint)).toBeInTheDocument()
    const errors = within(report).getByRole('list', { name: copy.gradesErrorsTitle })
    expect(
      within(errors).getByText(copy.fieldError(copy.gradeFields.rank, copy.gradeError.unknown_rank)),
    ).toBeInTheDocument()
    expect(
      within(errors).getByText(copy.fieldError(copy.gradeFields.name, copy.gradeError.unknown_person)),
    ).toBeInTheDocument()
    expect(sent[0]?.grados).toEqual({ rows: BOOK.grados?.rows, mapping: BOOK.grados?.mapping, ranks: { Azul: 'blue' } })

    await userEvent.click(screen.getByRole('button', { name: copy.back }))
    await userEvent.selectOptions(screen.getByLabelText('Marrón'), 'brown')
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    await waitFor(() => expect(sent[1]?.grados?.ranks).toEqual({ Azul: 'blue', Marrón: 'brown' }))
    // The apply button counts every tab's rows: 1 of Alumnos, 2 of Grados.
    expect(await screen.findByRole('button', { name: copy.apply(3) })).toBeEnabled()
  })

  it('imports a Grados tab alone, and needs its rank, day and who', async () => {
    const sent = stubApi({ sheet: { ...BOOK, headers: [], rows: [], mapping: {} } })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByText(copy.fileSummary('alumnos.csv', 0, [{ tab: copy.tabs.grados, rows: 3 }]))).toBeInTheDocument()
    expect(screen.getByRole('region', { name: copy.mappingTitle })).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Fecha'), '')
    expect(screen.getByText(copy.gradesRequired)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.check })).toBeDisabled()

    await userEvent.selectOptions(screen.getByLabelText('Fecha'), 'awarded_on')
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    await waitFor(() => expect(sent[0]?.rows).toEqual([]))
  })

  it('maps a workbook\'s Pagos tab on a step of its own and reports its payments (#298)', async () => {
    const sent = stubApi({ sheet: PAYMENTS_BOOK })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(
      await screen.findByText(copy.fileSummary('alumnos.csv', 3, [{ tab: copy.tabs.pagos, rows: 3 }])),
    ).toBeInTheDocument()
    expect(screen.getByRole('region', { name: copy.tabMappingTitle(copy.tabs.alumnos) })).toBeInTheDocument()
    const pagos = screen.getByRole('region', { name: copy.tabMappingTitle(copy.tabs.pagos) })
    expect(within(pagos).getByLabelText('Valor')).toHaveValue('amount_clp')
    expect(within(pagos).getByLabelText('Mes')).toHaveValue('covers_month')

    // The day paid and the amount are needed.
    await userEvent.selectOptions(within(pagos).getByLabelText('Valor'), '')
    expect(screen.getByText(copy.paymentsRequired)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: copy.check })).toBeDisabled()
    await userEvent.selectOptions(within(pagos).getByLabelText('Valor'), 'amount_clp')

    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    const report = await screen.findByRole('region', { name: copy.paymentsTitle })
    expect(within(report).getByText(copy.paymentsSummary(1, 1, 1))).toBeInTheDocument()
    expect(screen.getByText(copy.paymentsCreated(1, 25_000))).toBeInTheDocument()
    const errors = within(report).getByRole('list', { name: copy.paymentsErrorsTitle })
    expect(
      within(errors).getByText(copy.fieldError(copy.paymentFields.name, copy.paymentError.unknown_person)),
    ).toBeInTheDocument()
    expect(
      within(errors).getByText(copy.fieldError(copy.paymentFields.amount_clp, copy.paymentError.invalid_amount)),
    ).toBeInTheDocument()
    expect(sent[0]?.pagos).toEqual({ rows: PAYMENTS_BOOK.pagos?.rows, mapping: PAYMENTS_BOOK.pagos?.mapping })
    // The apply button counts every tab's rows: 1 of Alumnos, 2 of Pagos.
    expect(screen.getByRole('button', { name: copy.apply(3) })).toBeEnabled()
  })

  it('imports a Pagos tab alone', async () => {
    const sent = stubApi({ sheet: { ...PAYMENTS_BOOK, headers: [], rows: [], mapping: {} } })
    renderAt('/admin/alumnos/importar')
    await userEvent.selectOptions(await screen.findByLabelText(copy.csvTab), copy.tabs.pagos)
    await chooseFile()

    expect(
      await screen.findByText(copy.fileSummary('alumnos.csv', 0, [{ tab: copy.tabs.pagos, rows: 3 }])),
    ).toBeInTheDocument()
    expect(uploadedTabs).toEqual(['pagos'])
    expect(screen.getByRole('region', { name: copy.mappingTitle })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    await waitFor(() => expect(sent[0]?.rows).toEqual([]))
    expect(sent[0]?.grados).toBeUndefined()
  })

  it('says which tab a CSV is', async () => {
    stubApi()
    renderAt('/admin/alumnos/importar')
    await userEvent.selectOptions(await screen.findByLabelText(copy.csvTab), copy.tabs.grados)
    await chooseFile()

    await screen.findByText(copy.fileSummary('alumnos.csv', 3, []))
    expect(uploadedTabs).toEqual(['grados'])
  })

  it('lists a Grados tab the gym does not grade for as ignored, and why (#352)', async () => {
    const sent = stubApi({ sheet: { ...SHEET, grados_ignored: true }, grades: false })
    renderAt('/admin/alumnos/importar')
    // A CSV cannot be said to be one either.
    const tabs = await screen.findByLabelText(copy.csvTab)
    expect(within(tabs).queryByRole('option', { name: copy.tabs.grados })).not.toBeInTheDocument()
    await chooseFile()

    expect(await screen.findByText(copy.gradosIgnored)).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: copy.tabMappingTitle(copy.tabs.grados) })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: copy.check }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]?.grados).toBeUndefined()
  })

  it('reads a CSV picked as Grados as Alumnos once the gym stops grading', async () => {
    stubApi()
    const queryClient = renderAt('/admin/alumnos/importar')
    const tabs = await screen.findByLabelText(copy.csvTab)
    await within(tabs).findByRole('option', { name: copy.tabs.grados })
    await userEvent.selectOptions(tabs, copy.tabs.grados)

    grading = false
    await queryClient.invalidateQueries({ queryKey: ['me', 'role'] })
    await waitFor(() => expect(within(tabs).queryByRole('option', { name: copy.tabs.grados })).not.toBeInTheDocument())
    expect(tabs).toHaveValue('alumnos')
    await chooseFile()

    await screen.findByText(copy.fileSummary('alumnos.csv', 3, []))
    expect(uploadedTabs).toEqual(['alumnos'])
  })

  it('has nothing to check in a file whose only tab is an ignored Grados', async () => {
    stubApi({ sheet: { ...SHEET, headers: [], rows: [], mapping: {}, grados_ignored: true }, grades: false })
    renderAt('/admin/alumnos/importar')
    await chooseFile()

    expect(await screen.findByText(copy.gradosIgnored)).toBeInTheDocument()
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
