import { keepPreviousData, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import { useGrades } from '../api/activities'
import { gradingSchemeQuery, isLevels } from '../api/grading'
import { myAccessQuery, myselfQuery, readsLedger } from '../api/me'
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
import { cx } from '../components/classNames'
import { SearchInput, Select } from '../components/Field'
import { JoinRequests } from '../components/JoinRequests'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { hasRanks, RankFilter, rankFilters, type RankChoice } from '../components/RankFilter'
import { StatusPill } from '../components/StatusPill'
import { formatPhone, formatRut } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { PaymentFor } from './Payments'
import { Banner, Card, EmptyState, PlainList } from '../components/Card'
import './Students.css'
import { LoadingText } from '../components/Loading'

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
  // "Falta apoderado": minors with no guardian, whom nothing reaches (#368).
  missingGuardian?: true
  // "Sin venir 14 d": members away 14 days or more, as Hoy's "A quién llamar" counts them.
  away?: true
  // A belt by rank key (#219); with `beltUp`, that belt or any above it ("Azul o superior").
  belt?: string
  beltUp?: true
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
  const missingGuardian =
    search.missingGuardian === true || search.missingGuardian === 'true' ? true : undefined
  const away = search.away === true || search.away === 'true' ? true : undefined
  const belt = typeof search.belt === 'string' && search.belt ? search.belt : undefined
  const beltUp = belt && (search.beltUp === true || search.beltUp === 'true') ? true : undefined
  return {
    q,
    status: status.length ? status : undefined,
    plan,
    program,
    left,
    missingPhone,
    missingRut,
    missingGuardian,
    away,
    belt,
    beltUp,
  }
}

const route = getRouteApi('/admin/alumnos')

// Typing waits this long before it becomes a search.
const SEARCH_DEBOUNCE_MS = 250

