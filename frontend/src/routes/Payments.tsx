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
import { Button, buttonClass } from '../components/Button'
import { ListRowContent, listRowClass } from '../components/Card'
import { Chip, ChipGroup } from '../components/Chip'
import { SearchInput } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { StatusPill, type Status } from '../components/StatusPill'
import { dayTime, isoDay, monthName, monthYear, shortDay, toDate } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { PaymentAheadForm, PaymentForm } from './MemberDetail'
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
 * Pagos, the gym's book: every ledger entry, newest first, with the month's KPIs. Owner
 * and admin only; a coach is told so and nothing is asked of the API.
 *
 * Freezes are not ledger entries, but the book lists where each started and ended
 * among them (#26), as rows with no amount. Reminders are not listed. Adjustments and
 * refunds are made on the member's detail (#38) and listed here with their sign.
 *
 * A search keeps a member's lines, and a guardian's dependents'; "Registrar pago" picks
 * a member and opens the member detail's payment form for them (#107).
 *
 * One primary action: "Revisar N comprobantes" while proofs wait, else "Registrar pago".
 * Below 960px each line of the table is drawn as a card (Payments.css) and the KPIs are
 * a 2×2 grid, so a phone sees name, status and amount with no sideways scroll (#180).
 */
export function Payments() {
  usePageTitle(t.nav.payments)
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
    <PageContainer className="payments">
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
          <Link to="/admin/pagos/cobros" className={buttonClass({ variant: 'ghost' })}>
            {copy.extra}
          </Link>
          {pending > 0 && (
            <Link to="/admin/pagos/comprobantes" className={buttonClass({ variant: 'primary' })}>
              {copy.review(pending)}
            </Link>
          )}
          <Button
            variant={pending > 0 ? 'secondary' : 'primary'}
            aria-expanded={recording}
            onClick={() => {
              setDone(null)
              setRecording(!recording)
            }}
          >
            {copy.record}
          </Button>
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
          <Button onClick={() => void book.refetch()}>{copy.retry}</Button>
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
                <SearchInput
                  id={searchId}
                  className="payments__search-input"
                  placeholder={copy.searchPlaceholder}
                  autoComplete="off"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </div>
              <div className="payments__filters">
                <ChipGroup label={copy.filtersLabel}>
                  {BOOK_FILTERS.map((value) => (
                    <Chip
                      key={value}
                      pressed={filter === value}
                      onClick={() => setSearch({ filter: value === 'all' ? undefined : value })}
                    >
                      {copy.filters[value]}
                    </Chip>
                  ))}
                </ChipGroup>
              </div>
              {lines.length === 0 ? (
                <p className="payments__note">{q.trim() ? copy.noMatch(q.trim()) : copy.empty}</p>
              ) : (
                <div className="payments__scroll">
                  {/* Explicit roles: below 960px the cards set `display` on the table, its groups and
                      rows, and WebKit then drops their implicit roles, so VoiceOver would
                      stop reading the column headers with each cell. */}
                  <table className="payments__table" role="table">
                    <thead role="rowgroup">
                      <tr role="row">
                        <th role="columnheader" scope="col">{copy.columns.date}</th>
                        <th role="columnheader" scope="col">{copy.columns.student}</th>
                        <th role="columnheader" scope="col">{copy.columns.kind}</th>
                        <th role="columnheader" scope="col">{copy.columns.period}</th>
                        <th role="columnheader" scope="col">{copy.columns.detail}</th>
                        <th role="columnheader" scope="col">{copy.columns.status}</th>
                        <th role="columnheader" scope="col" className="payments__amount">
                          {copy.columns.amount}
                        </th>
                      </tr>
                    </thead>
                    <tbody role="rowgroup">
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
                  <Button
                    variant="ghost"
                    disabled={book.isFetchingNextPage}
                    onClick={() => void book.fetchNextPage()}
                  >
                    {copy.more}
                  </Button>
                )}
              </div>
            </section>
          </>
        )
      )}
    </PageContainer>
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
      <SearchInput
        id={inputId}
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
              <button type="button" className={listRowClass(true)} onClick={() => onPick(row)}>
                <ListRowContent title={row.name} detail={pickDetail(row)} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Button onClick={onCancel}>
        {words.cancel}
      </Button>
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
    body = (
      <PaymentAheadForm
        membership={membership}
        onCancel={onBack}
        onDone={onDone}
        nothing={<p className="payments__hint">{words.upToDate}</p>}
      />
    )
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
        <Button variant="ghost" onClick={onBack}>
          {words.change}
        </Button>
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
      detail:
        words.collectedDetail(kpis.collected_payments, kpis.refunds ? clp(kpis.refunded_clp) : null) +
        (kpis.collected_extra_clp ? copy.kpiExtra(clp(kpis.collected_extra_clp)) : ''),
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
    <tr className="payments__line" role="row">
      <td role="cell" className="payments__muted payments__date">{entryDate(entry, timeZone)}</td>
      <Student person={entry.person} guardian={entry.guardian} />
      <td role="cell" className="payments__kind">{kindLabel(entry)}</td>
      <td role="cell" className="payments__period">{periodLabel(entry)}</td>
      <td role="cell" className="payments__detail">{detailLabel(entry)}</td>
      <td role="cell" className="payments__status">
        {status.review ? (
          <Link to="/admin/pagos/comprobantes" className="payments__to-review">
            <StatusPill status={status.status}>{status.label}</StatusPill>
          </Link>
        ) : (
          <StatusPill status={status.status}>{status.label}</StatusPill>
        )}
      </td>
      {/* A voided charge (#256) is struck through as a rejected payment is. */}
      <td role="cell" className={`payments__amount payments__amount--${entry.voided ? 'rejected' : entry.status}`}>
        {bookAmount(entry)}
      </td>
    </tr>
  )
}

