import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { getRouteApi, Link } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  addTrialGuest,
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
import { rankLabel } from '../api/grading'
import { sessionQuery, todaySessionsQuery, updateSession, type ClassSession } from '../api/sessions'
import { CheckIcon, ChevronLeftIcon } from '../components/icons'
import { clockTime } from '../format'
import { t } from '../i18n/es'
import './Classes.css'

const copy = t.admin.session

const route = getRouteApi('/admin/clases/$sessionId')

// The topic is one line and notes a few paragraphs: the backend's MAX_TOPIC and MAX_NOTES.
const MAX_TOPIC = 200
const MAX_NOTES = 4000

/**
 * One class: what it is, when it started and who teaches it, "Asistencia" (the roster,
 * tapped name by name), and its topic and notes, written during or after class.
 */
export function SessionDetail() {
  const { sessionId } = route.useParams()
  const session = useQuery(sessionQuery(sessionId))
  // The gym's timezone, from the day's list; the browser's until it arrives.
  const today = useQuery(todaySessionsQuery())
  const timeZone = today.data?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone

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
            <button type="button" className="classes__button" onClick={() => void session.refetch()}>
              {copy.retry}
            </button>
          )}
        </div>
      </Shell>
    )
  }

  const data = session.data
  return (
    <Shell
      eyebrow={copy.eyebrow(data.program_name, clockTime(data.starts_at, timeZone))}
      title={data.class_type_name}
      subtitle={copy.coach(data.coach_name)}
    >
      <Attendance key={`attendance-${data.id}`} sessionId={data.id} />
      <TopicForm key={data.id} session={data} />
    </Shell>
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
        <Link to="/admin/clases" className="classes__icon-button" aria-label={copy.back}>
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

function TopicForm({ session }: { session: ClassSession }) {
  const queryClient = useQueryClient()
  const topicId = useId()
  const notesId = useId()
  const [topic, setTopic] = useState(session.topic ?? '')
  const [notes, setNotes] = useState(session.notes ?? '')
  const [saved, setSaved] = useState(false)
  const save = useMutation({
    mutationFn: () => updateSession(session.id, { topic, notes }),
    onSuccess: (updated) => {
      // As stored: trimmed, and blank as none.
      setTopic(updated.topic ?? '')
      setNotes(updated.notes ?? '')
      setSaved(true)
      queryClient.setQueryData(['sessions', 'detail', session.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
    },
  })
  // "Guardado" until the next edit.
  const changed = topic !== (session.topic ?? '') || notes !== (session.notes ?? '')

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
      <input
        id={topicId}
        className="classes__input"
        value={topic}
        maxLength={MAX_TOPIC}
        placeholder={copy.form.topicPlaceholder}
        onChange={(e) => setTopic(e.target.value)}
      />
      <label htmlFor={notesId} className="classes__label">
        {copy.form.notes}
      </label>
      <textarea
        id={notesId}
        className="classes__input classes__textarea"
        value={notes}
        maxLength={MAX_NOTES}
        rows={5}
        placeholder={copy.form.notesPlaceholder}
        onChange={(e) => setNotes(e.target.value)}
      />
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
      <button type="submit" className="classes__button classes__button--primary" disabled={save.isPending}>
        {save.isPending ? copy.form.working : copy.form.submit}
      </button>
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
      refreshFlags(queryClient)
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
        <button type="button" className="classes__button" onClick={() => void roster.refetch()}>
          {copy.retry}
        </button>
      </div>
    )
  }

  const members = roster.data.members
  const here = (member: RosterMember) => taps.get(member.membership_id) ?? member.present
  const present = members.filter(here).length
  const change = changeOf(roster.data, taps)
  const changed = change.mark.length + change.unmark.length > 0

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
          {words.count(present, members.length)}
        </span>
      </div>
      <p className="classes__note">{members.length === 0 ? words.empty : words.hint}</p>
      <ul className="classes__list" aria-label={words.title}>
        {members.map((member) => (
          <li key={member.membership_id}>
            <RosterRow member={member} here={here(member)} onToggle={() => toggle(member)} />
          </li>
        ))}
      </ul>
      <TrialGuest sessionId={sessionId} onMember={markMember} />
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
      {saved && !changed && !queued && (
        <p className="classes__done" role="status">
          {words.saved}
        </p>
      )}
      <div className="attendance__bar">
        <button
          type="button"
          className="classes__button classes__button--primary attendance__save"
          disabled={!changed || save.isPending}
          onClick={() => {
            setSaved(false)
            save.mutate({ change, replay: false })
          }}
        >
          {save.isPending ? words.working : words.save(present)}
        </button>
      </div>
    </section>
  )
}