export function Students() {
  usePageTitle(copy.title)
  const search = route.useSearch()
  const navigate = route.useNavigate()
  const status = search.status ?? []
  // A gym known not to grade (#352) filters by no belt: a `?belt=` it is sent is dropped,
  // not applied with no chip to show it. Until the answer is in, the URL's stands.
  const gradingOff = useQuery(myselfQuery()).data?.uses_grades === false
  const beltSet = gradingOff ? undefined : search.belt
  const belt: RankChoice | null = beltSet ? { rank: beltSet, orHigher: search.beltUp === true } : null
  const filters = {
    q: search.q ?? '',
    status,
    plan: search.plan ? [search.plan] : [],
    program: search.program ? [search.program] : [],
    left: search.left ? ('only' as const) : ('no' as const),
    missingPhone: search.missingPhone === true,
    missingRut: search.missingRut === true,
    missingGuardian: search.missingGuardian === true,
    away: search.away === true,
    ...rankFilters(belt),
  }
  const filtered =
    filters.q.trim() !== '' ||
    status.length > 0 ||
    search.plan !== undefined ||
    search.program !== undefined ||
    search.left !== undefined ||
    search.missingPhone !== undefined ||
    search.missingRut !== undefined ||
    search.missingGuardian !== undefined ||
    search.away !== undefined ||
    beltSet !== undefined

  useEffect(() => {
    if (!gradingOff || search.belt === undefined) return
    void navigate({ search: (prev) => ({ ...prev, belt: undefined, beltUp: undefined }), replace: true })
  }, [gradingOff, search.belt, navigate])

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
  // A gym that does not grade (#226), or none of whose activities does (#245), gets no
  // belt filter.
  const grades = useGrades()
  const scheme = useQuery({ ...gradingSchemeQuery(), enabled: grades })
  // Importing starts memberships, and "Pagó" records money, which only an owner or admin may.
  const access = useQuery(myAccessQuery())

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
  const setBelt = (choice: RankChoice | null) => {
    void navigate({
      search: (prev) => ({ ...prev, belt: choice?.rank, beltUp: choice?.orHigher ? true : undefined }),
      replace: true,
    })
  }
  const clear = () => {
    setDraft('')
    void navigate({ search: {}, replace: true })
  }

  const searchId = useId()
  const planId = useId()
  const programId = useId()
  const rankId = useId()
  const moreId = useId()
  // Plan, programa and cinturón, behind "Filtros" so the list starts in a phone's first
  // screen (#358); the button counts those set.
  const [more, setMore] = useState(false)
  const showPlans = plans.data !== undefined && plans.data.length > 0
  const showPrograms = programs.data !== undefined && programs.data.length > 0
  const showRanks = grades && hasRanks(scheme.data)
  const moreSet = [search.plan, search.program, beltSet].filter((v) => v !== undefined).length
  const rows = members.data?.pages.flatMap((page) => page.items) ?? []
  const total = members.data?.pages[0]?.total

  return (
    <PageContainer className="students__page">
      <PageHeader title={copy.title} />
      <JoinRequests />
      <div className="students">
        <div role="search" className="students__filters">
          <label htmlFor={searchId} className="visually-hidden">
            {copy.searchLabel}
          </label>
          <div className="students__search-row">
            <SearchInput
              id={searchId}
              className="students__search"
              placeholder={copy.searchPlaceholder}
              autoComplete="off"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            {(showPlans || showPrograms || showRanks) && (
              <Button
                className="students__filters-toggle"
                aria-expanded={more}
                aria-controls={moreId}
                aria-label={copy.moreFiltersLabel(moreSet)}
                onClick={() => setMore(!more)}
              >
                {copy.filtersLabel}
                {moreSet > 0 && (
                  <span className="students__filters-count" aria-hidden="true">
                    {moreSet}
                  </span>
                )}
              </Button>
            )}
          </div>
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
          <div id={moreId} className="students__extra" hidden={!more}>
            {plans.data && plans.data.length > 0 && (
              <div className="field">
                <label htmlFor={planId} className="field__label">
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
              </div>
            )}
            {programs.data && programs.data.length > 0 && (
              <div className="field">
                <label htmlFor={programId} className="field__label">
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
              </div>
            )}
            {grades && hasRanks(scheme.data) && (
              <div className="field">
                <label htmlFor={rankId} className="field__label">
                  {isLevels(scheme.data) ? copy.levelLabel : copy.rankLabel}
                </label>
                <RankFilter
                  id={rankId}
                  className="students__picker"
                  scheme={scheme.data}
                  value={belt}
                  onChange={setBelt}
                  anyLabel={isLevels(scheme.data) ? copy.allLevels : copy.allRanks}
                />
              </div>
            )}
          </div>
        </div>

        {/* The count, then adding students, on one line: the list starts in a phone's first screen (#358). */}
        <div className="students__summary">
          <span aria-live="polite">{total !== undefined && copy.count(total)}</span>
          {filtered && (
            <Button variant="ghost" onClick={clear}>
              {copy.clearFilters}
            </Button>
          )}
          {readsLedger(access.data) && (
            <div className="students__links">
              <Link to="/admin/alumnos/nuevo" className={buttonClass({ variant: 'primary' })}>
                {copy.newLink}
              </Link>
              <Link to="/admin/alumnos/importar" className={buttonClass()}>
                {copy.importLink}
              </Link>
            </div>
          )}
        </div>

        {members.isPending ? (
          <Card flush>
            <EmptyState>
              <LoadingText>{copy.loading}</LoadingText>
            </EmptyState>
          </Card>
        ) : members.isError && rows.length === 0 ? (
          <Card flush role="alert">
            <EmptyState action={<Button onClick={() => void members.refetch()}>{copy.retry}</Button>}>
              {copy.error}
            </EmptyState>
          </Card>
        ) : rows.length === 0 ? (
          <Card flush>
            <EmptyState>{filtered ? copy.noMatches : copy.empty}</EmptyState>
          </Card>
        ) : (
          <Card as="div" flush className={cx('students__table', readsLedger(access.data) && 'students__table--pays')}>
            {/* The columns' labels, over a desktop's one-line rows; the list is still a list. */}
            <div className="students__columns" aria-hidden="true">
              <span>{copy.columns.name}</span>
              <span>{copy.columns.phone}</span>
              <span>{copy.columns.rut}</span>
              <span>{copy.columns.plan}</span>
              <span>{copy.columns.status}</span>
            </div>
            <PlainList className="students__list" aria-label={copy.title}>
              {rows.map((row) => (
                <MemberItem key={row.id} row={row} pays={readsLedger(access.data)} />
              ))}
            </PlainList>
          </Card>
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

/** A member's row. `pays`: the signed-in owner or admin may record a payment, so a row
 *  that owes has "Pagó", as Hoy says it (#358), which opens the ficha's payment form
 *  under it (#265). The family is the ficha's (#358): the row only says who it is. */
function MemberItem({ row, pays }: { row: MemberRow; pays: boolean }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const panelId = useId()
  const toggle = () => {
    setDone(null)
    setOpen(!open)
  }
  const paid = async (message: string) => {
    setOpen(false)
    setDone(message)
    // The row's "Pagar" and status pill, as the payment left them.
    await queryClient.invalidateQueries({ queryKey: ['people', 'list'] })
  }
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
            {row.missing_guardian && <span className="students__flag">{copy.missingGuardian}</span>}
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
          {/* Above the row's link to the ficha, so a tap here opens what it says and nothing else. */}
          {pays && row.owes && (
            <div className="students__actions">
              <Button aria-expanded={open} aria-controls={panelId} aria-label={copy.payLabel(row.name)} onClick={toggle}>
                {copy.pay}
              </Button>
            </div>
          )}
        </div>
      </div>
      {done && (
        <Banner tone="done" className="students__done">
          {done}
        </Banner>
      )}
      {/* Always there, so `aria-controls` names an element; filled only when open. */}
      <div id={panelId} hidden={!open}>
        {open && (
          <div className="students__payment">
            <PaymentFor personId={row.id} onCancel={() => setOpen(false)} onDone={(message) => void paid(message)} />
          </div>
        )}
      </div>
    </li>
  )
}
