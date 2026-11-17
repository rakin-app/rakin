import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useMemo, useState, type ChangeEvent } from 'react'
import { useGrades } from '../api/activities'
import { gradingSchemeQuery, type SchemeRank } from '../api/grading'
import {
  fold,
  GRADE_FIELDS,
  IMPORT_FIELDS,
  MAX_SHEET_BYTES,
  PAYMENT_FIELDS,
  runImport,
  SHEET_TABS,
  SHEET_TYPES,
  sheetRefusal,
  TEMPLATE_PATH,
  uploadSheet,
  type GradeField,
  type GradeMapping,
  type GradeReport,
  type ImportField,
  type ImportReport,
  type Mapping,
  type PaymentField,
  type PaymentMapping,
  type PaymentReport,
  type RowResult,
  type Sheet,
  type SheetRow,
  type SheetTab,
} from '../api/memberImport'
import { plansQuery, type Plan } from '../api/people'
import { Button, buttonClass } from '../components/Button'
import { Select } from '../components/Field'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './MemberImport.css'
import { RecentImports } from './RecentImports'
import { useSubmit } from '../api/submit'
import { Banner, PlainList } from '../components/Card'

const copy = t.admin.import

// The plan step's "Sin plan": import the person with no membership. Never a plan id.
const NO_PLAN = 'none'

/**
 * "Importar alumnos": upload the gym's spreadsheet, say what each column is, check
 * every row without saving (the dry run), then import. The file is read once; the
 * rows stay here and go back to the API with the mapping each time. A workbook's
 * Pagos (#298) and Grados (#299) tabs each get a mapping step of their own, and are
 * checked and imported with the Alumnos tab, after it. Below the picker, the gym's
 * recent imports, which the owner can undo (#300).
 */
export function MemberImport() {
  usePageTitle(copy.title)
  const [file, setFile] = useState<{ name: string; sheet: Sheet } | null>(null)

  return (
    <>
      <PageHeader title={copy.title} eyebrow={copy.eyebrow} />
      <div className="import">
        {file === null ? (
          <>
            <SheetPicker onRead={(name, sheet) => setFile({ name, sheet })} />
            <RecentImports />
          </>
        ) : (
          <SheetImport key={file.name} name={file.name} sheet={file.sheet} onOther={() => setFile(null)} />
        )}
      </div>
    </>
  )
}

function SheetPicker({ onRead }: { onRead: (name: string, sheet: Sheet) => void }) {
  const inputId = useId()
  const tabId = useId()
  const [tooLarge, setTooLarge] = useState(false)
  // Which tab a CSV is: a workbook says by its tabs' names.
  const [chosenTab, setCsvTab] = useState<SheetTab>('alumnos')
  // A gym that grades in none of its activities reads no Grados tab (#352): one picked
  // before grading went off is Alumnos again, so the picker never holds an option it lacks.
  const grades = useGrades()
  const csvTab = grades || chosenTab !== 'grados' ? chosenTab : 'alumnos'
  const read = useSubmit({
    offline: 'refuse',
    mutationFn: (file: File) => uploadSheet(file, csvTab),
    onSuccess: (sheet, file) => onRead(file.name, sheet),
  })

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setTooLarge(file.size > MAX_SHEET_BYTES)
    if (file.size <= MAX_SHEET_BYTES) read.mutate(file)
  }

  const problem = tooLarge ? copy.tooLarge : read.error ? copy.refused[sheetRefusal(read.error) ?? 'failed'] : null
  return (
    <section className="import__card">
      <p className="import__note">{copy.intro}</p>
      <p className="import__note">
        {copy.templateHint}{' '}
        <a href={TEMPLATE_PATH} download className="tap-link tap-link--inline import__template">
          {copy.template}
        </a>
      </p>
      <label htmlFor={tabId} className="import__label">
        {copy.csvTab}
      </label>
      <Select id={tabId} value={csvTab} onChange={(event) => setCsvTab(event.target.value as SheetTab)}>
        {SHEET_TABS.filter((tab) => grades || tab !== 'grados').map((tab) => (
          <option key={tab} value={tab}>
            {copy.tabs[tab]}
          </option>
        ))}
      </Select>
      <span className="import__label">{copy.fileLabel}</span>
      <div>
        <input
          id={inputId}
          className="visually-hidden import__file"
          type="file"
          accept={SHEET_TYPES.join(',')}
          disabled={read.isPending}
          onChange={pick}
        />
        <label htmlFor={inputId} className={buttonClass({ variant: 'primary' })}>
          {copy.choose}
        </label>
      </div>
      {read.isPending && (
        <p className="import__note" role="status">
          {copy.reading}
        </p>
      )}
      {problem && (
        <Banner tone="error">
          {problem}
        </Banner>
      )}
    </section>
  )
}

