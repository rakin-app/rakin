import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useMemo, useState, type ChangeEvent } from 'react'
import {
  fold,
  IMPORT_FIELDS,
  MAX_SHEET_BYTES,
  runImport,
  SHEET_TYPES,
  sheetRefusal,
  uploadSheet,
  type ImportField,
  type ImportReport,
  type Mapping,
  type RowResult,
  type Sheet,
} from '../api/memberImport'
import { plansQuery, type Plan } from '../api/people'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import './MemberImport.css'

const copy = t.admin.import

/**
 * "Importar alumnos": upload the gym's spreadsheet, say what each column is, check
 * every row without saving (the dry run), then import. The file is read once; the
 * rows stay here and go back to the API with the mapping each time.
 */
export function MemberImport() {
  const [file, setFile] = useState<{ name: string; sheet: Sheet } | null>(null)

  return (
    <>
      <PageHeader title={copy.title} eyebrow={copy.eyebrow} />
      <div className="import">
        {file === null ? (
          <SheetPicker onRead={(name, sheet) => setFile({ name, sheet })} />
        ) : (
          <SheetImport key={file.name} name={file.name} sheet={file.sheet} onOther={() => setFile(null)} />
        )}
      </div>
    </>
  )
}

function SheetPicker({ onRead }: { onRead: (name: string, sheet: Sheet) => void }) {
  const inputId = useId()
  const [tooLarge, setTooLarge] = useState(false)
  const read = useMutation({
    mutationFn: (file: File) => uploadSheet(file),
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
        <label htmlFor={inputId} className="import__button import__button--primary">
          {copy.choose}
        </label>
      </div>
      {read.isPending && (
        <p className="import__note" role="status">
          {copy.reading}
        </p>
      )}
      {problem && (
        <p className="import__error" role="alert">
          {problem}
        </p>
      )}
    </section>
  )
}

/** Column index to field, from the field-to-column mapping the API speaks. */
function byColumn(mapping: Mapping): (ImportField | '')[] {
  const columns: (ImportField | '')[] = []
  for (const field of IMPORT_FIELDS) {
    const column = mapping[field]
    if (column !== undefined) columns[column] = field
  }
  return columns
}

function SheetImport({ name, sheet, onOther }: { name: string; sheet: Sheet; onOther: () => void }) {
  const queryClient = useQueryClient()
  const plans = useQuery(plansQuery)
  const [mapping, setMapping] = useState<Mapping>(sheet.mapping)
  // The admin's choice of plan for a plan cell's value; absent means "as matched by name".
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const [report, setReport] = useState<ImportReport | null>(null)

  const planValues = useMemo(() => {
    const column = mapping.plan
    if (column === undefined) return []
    const values = new Map<string, string>()
    for (const row of sheet.rows) {
      const value = row.cells[column]?.trim()
      if (value && !values.has(fold(value))) values.set(fold(value), value)
    }
    return [...values.values()]
  }, [mapping.plan, sheet.rows])

  const matched = (value: string): string => {
    const key = fold(value)
    // An inactive plan of that name is left to the API, which reports it.
    return plans.data?.find((p) => p.active && fold(p.name) === key)?.id ?? ''
  }
  const planFor = (value: string) => chosen[value] ?? matched(value)

  const request = (dryRun: boolean) => {
    const choices: Record<string, string> = {}
    for (const value of planValues) {
      const plan = planFor(value)
      if (plan) choices[value] = plan
    }
    return runImport({ rows: sheet.rows, mapping, plans: choices, dry_run: dryRun })
  }
  const check = useMutation({ mutationFn: () => request(true), onSuccess: setReport })
  const apply = useMutation({
    mutationFn: () => request(false),
    onSuccess: (done) => {
      setReport(done)
      void queryClient.invalidateQueries({ queryKey: ['people'] })
    },
  })

  const setColumn = (column: number, field: ImportField | '') => {
    setMapping((current) => {
      const next: Mapping = {}
      for (const f of IMPORT_FIELDS) {
        // One column is one field: picking a field moves it here from wherever it was.
        if (current[f] !== undefined && current[f] !== column && f !== field) next[f] = current[f]
      }
      if (field) next[field] = column
      return next
    })
    setReport(null)
    check.reset()
  }

  if (report && !report.dry_run) {
    return <Done name={name} report={report} onOther={onOther} />
  }

  return (
    <>
      <section className="import__card">
        <div className="import__file-row">
          <span className="import__file-name">{copy.fileSummary(name, sheet.rows.length)}</span>
          <button type="button" className="import__button" onClick={onOther}>
            {copy.otherFile}
          </button>
        </div>
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
          <ColumnMapping sheet={sheet} columns={byColumn(mapping)} onChange={setColumn} />
          {planValues.length > 0 && (
            <PlanChoices
              values={planValues}
              plans={plans.data ?? []}
              planFor={planFor}
              onChange={(value, plan) => setChosen((current) => ({ ...current, [value]: plan }))}
            />
          )}
          <section className="import__card">
            {mapping.name === undefined && <p className="import__note">{copy.nameRequired}</p>}
            {check.isError && (
              <p className="import__error" role="alert">
                {copy.failed}
              </p>
            )}
            <button
              type="button"
              className="import__button import__button--primary"
              disabled={mapping.name === undefined || check.isPending}
              onClick={() => check.mutate()}
            >
              {check.isPending ? copy.checking : copy.check}
            </button>
          </section>
        </>
      )}
    </>
  )
}

