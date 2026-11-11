import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  addTrialGuest,
  hasLeft,
  changeAttendance,
  clearQueuedChange,
  isOffline,
  isRefusal,
  queueChange,
  queuedChange,
  rosterQuery,
  trialPlansQuery,
  type AttendanceChange,
  type Roster,
  type RosterMember,
} from '../api/attendance'
import { ApiError } from '../api/client'
import { useKeptDraft, useRestoredDraft } from '../api/drafts'
import { rankLabel } from '../api/grading'
import { managesGym, myselfQuery, runsSession } from '../api/me'
import { sessionQuery, updateSession, useGymTimeZone, useGymToday, type ClassSession } from '../api/sessions'
import { RankBelt } from '../components/Belt'
import { Button, buttonClass } from '../components/Button'
import { Input, Select, Textarea } from '../components/Field'
import { CheckIcon, ChevronLeftIcon } from '../components/icons'
import { clockTime, dayTime, isoDay } from '../format'
import { t } from '../i18n/es'
import { usePageTitle } from '../pageTitle'
import { ClassActions, ClassEdit, refreshSession } from './ClassManage'
import { TimerRecord } from './TimerRecord'
import { savedRun } from './timerEngine'
import './Classes.css'
import './ClassTimer.css'

const copy = t.admin.session

const route = getRouteApi('/admin/clases/$sessionId')

// The topic is one line and notes a few paragraphs: the backend's MAX_TOPIC and MAX_NOTES.
const MAX_TOPIC = 200
const MAX_NOTES = 4000

/**
 * One class: what it is, when it started and who teaches it, "Asistencia" (the roster,
 * tapped name by name), and its topic and notes, written during or after class by its
 * coach. Once it has begun, "Registro del timer", what its blocks ran, which its coach
 * or an owner or admin corrects after. An owner or admin also edits it ("Editar clase"),
 * cancels it or deletes it. A cancelled class takes no attendance and runs no timer.
 */
export function SessionDetail() {
  const { sessionId } = route.useParams()
  const session = useQuery(sessionQuery(sessionId))
  usePageTitle(session.data?.class_type_name)
  const me = useQuery(myselfQuery())
  const timeZone = useGymTimeZone()
  const today = useGymToday()

  if (session.isPending) {
    return (
      <Shell>
        <p className="classes__note">{copy.loading}</p>
      </Shell>
    )
  }
  if (session.isError) {
    const missing = session.error instanceof ApiError && session.error.status === 404
    return (
      <Shell>
        <div className="classes__error" role="alert">
          <p>{missing ? copy.notFound : copy.error}</p>
          {!missing && (
            <Button onClick={() => void session.refetch()}>
              {copy.retry}
            </Button>
          )}
        </div>
      </Shell>
    )
  }

  const data = session.data
  const cancelled = data.cancelled_at !== null
  const begun = new Date(data.starts_at) <= new Date()
  const runs = runsSession(me.data, data.coach_id)
  // A class moved to another day says which.
  const when =
    isoDay(data.starts_at, timeZone) === today ? clockTime(data.starts_at, timeZone) : dayTime(data.starts_at, timeZone)
  return (
    <Shell eyebrow={copy.eyebrow(data.program_name, when)} title={data.class_type_name} subtitle={copy.coach(data.coach_name)}>
      {cancelled && (
        <div className="classes__error class-cancelled" role="status">
          <span className="classes__flag classes__flag--cancelled">{copy.cancelled.badge}</span>
          <p>{copy.cancelled.note}</p>
        </div>
      )}
      {!cancelled && <TimerLink session={data} />}
      {!cancelled && <Attendance key={`attendance-${data.id}`} sessionId={data.id} />}
      {runs ? <TopicForm key={data.id} session={data} /> : <TopicView session={data} />}
      {runs && begun && !cancelled && <TimerRecord key={`record-${data.id}`} session={data} />}
      {managesGym(me.data?.role) && (
        <>
          <ClassEdit key={`edit-${data.id}`} session={data} timeZone={timeZone} />
          <ClassActions key={`actions-${data.id}`} session={data} />
        </>
      )}
    </Shell>
  )
}

