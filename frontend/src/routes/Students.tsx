import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import { myRoleQuery, readsLedger } from '../api/me'
import {
  MEMBERSHIP_STATUSES,
  membersQuery,
  plansQuery,
  programsQuery,
  type MemberRow,
  type MembershipStatus,
} from '../api/people'
import { Button, buttonClass } from '../components/Button'
import { Chip, ChipGroup } from '../components/Chip'
import { Input, Select } from '../components/Field'
import { JoinRequests } from '../components/JoinRequests'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { StatusPill } from '../components/StatusPill'
import { formatPhone, formatRut } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { FamilyPanel } from './FamilyPanel'
import './Students.css'

const copy = t.admin.students

// The filters live in the URL, so coming back to the list finds it as it was left.
export type StudentsSearch = {
  q?: string
  status?: MembershipStatus[]
  plan?: string
  program?: string
  // "Dados de baja": who has left the gym, instead of who is in it.
  left?: true
  // "Falta teléfono": members the gym cannot reach on WhatsApp yet (#165).
  missingPhone?: true
  // "Falta RUT": members with neither a RUT nor an email, found again only by name.
  missingRut?: true
  // "Sin venir 14 d": members away 14 days or more, as Hoy's "A quién llamar" counts them.
  away?: true
}

export function validateStudentsSearch(search: Record<string, unknown>): StudentsSearch {
  const q = typeof search.q === 'string' && search.q.trim() ? search.q : undefined
  const raw = Array.isArray(search.status) ? search.status : [search.status]
  const status = MEMBERSHIP_STATUSES.filter((s) => raw.includes(s))
  const plan = typeof search.plan === 'string' && search.plan ? search.plan : undefined
  const program = typeof search.program === 'string' && search.program ? search.program : undefined
  const left = search.left === true || search.left === 'true' ? true : undefined
  const missingPhone = search.missingPhone === true || search.missingPhone === 'true' ? true : undefined
  const missingRut = search.missingRut === true || search.missingRut === 'true' ? true : undefined
  const away = search.away === true || search.away === 'true' ? true : undefined
  return { q, status: status.length ? status : undefined, plan, program, left, missingPhone, missingRut, away }
}

const route = getRouteApi('/admin/alumnos')

// Typing waits this long before it becomes a search.
const SEARCH_DEBOUNCE_MS = 250

