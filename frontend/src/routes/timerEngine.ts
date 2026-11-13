import { MAX_BLOCK_SECONDS, sparredAtMost, type BlockActual, type PlannedBlock } from '../api/sessionBlocks'

/**
 * The class timer as data: a plan of blocks and where the class is in it, worked out from
 * timestamps alone. Nothing counts in an interval, so a phone that locks, or a page that
 * reloads, finds the class where it would be: `advance` walks every phase that ran out
 * meanwhile, at the instant it did.
 *
 * A block is one phase, of its seconds. A sparring block is rounds: round 1, rest, round
 * 2, ... round N, with no rest after the last. What a block ran is its time in phases
 * other than rest, and for sparring the rounds that ran out; a round skipped or stopped
 * part-way counts its seconds, not as a round. The API holds a sparring block to its
 * rounds (`sparredAtMost`), so its seconds are cut to that.
 */
export type TimerBlock = {
  id: string
  kindId: string
  kindName: string
  sparring: boolean
  /** A block's planned seconds; a sparring block's are its rounds'. */
  seconds: number
  rounds: number | null
  roundSeconds: number | null
  restSeconds: number | null
}

export type BlockResult = BlockActual & { blockId: string }

export type RunState = {
  version: 1
  blocks: TimerBlock[]
  /** The block running. */
  index: number
  /** 1-based, of a sparring block; 1 for any other. */
  round: number
  resting: boolean
  /** When the phase started, moved forward by every pause since. */
  phaseStart: number
  pausedAt: number | null
  /** Added to the phase with "+1 min". */
  extraMs: number
  /** The block's time, rest excluded, before this phase. */
  workMs: number
  /** The block's rounds that ran out. */
  roundsDone: number
  /** What each finished block ran, by id. */
  results: Record<string, BlockResult>
  startedAt: number
  /** The last time the timer was on screen (`touch`): a run not seen for long was
   * left, and its time since then is not the class's until the coach says so. */
  lastSeen: number
  /** An open mat: one sparring block, nothing to add after it. */
  openMat: boolean
  /** Set once the last block ran out or the class was ended. */
  endedAt: number | null
}

/** A change to the run: the new state, the blocks it finished, and when the last phase it
 * ended ran out (for the signal; null when none did). */
export type Step = { state: RunState; finished: BlockResult[]; phaseEndedAt: number | null }

export const MINUTE_MS = 60_000

export function plannedSeconds(block: Pick<TimerBlock, 'sparring' | 'seconds' | 'rounds' | 'roundSeconds'>): number {
  return block.sparring ? (block.rounds ?? 0) * (block.roundSeconds ?? 0) : block.seconds
}

/** The block as the plan sends it. */
export function plannedBlock(block: TimerBlock): PlannedBlock {
  return block.sparring
    ? {
        id: block.id,
        block_kind_id: block.kindId,
        planned_seconds: null,
        rounds_planned: block.rounds,
        round_seconds: block.roundSeconds,
        rest_seconds: block.restSeconds ?? 0,
      }
    : {
        id: block.id,
        block_kind_id: block.kindId,
        planned_seconds: block.seconds,
        rounds_planned: null,
        round_seconds: null,
        rest_seconds: null,
      }
}

export function startRun(blocks: TimerBlock[], now: number, openMat = false): RunState {
  return {
    version: 1,
    blocks,
    index: 0,
    round: 1,
    resting: false,
    phaseStart: now,
    pausedAt: null,
    extraMs: 0,
    workMs: 0,
    roundsDone: 0,
    results: {},
    startedAt: now,
    lastSeen: now,
    openMat,
    endedAt: blocks.length === 0 ? now : null,
  }
}

export function currentBlock(state: RunState): TimerBlock | null {
  return state.endedAt === null ? (state.blocks[state.index] ?? null) : null
}

/** The phase's length, "+1 min" included. */
export function phaseMs(state: RunState): number {
  const block = currentBlock(state)
  if (!block) return 0
  const base = !block.sparring ? block.seconds : state.resting ? (block.restSeconds ?? 0) : (block.roundSeconds ?? 0)
  return base * 1000 + state.extraMs
}

/** How long the phase has run, pauses excluded. */
export function elapsedMs(state: RunState, now: number): number {
  return Math.max(0, (state.pausedAt ?? now) - state.phaseStart)
}

export function remainingMs(state: RunState, now: number): number {
  return Math.max(0, phaseMs(state) - elapsedMs(state, now))
}

/** What a block ran: its time and, for sparring, its rounds, as the API takes them. */
export function blockResult(block: TimerBlock, workMs: number, roundsDone: number): BlockResult {
  const ran = Math.min(Math.round(workMs / 1000), MAX_BLOCK_SECONDS)
  if (!block.sparring) return { blockId: block.id, actual_seconds: ran, rounds_completed: null }
  const rounds = block.rounds ?? 0
  const completed = Math.min(roundsDone, rounds)
  return {
    blockId: block.id,
    actual_seconds: Math.min(ran, sparredAtMost(completed, rounds, block.roundSeconds ?? 0)),
    rounds_completed: completed,
  }
}

