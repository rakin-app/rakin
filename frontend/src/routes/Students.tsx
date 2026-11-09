import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import {
  MEMBERSHIP_STATUSES,
  membersQuery,
  plansQuery,
  type MemberRow,
  type MembershipStatus,
} from '../api/people'
import { PageHeader } from '../components/PageHeader'
import { t } from '../i18n/es'
import { FamilyPanel } from './FamilyPanel'
import './Students.css'

const copy = t.admin.students

// The filters live in the URL, so coming back to the list finds it as it was left.
export type StudentsSearch = {
  q?: string
  status?: MembershipStatus[]
  plan?: string
}

export function validateStudentsSearch(search: Record<string, unknown>): StudentsSearch {
  const q = typeof search.q === 'string' && search.q.trim() ? search.q : undefined
  const raw = Array.isArray(search.status) ? search.status : [search.status]
  const status = MEMBERSHIP_STATUSES.filter((s) => raw.includes(s))
  const plan = typeof search.plan === 'string' && search.plan ? search.plan : undefined
  return { q, status: status.length ? status : undefined, plan }
}

const route = getRouteApi('/admin/alumnos')

// Typing waits this long before it becomes a search.
const SEARCH_DEBOUNCE_MS = 250

export function Students() {
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const status = search.status ?? []
  const filters = { q: search.q ?? '', status, plan: search.plan ? [search.plan] : [] }
  const filtered = filters.q.trim() !== '' || status.length > 0 || search.plan !== undefined

  const [draft, setDraft] = useState(filters.q)
  useEffect(() => {
    if (draft.trim() === filters.q.trim()) return
    const timer = setTimeout(() => {
      void navigate({ search: (prev) => ({ ...prev, q: draft.trim() ? draft : undefined }), replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft, filters.q, navigate])

  const members = useInfiniteQuery({ ...membersQuery(filters), placeholderData: keepPreviousData })
  // Without plans (an older API, a failed request) the list still works, unfiltered by plan.
  const plans = useQuery(plansQuery)

  const toggleStatus = (value: MembershipStatus) => {
    // In the chips' order, whatever the clicks', so a filter has one URL and one cache key.
    const next = MEMBERSHIP_STATUSES.filter((s) => (s === value ? !status.includes(s) : status.includes(s)))
    void navigate({ search: (prev) => ({ ...prev, status: next.length ? next : undefined }), replace: true })
  }
  const setPlan = (plan: string) => {
    void navigate({ search: (prev) => ({ ...prev, plan: plan || undefined }), replace: true })
  }
  const clear = () => {
    setDraft('')
    void navigate({ search: {}, replace: true })
  }

  const searchId = useId()
  const planId = useId()
  const rows = members.data?.pages.flatMap((page) => page.items) ?? []
  const total = members.data?.pages[0]?.total

  return (
    <>
      <PageHeader title={copy.title} />
      <div className="students">
        <div role="search" className="students__filters">
          <label htmlFor={searchId} className="visually-hidden">
            {copy.searchLabel}
          </label>
          <input
            id={searchId}
            type="search"
            className="students__search"
            placeholder={copy.searchPlaceholder}
            autoComplete="off"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div role="group" aria-label={copy.statusLabel} className="students__chips">
            {MEMBERSHIP_STATUSES.map((value) => (
              <button
                key={value}
                type="button"
                className="students__chip"
                aria-pressed={status.includes(value)}
                onClick={() => toggleStatus(value)}
              >
                {copy.status[value]}
              </button>
            ))}
          </div>
          {plans.data && plans.data.length > 0 && (
            <>
              <label htmlFor={planId} className="visually-hidden">
                {copy.planLabel}
              </label>
              <select
                id={planId}
                className="students__plan"
                value={search.plan ?? ''}
                onChange={(event) => setPlan(event.target.value)}
              >
                <option value="">{copy.allPlans}</option>
                {plans.data.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.active ? plan.name : copy.inactivePlan(plan.name)}
                  </option>
                ))}
              </select>
            </>
          )}
        </div>

        <div className="students__summary" aria-live="polite">
          {total !== undefined && <span>{copy.count(total)}</span>}
          {filtered && (
            <button type="button" className="students__clear" onClick={clear}>
              {copy.clearFilters}
            </button>
          )}
        </div>

        {members.isPending ? (
          <p className="students__note">{copy.loading}</p>
        ) : members.isError && rows.length === 0 ? (
          <div className="students__note" role="alert">
            <p>{copy.error}</p>
            <button type="button" className="students__button" onClick={() => void members.refetch()}>
              {copy.retry}
            </button>
          </div>
        ) : rows.length === 0 ? (
          <p className="students__note">{filtered ? copy.noMatches : copy.empty}</p>
        ) : (
          <ul className="students__list" aria-label={copy.title}>
            {rows.map((row) => (
              <MemberItem key={row.id} row={row} />
            ))}
          </ul>
        )}

        {members.hasNextPage && (
          <button
            type="button"
            className="students__button students__more"
            disabled={members.isFetchingNextPage}
            onClick={() => void members.fetchNextPage()}
          >
            {copy.more}
          </button>
        )}
      </div>
    </>
  )
}

function MemberItem({ row }: { row: MemberRow }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const details = [row.phone && formatPhone(row.phone), row.rut && formatRut(row.rut)].filter(Boolean)
  const family = row.guardian
    ? copy.guardianOf(row.guardian.name)
    : row.dependents > 0
      ? copy.dependentsCount(row.dependents)
      : null
  return (
    <li className="students__item">
      <div className="students__row">
        <div className="students__who">
          <Link to="/admin/alumnos/$personId" params={{ personId: row.id }} className="students__name">
            {row.name}
          </Link>
          {details.length > 0 && <span className="students__details">{details.join(' · ')}</span>}
          {family && <span className="students__details">{family}</span>}
        </div>
        <div className="students__plan-cell">
          {row.membership ? (
            <>
              <span className={`students__status students__status--${row.membership.status}`}>
                {copy.status[row.membership.status]}
              </span>
              <span className="students__plan-name">{row.membership.plan_name}</span>
            </>
          ) : (
            <span className="students__status">{copy.noPlan}</span>
          )}
          <button
            type="button"
            className="students__clear"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={t.admin.family.toggleLabel(row.name)}
            onClick={() => setOpen(!open)}
          >
            {t.admin.family.toggle}
          </button>
        </div>
      </div>
      {/* Always there, so `aria-controls` names an element; filled only when open. */}
      <div id={panelId} hidden={!open}>
        {open && <FamilyPanel person={row} />}
      </div>
    </li>
  )
}

/** `+56987654321` as `+56 9 8765 4321`; any other number as stored. */
export function formatPhone(phone: string): string {
  const match = /^\+56(9)(\d{4})(\d{4})$/.exec(phone)
  return match ? `+56 ${match[1]} ${match[2]} ${match[3]}` : phone
}

/** `7654321-6` as `7.654.321-6`. */
export function formatRut(rut: string): string {
  const [body, digit] = rut.split('-')
  if (!body || !digit) return rut
  return `${body.replace(/\B(?=(\d{3})+(?!\d))/g, '.')}-${digit}`
}
