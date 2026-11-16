import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { candidatesQuery, checkIn, doorsQuery, undoCheckIn, warning, type Door, type Visitor } from '../api/checkIn'
import { useSubmit } from '../api/submit'
import { Button, buttonClass } from '../components/Button'
import { Banner, Card, EmptyState, PlainList, SectionTitle } from '../components/Card'
import { SegmentedControl } from '../components/Chip'
import { SearchInput } from '../components/Field'
import { Grid, PageContainer } from '../components/Layout'
import { Loading } from '../components/Loading'
import { PageHeader } from '../components/PageHeader'
import { clockTime, toDate, weekdayDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import './CheckIn.css'

const copy = t.admin.checkIn

// Typing waits this long before it becomes a search.
const SEARCH_DEBOUNCE_MS = 150

/**
 * "Entrada" (#348): checking people in at the door of a gym open all day, with no class
 * scheduled. A search box, by name or RUT, finds who may come in, each with their plan's
 * state; one tap checks them in at the day's session of the gym's open-access class
 * type, which the first check-in makes, and spends a pack's credits as a class does. A
 * lapsed plan or a spent pack is a warning, never a refusal. Under it, today's arrivals
 * with their time, newest first, each a tap from undoing it.
 *
 * After a check-in the box is cleared and focused again, so twenty people at the door
 * are a search and a tap each; Enter checks in the one person a search found. A gym
 * with two open-access types (a climbing wall and a gym floor, say) picks one above the
 * box. From 1024px the arrivals sit beside it.
 */
export function CheckIn() {
  usePageTitle(copy.title)
  const doors = useQuery(doorsQuery())
  const [picked, setPicked] = useState<string | null>(null)
  const door = doors.data?.find((d) => d.class_type_id === picked) ?? doors.data?.[0]

  return (
    <div className="check-in">
      <PageContainer>
        <PageHeader title={copy.title} eyebrow={door ? weekdayDay(toDate(door.date)) : undefined} />
        {doors.isPending ? (
          <Loading className="check-in__note">{copy.loading}</Loading>
        ) : doors.isError ? (
          <Banner tone="error" as="div">
            <p>{copy.error}</p>
            <Button onClick={() => void doors.refetch()}>{copy.retry}</Button>
          </Banner>
        ) : door === undefined ? (
          <Card>
            <EmptyState>{copy.none}</EmptyState>
          </Card>
        ) : (
          <>
            {doors.data.length > 1 && (
              <SegmentedControl
                label={copy.pick}
                options={doors.data.map((d) => ({ value: d.class_type_id, label: d.name }))}
                value={door.class_type_id}
                onChange={setPicked}
              />
            )}
            <DoorDay key={door.class_type_id} door={door} />
          </>
        )}
      </PageContainer>
    </div>
  )
}

function DoorDay({ door }: { door: Door }) {
  const queryClient = useQueryClient()
  const inputId = useId()
  const input = useRef<HTMLInputElement>(null)
  const [typed, setTyped] = useState('')
  const [q, setQ] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setQ(typed.trim()), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [typed])
  const found = useQuery(candidatesQuery(door.class_type_id, q))
  const searching = typed.trim() !== ''

  // The day as the API answered, in place of the one shown; every search is stale now.
  const settle = (day: Door) => {
    queryClient.setQueryData<Door[]>(['check-in'], (doors) =>
      doors?.map((d) => (d.class_type_id === day.class_type_id ? day : d)),
    )
    void queryClient.invalidateQueries({ queryKey: ['check-in', 'search'] })
    void queryClient.invalidateQueries({ queryKey: ['sessions'] })
  }
  const enter = useSubmit({
    mutationFn: (membershipId: string) => checkIn(door.class_type_id, membershipId),
    onSuccess: (day) => {
      settle(day)
      setTyped('')
      setQ('')
      input.current?.focus()
    },
  })
  const undo = useSubmit({
    mutationFn: (membershipId: string) => undoCheckIn(door.class_type_id, membershipId),
    onSuccess: settle,
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const only = found.data?.length === 1 ? found.data[0] : undefined
    if (only && only.checked_in_at === null && !door.cancelled) enter.mutate(only.membership_id)
  }

  return (
    <Grid className="check-in__grid">
      <Card aria-labelledby="check-in-search">
        <form role="search" onSubmit={submit} className="check-in__form">
          <label id="check-in-search" htmlFor={inputId} className="check-in__label">
            {copy.search.label(door.name)}
          </label>
          <SearchInput
            ref={input}
            id={inputId}
            autoFocus
            autoComplete="off"
            placeholder={copy.search.placeholder}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        </form>
        {door.cancelled && (
          <Banner tone="error" as="div">
            <p>{copy.cancelled}</p>
            {door.session_id && (
              <Link to="/admin/clases/$sessionId" params={{ sessionId: door.session_id }} className={buttonClass()}>
                {copy.openDay}
              </Link>
            )}
          </Banner>
        )}
        {enter.isError && <Banner tone="error">{copy.search.failed}</Banner>}
        {!searching ? (
          <p className="check-in__note">{copy.search.hint}</p>
        ) : found.isPending || q !== typed.trim() ? (
          <Loading className="check-in__note">{copy.loading}</Loading>
        ) : found.isError ? (
          <Banner tone="error" as="div">
            <p>{copy.search.error}</p>
            <Button onClick={() => void found.refetch()}>{copy.retry}</Button>
          </Banner>
        ) : found.data.length === 0 ? (
          <p className="check-in__note">{copy.search.empty}</p>
        ) : (
          <PlainList className="check-in__list" aria-label={copy.search.results}>
            {found.data.map((candidate) => (
              <li key={candidate.membership_id} className="check-in__row">
                <VisitorText visitor={candidate} creditCost={door.credit_cost} />
                {candidate.checked_in_at !== null ? (
                  <span className="check-in__in">
                    {copy.search.already(clockTime(candidate.checked_in_at, door.timezone))}
                  </span>
                ) : (
                  <Button
                    variant="primary"
                    disabled={door.cancelled || enter.isPending}
                    busy={enter.isPending && enter.variables === candidate.membership_id}
                    aria-label={copy.search.enterLabel(candidate.name)}
                    onClick={() => enter.mutate(candidate.membership_id)}
                  >
                    {copy.search.enter}
                  </Button>
                )}
              </li>
            ))}
          </PlainList>
        )}
      </Card>
      <Card aria-labelledby="check-in-today">
        <div className="check-in__head">
          <SectionTitle id="check-in-today">{copy.today.title}</SectionTitle>
          {door.arrivals.length > 0 && <span className="check-in__aside">{copy.today.count(door.arrivals.length)}</span>}
        </div>
        {undo.isError && <Banner tone="error">{copy.today.undoFailed}</Banner>}
        {door.arrivals.length === 0 ? (
          <p className="check-in__note">{copy.today.empty}</p>
        ) : (
          <PlainList className="check-in__list" aria-label={copy.today.title}>
            {door.arrivals.map((arrival) => (
              <li key={arrival.membership_id} className="check-in__row">
                <span className="check-in__time">{clockTime(arrival.marked_at, door.timezone)}</span>
                <VisitorText visitor={arrival} creditCost={0} />
                <Button
                  variant="ghost"
                  disabled={undo.isPending}
                  busy={undo.isPending && undo.variables === arrival.membership_id}
                  aria-label={copy.today.undoLabel(arrival.name)}
                  onClick={() => undo.mutate(arrival.membership_id)}
                >
                  {copy.today.undo}
                </Button>
              </li>
            ))}
          </PlainList>
        )}
      </Card>
    </Grid>
  )
}

/** Their name, and their plan's state under it: what is left of a pack, a payment past
 * due, and the warning, if any. An arrival's `creditCost` is 0: it is in already. */
function VisitorText({ visitor, creditCost }: { visitor: Visitor; creditCost: number }) {
  const warned = warning(visitor, creditCost)
  const detail = [visitor.plan_name, visitor.credits_remaining !== null && copy.left(visitor.credits_remaining)]
    .filter(Boolean)
    .join(' · ')
  return (
    <span className="check-in__text">
      <span className="check-in__name">{visitor.name}</span>
      <span className="check-in__detail">{detail}</span>
      {(warned || visitor.overdue) && (
        <span className="check-in__warnings">
          {warned && <span className="check-in__warning">{copy.warning[warned]}</span>}
          {visitor.overdue && <span className="check-in__warning">{copy.overdue}</span>}
        </span>
      )}
    </span>
  )
}