/** End the phase at `at`, `ranOut` when its time did rather than a skip, and go to the next
 * one: the next round or rest, else the next block, else the end of the class. */
function endPhase(state: RunState, at: number, ranOut: boolean, finished: BlockResult[]): RunState {
  const block = currentBlock(state)
  if (!block) return state
  const ran = Math.max(0, at - state.phaseStart)
  const workMs = state.workMs + (state.resting ? 0 : ran)
  const roundsDone = state.roundsDone + (block.sparring && !state.resting && ranOut ? 1 : 0)
  const fresh = { phaseStart: at, extraMs: 0, workMs, roundsDone }
  if (block.sparring && state.round < (block.rounds ?? 1)) {
    if (!state.resting && (block.restSeconds ?? 0) > 0) return { ...state, ...fresh, resting: true }
    return { ...state, ...fresh, resting: false, round: state.round + 1 }
  }
  return finishBlock(state, block, at, workMs, roundsDone, finished)
}

function finishBlock(
  state: RunState,
  block: TimerBlock,
  at: number,
  workMs: number,
  roundsDone: number,
  finished: BlockResult[],
): RunState {
  const result = blockResult(block, workMs, roundsDone)
  finished.push(result)
  const index = state.index + 1
  return {
    ...state,
    index,
    round: 1,
    resting: false,
    phaseStart: at,
    pausedAt: state.pausedAt === null ? null : at,
    extraMs: 0,
    workMs: 0,
    roundsDone: 0,
    results: { ...state.results, [block.id]: result },
    endedAt: index >= state.blocks.length ? at : null,
  }
}

/** Every phase that ran out by `now`, each ended at the instant it did. */
export function advance(state: RunState, now: number): Step {
  const finished: BlockResult[] = []
  let phaseEndedAt: number | null = null
  let current = state
  while (current.endedAt === null && current.pausedAt === null) {
    const end = current.phaseStart + phaseMs(current)
    if (end > now) break
    current = endPhase(current, end, true, finished)
    phaseEndedAt = end
  }
  return { state: current, finished, phaseEndedAt }
}

/** "Saltar": end the phase now; a block's, or a sparring block's round or rest. */
export function skip(state: RunState, now: number): Step {
  const step = advance(state, now)
  if (step.state.endedAt !== null) return step
  // A skip while paused starts the next phase paused, from its beginning.
  return { ...step, state: endPhase(step.state, step.state.pausedAt ?? now, false, step.finished) }
}

export function pause(state: RunState, now: number): Step {
  const step = advance(state, now)
  if (step.state.endedAt !== null || step.state.pausedAt !== null) return step
  return { ...step, state: { ...step.state, pausedAt: now } }
}

export function resume(state: RunState, now: number): RunState {
  if (state.pausedAt === null) return state
  return { ...state, phaseStart: state.phaseStart + (now - state.pausedAt), pausedAt: null, lastSeen: now }
}

/** A phase, to signal its end once; "+1 min" makes it another end, signalled again. */
export const phaseKey = (state: RunState) => `${state.index}:${state.round}:${state.resting}:${state.extraMs}`

/** The seconds counted down, one beep each, before a round or a rest of sparring ends. */
export const COUNTDOWN_SECONDS = 3

// How late a countdown second may be beeped: later, and it would sound halfway to the next.
const COUNTDOWN_LATE_MS = 500

/** Where the countdown was last looked at: the phase and the time it had left. */
export type CountdownMark = { phase: string; leftMs: number }

/**
 * The countdown second (3, 2 or 1) that the phase crossed since `mark`, the last look,
 * and the mark for the next one. A second is beeped as the time left reaches it, and once:
 * not for a phase of a non-sparring block, nor one of fewer than 4 seconds, where 3 would
 * sound with the switch before it. A paused run has its time left held, so a pause in the
 * countdown beeps the next second only once it runs again and reaches it. A first look at
 * a phase, a reload in the last seconds or a "+1 min", beeps nothing; nor a second reached
 * half a second ago or more (a phone that was locked).
 */
export function countdown(state: RunState, now: number, mark: CountdownMark | null): { beep: number | null; mark: CountdownMark | null } {
  const block = currentBlock(state)
  if (!block) return { beep: null, mark: null }
  const next = { phase: phaseKey(state), leftMs: remainingMs(state, now) }
  if (!block.sparring || phaseMs(state) < (COUNTDOWN_SECONDS + 1) * 1000 || mark?.phase !== next.phase) {
    return { beep: null, mark: next }
  }
  // The latest second reached: the smallest at or above the time left.
  const second = Math.max(1, Math.ceil(next.leftMs / 1000))
  const crossed = second <= COUNTDOWN_SECONDS && mark.leftMs > second * 1000 && second * 1000 - next.leftMs < COUNTDOWN_LATE_MS
  return { beep: crossed ? second : null, mark: next }
}

/** "+1 min" to the phase running. */
export function addMinute(state: RunState, now: number): Step {
  const step = advance(state, now)
  if (step.state.endedAt !== null) return step
  return { ...step, state: { ...step.state, extraMs: step.state.extraMs + MINUTE_MS } }
}