/** Column index to field, from the field-to-column mapping the API speaks. */
function byColumn<F extends string>(fields: readonly F[], mapping: Partial<Record<F, number>>): (F | '')[] {
  const columns: (F | '')[] = []
  for (const field of fields) {
    const column = mapping[field]
    if (column !== undefined) columns[column] = field
  }
  return columns
}

/** `mapping` with `field` on `column`: one column is one field, so picking a field moves it here from wherever it was. */
function moved<F extends string>(
  fields: readonly F[],
  current: Partial<Record<F, number>>,
  column: number,
  field: F | '',
): Partial<Record<F, number>> {
  const next: Partial<Record<F, number>> = {}
  for (const f of fields) {
    if (current[f] !== undefined && current[f] !== column && f !== field) next[f] = current[f]
  }
  if (field) next[field] = column
  return next
}

/** A column's values, each once, accents and case ignored, in the sheet's order. */
function valuesIn(rows: SheetRow[], column: number | undefined): string[] {
  if (column === undefined) return []
  const values = new Map<string, string>()
  for (const row of rows) {
    const value = row.cells[column]?.trim()
    if (value && !values.has(fold(value))) values.set(fold(value), value)
  }
  return [...values.values()]
}

const paymentsReady = (mapping: PaymentMapping) =>
  mapping.paid_on !== undefined &&
  mapping.amount_clp !== undefined &&
  (mapping.rut !== undefined || mapping.email !== undefined || mapping.name !== undefined)

const gradesReady = (mapping: GradeMapping) =>
  mapping.rank !== undefined &&
  mapping.awarded_on !== undefined &&
  (mapping.rut !== undefined || mapping.email !== undefined || mapping.name !== undefined)

/** Rows imported over every tab, and refused. */
function totals(report: ImportReport): { imported: number; refused: number } {
  return {
    imported:
      report.summary.imported + (report.pagos?.summary.imported ?? 0) + (report.grados?.summary.imported ?? 0),
    refused:
      report.summary.refused + (report.pagos?.summary.refused ?? 0) + (report.grados?.summary.refused ?? 0),
  }
}