function ColumnMapping({
  sheet,
  columns,
  onChange,
}: {
  sheet: Sheet
  columns: (ImportField | '')[]
  onChange: (column: number, field: ImportField | '') => void
}) {
  const baseId = useId()
  return (
    <section className="import__card" aria-labelledby={`${baseId}-title`}>
      <h2 id={`${baseId}-title`} className="import__title">
        {copy.mappingTitle}
      </h2>
      <p className="import__note">{copy.mappingHint}</p>
      <ul className="import__columns">
        {sheet.headers.map((header, column) => {
          const sample = sheet.rows.find((row) => row.cells[column])?.cells[column]
          const label = header || copy.unnamedColumn(column + 1)
          const id = `${baseId}-${column}`
          return (
            <li key={column} className="import__column">
              <label htmlFor={id} className="import__column-name">
                {label}
              </label>
              {sample && <span className="import__sample">{copy.sample(sample)}</span>}
              <select
                id={id}
                className="import__select"
                value={columns[column] ?? ''}
                onChange={(event) => onChange(column, event.target.value as ImportField | '')}
              >
                <option value="">{copy.skip}</option>
                {IMPORT_FIELDS.map((field) => (
                  <option key={field} value={field}>
                    {copy.fields[field]}
                  </option>
                ))}
              </select>
            </li>
          )
        })}
      </ul>
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
      <ul className="import__columns">
        {values.map((value, index) => {
          const id = `${baseId}-${index}`
          return (
            <li key={value} className="import__column">
              <label htmlFor={id} className="import__column-name">
                {value}
              </label>
              <select
                id={id}
                className="import__select"
                value={planFor(value)}
                onChange={(event) => onChange(value, event.target.value)}
              >
                <option value="">{copy.noPlan}</option>
                {plans
                  .filter((plan) => plan.active)
                  .map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name}
                    </option>
                  ))}
              </select>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Counts({ report }: { report: ImportReport }) {
  const { people_created: people, links_created: links, memberships_created: memberships } = report.summary
  return (
    <p className="import__note">
      {people + links + memberships === 0 ? copy.nothingNew : copy.created(people, links, memberships)}
    </p>
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
  const { imported, refused } = report.summary
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
          <p className="import__error" role="alert">
            {copy.applyFailed}
          </p>
        )}
        <div className="import__actions">
          <button type="button" className="import__button" onClick={onBack} disabled={applying}>
            {copy.back}
          </button>
          <button
            type="button"
            className="import__button import__button--primary"
            disabled={imported === 0 || applying}
            onClick={onApply}
          >
            {applying ? copy.applying : copy.apply(imported)}
          </button>
        </div>
      </section>
      <RefusedRows rows={report.rows} />
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
          {copy.doneSummary(name, report.summary.imported, report.summary.refused)}
        </p>
        <Counts report={report} />
        <div className="import__actions">
          <button type="button" className="import__button" onClick={onOther}>
            {copy.again}
          </button>
          <Link to="/admin/alumnos" className="import__button import__button--primary">
            {copy.toStudents}
          </Link>
        </div>
      </section>
      <RefusedRows rows={report.rows} />
    </>
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
      <ul className="import__errors" aria-label={copy.errorsTitle}>
        {refused.map((row) => (
          <li key={row.row} className="import__error-row">
            <span className="import__error-who">{copy.rowLabel(row.row, row.name)}</span>
            {row.errors.map((error) => (
              <span key={`${error.field}-${error.code}`} className="import__error-what">
                {copy.fieldError(copy.fields[error.field], copy.error[error.code])}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </section>
  )
}
