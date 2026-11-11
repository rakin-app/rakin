import { keepPreviousData, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useId, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import {
  chargesQuery,
  deleteGroup,
  groupQuery,
  groupsQuery,
  progress,
  saveGroup,
  type ExtraChargeSummary,
} from '../api/extraCharges'
import type { PersonRef } from '../api/ledger'
import { myRoleQuery, readsLedger } from '../api/me'
import { membersPath, membersQuery, plansQuery, programsQuery, type MemberRow } from '../api/people'
import { Button, buttonClass } from '../components/Button'
import { Card, EmptyState, ListRowContent, listRowClass, SectionHeader } from '../components/Card'
import { Field, Input, SearchInput, Select } from '../components/Field'
import { ChevronLeftIcon } from '../components/icons'
import { PageContainer } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { shortDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './ExtraCharges.css'
import { useSubmit } from '../api/submit'

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
  const role = useQuery(myRoleQuery())
  if (!readsLedger(role.data)) {
    return (
      <PageContainer>
        <PageHeader title={copy.title} />
        {role.isSuccess && <p className="extra__note">{t.admin.payments.coachesOnly}</p>}
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
      <Link
        to={back === 'pagos' ? '/admin/pagos' : '/admin/pagos/cobros'}
        className={buttonClass({ icon: true })}
        aria-label={back === 'pagos' ? copy.back : copy.title}
      >
        <ChevronLeftIcon />
      </Link>
      <div className="extra__heading">
        <h1 className="extra__title">{title}</h1>
        {subtitle && <p className="extra__subtitle">{subtitle}</p>}
      </div>
      {children && <div className="extra__actions">{children}</div>}
    </header>
  )
}

function ChargeList() {
  const charges = useQuery(chargesQuery())
  if (charges.isPending) return <p className="extra__note">{copy.loading}</p>
  if (charges.isError) {
    return (
      <div className="extra__note" role="alert">
        <p>{copy.error}</p>
        <Button onClick={() => void charges.refetch()}>{copy.retry}</Button>
      </div>
    )
  }
  if (charges.data.length === 0) return <EmptyState>{copy.empty}</EmptyState>
  return (
    <ul className="extra__list" aria-label={copy.listLabel}>
      {charges.data.map((charge) => (
        <li key={charge.id}>
          <Link
            to="/admin/pagos/cobros/$chargeId"
            params={{ chargeId: charge.id }}
            className={listRowClass(true, 'extra__row')}
          >
            <ListRowContent
              title={charge.title}
              detail={`${copy.category[charge.category]} · ${copy.due(shortDay(charge.due_date))}`}
              trailing={<Progress charge={charge} />}
            />
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** "7 de 9 pagaron · $140.000 de $180.000", with a bar. */
export function Progress({ charge }: { charge: ExtraChargeSummary }) {
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
        <p className="extra__done" role="status">
          {done}
        </p>
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
      {groups.isSuccess && groups.data.length === 0 && editing === null && <p className="extra__note">{words.empty}</p>}
      {groups.isSuccess && groups.data.length > 0 && (
        <ul className="extra__list">
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
        </ul>
      )}
    </Card>
  )
}

/** Every member a filter finds, all pages: what "Agregar a las N personas" adds. */
async function everyone(program: string, plan: string): Promise<PersonRef[]> {
  const found: PersonRef[] = []
  const filters = { q: '', status: [], plan: plan ? [plan] : [], program: program ? [program] : [] }
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
  if (!existing.data) return <p className="extra__note">{copy.loading}</p>
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
        <ul className="extra__chosen">
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
        </ul>
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

/** Build a group from the member list's filters: a program, a plan, or both. */
function FilterAdd({ onAdd }: { onAdd: (people: PersonRef[]) => void }) {
  const words = copy.groups
  const programs = useQuery(programsQuery)
  const plans = useQuery(plansQuery)
  const [program, setProgram] = useState('')
  const [plan, setPlan] = useState('')
  const found = useQuery({
    queryKey: ['groups', 'filter', program, plan],
    queryFn: () => everyone(program, plan),
    enabled: program !== '' || plan !== '',
  })
  return (
    <fieldset className="extra__filters">
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
      {(program || plan) && (
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
        <ul className="extra__picks">
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
        </ul>
      )}
    </div>
  )
}