/** The topic and notes, for a coach who does not teach the class: theirs to read. */
function TopicView({ session }: { session: ClassSession }) {
  if (!session.topic && !session.notes) return null
  return (
    <section className="classes__card" aria-label={copy.form.label}>
      <span className="classes__label">{copy.form.topic}</span>
      <span className={session.topic ? 'classes__topic' : 'classes__topic classes__topic--none'}>
        {session.topic ?? t.admin.classes.today.noTopic}
      </span>
      {session.notes && (
        <>
          <span className="classes__label">{copy.form.notes}</span>
          <p className="classes__topic class-notes">{session.notes}</p>
        </>
      )}
    </section>
  )
}

function Shell({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow?: string
  title?: string
  subtitle?: string
  children: ReactNode
}) {
  return (
    <div className="classes">
      <header className="classes__header">
        <Link to="/admin/clases" className={buttonClass({ icon: true })} aria-label={copy.back}>
          <ChevronLeftIcon />
        </Link>
        {title && (
          <div className="classes__heading">
            {eyebrow && <span className="classes__eyebrow">{eyebrow}</span>}
            <h1 className="classes__title">{title}</h1>
            {subtitle && <span className="classes__detail">{subtitle}</span>}
          </div>
        )}
      </header>
      <div className="classes__body">{children}</div>
    </div>
  )
}

/** "Abrir timer": the class timer, a secondary button for who may run it; "Volver al timer" while it runs. */
function TimerLink({ session }: { session: ClassSession }) {
  const me = useQuery(myselfQuery())
  if (!runsSession(me.data, session.coach_id)) return null
  const running = savedRun(session.id)
  return (
    <Link
      to="/admin/clases/$sessionId/timer"
      params={{ sessionId: session.id }}
      className={buttonClass({ className: 'timer-link' })}
    >
      {running && running.endedAt === null ? copy.timer.resume : copy.timer.open}
    </Link>
  )
}

function TopicForm({ session }: { session: ClassSession }) {
  const queryClient = useQueryClient()
  const topicId = useId()
  const notesId = useId()
  // What was typed here when the session last ended, given back after signing in again (#212).
  const draftKey = `class-topic:${session.id}`
  const restored = useRestoredDraft(draftKey, useQuery(myselfQuery()).data?.person_id)
  const [topic, setTopic] = useState(restored?.topic ?? session.topic ?? '')
  const [notes, setNotes] = useState(restored?.notes ?? session.notes ?? '')
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => updateSession(session.id, { topic, notes }),
    onSuccess: (updated) => {
      // As stored: trimmed, and blank as none.
      setTopic(updated.topic ?? '')
      setNotes(updated.notes ?? '')
      setSaved(true)
      refreshSession(queryClient, updated)
    },
  })
  // "Guardado" until the next edit.
  const changed = topic !== (session.topic ?? '') || notes !== (session.notes ?? '')
  useKeptDraft(draftKey, changed ? { topic, notes } : null)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setSaved(false)
    save.mutate()
  }

  return (
    <form className="classes__card classes__form" aria-label={copy.form.label} onSubmit={submit}>
      <label htmlFor={topicId} className="classes__label">
        {copy.form.topic}
      </label>
      <Input
        id={topicId}
        value={topic}
        maxLength={MAX_TOPIC}
        placeholder={copy.form.topicPlaceholder}
        onChange={(e) => setTopic(e.target.value)}
      />
      <label htmlFor={notesId} className="classes__label">
        {copy.form.notes}
      </label>
      <Textarea
        id={notesId}
        value={notes}
        maxLength={MAX_NOTES}
        rows={5}
        placeholder={copy.form.notesPlaceholder}
        onChange={(e) => setNotes(e.target.value)}
      />
      {restored && changed && !save.isError && (
        <p className="classes__restored" role="status">
          {copy.form.restored}
        </p>
      )}
      {save.isError && (
        <p className="classes__error" role="alert">
          {copy.form.failed}
        </p>
      )}
      {saved && !changed && (
        <p className="classes__done" role="status">
          {copy.form.saved}
        </p>
      )}
      {/* Secondary: "Guardar asistencia" is the screen's one primary. */}
      <Button type="submit" disabled={save.isPending}>
        {save.isPending ? copy.form.working : copy.form.submit}
      </Button>
    </form>
  )
}

