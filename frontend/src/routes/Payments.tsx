import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import {
  BOOK_FILTERS,
  ledgerBookQuery,
  type BookEntry,
  type BookFilter,
  type BookFreeze,
  type BookKpis,
  type PersonRef,
} from '../api/ledger'
import { myRoleQuery, readsLedger } from '../api/me'
import { membershipLedgerQuery, membershipsQuery, shownMembership } from '../api/member'
import { membersQuery, type MemberRow } from '../api/people'
import { pendingCountQuery } from '../api/proofs'
import { PageHeader } from '../components/PageHeader'
import { dayTime, isoDay, monthName, monthYear, shortDay, toDate } from '../format'
import { t } from '../i18n/es'
import { PaymentForm } from './MemberDetail'
import './Payments.css'

const copy = t.admin.payments
const clp = t.common.clp

// The month, filter and search live in the URL, so coming back to the book finds it as
// it was left.
export type PaymentsSearch = {
  // The first day of the month shown, `2026-10-01`; the current month when absent.
  month?: string
  filter?: BookFilter
  // A member's name, phone or RUT (#107).
  q?: string
}

export function validatePaymentsSearch(search: Record<string, unknown>): PaymentsSearch {
  const month = typeof search.month === 'string' && /^\d{4}-\d{2}-01$/.test(search.month) ? search.month : undefined
  const filter = BOOK_FILTERS.find((f) => f !== 'all' && f === search.filter)
  const q = typeof search.q === 'string' && search.q.trim() ? search.q : undefined
  return { month, filter, q }
}

// Typing waits this long before it becomes a search, as on the member list.
const SEARCH_DEBOUNCE_MS = 250
// The members the picker offers for what was typed.
const PICKER_ROWS = 8

const route = getRouteApi('/admin/pagos')

/**
 * "Libro de pagos": every ledger entry, newest first, with the month's KPIs. Owner and
 * admin only; a coach is told so and nothing is asked of the API.
 *
 * Freezes are not ledger entries, but the book lists where each started and ended
 * among them (#26), as rows with no amount. Reminders are not listed. Adjustments and
 * refunds are made on the member's detail (#38) and listed here with their sign.
 *
 * A search keeps a member's lines, and a guardian's dependents'; "Registrar pago" picks
 * a member and opens the member detail's payment form for them (#107).
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
  const q = search.q ?? ''
  const book = useInfiniteQuery({ ...ledgerBookQuery(search.month, filter, q), placeholderData: keepPreviousData })
  // The nav badge's count, so the link stands even while the book cannot load.
  const pending = useQuery(pendingCountQuery()).data ?? 0
  const monthId = useId()
  const searchId = useId()
  const [recording, setRecording] = useState(false)
  const [done, setDone] = useState<string | null>(null)

  const [draft, setDraft] = useState(q)
  useEffect(() => {
    if (draft.trim() === q.trim()) return
    const timer = setTimeout(() => {
      void navigate({ search: (prev) => ({ ...prev, q: draft.trim() ? draft : undefined }), replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft, q, navigate])

  // The last page loaded is the freshest: its total and KPIs are what the footer and
  // tiles show once "Cargar más" has run.
  const latest = book.data?.pages.at(-1)
  const rows = uniqueEntries(book.data?.pages.flatMap((page) => page.items) ?? [])
  const lines = latest ? bookLines(rows, latest.freezes, latest.timezone, !book.hasNextPage) : []
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
          <button
            type="button"
            className="payments__record"
            aria-expanded={recording}
            onClick={() => {
              setDone(null)
              setRecording(!recording)
            }}
          >
            {copy.record}
          </button>
        </div>
      </header>

      {done && (
        <p className="payments__done" role="status">
          {done}
        </p>
      )}
      {recording && (
        <RecordPayment
          onCancel={() => setRecording(false)}
          onDone={(message) => {
            setRecording(false)
            setDone(message)
          }}
        />
      )}

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
              <div role="search" className="payments__search">
                <label htmlFor={searchId} className="visually-hidden">
                  {copy.searchLabel}
                </label>
                <input
                  id={searchId}
                  type="search"
                  className="payments__search-input"
                  placeholder={copy.searchPlaceholder}
                  autoComplete="off"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </div>
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
              {lines.length === 0 ? (
                <p className="payments__note">{q.trim() ? copy.noMatch(q.trim()) : copy.empty}</p>
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
                      {lines.map((line) =>
                        line.kind === 'entry' ? (
                          <Row key={line.entry.id} entry={line.entry} timeZone={latest.timezone} />
                        ) : (
                          <FreezeRow key={`${line.line.freeze_id}-${line.line.edge}`} line={line.line} />
                        ),
                      )}
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

/** "Registrar pago" from the book: pick a member, then the member detail's payment form
 *  for the membership their detail shows. */