function RosterRow({ member, here, onToggle }: { member: RosterMember; here: boolean; onToggle: () => void }) {
  const words = copy.attendance
  const detail = [
    member.rank && rankLabel(member.rank),
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
        <span className="classes__detail">{detail}</span>
      </span>
      {member.overdue && <span className="attendance__overdue" role="img" aria-label={words.overdue} />}
    </button>
  )
}

/** The Clases list and the dashboard flag a class no one is marked at: refetch both. */
function refreshFlags(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'today'] })
  void queryClient.invalidateQueries({ queryKey: ['sessions', 'unmarked'] })
}

/** "+ Agregar alumno de prueba": someone trying a class, added by phone, present at it. */
function TrialGuest({ sessionId, onMember }: { sessionId: string; onMember: (membershipId: string) => void }) {
  const words = copy.attendance.guest
  const queryClient = useQueryClient()
  const plans = useQuery(trialPlansQuery())
  const ids = { name: useId(), phone: useId(), plan: useId() }
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [planId, setPlanId] = useState('')
  const [done, setDone] = useState<string | null>(null)
  const add = useMutation({
    mutationFn: (guest: { name: string; phone: string; planId: string }) => addTrialGuest(sessionId, guest),
    onSuccess: (added, guest) => {
      if ('roster' in added) {
        queryClient.setQueryData(rosterQuery(sessionId).queryKey, added.roster)
        refreshFlags(queryClient)
        setDone(words.done(guest.name))
      } else {
        onMember(added.member)
        setDone(words.member(guest.name))
      }
      setOpen(false)
      setName('')
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
        <button
          type="button"
          className="attendance__add"
          onClick={() => {
            setDone(null)
            add.reset()
            setOpen(true)
          }}
        >
          {words.open}
        </button>
      </>
    )
  }

  const trials = plans.data ?? []
  const chosen = planId || trials[0]?.id || ''
  const submit = (event: FormEvent) => {
    event.preventDefault()
    add.mutate({ name: name.trim(), phone, planId: chosen })
  }
  const failure = add.isError
    ? isOffline(add.error)
      ? words.offline
      : add.error instanceof ApiError && add.error.status === 422
        ? words.badPhone
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
          <input
            id={ids.name}
            className="classes__input"
            value={name}
            required
            autoComplete="off"
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor={ids.phone} className="classes__label">
            {words.phone}
          </label>
          <input
            id={ids.phone}
            className="classes__input"
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
              <select
                id={ids.plan}
                className="classes__input"
                value={chosen}
                onChange={(e) => setPlanId(e.target.value)}
              >
                {trials.map((plan) => (
                  <option key={plan.id} value={plan.id}>
                    {plan.name}
                  </option>
                ))}
              </select>
            </>
          )}
          {failure && (
            <p className="classes__error" role="alert">
              {failure}
            </p>
          )}
          <button
            type="submit"
            className="classes__button classes__button--primary"
            disabled={add.isPending || !chosen || !name.trim()}
          >
            {add.isPending ? words.working : words.submit}
          </button>
        </>
      )}
      <button type="button" className="classes__button" onClick={() => setOpen(false)}>
        {words.cancel}
      </button>
    </form>
  )
}