// Days away after which the roster says how long: the retention list's first bucket.
const ABSENT_DAYS = 14

/** What the coach tapped and has not saved: membership id → present. */
type Taps = ReadonlyMap<string, boolean>

function tapsOf(change: AttendanceChange | null): Taps {
  const taps = new Map<string, boolean>()
  for (const id of change?.mark ?? []) taps.set(id, true)
  for (const id of change?.unmark ?? []) taps.set(id, false)
  return taps
}

/** The taps that differ from the roster as saved, as the change to send. */
function changeOf(roster: Roster, taps: Taps): AttendanceChange {
  const change: AttendanceChange = { mark: [], unmark: [] }
  for (const member of roster.members) {
    const here = taps.get(member.membership_id)
    if (here === undefined || here === member.present) continue
    if (here) change.mark.push(member.membership_id)
    else change.unmark.push(member.membership_id)
  }
  return change
}

/** A save: what it sends, and whether it replays what an earlier one left on the phone. */
type Save = { change: AttendanceChange; replay: boolean }

/**
 * "Asistencia": tap a name to mark it present, again to unmark it, and the count goes
 * with each tap; "Guardar asistencia" sends what changed. Without signal the change
 * stays on the phone (`queueChange`), kept up to date with every later tap, and goes as
 * soon as the signal is back, or on the next visit; the API takes a change twice as
 * once, so resending is safe. A queued change the API refuses (`isRefusal`) is dropped,
 * not resent forever: the coach sees the roster as saved and marks again. Any other
 * failure keeps it queued, for the next flush.
 */