function RecordPayment({ onCancel, onDone }: { onCancel: () => void; onDone: (message: string) => void }) {
  const [member, setMember] = useState<MemberRow | null>(null)
  return (
    <section className="payments__record-panel" aria-label={copy.record}>
      {member ? (
        <PayFor member={member} onBack={() => setMember(null)} onDone={onDone} />
      ) : (
        <MemberPicker onPick={setMember} onCancel={onCancel} />
      )}
    </section>
  )
}

function MemberPicker({ onPick, onCancel }: { onPick: (member: MemberRow) => void; onCancel: () => void }) {
  const words = copy.picker
  const inputId = useId()
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setQ(draft.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft])
  const members = useInfiniteQuery({
    // Whoever left still owes what they owe, and pays it here.
    ...membersQuery({ q, status: [], plan: [], program: [], left: 'any' }),
    enabled: q !== '',
    placeholderData: keepPreviousData,
  })
  const found = q ? (members.data?.pages[0]?.items ?? []) : []

  return (
    <div className="payments__picker">
      <label htmlFor={inputId} className="payments__label">
        {words.label}
      </label>
      <input
        id={inputId}
        type="search"
        className="payments__search-input"
        placeholder={copy.searchPlaceholder}
        autoComplete="off"
        // The panel opens to pick someone: start where the typing goes.
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      {members.isError && (
        <p className="payments__error" role="alert">
          {words.error}
        </p>
      )}
      {q && members.isSuccess && found.length === 0 && <p className="payments__hint">{words.none}</p>}
      {found.length > 0 && (
        <ul className="payments__picks" aria-label={words.results}>
          {found.slice(0, PICKER_ROWS).map((row) => (
            <li key={row.id}>
              <button type="button" className="payments__pick" onClick={() => onPick(row)}>
                <span className="payments__pick-name">{row.name}</span>
                <span className="payments__pick-detail">{pickDetail(row)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="payments__button" onClick={onCancel}>
        {words.cancel}
      </button>
    </div>
  )
}

/** `Mensual adultos · Apoderado: Camila Ortiz`: who the picked row is. */
function pickDetail(row: MemberRow): string {
  const parts = [row.membership?.plan_name ?? t.admin.member.noPlan]
  if (row.guardian) parts.push(t.admin.students.guardianOf(row.guardian.name))
  else if (row.phone) parts.push(row.phone)
  return parts.join(' · ')
}

function PayFor({ member, onBack, onDone }: { member: MemberRow; onBack: () => void; onDone: (message: string) => void }) {
  const words = copy.picker
  const memberships = useQuery(membershipsQuery(member.id))
  const membership = memberships.data ? shownMembership(memberships.data) : undefined
  const ledger = useQuery({ ...membershipLedgerQuery(membership?.id ?? ''), enabled: membership !== undefined })
  const periods = ledger.data?.open_periods ?? []

  let body
  if (memberships.isError || ledger.isError) {
    body = (
      <p className="payments__error" role="alert">
        {words.error}
      </p>
    )
  } else if (memberships.isPending || (membership && ledger.isPending)) {
    body = <p className="payments__hint">{words.loading}</p>
  } else if (!membership) {
    body = <p className="payments__hint">{words.noPlan}</p>
  } else if (periods.length === 0) {
    body = <p className="payments__hint">{words.upToDate}</p>
  } else {
    body = <PaymentForm membership={membership} periods={periods} onCancel={onBack} onDone={onDone} />
  }

  return (
    <div className="payments__picker">
      <div className="payments__picked">
        <span>
          <span className="payments__pick-name">{member.name}</span>
          {membership && <span className="payments__pick-detail">{membership.plan_name}</span>}
        </span>
        <button type="button" className="payments__more" onClick={onBack}>
          {words.change}
        </button>
      </div>
      {body}
    </div>
  )
}

/** The pages' entries, each once: offset pages of a list that grows at its head can
 *  repeat an entry when one lands between two fetches. */
function uniqueEntries(entries: BookEntry[]): BookEntry[] {
  const seen = new Set<string>()
  return entries.filter((entry) => !seen.has(entry.id) && seen.add(entry.id))
}

type BookLine = { kind: 'entry'; entry: BookEntry } | { kind: 'freeze'; line: BookFreeze }

/** The entries loaded and the month's freeze lines among them, newest first, a freeze
 *  line after its day's entries. While more entries remain to load, a freeze line older
 *  than the last one loaded waits for the page it belongs on. */
function bookLines(entries: BookEntry[], freezes: BookFreeze[], timeZone: string, complete: boolean): BookLine[] {
  const lines: BookLine[] = []
  const waiting = [...freezes]
  for (const entry of entries) {
    const day = isoDay(entry.created_at, timeZone)
    while (waiting[0] && waiting[0].day > day) lines.push({ kind: 'freeze', line: waiting.shift()! })
    lines.push({ kind: 'entry', entry })
  }
  if (complete) lines.push(...waiting.map((line) => ({ kind: 'freeze' as const, line })))
  return lines
}

function Kpis({ kpis }: { kpis: BookKpis }) {
  const words = copy.kpis
  const days = kpis.overdue_avg_days.toLocaleString('es-CL', { maximumFractionDigits: 1 })
  const tiles = [
    {
      key: 'collected',
      label: words.collected,
      amount: kpis.collected_clp,
      detail: words.collectedDetail(kpis.collected_payments, kpis.refunds ? clp(kpis.refunded_clp) : null),
    },
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
      <Student person={entry.person} guardian={entry.guardian} />
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
        {bookAmount(entry)}
      </td>
    </tr>
  )
}

/** An adjustment with its sign, `+$5.000` in the member's favour or `−$5.000` owed; a
 * refund, money out, `−$10.000`. */
function bookAmount(entry: BookEntry): string {
  if (entry.kind === 'adjustment') return t.common.signedClp(entry.amount_clp)
  if (entry.kind === 'refund') return t.common.signedClp(-entry.amount_clp)
  return clp(entry.amount_clp)
}

function Student({ person, guardian }: { person: PersonRef; guardian: PersonRef | null }) {
  return (
    <td>
      <Link to="/admin/alumnos/$personId" params={{ personId: person.id }} className="payments__student">
        {person.name}
      </Link>
      {guardian && <span className="payments__guardian">{t.admin.students.guardianOf(guardian.name)}</span>}
    </td>
  )
}

/** A freeze starting or ending: the days it covers and why, with no amount. */
function FreezeRow({ line }: { line: BookFreeze }) {
  return (
    <tr className="payments__freeze">
      <td className="payments__muted">{shortDay(line.day)}</td>
      <Student person={line.person} guardian={line.guardian} />
      <td>{copy.kind.freeze}</td>
      <td>{t.common.span(shortDay(line.from_date), shortDay(line.to_date))}</td>
      <td>{line.reason}</td>
      <td>
        <span className="payments__pill payments__pill--muted">
          {line.edge === 'start' ? copy.status.freezeStart : copy.status.freezeEnd}
        </span>
      </td>
      <td className="payments__amount payments__muted">{t.common.noAmount}</td>
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