/** A charge on a period by the day its period starts, the day the book files it under
 * (#206); any other entry by when it was made, `8 nov 14:12`. */
function entryDate(entry: BookEntry, timeZone: string): string {
  if (entry.kind === 'charge' && entry.period) return shortDay(entry.period.period_start)
  return dayTime(entry.created_at, timeZone)
}

/** `Descuento` or `Recargo` for an adjustment on a period (#210); any other kind as named. */
function kindLabel(entry: BookEntry): string {
  if (entry.voids) return copy.void
  if (entry.kind === 'adjustment' && entry.period) return copy.adjustment[entry.amount_clp > 0 ? 'favor' : 'owed']
  return copy.kind[entry.kind]
}

/** An adjustment by what it does to what is owed, a discount `−$5.000` and a surcharge
 * `+$5.000`, and a carried credit as held; a refund, money out, `−$10.000`. */
function bookAmount(entry: BookEntry): string {
  if (entry.kind === 'adjustment' && entry.period) return t.common.adjustmentClp(entry.amount_clp)
  if (entry.kind === 'refund') return t.common.signedClp(-entry.amount_clp)
  return clp(entry.amount_clp)
}

function Student({ person, guardian }: { person: PersonRef; guardian: PersonRef | null }) {
  return (
    <td role="cell" className="payments__who">
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
    <tr className="payments__line payments__freeze" role="row">
      <td role="cell" className="payments__muted payments__date">{shortDay(line.day)}</td>
      <Student person={line.person} guardian={line.guardian} />
      <td role="cell" className="payments__kind">{copy.kind.freeze}</td>
      <td role="cell" className="payments__period">{t.common.span(shortDay(line.from_date), shortDay(line.to_date))}</td>
      <td role="cell" className="payments__detail">{line.reason}</td>
      <td role="cell" className="payments__status">
        <StatusPill status="freeze">{line.edge === 'start' ? copy.status.freezeStart : copy.status.freezeEnd}</StatusPill>
      </td>
      <td role="cell" className="payments__amount payments__muted">{t.common.noAmount}</td>
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
  if (entry.extra) return entry.extra.title
  const period = entry.period
  if (!period) return copy.credit
  const start = toDate(period.period_start)
  const end = toDate(period.period_end)
  const days = (end.getTime() - start.getTime()) / 86_400_000
  return days > MONTH_DAYS
    ? `${shortMonth(period.period_start)} – ${shortMonth(period.period_end)}`
    : shortMonth(period.period_start)
}

/** The "Detalle" column: how the money came; for a charge, the plan it bills, and what
 *  became of the membership once it is no longer active (#207); for an adjustment, its
 *  note. */
function detailLabel(entry: BookEntry): string {
  if (entry.voided) {
    const { reason, by_name, at } = entry.voided
    return t.admin.member.ledger.voided(reason, by_name, shortDay(isoDay(at)))
  }
  if (entry.kind === 'charge') {
    const plan = entry.plan_name ?? '—'
    const membership = entry.membership_status && copy.membership[entry.membership_status]
    return membership ? `${plan} · ${membership}` : plan
  }
  // A cobro extra, labelled by its category (#195), then how the money came.
  if (entry.extra) {
    const category = t.admin.extra.category[entry.extra.category]
    return entry.method ? `${category} · ${copy.method[entry.method]}` : category
  }
  if (entry.method) return copy.method[entry.method]
  return entry.note ?? '—'
}

function describeStatus(entry: BookEntry): { label: string; status: Status; review?: boolean } {
  const words = copy.status
  if (entry.voided) return { label: words.voided, status: 'cancelled' }
  if (entry.kind === 'charge' && entry.period) {
    const period = entry.period
    if (period.outstanding_clp === 0) return { label: words.paid, status: 'paid' }
    if (period.days_overdue > 0) return { label: words.overdue(period.days_overdue), status: 'overdue' }
    return { label: words.open(shortDay(period.due_date)), status: 'open' }
  }
  if (entry.status === 'pending') return { label: words.pending, status: 'pending', review: entry.kind === 'payment' }
  if (entry.status === 'rejected') return { label: words.rejected, status: 'rejected' }
  return {
    label: entry.validated_by_name ? words.validatedBy(entry.validated_by_name) : words.validated,
    status: 'validated',
  }
}
