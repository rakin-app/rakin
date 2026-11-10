import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getRouteApi, Link, useNavigate } from '@tanstack/react-router'
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { blockKindsQuery, type BlockKind } from '../api/blockKinds'
import { ApiError } from '../api/client'
import { myselfQuery, runsSession } from '../api/me'
import {
  MAX_BLOCK_SECONDS,
  MAX_BLOCKS,
  MAX_ROUND_SECONDS,
  MAX_ROUNDS,
  queueActual,
  queuePlan,
  sessionPlanQuery,
  suggestedPlanQuery,
  syncSession,
  usePendingSync,
  type SessionBlock,
  type SuggestedBlock,
} from '../api/sessionBlocks'
import { sessionQuery, useGymTimeZone, type ClassSession } from '../api/sessions'
import { ChevronDownIcon, ChevronLeftIcon, ChevronUpIcon, CloseIcon } from '../components/icons'
import { clockTime } from '../format'
import { t } from '../i18n/es'
import {
  addMinute,
  advance,
  clearRun,
  currentBlock,
  endClass,
  leftUnseen,
  pause,
  phaseMs,
  plannedBlock,
  plannedSeconds,
  remainingMs,
  replaceUpcoming,
  resume,
  savedRun,
  saveRun,
  skip,
  startRun,
  touch,
  upcomingBlocks,
  type BlockResult,
  type RunState,
  type Step,
  type TimerBlock,
} from './timerEngine'
import { signal, unlockSound, useWakeLock } from './timerSignal'
import './Classes.css'
import './ClassTimer.css'

const copy = t.admin.timer

const route = getRouteApi('/admin/clases/$sessionId/timer')

// The warning before a phase ends, and how late a phase's end may be noticed and still
// be signalled: one that ran out while the phone was locked is not beeped at on return.
const WARN_MS = 10_000
const SIGNAL_LATE_MS = 3_000
const TICK_MS = 250

// An open mat with no earlier one to start from.
const OPEN_MAT_DEFAULT = { rounds: 6, roundSeconds: 5 * 60, restSeconds: 60 }

