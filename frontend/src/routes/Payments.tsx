import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useId } from 'react'
import { BOOK_FILTERS, ledgerBookQuery, type BookEntry, type BookFilter, type BookKpis } from '../api/ledger'
import { myRoleQuery, readsLedger } from '../api/me'
import { pendingCountQuery } from '../api/proofs'
import { PageHeader } from '../components/PageHeader'
import { dayTime, monthName, monthYear, shortDay, toDate } from '../format'
import { t } from '../i18n/es'
import './Payments.css'

const copy = t.admin.payments
const clp = t.common.clp

// The month and filter live in the URL, so coming back to the book finds it as it was left.
export type PaymentsSearch = {
  // The first day of the month shown, `2026-10-01`; the current month when absent.
  month?: string
  filter?: BookFilter
}

export function validatePaymentsSearch(search: Record<string, unknown>): PaymentsSearch {
  const month = typeof search.month === 'string' && /^\d{4}-\d{2}-01$/.test(search.month) ? search.month : undefined
  const filter = BOOK_FILTERS.find((f) => f !== 'all' && f === search.filter)
  return { month, filter }
}

const route = getRouteApi('/admin/pagos')

/**
 * "Libro de pagos": every ledger entry, newest first, with the month's KPIs. Owner and
 * admin only; a coach is told so and nothing is asked of the API.
 *
 * Reminders and freezes are not ledger entries, and refunds and manual adjustments
 * have no way in yet (#38), so the book lists what the ledger holds today.
 */
export function Payments() {
  const role = useQuery(myRoleQuery())

  if (readsLedger(role.data)) return <Book />
  return (
    <>
      <PageHeader title={copy.title} />
      {role.isError && (
        <p className="payments__note" role="alert">
          {copy.error}
        </p>
      )}
      {role.isSuccess && <p className="payments__note">{copy.coachesOnly}</p>}
    </>
  )
}