function SheetImport({ name, sheet, onOther }: { name: string; sheet: Sheet; onOther: () => void }) {
  const queryClient = useQueryClient()
  const plans = useQuery(plansQuery)
  const pagos = sheet.pagos
  const grados = sheet.grados
  const hasAlumnos = sheet.rows.length > 0
  // The Alumnos step says which tab it is when it is not the only one.
  const tabbed = pagos !== null || grados !== null
  const scheme = useQuery({ ...gradingSchemeQuery(), enabled: grados !== null })
  const [mapping, setMapping] = useState<Mapping>(sheet.mapping)
  const [paymentMapping, setPaymentMapping] = useState<PaymentMapping>(pagos?.mapping ?? {})
  const [gradeMapping, setGradeMapping] = useState<GradeMapping>(grados?.mapping ?? {})
  // The admin's choice for a Grado cell's value: a rank's key, or `''` for none.
  const [rankChosen, setRankChosen] = useState<Record<string, string>>({})
  // The admin's choice for a plan cell's value: a plan's id, `NO_PLAN`, or `''` for none
  // made yet. Absent means "as matched by name".
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const [report, setReport] = useState<ImportReport | null>(null)

  const planValues = useMemo(() => valuesIn(sheet.rows, mapping.plan), [mapping.plan, sheet.rows])
  const rankValues = useMemo(() => valuesIn(grados?.rows ?? [], gradeMapping.rank), [gradeMapping.rank, grados])
  const ranks = useMemo(
    () => (scheme.data ? [...scheme.data.ranks, ...scheme.data.kids_ladder] : []),
    [scheme.data],
  )
  const rankFor = (value: string) =>
    rankChosen[value] ?? ranks.find((rank) => fold(rank.label) === fold(value))?.key ?? ''

  const matched = (value: string): string => {
    const key = fold(value)
    // An inactive plan of that name is left to the API, which reports it.
    return plans.data?.find((p) => p.active && fold(p.name) === key)?.id ?? ''
  }
  const planFor = (value: string) => chosen[value] ?? matched(value)

  const request = (dryRun: boolean) => {
    // Unchosen values are left out, and the API reports them as no plan it knows.
    const choices: Record<string, string | null> = {}
    for (const value of planValues) {
      const plan = planFor(value)
      if (plan) choices[value] = plan === NO_PLAN ? null : plan
    }
    const rankChoices: Record<string, string> = {}
    for (const value of rankValues) {
      const rank = rankFor(value)
      if (rank) rankChoices[value] = rank
    }
    return runImport({
      rows: sheet.rows,
      mapping,
      plans: choices,
      dry_run: dryRun,
      file: sheet.file,
      ...(pagos && { pagos: { rows: pagos.rows, mapping: paymentMapping } }),
      ...(grados && { grados: { rows: grados.rows, mapping: gradeMapping, ranks: rankChoices } }),
    })
  }
  const check = useSubmit({ offline: 'refuse', mutationFn: () => request(true), onSuccess: setReport })
  const apply = useSubmit({
    offline: 'refuse',
    mutationFn: () => request(false),
    onSuccess: (done) => {
      setReport(done)
      void queryClient.invalidateQueries({ queryKey: ['people'] })
      // Importar's recent imports gain this one (#300).
      void queryClient.invalidateQueries({ queryKey: ['import', 'recent'] })
    },
  })

  const changed = () => {
    setReport(null)
    check.reset()
  }
  const setColumn = (column: number, field: ImportField | '') => {
    setMapping((current) => moved(IMPORT_FIELDS, current, column, field))
    changed()
  }
  const setPaymentColumn = (column: number, field: PaymentField | '') => {
    setPaymentMapping((current) => moved(PAYMENT_FIELDS, current, column, field))
    changed()
  }
  const setGradeColumn = (column: number, field: GradeField | '') => {
    setGradeMapping((current) => moved(GRADE_FIELDS, current, column, field))
    changed()
  }
  const alumnosReady = !hasAlumnos || mapping.name !== undefined
  const pagosReady = pagos === null || paymentsReady(paymentMapping)
  const gradosReady = grados === null || gradesReady(gradeMapping)
  // Only an ignored Grados tab: nothing to check.
  const anything = hasAlumnos || pagos !== null || grados !== null

  if (report && !report.dry_run) {
    return <Done name={name} report={report} onOther={onOther} />
  }

  return (
    <>
      <section className="import__card">
        <div className="import__file-row">
          <span className="import__file-name">
            {copy.fileSummary(name, sheet.rows.length, [
              ...(pagos ? [{ tab: copy.tabs.pagos, rows: pagos.rows.length }] : []),
              ...(grados ? [{ tab: copy.tabs.grados, rows: grados.rows.length }] : []),
            ])}
          </span>
          <Button onClick={onOther}>
            {copy.otherFile}
          </Button>
        </div>
        {sheet.grados_ignored && <p className="import__note">{copy.gradosIgnored}</p>}
      </section>

      {report ? (
        <Review
          report={report}
          applying={apply.isPending}
          failed={apply.isError}
          onBack={() => setReport(null)}
          onApply={() => apply.mutate()}
        />
      ) : (
        <>
          {hasAlumnos && (
            <ColumnMapping
              title={tabbed ? copy.tabMappingTitle(copy.tabs.alumnos) : copy.mappingTitle}
              headers={sheet.headers}
              rows={sheet.rows}
              fields={IMPORT_FIELDS}
              labels={copy.fields}
              columns={byColumn(IMPORT_FIELDS, mapping)}
              onChange={setColumn}
            />
          )}
          {hasAlumnos && planValues.length > 0 && (
            <PlanChoices
              values={planValues}
              plans={plans.data ?? []}
              planFor={planFor}
              onChange={(value, plan) => setChosen((current) => ({ ...current, [value]: plan }))}
            />
          )}
          {pagos && (
            <ColumnMapping
              title={hasAlumnos || grados ? copy.tabMappingTitle(copy.tabs.pagos) : copy.mappingTitle}
              headers={pagos.headers}
              rows={pagos.rows}
              fields={PAYMENT_FIELDS}
              labels={copy.paymentFields}
              columns={byColumn(PAYMENT_FIELDS, paymentMapping)}
              onChange={setPaymentColumn}
            />
          )}
          {grados && (
            <ColumnMapping
              title={hasAlumnos || pagos ? copy.tabMappingTitle(copy.tabs.grados) : copy.mappingTitle}
              headers={grados.headers}
              rows={grados.rows}
              fields={GRADE_FIELDS}
              labels={copy.gradeFields}
              columns={byColumn(GRADE_FIELDS, gradeMapping)}
              onChange={setGradeColumn}
            />
          )}
          {grados && rankValues.length > 0 && (
            <RankChoices
              values={rankValues}
              ranks={ranks}
              rankFor={rankFor}
              onChange={(value, rank) => {
                setRankChosen((current) => ({ ...current, [value]: rank }))
                changed()
              }}
            />
          )}
          <section className="import__card">
            {!alumnosReady && <p className="import__note">{copy.nameRequired}</p>}
            {!pagosReady && <p className="import__note">{copy.paymentsRequired}</p>}
            {!gradosReady && <p className="import__note">{copy.gradesRequired}</p>}
            {check.isError && (
              <Banner tone="error">
                {copy.failed}
              </Banner>
            )}
            <Button
              variant="primary"
              disabled={!anything || !alumnosReady || !pagosReady || !gradosReady || check.isPending}
              onClick={() => check.mutate()}
            >
              {check.isPending ? copy.checking : copy.check}
            </Button>
          </section>
        </>
      )}
    </>
  )
}