/** A block id for the plan: the API keeps a block, and what it ran, by it. */
export function newId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // Over plain http on a LAN, `randomUUID` is missing; `getRandomValues` is not.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** `12:05`; a second started counts whole. */
export function clock(ms: number): string {
  const seconds = Math.ceil(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** `Técnica · 20 min`, `Sparring · 6 × 5 min + 1 min descanso`. */
function summary(block: TimerBlock): string {
  if (!block.sparring) return copy.blockSummary(block.kindName, copy.minutes(block.seconds))
  const rest = block.restSeconds ? copy.minutes(block.restSeconds) : null
  return copy.roundsSummary(block.kindName, block.rounds ?? 0, copy.minutes(block.roundSeconds ?? 0), rest)
}

/**
 * The class timer (#139): the coach runs a class as blocks. First the blocks, from the
 * last class of the type, changed as needed; then the countdown, full screen, one block
 * and round at a time; then what ran. What each block ran is sent as it finishes,
 * through a queue that waits for signal (`queuePlan`, `queueActual`), and the run itself
 * is kept on the phone, so a reload or a locked phone finds the class where it is.
 *
 * Only the session's coach, an owner or an admin runs it, as the API allows.
 */
export function ClassTimer() {
  const { sessionId } = route.useParams()
  const queryClient = useQueryClient()
  const session = useQuery(sessionQuery(sessionId))
  const me = useQuery(myselfQuery())
  const [run, setRun] = useState<RunState | null>(() => savedRun(sessionId))

  /** Keep `state`, and queue what it changed for the API: its plan, its finished blocks. */
  const commit = useCallback(
    (state: RunState, finished: BlockResult[] = [], planChanged = false) => {
      if (planChanged) queuePlan(sessionId, state.blocks.map(plannedBlock))
      for (const { blockId, ...actual } of finished) queueActual(sessionId, blockId, actual)
      saveRun(sessionId, state)
      setRun(state)
      if (planChanged || finished.length > 0) void syncSession(queryClient, sessionId)
    },
    [sessionId, queryClient],
  )

  if (session.isPending || me.isPending) {
    return (
      <Shell sessionId={sessionId}>
        <p className="classes__note">{copy.loading}</p>
      </Shell>
    )
  }
  if (session.isError || me.isError) {
    const missing = session.error instanceof ApiError && session.error.status === 404
    return (
      <Shell sessionId={sessionId}>
        <div className="classes__error" role="alert">
          <p>{missing ? t.admin.session.notFound : copy.error}</p>
          {!missing && (
            <button
              type="button"
              className="classes__button"
              onClick={() => void (session.isError ? session.refetch() : me.refetch())}
            >
              {copy.retry}
            </button>
          )}
        </div>
      </Shell>
    )
  }
  if (!runsSession(me.data, session.data.coach_id)) {
    return (
      <Shell sessionId={sessionId} title={session.data.class_type_name}>
        <p className="classes__note" role="alert">
          {copy.notAllowed}
        </p>
      </Shell>
    )
  }

  if (run === null) {
    return (
      <Prepare
        session={session.data}
        onStart={(blocks, openMat) => {
          unlockSound()
          commit(startRun(blocks, Date.now(), openMat), [], true)
        }}
      />
    )
  }
  if (run.endedAt !== null) {
    return <Finished session={session.data} run={run} />
  }
  return <Running session={session.data} run={run} commit={commit} />
}

function Shell({ sessionId, title, children }: { sessionId: string; title?: string; children: ReactNode }) {
  return (
    <div className="classes">
      <header className="classes__header">
        <Link
          to="/admin/clases/$sessionId"
          params={{ sessionId }}
          className="classes__icon-button"
          aria-label={copy.back}
        >
          <ChevronLeftIcon />
        </Link>
        {title && (
          <div className="classes__heading">
            <h1 className="classes__title">{title}</h1>
          </div>
        )}
      </header>
      <div className="classes__body">{children}</div>
    </div>
  )
}

// --- before the class: the blocks ----------------------------------------------------

/** A block as typed: numbers as text, checked on "Comenzar". */
type Draft = {
  id: string
  kindId: string
  minutes: string
  rounds: string
  roundMinutes: string
  restSeconds: string
}

type Field = 'minutes' | 'rounds' | 'roundMinutes' | 'restSeconds'

type Planned = Pick<SuggestedBlock, 'block_kind_id' | 'rounds_planned' | 'round_seconds' | 'rest_seconds'> & {
  planned_seconds: number | null
}

const asMinutes = (seconds: number | null) => (seconds === null ? '' : String(Math.round(seconds / 6) / 10))

function draftOf(block: Planned, id: string): Draft {
  return {
    id,
    kindId: block.block_kind_id,
    minutes: asMinutes(block.planned_seconds),
    rounds: block.rounds_planned === null ? '' : String(block.rounds_planned),
    roundMinutes: asMinutes(block.round_seconds),
    restSeconds: block.rest_seconds === null ? '' : String(block.rest_seconds),
  }
}

function draftOfBlock(block: TimerBlock): Draft {
  return draftOf(
    {
      block_kind_id: block.kindId,
      planned_seconds: block.seconds,
      rounds_planned: block.rounds,
      round_seconds: block.roundSeconds,
      rest_seconds: block.restSeconds,
    },
    block.id,
  )
}

function openMatDraft(kind: BlockKind | undefined): Draft {
  return draftOf(
    {
      block_kind_id: kind?.id ?? '',
      planned_seconds: null,
      rounds_planned: OPEN_MAT_DEFAULT.rounds,
      round_seconds: OPEN_MAT_DEFAULT.roundSeconds,
      rest_seconds: OPEN_MAT_DEFAULT.restSeconds,
    },
    newId(),
  )
}

function newDraft(kind: BlockKind | undefined): Draft {
  return kind?.is_sparring
    ? openMatDraft(kind)
    : { id: newId(), kindId: kind?.id ?? '', minutes: '10', rounds: '', roundMinutes: '', restSeconds: '' }
}

const number = (text: string) => (text.trim() === '' ? NaN : Number(text.replace(',', '.').trim()))

/** The draft as a block, or the fields that are wrong. */
function blockOf(draft: Draft, kind: BlockKind | undefined): TimerBlock | Set<Field> {
  const wrong = new Set<Field>()
  if (!kind) return wrong
  const base = { id: draft.id, kindId: kind.id, kindName: kind.name, sparring: kind.is_sparring }
  if (!kind.is_sparring) {
    const seconds = Math.round(number(draft.minutes) * 60)
    if (!(seconds >= 1 && seconds <= MAX_BLOCK_SECONDS)) return new Set(['minutes'])
    return { ...base, seconds, rounds: null, roundSeconds: null, restSeconds: null }
  }
  const rounds = number(draft.rounds)
  const roundSeconds = Math.round(number(draft.roundMinutes) * 60)
  const restSeconds = draft.restSeconds.trim() === '' ? 0 : number(draft.restSeconds)
  if (!(Number.isInteger(rounds) && rounds >= 1 && rounds <= MAX_ROUNDS)) wrong.add('rounds')
  if (!(roundSeconds >= 1 && roundSeconds <= MAX_ROUND_SECONDS)) wrong.add('roundMinutes')
  if (!(Number.isInteger(restSeconds) && restSeconds >= 0 && restSeconds <= MAX_ROUND_SECONDS)) wrong.add('restSeconds')
  if (wrong.size === 0 && rounds * roundSeconds > MAX_BLOCK_SECONDS) wrong.add('rounds')
  if (wrong.size > 0) return wrong
  return { ...base, seconds: rounds * roundSeconds, rounds, roundSeconds, restSeconds }
}

/** The blocks to start from: the session's own plan, if it has one; else the last class
 * of the type's; an open mat, its rounds. */
function initialDrafts(plan: SessionBlock[], suggested: SuggestedBlock[], openMat: boolean, kinds: BlockKind[]) {
  const sparringKind = kinds.find((k) => k.is_sparring && !k.archived)
  if (openMat) {
    const own = plan.length === 1 && plan[0]!.is_sparring ? plan[0]! : null
    if (own) return [draftOf(own, newId())]
    const last = suggested.find((b) => b.is_sparring)
    return [last ? draftOf(last, newId()) : openMatDraft(sparringKind)]
  }
  // New ids: a session run again starts unrecorded, and the API drops what the old
  // blocks had, rather than keep it on blocks this run leaves out.
  if (plan.length > 0) return plan.map((b) => draftOf(b, newId()))
  return suggested.map((b) => draftOf(b, newId()))
}

/** "Iniciar clase": the blocks, prefilled, then "Comenzar". */
function Prepare({
  session,
  onStart,
}: {
  session: ClassSession
  onStart: (blocks: TimerBlock[], openMat: boolean) => void
}) {
  const plan = useQuery(sessionPlanQuery(session.id))
  const suggested = useQuery(suggestedPlanQuery(session.id))
  const kinds = useQuery(blockKindsQuery)

  const failed = plan.isError || suggested.isError || kinds.isError
  if (failed) {
    return (
      <Shell sessionId={session.id} title={session.class_type_name}>
        <div className="classes__error" role="alert">
          <p>{copy.error}</p>
          <button
            type="button"
            className="classes__button"
            onClick={() => {
              void plan.refetch()
              void suggested.refetch()
              void kinds.refetch()
            }}
          >
            {copy.retry}
          </button>
        </div>
      </Shell>
    )
  }
  if (plan.isPending || suggested.isPending || kinds.isPending) {
    return (
      <Shell sessionId={session.id} title={session.class_type_name}>
        <p className="classes__note">{copy.loading}</p>
      </Shell>
    )
  }

  const openMat = plan.data.class_kind === 'open_mat'
  const initial = initialDrafts(plan.data.blocks, suggested.data.blocks, openMat, kinds.data)
  const hint = openMat ? copy.editor.hintOpenMat : initial.length > 0 ? copy.editor.hint : copy.editor.hintEmpty
  return (
    <Shell sessionId={session.id} title={session.class_type_name}>
      <PlanEditor
        initial={initial}
        kinds={kinds.data}
        openMat={openMat}
        fixed={0}
        hint={hint}
        submit={copy.editor.start}
        onSubmit={(blocks) => onStart(blocks, openMat)}
      />
    </Shell>
  )
}

/**
 * The blocks, one card each: its kind, and its minutes, or for sparring its rounds, each
 * round's minutes and the rest between them. Moved up and down, removed, added. An open
 * mat is one sparring block, its rounds only. `fixed` blocks of the plan are not here
 * (they ran or are running) but count toward its limit.
 */
function PlanEditor({
  initial,
  kinds,
  openMat,
  fixed,
  hint,
  submit,
  onSubmit,
  onCancel,
}: {
  initial: Draft[]
  kinds: BlockKind[]
  openMat: boolean
  fixed: number
  hint: string
  submit: string
  onSubmit: (blocks: TimerBlock[]) => void
  onCancel?: () => void
}) {
  const words = copy.editor
  const [drafts, setDrafts] = useState(initial)
  const [checked, setChecked] = useState(false)
  // What can be picked: the kinds not archived, and an archived one a kept block is of.
  const byId = new Map(kinds.map((k) => [k.id, k]))
  const choices = kinds.filter(
    (k) => (!k.archived || initial.some((d) => d.kindId === k.id)) && (!openMat || k.is_sparring),
  )
  const firstKind = choices.find((k) => !k.archived && !k.is_sparring) ?? choices.find((k) => !k.archived)
  const blocks = drafts.map((d) => blockOf(d, byId.get(d.kindId)))
  const valid = blocks.every((b) => !(b instanceof Set))
  const full = fixed + drafts.length >= MAX_BLOCKS
  const total = blocks.reduce((sum, b) => sum + (b instanceof Set ? 0 : plannedSeconds(b)), 0)

  const change = (index: number, update: Partial<Draft>) =>
    setDrafts((all) => all.map((d, i) => (i === index ? { ...d, ...update } : d)))
  const move = (index: number, by: number) =>
    setDrafts((all) => {
      const next = [...all]
      const [moved] = next.splice(index, 1)
      next.splice(index + by, 0, moved!)
      return next
    })

  const kindChanged = (index: number, kindId: string) => {
    const kind = byId.get(kindId)
    const draft = drafts[index]!
    // A block turned sparring starts from the open mat's rounds; one turned back, 10 min.
    const was = byId.get(draft.kindId)?.is_sparring ?? false
    if (kind && kind.is_sparring !== was) {
      change(index, { ...(kind.is_sparring ? openMatDraft(kind) : newDraft(kind)), id: draft.id, kindId })
    } else {
      change(index, { kindId })
    }
  }

  const noKinds = choices.length === 0
  return (
    <form
      className="timer-editor"
      aria-label={words.title}
      onSubmit={(event) => {
        event.preventDefault()
        setChecked(true)
        if (!valid || noKinds) return
        onSubmit(blocks as TimerBlock[])
      }}
    >
      <div className="classes__section-head">
        <h2 className="classes__section-title">{words.title}</h2>
        {total > 0 && <span className="classes__aside">{words.total(copy.minutes(total))}</span>}
      </div>
      <p className="classes__note">{hint}</p>
      {noKinds && (
        <p className="classes__error" role="alert">
          {openMat ? words.noSparring : words.noKinds}
        </p>
      )}
      {drafts.length === 0 && !noKinds && <p className="classes__note">{words.empty}</p>}
      <ol className="timer-editor__list">
        {drafts.map((draft, index) => (
          <li key={draft.id}>
            <DraftCard
              draft={draft}
              number={index + 1}
              kind={byId.get(draft.kindId)}
              choices={choices}
              wrong={checked && blocks[index] instanceof Set ? (blocks[index] as Set<Field>) : new Set()}
              fixedKind={openMat}
              first={index === 0}
              last={index === drafts.length - 1}
              onKind={(kindId) => kindChanged(index, kindId)}
              onChange={(update) => change(index, update)}
              onMove={(by) => move(index, by)}
              onRemove={() => setDrafts((all) => all.filter((_, i) => i !== index))}
            />
          </li>
        ))}
      </ol>
      {!openMat && !noKinds && (
        <>
          {full && <p className="classes__note">{words.tooMany(MAX_BLOCKS)}</p>}
          <button
            type="button"
            className="attendance__add"
            disabled={full}
            onClick={() => setDrafts((all) => [...all, newDraft(firstKind)])}
          >
            {words.add}
          </button>
        </>
      )}
      <div className="attendance__bar">
        {checked && !valid && (
          <p className="classes__error" role="alert">
            {words.invalid}
          </p>
        )}
        <button
          type="submit"
          className="classes__button classes__button--primary"
          disabled={noKinds || (fixed === 0 && drafts.length === 0)}
        >
          {submit}
        </button>
        {onCancel && (
          <button type="button" className="classes__button" onClick={onCancel}>
            {words.cancel}
          </button>
        )}
      </div>
    </form>
  )
}

function DraftCard({
  draft,
  number: n,
  kind,
  choices,
  wrong,
  fixedKind,
  first,
  last,
  onKind,
  onChange,
  onMove,
  onRemove,
}: {
  draft: Draft
  number: number
  kind: BlockKind | undefined
  choices: BlockKind[]
  wrong: Set<Field>
  fixedKind: boolean
  first: boolean
  last: boolean
  onKind: (kindId: string) => void
  onChange: (update: Partial<Draft>) => void
  onMove: (by: number) => void
  onRemove: () => void
}) {
  const words = copy.editor
  const id = useId()
  const input = (field: Field, label: string, mode: 'numeric' | 'decimal') => (
    <div className="timer-editor__field">
      <label htmlFor={`${id}-${field}`} className="classes__label">
        {label}
      </label>
      <input
        id={`${id}-${field}`}
        className="classes__input"
        inputMode={mode}
        value={draft[field]}
        aria-invalid={wrong.has(field) || undefined}
        onChange={(e) => onChange({ [field]: e.target.value })}
      />
    </div>
  )
  return (
    <fieldset className="classes__card timer-editor__card">
      <legend className="visually-hidden">{words.label(n)}</legend>
      <div className="timer-editor__head">
        <span className="classes__section-title" aria-hidden="true">
          {words.label(n)}
        </span>
        {!fixedKind && (
          <span className="timer-editor__actions">
            <button
              type="button"
              className="classes__icon-button"
              aria-label={words.up(n)}
              disabled={first}
              onClick={() => onMove(-1)}
            >
              <ChevronUpIcon />
            </button>
            <button
              type="button"
              className="classes__icon-button"
              aria-label={words.down(n)}
              disabled={last}
              onClick={() => onMove(1)}
            >
              <ChevronDownIcon />
            </button>
            <button type="button" className="classes__icon-button" aria-label={words.remove(n)} onClick={onRemove}>
              <CloseIcon />
            </button>
          </span>
        )}
      </div>
      <label htmlFor={`${id}-kind`} className="classes__label">
        {words.kind}
      </label>
      <select id={`${id}-kind`} className="classes__input" value={draft.kindId} onChange={(e) => onKind(e.target.value)}>
        {choices.map((k) => (
          <option key={k.id} value={k.id}>
            {k.name}
          </option>
        ))}
      </select>
      {kind?.is_sparring ? (
        <div className="timer-editor__rounds">
          {input('rounds', words.rounds, 'numeric')}
          {input('roundMinutes', words.roundMinutes, 'decimal')}
          {input('restSeconds', words.restSeconds, 'numeric')}
        </div>
      ) : (
        input('minutes', words.minutes, 'decimal')
      )}
    </fieldset>
  )
}

// --- during the class: the countdown -------------------------------------------------

/** What the phase is: `Técnica`, `Sparring · ronda 3/6`, `Descanso · sigue la ronda 4/6`. */
function phaseLabel(run: RunState, block: TimerBlock): string {
  if (!block.sparring) return block.kindName
  const rounds = block.rounds ?? 1
  return run.resting ? copy.running.rest(run.round + 1, rounds) : copy.running.round(block.kindName, run.round, rounds)
}

/** What comes after the phase: the next round or rest, else the next block. */
function nextLabel(run: RunState, block: TimerBlock): string {
  const words = copy.running
  const rounds = block.rounds ?? 1
  if (block.sparring && run.round < rounds) {
    if (!run.resting && (block.restSeconds ?? 0) > 0) return words.next(words.nextRest(copy.minutes(block.restSeconds!)))
    return words.next(words.nextRound(run.round + 1, rounds))
  }
  const next = run.blocks[run.index + 1]
  return next ? words.next(summary(next)) : words.last
}

// A phase, to warn of its end once; "+1 min" makes it another end, warned of again.
const phaseKey = (run: RunState) => `${run.index}:${run.round}:${run.resting}:${run.extraMs}`

function Running({
  session,
  run,
  commit,
}: {
  session: ClassSession
  run: RunState
  commit: (state: RunState, finished?: BlockResult[], planChanged?: boolean) => void
}) {
  const words = copy.running
  const kinds = useQuery(blockKindsQuery)
  const [now, setNow] = useState(() => Date.now())
  const [editing, setEditing] = useState(false)
  const [ending, setEnding] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // When the class was last seen, if it went unseen too long and waits for the coach.
  const [unseenAt, setUnseenAt] = useState<number | null>(null)
  const navigate = useNavigate()
  const timeZone = useGymTimeZone()
  const wakeLock = useWakeLock(true)
  // The run as last committed, for the tick and the buttons between renders.
  const latest = useRef(run)
  const warned = useRef<string | null>(null)
  useEffect(() => {
    latest.current = run
  }, [run])

  const apply = useCallback(
    (step: Step, planChanged = false) => {
      latest.current = step.state
      commit(step.state, step.finished, planChanged)
      setNow(Date.now())
    },
    [commit],
  )

  // Each tick works out where the class is from the clock; nothing counts down by itself.
  useEffect(() => {
    const tick = () => {
      const at = Date.now()
      if (leftUnseen(latest.current, at)) {
        // Left running and found again: stop where it was last seen, and ask.
        const seen = latest.current.lastSeen
        apply(pause(latest.current, seen))
        setUnseenAt(seen)
        setNow(at)
        return
      }
      const step = advance(latest.current, at)
      const seen = touch(step.state, at)
      if (seen !== latest.current) {
        apply({ ...step, state: seen })
        if (step.phaseEndedAt !== null && at - step.phaseEndedAt < SIGNAL_LATE_MS) signal('end')
      }
      const state = latest.current
      if (state.endedAt === null && state.pausedAt === null && phaseMs(state) > WARN_MS) {
        const left = remainingMs(state, at)
        if (left <= WARN_MS && left > 0 && warned.current !== phaseKey(state)) {
          warned.current = phaseKey(state)
          signal('warn')
        }
      }
      setNow(at)
    }
    tick()
    const timer = window.setInterval(tick, TICK_MS)
    document.addEventListener('visibilitychange', tick)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
    }
  }, [apply])

  const act = (change: (state: RunState, at: number) => Step) => apply(change(latest.current, Date.now()))
  const block = currentBlock(run)
  if (!block) return null
  const left = remainingMs(run, now)
  const paused = run.pausedAt !== null
  const warning = !paused && left <= WARN_MS
  const skipLabel = !block.sparring ? words.skip : run.resting ? words.skipRest : words.skipRound

  return (
    <div className={`timer${warning ? ' timer--warning' : ''}${paused ? ' timer--paused' : ''}`}>
      <header className="timer__top">
        <button type="button" className="timer__back" aria-label={copy.back} onClick={() => setLeaving(true)}>
          <ChevronLeftIcon />
        </button>
        <span className="timer__class">{session.class_type_name}</span>
        <span className="timer__position">{words.position(run.index + 1, run.blocks.length)}</span>
      </header>
      <div className="timer__main">
        <p className="timer__phase">{phaseLabel(run, block)}</p>
        <p className="timer__clock" role="timer" aria-label={words.countdown}>
          {clock(left)}
        </p>
        <p className="timer__next">{paused ? words.paused : nextLabel(run, block)}</p>
      </div>
      <div className="timer__controls">
        <button
          type="button"
          className="timer__button timer__button--main"
          onClick={() => act(paused ? (state, at) => ({ state: resume(state, at), finished: [], phaseEndedAt: null }) : pause)}
        >
          {paused ? words.resume : words.pause}
        </button>
        <button type="button" className="timer__button" onClick={() => act(addMinute)}>
          {words.addMinute}
        </button>
        <button type="button" className="timer__button" onClick={() => act(skip)}>
          {skipLabel}
        </button>
        {!run.openMat && kinds.data && (
          <button type="button" className="timer__button" onClick={() => setEditing(true)}>
            {words.edit}
          </button>
        )}
        <button type="button" className="timer__button timer__button--end" onClick={() => setEnding(true)}>
          {words.end}
        </button>
      </div>
      <TimerNotes sessionId={session.id} noWakeLock={wakeLock === 'unsupported'} />
      {unseenAt !== null && (
        <div className="timer__sheet" role="alertdialog" aria-label={words.unseen.title}>
          <p>{words.unseen.title}</p>
          <p className="timer__sheet-detail">{words.unseen.detail(clockTime(new Date(unseenAt).toISOString(), timeZone))}</p>
          <button
            type="button"
            className="timer__button timer__button--main"
            onClick={() => {
              setUnseenAt(null)
              act((state, at) => ({ state: resume(state, at), finished: [], phaseEndedAt: null }))
            }}
          >
            {words.unseen.resume}
          </button>
          <button
            type="button"
            className="timer__button timer__button--end"
            onClick={() => {
              setUnseenAt(null)
              // Paused when last seen, so it ends then.
              act(endClass)
            }}
          >
            {words.unseen.end(clockTime(new Date(unseenAt).toISOString(), timeZone))}
          </button>
        </div>
      )}
      {leaving && (
        <div className="timer__sheet" role="alertdialog" aria-label={words.leave.title}>
          <p>{words.leave.title}</p>
          <button
            type="button"
            className="timer__button"
            onClick={() => void navigate({ to: '/admin/clases/$sessionId', params: { sessionId: session.id } })}
          >
            {words.leave.yes}
          </button>
          <button type="button" className="timer__button timer__button--main" onClick={() => setLeaving(false)}>
            {words.leave.no}
          </button>
        </div>
      )}
      {ending && (
        <div className="timer__sheet" role="alertdialog" aria-label={words.end}>
          <p>{words.endConfirm}</p>
          <button
            type="button"
            className="timer__button timer__button--end"
            onClick={() => {
              setEnding(false)
              act(endClass)
            }}
          >
            {words.endYes}
          </button>
          <button type="button" className="timer__button" onClick={() => setEnding(false)}>
            {words.endNo}
          </button>
        </div>
      )}
      {editing && kinds.data && (
        <div className="timer__overlay">
          <p className="timer__mini" aria-hidden="true">
            {words.mini(phaseLabel(run, block), clock(left))}
          </p>
          <PlanEditor
            initial={upcomingBlocks(run).map(draftOfBlock)}
            kinds={kinds.data}
            openMat={false}
            fixed={run.index + 1}
            hint={copy.editor.hintRunning}
            submit={copy.editor.save}
            onCancel={() => setEditing(false)}
            onSubmit={(blocks) => {
              const step = advance(latest.current, Date.now())
              apply({ ...step, state: replaceUpcoming(step.state, blocks) }, true)
              setEditing(false)
            }}
          />
        </div>
      )}
    </div>
  )
}

/** Below the controls: blocks waiting for signal, a screen that will not stay on. */
function TimerNotes({ sessionId, noWakeLock }: { sessionId: string; noWakeLock: boolean }) {
  const pending = useDelayed(usePendingSync(sessionId))
  if (!pending && !noWakeLock) return null
  return (
    <div className="timer__notes">
      {pending && <p role="status">{copy.sync.pending}</p>}
      {noWakeLock && <p>{copy.running.noWakeLock}</p>}
    </div>
  )
}

// A write on its way for a moment is not news: only one still waiting after this long is.
const PENDING_SHOWN_AFTER_MS = 2_000

function useDelayed(on: boolean): boolean {
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (!on) return
    const timer = window.setTimeout(() => setShown(true), PENDING_SHOWN_AFTER_MS)
    return () => {
      window.clearTimeout(timer)
      setShown(false)
    }
  }, [on])
  return on && shown
}