function Book() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const filter = search.filter ?? 'all'
  const book = useInfiniteQuery({ ...ledgerBookQuery(search.month, filter), placeholderData: keepPreviousData })
  // The nav badge's count, so the link stands even while the book cannot load.
  const pending = useQuery(pendingCountQuery()).data ?? 0
  const monthId = useId()

  // The last page loaded is the freshest: its total and KPIs are what the footer and
  // tiles show once "Cargar más" has run.
  const latest = book.data?.pages.at(-1)
  const rows = uniqueEntries(book.data?.pages.flatMap((page) => page.items) ?? [])
  const setSearch = (next: PaymentsSearch) => {
    void navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })
  }

  return (
    <div className="payments">
      <header className="payments__header">
        <div className="payments__heading">
          <h1 className="payments__title">{copy.title}</h1>
          <span className="payments__subtitle">{copy.subtitle}</span>
        </div>
        <div className="payments__actions">
          {latest && (
            <label htmlFor={monthId} className="payments__month">
              {copy.month}
              <select
                id={monthId}
                className="payments__month-select"
                value={latest.month}
                onChange={(event) => setSearch({ month: event.target.value })}
              >
                {latest.months.map((month) => (
                  <option key={month} value={month}>
                    {t.common.month(month, '')}
                  </option>
                ))}
              </select>
            </label>
          )}
          {pending > 0 && (
            <Link to="/admin/pagos/comprobantes" className="payments__review-link">
              {copy.review(pending)}
            </Link>
          )}
        </div>
      </header>

      {book.isPending ? (
        <p className="payments__note">{copy.loading}</p>
      ) : book.isError && !latest ? (
        <div className="payments__note" role="alert">
          <p>{copy.error}</p>
          <button type="button" className="payments__button" onClick={() => void book.refetch()}>
            {copy.retry}
          </button>
        </div>
      ) : (
        latest && (
          <>
            <Kpis kpis={latest.kpis} />
            <section className="payments__table-card" aria-label={copy.title}>
              <div role="group" aria-label={copy.filtersLabel} className="payments__filters">
                {BOOK_FILTERS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className="payments__chip"
                    aria-pressed={filter === value}
                    onClick={() => setSearch({ filter: value === 'all' ? undefined : value })}
                  >
                    {copy.filters[value]}
                  </button>
                ))}
              </div>
              {rows.length === 0 ? (
                <p className="payments__note">{copy.empty}</p>
              ) : (
                <div className="payments__scroll">
                  <table className="payments__table">
                    <thead>
                      <tr>
                        <th scope="col">{copy.columns.date}</th>
                        <th scope="col">{copy.columns.student}</th>
                        <th scope="col">{copy.columns.kind}</th>
                        <th scope="col">{copy.columns.period}</th>
                        <th scope="col">{copy.columns.method}</th>
                        <th scope="col">{copy.columns.status}</th>
                        <th scope="col" className="payments__amount">
                          {copy.columns.amount}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((entry) => (
                        <Row key={entry.id} entry={entry} timeZone={latest.timezone} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="payments__footer" aria-live="polite">
                <span>
                  {copy.showing(
                    rows.length,
                    latest.total,
                    filter === 'all' || filter === 'kids' ? monthName(latest.month) : null,
                  )}
                </span>
                {book.hasNextPage && (
                  <button
                    type="button"
                    className="payments__more"
                    disabled={book.isFetchingNextPage}
                    onClick={() => void book.fetchNextPage()}
                  >
                    {copy.more}
                  </button>
                )}
              </div>
            </section>
          </>
        )
      )}
    </div>
  )
}

/** The pages' entries, each once: offset pages of a list that grows at its head can
 *  repeat an entry when one lands between two fetches. */
function uniqueEntries(entries: BookEntry[]): BookEntry[] {
  const seen = new Set<string>()
  return entries.filter((entry) => !seen.has(entry.id) && seen.add(entry.id))
}

function Kpis({ kpis }: { kpis: BookKpis }) {
  const words = copy.kpis
  const days = kpis.overdue_avg_days.toLocaleString('es-CL', { maximumFractionDigits: 1 })
  const tiles = [
    { key: 'collected', label: words.collected, amount: kpis.collected_clp, detail: words.collectedDetail(kpis.collected_payments) },
    { key: 'pending', label: words.pending, amount: kpis.pending_clp, detail: words.pendingDetail(kpis.pending_payments) },
    { key: 'overdue', label: words.overdue, amount: kpis.overdue_clp, detail: words.overdueDetail(kpis.overdue_members, days) },
    {
      key: 'expected',
      label: words.expected,
      amount: kpis.expected_clp,
      detail: words.expectedDetail(kpis.active_memberships, kpis.frozen_memberships),
    },
  ]
  return (
    <section className="payments__kpis" aria-label={copy.kpisLabel}>
      {tiles.map((tile) => (
        <div key={tile.key} className={`payments__kpi payments__kpi--${tile.key}`}>
          <span className="payments__kpi-label">{tile.label}</span>
          <span className="payments__kpi-amount">{clp(tile.amount)}</span>
          <span className="payments__kpi-detail">{tile.detail}</span>
        </div>
      ))}
    </section>
  )
}

function Row({ entry, timeZone }: { entry: BookEntry; timeZone: string }) {
  const status = describeStatus(entry)
  return (
    <tr>
      <td className="payments__muted">{dayTime(entry.created_at, timeZone)}</td>
      <td>
        <Link to="/admin/alumnos/$personId" params={{ personId: entry.person.id }} className="payments__student">
          {entry.person.name}
        </Link>
        {entry.guardian && (
          <span className="payments__guardian">{t.admin.students.guardianOf(entry.guardian.name)}</span>
        )}
      </td>
      <td>{copy.kind[entry.kind]}</td>
      <td>{periodLabel(entry)}</td>
      <td>{mediumLabel(entry)}</td>
      <td>
        {status.review ? (
          <Link to="/admin/pagos/comprobantes" className={`payments__pill payments__pill--${status.tone}`}>
            {status.label}
          </Link>
        ) : (
          <span className={`payments__pill payments__pill--${status.tone}`}>{status.label}</span>
        )}
      </td>
      <td className={`payments__amount payments__amount--${entry.status}`}>
        {entry.kind === 'adjustment' ? `+${clp(entry.amount_clp)}` : clp(entry.amount_clp)}
      </td>
    </tr>
  )
}

// A month as the table says it: `Nov 2026`.
function shortMonth(iso: string): string {
  const label = monthYear(iso).replace('.', '')
  return label[0]!.toUpperCase() + label.slice(1)
}

// Longer than a month: a prepaid plan's whole span.
const MONTH_DAYS = 31

/** `Nov 2026`, or `Dic 2026 – May 2027` for a period longer than a month. */
function periodLabel(entry: BookEntry): string {
  const period = entry.period
  if (!period) return copy.credit
  const start = toDate(period.period_start)
  const end = toDate(period.period_end)
  const days = (end.getTime() - start.getTime()) / 86_400_000
  return days > MONTH_DAYS
    ? `${shortMonth(period.period_start)} – ${shortMonth(period.period_end)}`
    : shortMonth(period.period_start)
}

/** How the money came; for a charge, the plan it bills; for an adjustment, its note. */
function mediumLabel(entry: BookEntry): string {
  if (entry.kind === 'charge') return entry.plan_name
  if (entry.method) return copy.method[entry.method]
  return entry.note ?? '—'
}

type Tone = 'pending' | 'paid' | 'overdue' | 'muted'

function describeStatus(entry: BookEntry): { label: string; tone: Tone; review?: boolean } {
  const words = copy.status
  if (entry.kind === 'charge' && entry.period) {
    const period = entry.period
    if (period.outstanding_clp === 0) return { label: words.paid, tone: 'paid' }
    if (period.days_overdue > 0) return { label: words.overdue(period.days_overdue), tone: 'overdue' }
    return { label: words.open(shortDay(period.due_date)), tone: 'muted' }
  }
  if (entry.status === 'pending') return { label: words.pending, tone: 'pending', review: entry.kind === 'payment' }
  if (entry.status === 'rejected') return { label: words.rejected, tone: 'muted' }
  return {
    label: entry.validated_by_name ? words.validatedBy(entry.validated_by_name) : words.validated,
    tone: 'paid',
  }
}