export function Students() {
  usePageTitle(copy.title)
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const status = search.status ?? []
  const filters = {
    q: search.q ?? '',
    status,
    plan: search.plan ? [search.plan] : [],
    program: search.program ? [search.program] : [],
    left: search.left ? ('only' as const) : ('no' as const),
    missingPhone: search.missingPhone === true,
    missingRut: search.missingRut === true,
    away: search.away === true,
  }
  const filtered =
    filters.q.trim() !== '' ||
    status.length > 0 ||
    search.plan !== undefined ||
    search.program !== undefined ||
    search.left !== undefined ||
    search.missingPhone !== undefined ||
    search.missingRut !== undefined ||
    search.away !== undefined

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
  // Likewise programs: a gym that has none yet gets no program filter.
  const programs = useQuery(programsQuery)
  // Importing starts memberships, which only an owner or admin may.
  const role = useQuery(myRoleQuery())

  const toggleStatus = (value: MembershipStatus) => {
    // In the chips' order, whatever the clicks', so a filter has one URL and one cache key.
    const next = MEMBERSHIP_STATUSES.filter((s) => (s === value ? !status.includes(s) : status.includes(s)))
    void navigate({ search: (prev) => ({ ...prev, status: next.length ? next : undefined }), replace: true })
  }
  const toggleLeft = () => {
    void navigate({ search: (prev) => ({ ...prev, left: prev.left ? undefined : true }), replace: true })
  }
  const toggleMissingRut = () => {
    void navigate({
      search: (prev) => ({ ...prev, missingRut: prev.missingRut ? undefined : true }),
      replace: true,
    })
  }
  const toggleMissingPhone = () => {
    void navigate({
      search: (prev) => ({ ...prev, missingPhone: prev.missingPhone ? undefined : true }),
      replace: true,
    })
  }
  const toggleAway = () => {
    void navigate({ search: (prev) => ({ ...prev, away: prev.away ? undefined : true }), replace: true })
  }
  const setPlan = (plan: string) => {
    void navigate({ search: (prev) => ({ ...prev, plan: plan || undefined }), replace: true })
  }
  const setProgram = (program: string) => {
    void navigate({ search: (prev) => ({ ...prev, program: program || undefined }), replace: true })
  }
  const clear = () => {
    setDraft('')
    void navigate({ search: {}, replace: true })
  }

  const searchId = useId()
  const planId = useId()
  const programId = useId()
  const rows = members.data?.pages.flatMap((page) => page.items) ?? []
  const total = members.data?.pages[0]?.total

  return (
    <PageContainer className="students__page">
      <PageHeader title={copy.title} />
      <JoinRequests />
      <div className="students">
        {readsLedger(role.data) && (
          <div className="students__links">
            <Link to="/admin/alumnos/nuevo" className={buttonClass({ variant: 'primary' })}>
              {copy.newLink}
            </Link>
            <Link to="/admin/alumnos/importar" className={buttonClass()}>
              {copy.importLink}
            </Link>
          </div>
        )}
        <div role="search" className="students__filters">
          <label htmlFor={searchId} className="visually-hidden">
            {copy.searchLabel}
          </label>
          <Input
            id={searchId}
            type="search"
            className="students__search"
            placeholder={copy.searchPlaceholder}
            autoComplete="off"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <ChipGroup label={copy.statusLabel}>
            {MEMBERSHIP_STATUSES.map((value) => (
              <Chip key={value} pressed={status.includes(value)} onClick={() => toggleStatus(value)}>
                {copy.status[value]}
              </Chip>
            ))}
            <Chip pressed={search.left === true} onClick={toggleLeft}>
              {copy.left}
            </Chip>
            <Chip pressed={search.missingPhone === true} onClick={toggleMissingPhone}>
              {copy.missingPhone}
            </Chip>
            <Chip pressed={search.missingRut === true} onClick={toggleMissingRut}>
              {copy.missingRut}
            </Chip>
            <Chip pressed={search.away === true} onClick={toggleAway}>
              {copy.away}
            </Chip>
          </ChipGroup>
          {plans.data && plans.data.length > 0 && (
            <>
              <label htmlFor={planId} className="visually-hidden">
                {copy.planLabel}
              </label>
              <Select
                id={planId}
                className="students__picker"
                value={search.plan ?? ''}
                onChange={(event) => setPlan(event.target.value)}
              >
                <option value="">{copy.allPlans}</option>
                {plans.data.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.active ? plan.name : copy.inactivePlan(plan.name)}
                  </option>
                ))}
              </Select>
            </>
          )}
          {programs.data && programs.data.length > 0 && (
            <>
              <label htmlFor={programId} className="visually-hidden">
                {copy.programLabel}
              </label>
              <Select
                id={programId}
                className="students__picker"
                value={search.program ?? ''}
                onChange={(event) => setProgram(event.target.value)}
              >
                <option value="">{copy.allPrograms}</option>
                {programs.data.map((program) => (
                  <option key={program.id} value={program.id}>
                    {program.active ? program.name : copy.inactiveProgram(program.name)}
                  </option>
                ))}
              </Select>
            </>
          )}
        </div>

        <div className="students__summary" aria-live="polite">
          {total !== undefined && <span>{copy.count(total)}</span>}
          {filtered && (
            <Button variant="ghost" onClick={clear}>
              {copy.clearFilters}
            </Button>
          )}
        </div>

        {members.isPending ? (
          <p className="students__note">{copy.loading}</p>
        ) : members.isError && rows.length === 0 ? (
          <div className="students__note" role="alert">
            <p>{copy.error}</p>
            <Button onClick={() => void members.refetch()}>
              {copy.retry}
            </Button>
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
          <Button
            className="students__more"
            disabled={members.isFetchingNextPage}
            onClick={() => void members.fetchNextPage()}
          >
            {copy.more}
          </Button>
        )}
      </div>
    </PageContainer>
  )
}

function MemberItem({ row }: { row: MemberRow }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const family = row.guardian
    ? copy.guardianOf(row.guardian.name)
    : row.dependents > 0
      ? copy.dependentsCount(row.dependents)
      : null
  return (
    <li className="students__item">
      <div className="students__row">
        <div className="students__who">
          {/* The name and what more there is to say about them; on a desktop, one cell. */}
          <div className="students__title">
            <Link to="/admin/alumnos/$personId" params={{ personId: row.id }} className="students__name">
              {row.name}
            </Link>
            {family && <span className="students__details">{family}</span>}
            {row.left_on && <span className="students__details">{copy.leftOn(t.common.day(row.left_on))}</span>}
            {row.missing_phone && <span className="students__flag">{copy.missingPhone}</span>}
            {row.missing_rut && <span className="students__flag">{copy.missingRut}</span>}
            {row.no_whatsapp && <span className="students__details">{copy.noWhatsapp}</span>}
          </div>
          {(row.phone || row.rut) && (
            // One line on a phone; on a desktop, a column each.
            <span className="students__details students__contact">
              {row.phone && <span className="students__phone">{formatPhone(row.phone)}</span>}
              {row.rut && <span className="students__rut">{formatRut(row.rut)}</span>}
            </span>
          )}
        </div>
        <div className="students__plan-cell">
          {row.membership ? (
            <>
              <StatusPill status={row.membership.status}>{copy.status[row.membership.status]}</StatusPill>
              <span className="students__plan-name">{row.membership.plan_name}</span>
            </>
          ) : (
            <StatusPill status="none">{copy.noPlan}</StatusPill>
          )}
          <Button
            variant="ghost"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={t.admin.family.toggleLabel(row.name)}
            onClick={() => setOpen(!open)}
          >
            {t.admin.family.toggle}
          </Button>
        </div>
      </div>
      {/* Always there, so `aria-controls` names an element; filled only when open. */}
      <div id={panelId} hidden={!open}>
        {open && <FamilyPanel person={row} />}
      </div>
    </li>
  )
}
