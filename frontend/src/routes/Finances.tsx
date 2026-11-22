import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { useId, useState } from 'react'
import {
  financeMonthQuery,
  financeYearQuery,
  type CategoryYear,
  type FinanceMonth,
  type FinanceYear,
} from '../api/finances'
import { myAccessQuery, readsExpenses } from '../api/me'
import { Meter } from '../components/BarList'
import { Button } from '../components/Button'
import { Card, PlainList } from '../components/Card'
import { SegmentedControl } from '../components/Chip'
import { cx } from '../components/classNames'
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, ChevronUpIcon } from '../components/icons'
import { PageContainer } from '../components/Layout'
import { MoneyTabs } from '../components/MoneyTabs'
import { Loading } from '../components/Loading'
import { PageHeader, PageTitle } from '../components/PageHeader'
import { shiftMonth } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './Finances.css'

const copy = t.admin.finances
const clp = t.common.clp

export type FinancesSearch = {
  // The year, month by month; the month when absent.
  view?: 'year'
  // The first day of the month shown, `2026-10-01`; the current month when absent.
  month?: string
  // The year shown, `2026`; the current year when absent.
  year?: number
}

export function validateFinancesSearch(search: Record<string, unknown>): FinancesSearch {
  const view = search.view === 'year' ? 'year' : undefined
  const month = typeof search.month === 'string' && /^\d{4}-\d{2}-01$/.test(search.month) ? search.month : undefined
  const year = Number(search.year)
  return { view, month, year: Number.isInteger(year) && year >= 2000 && year <= 9999 ? year : undefined }
}

const route = getRouteApi('/admin/finanzas')

/**
 * Finanzas (#316): the month whole, what came in, what went out and what is left, and the
 * year month by month (docs/design/expenses-and-officers.md, section 13). Entradas is
 * Pagos' Cobrado, the same figure, split into plans and cobros extra; Salidas the month's
 * expenses that count, by category; Resultado the difference. It is the money section's
 * second tab, between Pagos and Gastos (#531).
 *
 * Who holds "Ver gastos" sees it. Without "Ver ingresos" the API sends no income, and the
 * page shows Salidas only, saying why. Anyone else is told so, and nothing is asked.
 */
export function Finances() {
  usePageTitle(copy.title)
  const access = useQuery(myAccessQuery())
  if (readsExpenses(access.data)) return <FinancesPage />
  return (
    <PageContainer>
      <PageHeader title={copy.title} />
      {access.isSuccess && <p className="finances__note">{t.admin.expenses.onlyWho}</p>}
    </PageContainer>
  )
}

function FinancesPage() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const go = (next: FinancesSearch) => void navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })
  const view = search.view ?? 'month'

  return (
    <PageContainer className="finances">
      <MoneyTabs />
      <header className="finances__header">
        <PageTitle>{copy.title}</PageTitle>
        <p className="finances__subtitle">{copy.subtitle}</p>
      </header>
      <div>
        <SegmentedControl
          label={copy.view.label}
          options={[
            { value: 'month', label: copy.view.month },
            { value: 'year', label: copy.view.year },
          ]}
          value={view}
          onChange={(next) => go({ view: next === 'year' ? 'year' : undefined })}
        />
      </div>
      {view === 'year' ? (
        <YearView year={search.year} onYear={(year) => go({ year })} />
      ) : (
        <MonthView month={search.month} onMonth={(month) => go({ month })} />
      )}
    </PageContainer>
  )
}

/** `+$917.010`, `−$50.000`. */
function signed(amount: number): string {
  return amount === 0 ? clp(0) : t.common.signedClp(amount)
}

function Stepper({
  label,
  shown,
  previous,
  next,
  canPrevious,
  canNext,
  onPrevious,
  onNext,
}: {
  label: string
  shown: string
  previous: string
  next: string
  canPrevious: boolean
  canNext: boolean
  onPrevious: () => void
  onNext: () => void
}) {
  return (
    <div className="finances__stepper" role="group" aria-label={label}>
      <Button icon variant="ghost" aria-label={previous} disabled={!canPrevious} onClick={onPrevious}>
        <ChevronLeftIcon />
      </Button>
      <span className="finances__stepper-label" aria-live="polite">
        {shown}
      </span>
      <Button icon variant="ghost" aria-label={next} disabled={!canNext} onClick={onNext}>
        <ChevronRightIcon />
      </Button>
    </div>
  )
}