/** "Terminar clase": the block running records what it ran so far; the blocks after it
 * stay in the plan, unrun. */
export function endClass(state: RunState, now: number): Step {
  const step = advance(state, now)
  const block = currentBlock(step.state)
  if (!block) return step
  const at = step.state.pausedAt ?? now
  // Paused at a `lastSeen` a few seconds stale, the phase may have started after it:
  // that phase ran nothing, not less than nothing.
  const ran = step.state.resting ? 0 : Math.max(0, at - step.state.phaseStart)
  const ended = finishBlock(step.state, block, at, step.state.workMs + ran, step.state.roundsDone, step.finished)
  return { ...step, state: { ...ended, endedAt: Math.max(at, step.state.phaseStart), pausedAt: null } }
}

/** The blocks after the one running, replaced: what "Editar" changes while the class runs.
 * One of `upcoming` that has started since the edit began stays as it ran. */
export function replaceUpcoming(state: RunState, upcoming: TimerBlock[]): RunState {
  const started = state.blocks.slice(0, state.index + 1)
  const ids = new Set(started.map((b) => b.id))
  return { ...state, blocks: [...started, ...upcoming.filter((b) => !ids.has(b.id))] }
}

export function upcomingBlocks(state: RunState): TimerBlock[] {
  return state.endedAt === null ? state.blocks.slice(state.index + 1) : []
}

// How long a run may go unseen and still be the class's: beyond it the coach is asked.
export const UNSEEN_MS = 5 * MINUTE_MS
// How stale `lastSeen` may get before it is written again: a write per tick is waste.
const SEEN_EVERY_MS = 5_000

/** The run, seen on screen at `now`; the same object when `lastSeen` is recent enough. */
export function touch(state: RunState, now: number): RunState {
  return now - state.lastSeen < SEEN_EVERY_MS ? state : { ...state, lastSeen: now }
}

/** Whether a running class went unseen so long that what ran meanwhile needs the coach's
 * word: a phone that died, a coach who never pressed "Terminar clase". */
export function leftUnseen(state: RunState, now: number): boolean {
  return state.endedAt === null && state.pausedAt === null && now - state.lastSeen > UNSEEN_MS
}

// The run, kept on the phone per session, so a reload or a locked phone resumes it.
const RUN_PREFIX = 'rakin:timer:'

export function savedRun(sessionId: string): RunState | null {
  try {
    const raw = localStorage.getItem(RUN_PREFIX + sessionId)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isRun(parsed) ? parsed : null
  } catch {
    return null
  }
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const isCount = (value: unknown) => Number.isInteger(value) && (value as number) >= 0
const orNull = (value: unknown, check: (v: unknown) => boolean) => value === null || check(value)

function isBlock(value: unknown): value is TimerBlock {
  if (typeof value !== 'object' || value === null) return false
  const b = value as Record<string, unknown>
  return (
    typeof b.id === 'string' &&
    typeof b.kindId === 'string' &&
    typeof b.kindName === 'string' &&
    typeof b.sparring === 'boolean' &&
    isNumber(b.seconds) &&
    orNull(b.rounds, isCount) &&
    orNull(b.roundSeconds, isNumber) &&
    orNull(b.restSeconds, isNumber) &&
    (!b.sparring || (isCount(b.rounds) && isNumber(b.roundSeconds)))
  )
}

function isResult(value: unknown): value is BlockResult {
  if (typeof value !== 'object' || value === null) return false
  const r = value as Record<string, unknown>
  return typeof r.blockId === 'string' && isCount(r.actual_seconds) && orNull(r.rounds_completed, isCount)
}

/** A run as `saveRun` wrote it, every field of its type: one that is not is discarded
 * rather than run, since a missing field would throw mid-class. */
function isRun(value: unknown): value is RunState {
  if (typeof value !== 'object' || value === null) return false
  const r = value as Record<string, unknown>
  return (
    r.version === 1 &&
    Array.isArray(r.blocks) &&
    r.blocks.every(isBlock) &&
    isCount(r.index) &&
    (r.index as number) <= r.blocks.length &&
    isCount(r.round) &&
    typeof r.resting === 'boolean' &&
    isNumber(r.phaseStart) &&
    orNull(r.pausedAt, isNumber) &&
    isNumber(r.extraMs) &&
    isNumber(r.workMs) &&
    isCount(r.roundsDone) &&
    typeof r.results === 'object' &&
    r.results !== null &&
    !Array.isArray(r.results) &&
    Object.values(r.results).every(isResult) &&
    isNumber(r.startedAt) &&
    isNumber(r.lastSeen) &&
    typeof r.openMat === 'boolean' &&
    orNull(r.endedAt, isNumber) &&
    (r.endedAt !== null || (r.index as number) < r.blocks.length)
  )
}

export function saveRun(sessionId: string, state: RunState): void {
  try {
    localStorage.setItem(RUN_PREFIX + sessionId, JSON.stringify(state))
  } catch {
    // Kept in memory only: a reload would lose the run, not what was sent.
  }
}

export function clearRun(sessionId: string): void {
  try {
    localStorage.removeItem(RUN_PREFIX + sessionId)
  } catch {
    // Nothing kept.
  }
}
