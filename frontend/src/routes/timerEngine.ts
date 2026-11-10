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
  return { ...state, phaseStart: state.phaseStart + (now - state.pausedAt), pausedAt: null }
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
  const ran = step.state.resting ? 0 : at - step.state.phaseStart
  const ended = finishBlock(step.state, block, at, step.state.workMs + ran, step.state.roundsDone, step.finished)
  return { ...step, state: { ...ended, endedAt: at, pausedAt: null } }
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

// The run, kept on the phone per session, so a reload or a locked phone resumes it.
const RUN_PREFIX = 'rakin:timer:'

export function savedRun(sessionId: string): RunState | null {
  try {
    const raw = localStorage.getItem(RUN_PREFIX + sessionId)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<RunState>
    if (parsed.version !== 1 || !Array.isArray(parsed.blocks) || typeof parsed.phaseStart !== 'number') return null
    return parsed as RunState
  } catch {
    return null
  }
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