function Attendance({ sessionId }: { sessionId: string }) {
  const words = copy.attendance
  const queryClient = useQueryClient()
  const roster = useQuery(rosterQuery(sessionId))
  const [taps, setTaps] = useState<Taps>(() => tapsOf(queuedChange(sessionId)))
  const [queued, setQueued] = useState(() => queuedChange(sessionId) !== null)
  const [saved, setSaved] = useState(false)
  const [dropped, setDropped] = useState(false)
  const [search, setSearch] = useState('')
  const [othersOpen, setOthersOpen] = useState(false)
  const searchId = useId()
  // The taps as of the last render, for a save that fails after more taps were made.
  const latestTaps = useRef(taps)
  useEffect(() => {
    latestTaps.current = taps
  }, [taps])
  const mutationKey = ['attendance', 'save', sessionId]

  /** Keep `current` on the phone while a change waits for signal; none left, none kept. */
  const persist = (current: Taps) => {
    const data = queryClient.getQueryData(rosterQuery(sessionId).queryKey)
    const change = data ? changeOf(data, current) : null
    if (change && change.mark.length + change.unmark.length > 0) {
      queueChange(sessionId, change)
      setQueued(true)
    } else {
      clearQueuedChange(sessionId)
      setQueued(false)
    }
  }

  const save = useMutation({
    mutationKey,
    mutationFn: ({ change }: Save) => changeAttendance(sessionId, change),
    onSuccess: (updated, { change: sent }) => {
      queryClient.setQueryData(rosterQuery(sessionId).queryKey, updated)
      refreshFlags(queryClient, sessionId)
      setSaved(true)
      setDropped(false)
      clearQueuedChange(sessionId)
      setQueued(false)
      // A tap made while it was on its way stays, to be saved with the button.
      const left = new Map(latestTaps.current)
      for (const id of sent.mark) if (left.get(id) === true) left.delete(id)
      for (const id of sent.unmark) if (left.get(id) === false) left.delete(id)
      setTaps(left)
    },
    onError: (error, { change: sent, replay }) => {
      if (!isRefusal(error)) {
        // No signal, a server error or an expired session: resending may well work,
        // so what waits on the phone stays, up to date, for the next flush.
        if (isOffline(error) || queuedChange(sessionId)) persist(latestTaps.current)
        return
      }
      // Refused: resending it would be refused again.
      clearQueuedChange(sessionId)
      setQueued(false)
      if (!replay) return
      setDropped(true)
      const left = new Map(latestTaps.current)
      for (const id of [...sent.mark, ...sent.unmark]) left.delete(id)
      setTaps(left)
    },
  })
  const { mutate } = save

  // What an earlier visit or a lost signal left on the phone, sent once there is signal,
  // and never beside a save still on its way, whose answer it could overwrite.
  useEffect(() => {
    const flush = () => {
      const change = queuedChange(sessionId)
      if (!change || queryClient.isMutating({ mutationKey: ['attendance', 'save', sessionId] }) > 0) return
      mutate({ change, replay: true })
    }
    flush()
    window.addEventListener('online', flush)
    return () => window.removeEventListener('online', flush)
  }, [sessionId, mutate, queryClient])

  if (roster.isPending) {
    return <p className="classes__note">{words.loading}</p>
  }
  if (roster.isError) {
    return (
      <div className="classes__error" role="alert">
        <p>{words.error}</p>
        <Button onClick={() => void roster.refetch()}>
          {copy.retry}
        </Button>
      </div>
    )
  }

  const members = roster.data.members
  const here = (member: RosterMember) => taps.get(member.membership_id) ?? member.present
  const present = members.filter(here).length
  // Regulars first, and whoever is already saved present; the rest under "Otros alumnos".
  // A class type nobody has come to lately has no regulars: everyone is listed as one.
  const first = members.filter((m) => m.regular || m.present)
  const grouped = first.length > 0
  const top = grouped ? first : members
  const rest = grouped ? members.filter((m) => !(m.regular || m.present)) : []
  const matches = matcher(search)
  const searching = search.trim() !== ''
  const shownTop = top.filter(matches)
  const shownRest = rest.filter(matches)
  const restOpen = othersOpen || searching
  const change = changeOf(roster.data, taps)
  const changed = change.mark.length + change.unmark.length > 0
  // "Guardado ✓" until the next tap.
  const done = saved && !changed && !queued && !save.isPending

  const tap = (member: RosterMember, value: boolean): Taps => {
    setSaved(false)
    setDropped(false)
    const next = new Map(taps)
    if (value === member.present) next.delete(member.membership_id)
    else next.set(member.membership_id, value)
    setTaps(next)
    if (queued) persist(next)
    return next
  }
  const toggle = (member: RosterMember) => tap(member, !here(member))

  /** A trial guest who was already a member: marked present and saved, as a tap would be. */
  const markMember = (membershipId: string) => {
    const member = members.find((m) => m.membership_id === membershipId)
    if (member) tap(member, true)
    save.mutate({ change: { mark: [membershipId], unmark: [] }, replay: false })
  }

  return (
    <section className="classes__section" aria-labelledby="attendance-title">
      <div className="classes__section-head">
        <h2 id="attendance-title" className="classes__section-title">
          {words.title}
        </h2>
        <span className="attendance__count" aria-live="polite">
          {words.count(top.filter(here).length, top.length)}
        </span>
      </div>
      <p className="classes__note">{members.length === 0 ? words.empty : words.hint}</p>
      {members.length > 0 && (
        <div role="search" className="attendance__search">
          <label htmlFor={searchId} className="visually-hidden">
            {words.search}
          </label>
          <Input
            id={searchId}
            type="search"
            autoComplete="off"
            placeholder={words.searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      )}
      {searching && shownTop.length + shownRest.length === 0 && <p className="classes__note">{words.noMatches}</p>}
      {shownTop.length > 0 && (
        <ul className="classes__list" aria-label={words.title}>
          {shownTop.map((member) => (
            <li key={member.membership_id}>
              <RosterRow member={member} here={here(member)} onToggle={() => toggle(member)} />
            </li>
          ))}
        </ul>
      )}
      {rest.length > 0 && !searching && (
        <Button fullWidth aria-expanded={othersOpen} onClick={() => setOthersOpen(!othersOpen)}>
          {words.others(rest.length, rest.filter(here).length)}
        </Button>
      )}
      {restOpen && shownRest.length > 0 && (
        <ul className="classes__list" aria-label={words.othersLabel}>
          {shownRest.map((member) => (
            <li key={member.membership_id}>
              <RosterRow member={member} here={here(member)} onToggle={() => toggle(member)} />
            </li>
          ))}
        </ul>
      )}
      <TrialGuest sessionId={sessionId} onMember={markMember} />
      {/* Sticky at the foot of the screen, so what a save did is in view however far down the list is. */}
      <div className="attendance__bar">
        {save.isError && !isOffline(save.error) && !dropped && (
          <p className="classes__error" role="alert">
            {words.failed}
          </p>
        )}
        {queued && (
          <p className="classes__error" role="status">
            {words.queued}
          </p>
        )}
        {dropped && (
          <p className="classes__error" role="alert">
            {words.dropped}
          </p>
        )}
        {done && (
          <div className="classes__done attendance__done">
            <p role="status">{words.saved}</p>
            <Link to="/admin/clases" className="attendance__back">
              {words.back}
            </Link>
          </div>
        )}
        <Button
          variant="primary"
          className={done ? 'attendance__save attendance__save--done' : 'attendance__save'}
          disabled={!changed || save.isPending}
          aria-busy={save.isPending}
          onClick={() => {
            setSaved(false)
            save.mutate({ change, replay: false })
          }}
        >
          {save.isPending ? words.working : done ? words.done : words.save(present)}
        </Button>
      </div>
    </section>
  )
}

/** Lower case, accents gone: "martin" finds "Martín". */
function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Whether a roster row is what `query` looks for: by name, or by RUT when it holds a digit,
 * typed in any format (`12.345.678-5`, `123456785`). */
export function matcher(query: string): (member: RosterMember) => boolean {
  const name = fold(query.trim())
  const rut = /\d/.test(query) ? query.toUpperCase().replace(/[^0-9K]/g, '') : ''
  if (!name) return () => true
  return (member) =>
    fold(member.name).includes(name) ||
    (rut !== '' && member.rut !== null && member.rut.toUpperCase().replace(/[^0-9K]/g, '').includes(rut))
}

function RosterRow({ member, here, onToggle }: { member: RosterMember; here: boolean; onToggle: () => void }) {
  const words = copy.attendance
  // A drawn belt says the rank itself; a rank with no colours says it in words.
  const belt = member.rank?.belt ? member.rank : null
  const detail = [
    member.rank && !belt && rankLabel(member.rank),
    member.plan_name,
    member.credits_remaining !== null && words.left(member.credits_remaining),
    (member.status === 'lapsed' || member.status === 'frozen') && t.admin.students.status[member.status],
    member.days_absent !== null && member.days_absent >= ABSENT_DAYS && words.absent(member.days_absent),
  ]
    .filter(Boolean)
    .join(' · ')
  return (
    <button
      type="button"
      className={`attendance__row${here ? ' attendance__row--here' : ''}`}
      aria-pressed={here}
      onClick={onToggle}
    >
      <span className="attendance__check" aria-hidden="true">
        {here && <CheckIcon />}
      </span>
      <span className="classes__row-text">
        <span className="classes__name">{member.name}</span>
        <span className="classes__detail">
          {belt && <RankBelt rank={belt} compact />}
          {detail}
        </span>
      </span>
      {member.overdue && <span className="attendance__overdue" role="img" aria-label={words.overdue} />}
    </button>
  )
}

/** The Clases list and the dashboard flag a class no one is marked at: refetch both, and
 * the session itself, whose `present` the change made stale. */
function refreshFlags(queryClient: QueryClient, sessionId: string) {
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'detail', sessionId] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
}