function ColumnMapping<F extends string>({
  title,
  headers,
  rows,
  fields,
  labels,
  columns,
  onChange,
}: {
  title: string
  headers: string[]
  rows: SheetRow[]
  fields: readonly F[]
  labels: Record<F, string>
  columns: (F | '')[]
  onChange: (column: number, field: F | '') => void
}) {
  const baseId = useId()
  return (
    <section className="import__card" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`} className="import__title">
        {title}
      </h2>
      <p className="import__note">{copy.mappingHint}</p>
      <PlainList className="import__columns">
        {headers.map((header, column) => {
          const sample = rows.find((row) => row.cells[column])?.cells[column]
          const label = header || copy.unnamedColumn(column + 1)
          const id = `${baseId}-${column}`
          return (
            <li key={column} className="import__column">
              <label htmlFor={id} className="import__column-name">
                {label}
              </label>
              {sample && <span className="import__sample">{copy.sample(sample)}</span>}
              <Select
                id={id}
                value={columns[column] ?? ''}
                onChange={(event) => onChange(column, event.target.value as F | '')}
              >
                <option value="">{copy.skip}</option>
                {fields.map((field) => (
                  <option key={field} value={field}>
                    {labels[field]}
                  </option>
                ))}
              </Select>
            </li>
          )
        })}
      </PlainList>
    </section>
  )
}

function PlanChoices({
  values,
  plans,
  planFor,
  onChange,
}: {
  values: string[]
  plans: Plan[]
  planFor: (value: string) => string
  onChange: (value: string, plan: string) => void
}) {
  const baseId = useId()
  return (
    <section className="import__card" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`} className="import__title">
        {copy.plansTitle}
      </h2>
      <p className="import__note">{copy.plansHint}</p>
      <PlainList className="import__columns">
        {values.map((value, index) => {
          const id = `${baseId}-${index}`
          return (
            <li key={value} className="import__column">
              <label htmlFor={id} className="import__column-name">
                {value}
              </label>
              <Select
                id={id}
                value={planFor(value)}
                onChange={(event) => onChange(value, event.target.value)}
              >
                <option value="">{copy.pickPlan}</option>
                <option value={NO_PLAN}>{copy.noPlan}</option>
                {plans
                  .filter((plan) => plan.active)
                  .map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name}
                    </option>
                  ))}
              </Select>
            </li>
          )
        })}
      </PlainList>
    </section>
  )
}

