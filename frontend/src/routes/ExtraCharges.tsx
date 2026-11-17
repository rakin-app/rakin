import { keepPreviousData, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import {
  chargesQuery,
  deleteGroup,
  groupQuery,
  groupsQuery,
  progress,
  saveGroup,
  type Counted,
} from '../api/extraCharges'
import { useGrades } from '../api/activities'
import { gradingSchemeQuery, isLevels } from '../api/grading'
import type { PersonRef } from '../api/ledger'
import { myAccessQuery, readsLedger } from '../api/me'
import { membersPath, membersQuery, plansQuery, programsQuery, type MemberRow } from '../api/people'
import { Button, buttonClass } from '../components/Button'
import { BackLink } from '../components/BackLink'
import { Banner, Card, EmptyState, listRowClass, ListRowContent, PlainList, SectionHeader } from '../components/Card'
import { Field, Input, SearchInput, Select } from '../components/Field'
import { PageContainer } from '../components/Layout'
import { PageHeader, PageTitle } from '../components/PageHeader'
import { hasRanks, RankFilter, rankFilters, type RankChoice } from '../components/RankFilter'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './ExtraCharges.css'
import { useSubmit } from '../api/submit'
import { Loading } from '../components/Loading'

const copy = t.admin.extra
const clp = t.common.clp

// Typing waits this long before it becomes a search, as on the member list.
const SEARCH_DEBOUNCE_MS = 250
const PICKER_ROWS = 8

/**
 * Pagos › Cobros extra (#195): every cobro with how far along it is, "7 de 9 pagaron ·
 * $140.000 de $180.000", and the groups a cobro can be for. Owner and admin only: a
 * coach never sees money, and is told so with nothing asked of the API.
 */
export function ExtraCharges() {
  usePageTitle(copy.title)
  const access = useQuery(myAccessQuery())
  if (!readsLedger(access.data)) {
    return (
      <PageContainer>
        <PageHeader title={copy.title} />
        {access.isSuccess && <p className="extra__note">{t.admin.payments.coachesOnly}</p>}
      </PageContainer>
    )
  }
  return (
    <PageContainer className="extra">
      <SubHeader title={copy.title} subtitle={copy.subtitle}>
        <Link to="/admin/pagos/cobros/nuevo" className={buttonClass({ variant: 'primary' })}>
          {copy.create}
        </Link>
      </SubHeader>
      <ChargeList />
      <Groups />
    </PageContainer>
  )
}

/** A sub-page's header: back to Pagos, its title, and its actions. */
export function SubHeader({
  title,
  subtitle,
  back = 'pagos',
  children,
}: {
  title: string
  subtitle?: string
  back?: 'pagos' | 'cobros'
  children?: React.ReactNode
}) {
  return (
    <header className="extra__header">
      <BackLink
        to={back === 'pagos' ? '/admin/pagos' : '/admin/pagos/cobros'}
        label={back === 'pagos' ? copy.back : copy.title} />
      <div className="extra__heading">
        <Title title={title} />
        {subtitle && <p className="extra__subtitle">{subtitle}</p>}
      </div>
      {children && <div className="extra__actions">{children}</div>}
    </header>
  )
}

/** A cobro's title at h1 size, cut to two lines; "Ver título completo" shows the rest,
 *  for a title too long for them (#357). A screen reader hears it whole either way. */
function Title({ title }: { title: string }) {
  const ref = useRef<HTMLHeadingElement>(null)
  const [cut, setCut] = useState(false)
  const [whole, setWhole] = useState(false)
  useLayoutEffect(() => {
    const heading = ref.current
    if (!heading || whole) return
    const measure = () => setCut(heading.scrollHeight > heading.clientHeight + 1)
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [title, whole])
  return (
    <>
      <PageTitle ref={ref} className={whole ? undefined : 'extra__title--clamped'} title={title}>
        {title}
      </PageTitle>
      {(cut || whole) && (
        <button type="button" className="extra__title-toggle" aria-expanded={whole} onClick={() => setWhole(!whole)}>
          {whole ? copy.titleLess : copy.titleMore}
        </button>
      )}
    </>
  )
}

function ChargeList() {
  const charges = useQuery(chargesQuery())
  if (charges.isPending) return <Loading className="extra__note">{copy.loading}</Loading>
  if (charges.isError) {
    return (
      <div className="extra__note" role="alert">
        <p>{copy.error}</p>
        <Button onClick={() => void charges.refetch()}>{copy.retry}</Button>
      </div>
    )
  }
  if (charges.data.length === 0) {
    return (
      <Card>
        <EmptyState>{copy.empty}</EmptyState>
      </Card>
    )
  }
  return (
    <PlainList className="extra__list" aria-label={copy.listLabel}>
      {charges.data.map((charge) => (
        <li key={charge.id}>
          <Link
            to="/admin/pagos/cobros/$chargeId"
            params={{ chargeId: charge.id }}
            className={listRowClass(true, 'extra__row')}
          >
            <ListRowContent
              title={charge.title}
              detail={[copy.category[charge.category], copy.due(shortDay(charge.due_date))]
                .concat(charge.instalments > 1 ? [copy.instalments(charge.instalments)] : [])
                .join(' · ')}
              trailing={<Progress charge={charge} />}
            />
          </Link>
        </li>
      ))}
    </PlainList>
  )
}

/** "7 de 9 pagaron · $140.000 de $180.000": a cobro's, or one of its instalments' (#356), with a bar. */
export function Progress({ charge }: { charge: Counted }) {
  const label = copy.progress(charge.paid_lines, charge.lines, clp(charge.collected_clp), clp(charge.due_clp))
  return (
    <span className="extra__progress">
      <span className="extra__progress-text">{label}</span>
      {charge.waived_lines > 0 && <span className="extra__progress-text">{copy.waived(charge.waived_lines)}</span>}
      <span
        className="extra__bar"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={charge.lines}
        aria-valuenow={charge.paid_lines}
      >
        <span className="extra__bar-fill" style={{ width: `${Math.round(progress(charge) * 100)}%` }} />
      </span>
    </span>
  )
}

// --- groups -----------------------------------------------------------------------

function Groups() {
  const words = copy.groups
  const groups = useQuery(groupsQuery())
  // `null`: nothing open; `''`: a new group; an id: that group.
  const [editing, setEditing] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  return (
    <Card className="extra__groups" aria-labelledby="extra-groups">
      <SectionHeader
        id="extra-groups"
        title={words.title}
        trailing={
          editing === null && (
            <Button
              onClick={() => {
                setDone(null)
                setEditing('')
              }}
            >
              {words.create}
            </Button>
          )
        }
      />
      <p className="extra__hint">{words.intro}</p>
      {done && (
        <Banner tone="done">
          {done}
        </Banner>
      )}
      {editing !== null && (
        <GroupEditor
          groupId={editing || null}
          onClose={(message) => {
            setEditing(null)
            setDone(message ?? null)
          }}
        />
      )}
      {groups.isSuccess && groups.data.length === 0 && editing === null && <EmptyState>{words.empty}</EmptyState>}
      {groups.isSuccess && groups.data.length > 0 && (
        <PlainList className="extra__list">
          {groups.data.map((group) => (
            <li key={group.id} className={listRowClass(false)}>
              <ListRowContent
                title={group.name}
                detail={words.size(group.size)}
                trailing={
                  <Button variant="ghost" aria-label={`${words.edit} ${group.name}`} onClick={() => setEditing(group.id)}>
                    {words.edit}
                  </Button>
                }
              />
            </li>
          ))}
        </PlainList>
      )}
    </Card>
  )
}

/** Every member a filter finds, all pages: what "Agregar a las N personas" adds. */
async function everyone(program: string, plan: string, rank: RankChoice | null): Promise<PersonRef[]> {
  const found: PersonRef[] = []
  const filters = {
    q: '',
    status: [],
    plan: plan ? [plan] : [],
    program: program ? [program] : [],
    ...rankFilters(rank),
  }
  for (let offset = 0; ; ) {
    const page = await apiFetch<{ items: MemberRow[]; total: number }>(membersPath(filters, offset))
    found.push(...page.items.map((row) => ({ id: row.id, name: row.name })))
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) return found
  }
}

function GroupEditor({ groupId, onClose }: { groupId: string | null; onClose: (message?: string) => void }) {
  const existing = useQuery({ ...groupQuery(groupId ?? ''), enabled: groupId !== null })
  if (groupId === null) return <GroupForm groupId={null} initialName="" initialMembers={[]} onClose={onClose} />
  if (!existing.data) return <Loading className="extra__note">{copy.loading}</Loading>
  return (
    <GroupForm
      groupId={groupId}
      initialName={existing.data.name}
      initialMembers={existing.data.members}
      onClose={onClose}
    />
  )
}

function GroupForm({
  groupId,
  initialName,
  initialMembers,
  onClose,
}: {
  groupId: string | null
  initialName: string
  initialMembers: PersonRef[]
  onClose: (message?: string) => void
}) {
  const words = copy.groups
  const queryClient = useQueryClient()
  const [name, setName] = useState(initialName)
  const [members, setMembers] = useState<PersonRef[]>(initialMembers)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [nameNeeded, setNameNeeded] = useState(false)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['groups'] })
  const save = useSubmit({
    mutationFn: () => saveGroup(groupId, name, members.map((m) => m.id)),
    onSuccess: async (group) => {
      await refresh()
      onClose(words.saved(group.name))
    },
  })
  const remove = useSubmit({
    mutationFn: () => deleteGroup(groupId!),
    onSuccess: async () => {
      await refresh()
      onClose()
    },
  })
  const add = (people: PersonRef[]) =>
    setMembers((current) => {
      const have = new Set(current.map((m) => m.id))
      return [...current, ...people.filter((p) => !have.has(p.id))].sort((a, b) => a.name.localeCompare(b.name, 'es'))
    })

  const error =
    save.error instanceof ApiError && save.error.status === 409 ? words.taken : save.error || remove.error ? words.failed : null

  return (
    <form
      className="extra__editor"
      onSubmit={(event) => {
        event.preventDefault()
        if (!name.trim()) {
          setNameNeeded(true)
          return
        }
        save.mutate()
      }}
    >
      <Field label={words.name} error={nameNeeded && !name.trim() ? words.nameNeeded : undefined}>
        {(props) => (
          <Input {...props} value={name} maxLength={80} placeholder={words.namePlaceholder} onChange={(e) => setName(e.target.value)} />
        )}
      </Field>
      <FilterAdd onAdd={add} />
      <PeoplePicker label={words.search} chosen={members} onPick={(person) => add([person])} />
      <SectionHeader as="h3" title={words.members(members.length)} />
      {members.length === 0 ? (
        <p className="extra__note">{words.noMembers}</p>
      ) : (
        <PlainList className="extra__chosen">
          {members.map((member) => (
            <li key={member.id} className="extra__chosen-item">
              <span>{member.name}</span>
              <Button
                variant="ghost"
                aria-label={words.remove(member.name)}
                onClick={() => setMembers((current) => current.filter((m) => m.id !== member.id))}
              >
                {words.removeShort}
              </Button>
            </li>
          ))}
        </PlainList>
      )}
      {error && (
        <p className="extra__error" role="alert">
          {error}
        </p>
      )}
      <div className="extra__form-actions">
        <Button type="submit" variant="primary" disabled={save.isPending} busy={save.isPending}>
          {save.isPending ? words.saving : words.save}
        </Button>
        <Button onClick={() => onClose()}>{words.cancel}</Button>
        {groupId &&
          (confirmDelete ? (
            <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {words.deleteConfirm}
            </Button>
          ) : (
            <Button variant="danger" onClick={() => setConfirmDelete(true)}>
              {words.delete}
            </Button>
          ))}
      </div>
      {confirmDelete && <p className="extra__hint">{words.deleteNote}</p>}
    </form>
  )
}