/** "+ Agregar alumno de prueba": someone trying a class, added by their RUT or email, with
 * their phone, present at it. */
function TrialGuest({ sessionId, onMember }: { sessionId: string; onMember: (membershipId: string) => void }) {
  const words = copy.attendance.guest
  const queryClient = useQueryClient()
  const plans = useQuery(trialPlansQuery())
  const ids = { name: useId(), who: useId(), phone: useId(), plan: useId() }
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [who, setWho] = useState('')
  const [phone, setPhone] = useState('')
  const [planId, setPlanId] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const add = useMutation({
    mutationFn: (guest: { name: string; who: string; phone: string; planId: string }) =>
      addTrialGuest(sessionId, guest),
    onSuccess: (added, guest) => {
      if ('roster' in added) {
        queryClient.setQueryData(rosterQuery(sessionId).queryKey, added.roster)
        refreshFlags(queryClient, sessionId)
        setDone(words.done(guest.name))
      } else {
        onMember(added.member)
        setDone(words.member(guest.name))
      }
      setOpen(false)
      setName('')
      setWho('')
      setPhone('')
    },
  })

  if (!open) {
    return (
      <>
        {done && (
          <p className="classes__done" role="status">
            {done}
          </p>
        )}
        <Button
          fullWidth
          onClick={() => {
            setDone(null)
            add.reset()
            setOpen(true)
          }}
        >
          {words.open}
        </Button>
      </>
    )
  }

  const trials = plans.data ?? []
  const chosen = planId || trials[0]?.id || ''
  const submit = (event: FormEvent) => {
    event.preventDefault()
    add.mutate({ name: name.trim(), who, phone, planId: chosen })
  }
  const failure = add.isError
    ? isOffline(add.error)
      ? words.offline
      : add.error instanceof ApiError && add.error.status === 422
        ? words.invalid
        : hasLeft(add.error)
          ? words.hasLeft
          : words.failed
    : null

  return (
    <form className="classes__card classes__form" aria-label={words.label} onSubmit={submit}>
      {plans.isSuccess && trials.length === 0 ? (
        <p className="classes__note">{words.noPlans}</p>
      ) : (
        <>
          <label htmlFor={ids.name} className="classes__label">
            {words.name}
          </label>
          <Input
            id={ids.name}
            value={name}
            required
            autoComplete="off"
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor={ids.who} className="classes__label">
            {words.who}
          </label>
          <Input
            id={ids.who}
            value={who}
            required
            autoComplete="off"
            placeholder={words.whoPlaceholder}
            onChange={(e) => setWho(e.target.value)}
          />
          <label htmlFor={ids.phone} className="classes__label">
            {words.phone}
          </label>
          <Input
            id={ids.phone}
            type="tel"
            inputMode="tel"
            value={phone}
            required
            placeholder={words.phonePlaceholder}
            onChange={(e) => setPhone(e.target.value)}
          />
          {trials.length > 1 && (
            <>
              <label htmlFor={ids.plan} className="classes__label">
                {words.plan}
              </label>
              <Select
                id={ids.plan}
                value={chosen}
                onChange={(e) => setPlanId(e.target.value)}
              >
                {trials.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                  </option>
                ))}
              </Select>
            </>
          )}
          {failure && (
            <p className="classes__error" role="alert">
              {failure}
            </p>
          )}
          <Button
            type="submit"
            variant="primary"
            disabled={add.isPending || !chosen || !name.trim() || !who.trim()}
          >
            {add.isPending ? words.working : words.submit}
          </Button>
        </>
      )}
      <Button onClick={() => setOpen(false)}>
        {words.cancel}
      </Button>
    </form>
  )
}