/** Entradas, Salidas and Resultado side by side; Salidas alone without income. */
function Tiles({ income, expenses, result }: { income: number | null; expenses: number; result: number | null }) {
  return (
    <dl className={cx('finances__tiles', income === null && 'finances__tiles--one')}>
      {income !== null && (
        <div className="finances__tile">
          <dt>{copy.income}</dt>
          <dd>{clp(income)}</dd>
        </div>
      )}
      <div className="finances__tile">
        <dt>{copy.expenses}</dt>
        <dd>{clp(expenses)}</dd>
      </div>
      {result !== null && (
        <div className="finances__tile">
          <dt>{copy.result}</dt>
          <dd className={cx(result < 0 && 'finances__negative')}>{signed(result)}</dd>
        </div>
      )}
    </dl>
  )
}

function Failed({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="finances__note" role="alert">
      <p>{copy.error}</p>
      <Button onClick={onRetry}>{copy.retry}</Button>
    </div>
  )
}

function MonthView({ month, onMonth }: { month: string | undefined; onMonth: (month: string) => void }) {
  const query = useQuery({ ...financeMonthQuery(month), placeholderData: keepPreviousData })
  const shown = query.data
  const shownMonth = shown?.month ?? month
  return (
    <>
      <Stepper
        label={copy.month}
        shown={shownMonth ? t.common.month(shownMonth, '') : ''}
        previous={copy.previous}
        next={copy.next}
        canPrevious={Boolean(shownMonth)}
        canNext={Boolean(shown && shown.month < shown.current_month)}
        onPrevious={() => shownMonth && onMonth(shiftMonth(shownMonth, -1))}
        onNext={() => shown && onMonth(shiftMonth(shown.month, 1))}
      />
      {query.isPending ? (
        <Loading className="finances__note">{copy.loading}</Loading>
      ) : query.isError && !shown ? (
        <Failed onRetry={() => void query.refetch()} />
      ) : (
        shown && <Month shown={shown} />
      )}
    </>
  )
}

function Month({ shown }: { shown: FinanceMonth }) {
  const { income } = shown
  return (
    <Card className="finances__card" aria-label={copy.monthLabel(t.common.month(shown.month, ''))}>
      <Tiles income={income?.total_clp ?? null} expenses={shown.expenses_clp} result={shown.result_clp} />
      {shown.recovered && (
        <p className="finances__hint">
          {copy.recovered(clp(shown.recovered.paid_clp), clp(shown.recovered.collected_clp))}
        </p>
      )}
      {income === null && <p className="finances__note">{copy.onlyExpenses}</p>}
      {income !== null && (
        <section className="finances__group" aria-label={copy.income}>
          <h2 className="finances__group-title">{copy.income}</h2>
          <PlainList className="finances__lines">
            <li className="finances__line">
              <span>{copy.plans}</span>
              <span className="finances__figure">{clp(income.plans_clp)}</span>
            </li>
            <li className="finances__line">
              <span>{copy.extra}</span>
              <span className="finances__figure">{clp(income.extra_clp)}</span>
            </li>
          </PlainList>
          <p className="finances__hint">{copy.incomeNote}</p>
        </section>
      )}
      <section className="finances__group" aria-label={copy.expenses}>
        <h2 className="finances__group-title">{copy.expenses}</h2>
        {shown.categories.length === 0 ? (
          <p className="finances__hint">{copy.noExpenses}</p>
        ) : (
          <PlainList className="finances__lines">
            {shown.categories.map((c) => (
              <li key={c.category_id} className="finances__line">
                <span>{c.name}</span>
                <span className="finances__figure">{clp(c.amount_clp)}</span>
              </li>
            ))}
          </PlainList>
        )}
      </section>
    </Card>
  )
}

function YearView({ year, onYear }: { year: number | undefined; onYear: (year: number) => void }) {
  const query = useQuery({ ...financeYearQuery(year), placeholderData: keepPreviousData })
  const shown = query.data
  const shownYear = shown?.year ?? year
  const currentYear = shown ? Number(shown.current_month.slice(0, 4)) : undefined
  return (
    <>
      <Stepper
        label={copy.yearNav}
        shown={shownYear ? String(shownYear) : ''}
        previous={copy.previousYear}
        next={copy.nextYear}
        canPrevious={Boolean(shownYear)}
        canNext={Boolean(shown && currentYear !== undefined && shown.year < currentYear)}
        onPrevious={() => shownYear && onYear(shownYear - 1)}
        onNext={() => shown && onYear(shown.year + 1)}
      />
      {query.isPending ? (
        <Loading className="finances__note">{copy.loading}</Loading>
      ) : query.isError && !shown ? (
        <Failed onRetry={() => void query.refetch()} />
      ) : (
        shown && <Year shown={shown} />
      )}
    </>
  )
}