/** The Grado step: which rank each value of the column is, matched by label until the admin picks. */
function RankChoices({
  values,
  ranks,
  rankFor,
  onChange,
}: {
  values: string[]
  ranks: SchemeRank[]
  rankFor: (value: string) => string
  onChange: (value: string, rank: string) => void
}) {
  const baseId = useId()
  return (
    <section className="import__card" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`} className="import__title">
        {copy.ranksTitle}
      </h2>
      <p className="import__note">{ranks.length === 0 ? copy.noRanks : copy.ranksHint}</p>
      <PlainList className="import__columns">
        {values.map((value, index) => {
          const id = `${baseId}-${index}`
          return (
            <li key={value} className="import__column">
              <label htmlFor={id} className="import__column-name">
                {value}
              </label>
              <Select id={id} value={rankFor(value)} onChange={(event) => onChange(value, event.target.value)}>
                <option value="">{copy.pickRank}</option>
                {ranks.map((rank) => (
                  <option key={rank.key} value={rank.key}>
                    {rank.label}
                  </option>
                ))}
              </Select>
            </li>
          )
        })}
      </PlainList>
    </section>
  )
}

function Counts({ report }: { report: ImportReport }) {
  const {
    rows,
    people_created: people,
    links_created: links,
    memberships_created: memberships,
    history_set: history,
    former_created: former,
  } = report.summary
  const payments = report.pagos?.summary.payments_created ?? 0
  const grades = report.grados?.summary.grades_created ?? 0
  return (
    <>
      {people + links + memberships + history + payments + grades === 0 ? (
        <p className="import__note">{copy.nothingNew}</p>
      ) : (
        rows > 0 && <p className="import__note">{copy.created(people, links, memberships)}</p>
      )}
      {(history > 0 || former > 0) && <p className="import__note">{copy.history(history, former)}</p>}
      {report.pagos && payments > 0 && (
        <p className="import__note">{copy.paymentsCreated(payments, report.pagos.summary.amount_clp)}</p>
      )}
      {report.grados && grades > 0 && <p className="import__note">{copy.gradesCreated(grades)}</p>}
    </>
  )
}

function Review({
  report,
  applying,
  failed,
  onBack,
  onApply,
}: {
  report: ImportReport
  applying: boolean
  failed: boolean
  onBack: () => void
  onApply: () => void
}) {
  const { imported, refused } = totals(report)
  return (
    <>
      <section className="import__card" aria-labelledby="import-review-title">
        <h2 id="import-review-title" className="import__title">
          {copy.reviewTitle}
        </h2>
        <p className="import__summary" role="status">
          {copy.summary(imported, refused)}
        </p>
        <Counts report={report} />
        {failed && (
          <Banner tone="error">
            {copy.applyFailed}
          </Banner>
        )}
        <div className="import__actions">
          <Button onClick={onBack} disabled={applying}>
            {copy.back}
          </Button>
          <Button
            variant="primary"
            disabled={imported === 0 || applying}
            busy={applying}
            onClick={onApply}
          >
            {applying ? copy.applying : copy.apply(imported)}
          </Button>
        </div>
      </section>
      <RefusedRows rows={report.rows} />
      <WarningRows rows={report.rows} />
      <FormerRows rows={report.rows} />
      <KeptRows rows={report.rows} />
      {report.pagos && <PaymentRows report={report.pagos} />}
      {report.grados && <GradeRows report={report.grados} />}
    </>
  )
}

function Done({ name, report, onOther }: { name: string; report: ImportReport; onOther: () => void }) {
  return (
    <>
      <section className="import__card" aria-labelledby="import-done-title">
        <h2 id="import-done-title" className="import__title">
          {copy.doneTitle}
        </h2>
        <p className="import__summary" role="status">
          {copy.doneSummary(name, totals(report).imported, totals(report).refused)}
        </p>
        <Counts report={report} />
        <div className="import__actions">
          <Button onClick={onOther}>
            {copy.again}
          </Button>
          <Link to="/admin/alumnos" className={buttonClass({ variant: 'primary' })}>
            {copy.toStudents}
          </Link>
        </div>
      </section>
      <RefusedRows rows={report.rows} />
      <WarningRows rows={report.rows} />
      <FormerRows rows={report.rows} />
      <KeptRows rows={report.rows} />
      {report.pagos && <PaymentRows report={report.pagos} />}
      {report.grados && <GradeRows report={report.grados} />}
    </>
  )
}

/** The Pagos tab's rows: how many payments are new, how many they already had, and those refused. */
function PaymentRows({ report }: { report: PaymentReport }) {
  const { imported, payments_created: created } = report.summary
  const refused = report.rows.filter((row) => row.errors.length > 0)
  return (
    <section className="import__card" aria-labelledby="import-payments-title">
      <h2 id="import-payments-title" className="import__title">
        {copy.paymentsTitle}
      </h2>
      <p className="import__note">{copy.paymentsSummary(created, imported - created, refused.length)}</p>
      {refused.length > 0 && (
        <>
          <p className="import__note">{copy.paymentsErrorsHint}</p>
          <PlainList className="import__errors" aria-label={copy.paymentsErrorsTitle}>
            {refused.map((row) => (
              <li key={row.row} className="import__error-row">
                <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
                {row.errors.map((error) => (
                  <span key={`${error.field}-${error.code}`} className="import__error-what">
                    {copy.fieldError(copy.paymentFields[error.field], copy.paymentError[error.code])}
                  </span>
                ))}
              </li>
            ))}
          </PlainList>
        </>
      )}
    </section>
  )
}

/** The Grados tab's rows: how many grades are new, how many they already had, and those refused. */
function GradeRows({ report }: { report: GradeReport }) {
  const { imported, grades_created: created } = report.summary
  const refused = report.rows.filter((row) => row.errors.length > 0)
  return (
    <section className="import__card" aria-labelledby="import-grades-title">
      <h2 id="import-grades-title" className="import__title">
        {copy.gradesTitle}
      </h2>
      <p className="import__note">{copy.gradesSummary(created, imported - created, refused.length)}</p>
      {imported > created && <p className="import__note">{copy.gradesExistingHint}</p>}
      {refused.length > 0 && (
        <>
          <p className="import__note">{copy.gradesErrorsHint}</p>
          <PlainList className="import__errors" aria-label={copy.gradesErrorsTitle}>
            {refused.map((row) => (
              <li key={row.row} className="import__error-row">
                <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
                {row.errors.map((error) => (
                  <span key={`${error.field}-${error.code}`} className="import__error-what">
                    {copy.fieldError(copy.gradeFields[error.field], copy.gradeError[error.code])}
                  </span>
                ))}
              </li>
            ))}
          </PlainList>
        </>
      )}
    </section>
  )
}

/** Rows imported with a warning, not an error: "Falta teléfono", or neither a RUT nor an
 * email to say who they are. */
function WarningRows({ rows }: { rows: RowResult[] }) {
  return (
    <>
      <Warned
        id="import-missing-phone-title"
        rows={rows.filter((row) => row.errors.length === 0 && row.missing_phone)}
        title={copy.missingPhoneTitle}
        hint={copy.missingPhoneHint}
      />
      <Warned
        id="import-missing-identity-title"
        rows={rows.filter((row) => row.errors.length === 0 && row.missing_identity)}
        title={copy.missingIdentityTitle}
        hint={copy.missingIdentityHint}
      />
    </>
  )
}

function Warned({
  id,
  rows,
  title,
  hint,
}: {
  id: string
  rows: RowResult[]
  title: (n: number) => string
  hint: string
}) {
  if (rows.length === 0) return null
  return (
    <section className="import__card" aria-labelledby={id}>
      <h2 id={id} className="import__title">
        {title(rows.length)}
      </h2>
      <p className="import__note">{hint}</p>
      <PlainList className="import__errors" aria-label={title(rows.length)}>
        {rows.map((row) => (
          <li key={row.row} className="import__error-row">
            <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
          </li>
        ))}
      </PlainList>
    </section>
  )
}

/** A former student's row creates them already gone: their plan is not imported. */
const newFormer = (row: RowResult) => row.former && row.person === 'created'

function FormerRows({ rows }: { rows: RowResult[] }) {
  const former = rows.filter((row) => row.errors.length === 0 && newFormer(row))
  if (former.length === 0) return null
  return (
    <section className="import__card" aria-labelledby="import-former-title">
      <h2 id="import-former-title" className="import__title">
        {copy.formerTitle(former.length)}
      </h2>
      <p className="import__note">{copy.formerHint}</p>
      <PlainList className="import__errors" aria-label={copy.formerTitle(former.length)}>
        {former.map((row) => (
          <li key={row.row} className="import__error-row">
            <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
            {row.ignored.length > 0 && (
              <span className="import__kept-what">
                {copy.formerKept(row.ignored.map((field) => copy.fields[field]))}
              </span>
            )}
          </li>
        ))}
      </PlainList>
    </section>
  )
}

/** Rows that found someone already here whose record the sheet would change. */
function KeptRows({ rows }: { rows: RowResult[] }) {
  const kept = rows.filter((row) => row.errors.length === 0 && row.ignored.length > 0 && !newFormer(row))
  if (kept.length === 0) return null
  return (
    <section className="import__card" aria-labelledby="import-kept-title">
      <h2 id="import-kept-title" className="import__title">
        {copy.keptTitle}
      </h2>
      <p className="import__note">{copy.keptHint}</p>
      <PlainList className="import__errors" aria-label={copy.keptTitle}>
        {kept.map((row) => (
          <li key={row.row} className="import__error-row">
            <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
            <span className="import__kept-what">{copy.kept(row.ignored.map((field) => copy.fields[field]))}</span>
          </li>
        ))}
      </PlainList>
    </section>
  )
}

function RefusedRows({ rows }: { rows: RowResult[] }) {
  const refused = rows.filter((row) => row.errors.length > 0)
  if (refused.length === 0) return null
  return (
    <section className="import__card" aria-labelledby="import-errors-title">
      <h2 id="import-errors-title" className="import__title">
        {copy.errorsTitle}
      </h2>
      <p className="import__note">{copy.errorsHint}</p>
      <PlainList className="import__errors" aria-label={copy.errorsTitle}>
        {refused.map((row) => (
          <li key={row.row} className="import__error-row">
            <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
            {row.errors.map((error) => (
              <span key={`${error.field}-${error.code}`} className="import__error-what">
                {error.code === 'ambiguous_name'
                  ? copy.error.ambiguous_name
                  : copy.fieldError(copy.fields[error.field], copy.error[error.code])}
              </span>
            ))}
          </li>
        ))}
      </PlainList>
    </section>
  )
}