// --- after the class: what ran -------------------------------------------------------

function Finished({ session, run }: { session: ClassSession; run: RunState }) {
  const words = copy.done
  const navigate = useNavigate()
  return (
    <Shell sessionId={session.id} title={session.class_type_name}>
      <section className="classes__section" aria-labelledby="timer-done">
        <h2 id="timer-done" className="classes__section-title">
          {words.title}
        </h2>
        <ul className="classes__list">
          {run.blocks.map((block) => {
            const result = run.results[block.id]
            const ran = !result
              ? words.notRun
              : block.sparring
                ? words.rounds(result.rounds_completed ?? 0, block.rounds ?? 0, copy.minutes(result.actual_seconds))
                : copy.minutes(result.actual_seconds)
            return (
              <li key={block.id} className="classes__row timer-done__row">
                <span className="classes__name">{block.kindName}</span>
                <span className="classes__detail">{ran}</span>
              </li>
            )
          })}
        </ul>
        <TimerNotes sessionId={session.id} noWakeLock={false} />
        <button
          type="button"
          className="classes__button classes__button--primary"
          onClick={() => {
            clearRun(session.id)
            void navigate({ to: '/admin/clases/$sessionId', params: { sessionId: session.id } })
          }}
        >
          {words.back}
        </button>
      </section>
    </Shell>
  )
}