/** Build a group from the member list's filters: a program, a plan, a belt, or any of them together. */
function FilterAdd({ onAdd }: { onAdd: (people: PersonRef[]) => void }) {
  const words = copy.groups
  const programs = useQuery(programsQuery)
  const plans = useQuery(plansQuery)
  const [program, setProgram] = useState('')
  const [plan, setPlan] = useState('')
  // A gym that does not grade (#226), or none of whose activities does (#245), gets no
  // belt filter.
  const grades = useGrades()
  const scheme = useQuery({ ...gradingSchemeQuery(), enabled: grades })
  const ranked = grades && hasRanks(scheme.data) ? scheme.data : null
  const [rank, setRank] = useState<RankChoice | null>(null)
  const chosen = program !== '' || plan !== '' || rank !== null
  const found = useQuery({
    queryKey: ['groups', 'filter', program, plan, rank],
    queryFn: () => everyone(program, plan, rank),
    enabled: chosen,
  })
  return (
    <fieldset className={ranked ? 'extra__filters extra__filters--ranks' : 'extra__filters'}>
      <legend className="extra__legend">{words.filters}</legend>
      <Field label={words.program}>
        {(props) => (
          <Select {...props} value={program} onChange={(e) => setProgram(e.target.value)}>
            <option value="">{words.any}</option>
            {(programs.data ?? []).filter((p) => p.active).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={words.plan}>
        {(props) => (
          <Select {...props} value={plan} onChange={(e) => setPlan(e.target.value)}>
            <option value="">{words.any}</option>
            {(plans.data ?? []).filter((p) => p.active).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {ranked && (
        <Field label={isLevels(ranked) ? words.level : words.rank}>
          {(props) => (
            <RankFilter {...props} scheme={ranked} value={rank} onChange={setRank} anyLabel={words.any} />
          )}
        </Field>
      )}
      {chosen && (
        <Button disabled={!found.isSuccess || found.data.length === 0} onClick={() => found.data && onAdd(found.data)}>
          {found.isSuccess ? words.addAll(found.data.length) : words.loadingFilter}
        </Button>
      )}
    </fieldset>
  )
}

/** Search the member list and pick people by hand; whoever is `chosen` is not offered. */
export function PeoplePicker({
  label,
  chosen,
  onPick,
}: {
  label: string
  chosen: PersonRef[]
  onPick: (person: PersonRef) => void
}) {
  const inputId = useId()
  const [draft, setDraft] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setQ(draft.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draft])
  const members = useInfiniteQuery({
    ...membersQuery({ q, status: [], plan: [], program: [] }),
    enabled: q !== '',
    placeholderData: keepPreviousData,
  })
  const taken = new Set(chosen.map((p) => p.id))
  const found = q ? (members.data?.pages[0]?.items ?? []).filter((row) => !taken.has(row.id)) : []
  return (
    <div className="extra__picker">
      <label htmlFor={inputId} className="extra__legend">
        {label}
      </label>
      <SearchInput
        id={inputId}
        autoComplete="off"
        placeholder={copy.groups.searchPlaceholder}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      {found.length > 0 && (
        <PlainList className="extra__picks">
          {found.slice(0, PICKER_ROWS).map((row) => (
            <li key={row.id}>
              <button
                type="button"
                className={listRowClass(true)}
                aria-label={copy.groups.add(row.name)}
                onClick={() => onPick({ id: row.id, name: row.name })}
              >
                <ListRowContent title={row.name} detail={row.membership?.plan_name} />
              </button>
            </li>
          ))}
        </PlainList>
      )}
    </div>
  )
}