function Year({ shown }: { shown: FinanceYear }) {
  const sees = shown.income_clp !== null
  // The bars at 1280 share one scale: the year's largest month, in or out.
  const longest = Math.max(1, ...shown.months.flatMap((m) => [m.income_clp ?? 0, m.expenses_clp]))
  const year = String(shown.year)
  return (
    <>
      <Card className="finances__card" aria-label={copy.yearLabel(year)}>
        <Tiles income={shown.income_clp} expenses={shown.expenses_clp} result={shown.result_clp} />
        {!sees && <p className="finances__note">{copy.onlyExpenses}</p>}
        <table className={cx('finances__year', !sees && 'finances__year--expenses')}>
          <thead>
            <tr>
              <th scope="col">{copy.columns.month}</th>
              {sees && <th scope="col">{copy.columns.income}</th>}
              <th scope="col">{copy.columns.expenses}</th>
              {sees && <th scope="col">{copy.columns.result}</th>}
            </tr>
          </thead>
          <tbody>
            {shown.months.map((m) => {
              const later = m.month > shown.current_month
              return (
                <tr key={m.month} className={cx(later && 'finances__later')}>
                  <th scope="row">{t.common.month(m.month, year)}</th>
                  {sees && (
                    <td data-label={copy.columns.income}>
                      <span className="finances__figure">{later ? copy.none : clp(m.income_clp ?? 0)}</span>
                      {!later && (
                        <span className="finances__bar finances__bar--in">
                          <Meter value={m.income_clp ?? 0} of={longest} />
                        </span>
                      )}
                    </td>
                  )}
                  <td data-label={copy.columns.expenses}>
                    <span className="finances__figure">{later ? copy.none : clp(m.expenses_clp)}</span>
                    {!later && (
                      <span className="finances__bar finances__bar--out">
                        <Meter value={m.expenses_clp} of={longest} />
                      </span>
                    )}
                  </td>
                  {sees && (
                    <td
                      data-label={copy.columns.result}
                      className={cx((m.result_clp ?? 0) < 0 && !later && 'finances__negative')}
                    >
                      <span className="finances__figure">{later ? copy.none : signed(m.result_clp ?? 0)}</span>
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{copy.total}</th>
              {sees && (
                <td data-label={copy.columns.income} className="finances__figure">
                  {clp(shown.income_clp ?? 0)}
                </td>
              )}
              <td data-label={copy.columns.expenses} className="finances__figure">
                {clp(shown.expenses_clp)}
              </td>
              {sees && (
                <td
                  data-label={copy.columns.result}
                  className={cx('finances__figure', (shown.result_clp ?? 0) < 0 && 'finances__negative')}
                >
                  {signed(shown.result_clp ?? 0)}
                </td>
              )}
            </tr>
          </tfoot>
        </table>
      </Card>
      <Card flush className="finances__card" aria-label={copy.byCategory}>
        <h2 className="finances__group-title finances__group-title--padded">{copy.byCategory}</h2>
        {shown.categories.length === 0 ? (
          <p className="finances__hint finances__hint--padded">{copy.noExpensesYear}</p>
        ) : (
          <PlainList className="finances__categories">
            {shown.categories.map((c) => (
              <CategoryRow key={c.category_id} category={c} year={shown} />
            ))}
          </PlainList>
        )}
      </Card>
    </>
  )
}

/** A category's year, opening to the months it had expenses in. */
function CategoryRow({ category, year }: { category: CategoryYear; year: FinanceYear }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const label = String(year.year)
  return (
    <li className="finances__category">
      <button
        type="button"
        className="finances__category-button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(!open)}
      >
        <span>{category.name}</span>
        <span className="finances__figure">{clp(category.amount_clp)}</span>
        <span className="finances__chevron" aria-hidden="true">
          {open ? <ChevronUpIcon /> : <ChevronDownIcon />}
        </span>
      </button>
      {open && (
        <PlainList id={panelId} className="finances__category-months" aria-label={copy.categoryMonths(category.name)}>
          {year.months.map((m, i) =>
            (category.months[i] ?? 0) === 0 ? null : (
              <li key={m.month} className="finances__line">
                <span>{t.common.month(m.month, label)}</span>
                <span className="finances__figure">{clp(category.months[i] ?? 0)}</span>
              </li>
            ),
          )}
        </PlainList>
      )}
    </li>
  )
}
