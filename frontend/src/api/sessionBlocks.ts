import { queryOptions, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'
import { isRefusal } from './attendance'
import { apiFetch } from './client'
import type { ClassKind } from './sessions'

/** One block of a session's plan, and what it ran once it has (backend `SessionBlock`). A
 * sparring block is rounds, and its seconds are the rounds' alone, rest not included. */
export type SessionBlock = {
  id: string
  position: number
  block_kind_id: string
  block_kind_name: string
  is_sparring: boolean
  planned_seconds: number
  actual_seconds: number | null
  rounds_planned: number | null
  rounds_completed: number | null
  round_seconds: number | null
  rest_seconds: number | null
}

/** A session's blocks in order (backend `SessionPlan`). An open mat's is one sparring block. */
export type SessionPlan = {
  session_id: string
  class_kind: ClassKind
  blocks: SessionBlock[]
}

/** A block of the plan to start from: no id and nothing recorded (backend `SuggestedBlock`). */
export type SuggestedBlock = Omit<SessionBlock, 'id' | 'position' | 'actual_seconds' | 'rounds_completed'>

/** The latest other session of the class type's plan, or none (backend `SuggestedPlan`). */
export type SuggestedPlan = {
  session_id: string
  from_session_id: string | null
  blocks: SuggestedBlock[]
}

/** One block as the plan sends it (backend `PlannedBlock`): a sparring block its rounds,
 * any other its seconds. */
export type PlannedBlock = {
  id: string
  block_kind_id: string
  planned_seconds: number | null
  rounds_planned: number | null
  round_seconds: number | null
  rest_seconds: number | null
}

/** What a block ran (backend `BlockActual`). */
export type BlockActual = { actual_seconds: number; rounds_completed: number | null }

// The backend's bounds (`app.schemas.blocks`).
export const MAX_BLOCK_SECONDS = 4 * 60 * 60
export const MAX_ROUND_SECONDS = 60 * 60
export const MAX_ROUNDS = 100
export const MAX_BLOCKS = 30

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

const blocksPath = (sessionId: string) => `/api/sessions/${encodeURIComponent(sessionId)}/blocks`

export function sessionPlanQuery(sessionId: string) {
  return queryOptions({
    queryKey: ['sessions', 'blocks', sessionId],
    queryFn: () => apiFetch<SessionPlan>(blocksPath(sessionId)),
  })
}

export function suggestedPlanQuery(sessionId: string) {
  return queryOptions({
    queryKey: ['sessions', 'blocks', sessionId, 'suggested'],
    queryFn: () => apiFetch<SuggestedPlan>(`${blocksPath(sessionId)}/suggested`),
  })
}

/** The session's plan, replaced whole; a block kept by id keeps what it recorded. */
export function replacePlan(sessionId: string, blocks: PlannedBlock[]): Promise<SessionPlan> {
  return apiFetch<SessionPlan>(blocksPath(sessionId), { method: 'PUT', body: JSON.stringify({ blocks }) })
}

/** What a block ran; recording it again replaces it. */
export function recordActual(sessionId: string, blockId: string, actual: BlockActual): Promise<SessionBlock> {
  return apiFetch<SessionBlock>(`${blocksPath(sessionId)}/${encodeURIComponent(blockId)}/actual`, {
    method: 'PUT',
    body: JSON.stringify(actual),
  })
}

/** The most seconds a sparring block may record: the backend's `sparred_at_most`, its
 * completed rounds and part of the next one, if one was planned. Rest never counts. */
export function sparredAtMost(completed: number, planned: number, roundSeconds: number): number {
  return Math.min(completed + 1, planned) * roundSeconds
}

/**
 * What the timer has to tell the API, per session, until it has: the latest plan and what
 * each finished block ran. Kept in the phone's storage, so a class run without signal, or
 * a tab closed mid-class, still reaches the API once there is signal.
 *
 * Every write is idempotent, so a resend is safe. The plan goes first, since a block's
 * result needs the block, and the latest plan always holds every block that ran: the
 * timer only ever changes the blocks still to come. A write the API refuses
 * (`isRefusal`: 404, 409, 422) is dropped, since it would be refused again; any other
 * failure keeps it for the next flush.
 */
export type PendingSync = { plan: PlannedBlock[] | null; actuals: Record<string, BlockActual> }

const SYNC_PREFIX = 'rakin:timer-sync:'
/** Fired on `window` whenever what waits to be sent changes. */
export const SYNC_EVENT = 'rakin:timer-sync'

export function pendingSync(sessionId: string): PendingSync | null {
  try {
    const raw = localStorage.getItem(SYNC_PREFIX + sessionId)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<PendingSync>
    const plan = Array.isArray(parsed.plan) ? parsed.plan : null
    const actuals = parsed.actuals && typeof parsed.actuals === 'object' ? parsed.actuals : {}
    return plan === null && Object.keys(actuals).length === 0 ? null : { plan, actuals }
  } catch {
    return null
  }
}

/** The sessions with something waiting to be sent. */
export function pendingSessions(): string[] {
  const ids: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith(SYNC_PREFIX)) ids.push(key.slice(SYNC_PREFIX.length))
    }
  } catch {
    // No storage, nothing kept.
  }
  return ids
}

function writeSync(sessionId: string, pending: PendingSync): void {
  try {
    if (pending.plan === null && Object.keys(pending.actuals).length === 0) {
      localStorage.removeItem(SYNC_PREFIX + sessionId)
    } else {
      localStorage.setItem(SYNC_PREFIX + sessionId, JSON.stringify(pending))
    }
  } catch {
    // An unusable storage keeps nothing; the timer's own state still holds what ran.
  }
  window.dispatchEvent(new Event(SYNC_EVENT))
}

function update(sessionId: string, change: (pending: PendingSync) => void): void {
  const pending = pendingSync(sessionId) ?? { plan: null, actuals: {} }
  change(pending)
  writeSync(sessionId, pending)
}

/** The session's plan to send, replacing one not yet sent. */
export function queuePlan(sessionId: string, plan: PlannedBlock[]): void {
  update(sessionId, (pending) => {
    pending.plan = plan
  })
}

/** What a block ran, to send after the plan. */
export function queueActual(sessionId: string, blockId: string, actual: BlockActual): void {
  update(sessionId, (pending) => {
    pending.actuals[blockId] = actual
  })
}

/** How a flush ended: all sent (or dropped), or something kept for the next one. */
export type FlushResult = { sent: boolean; dropped: number; kept: boolean }

export type SyncApi = {
  replacePlan: (sessionId: string, blocks: PlannedBlock[]) => Promise<unknown>
  recordActual: (sessionId: string, blockId: string, actual: BlockActual) => Promise<unknown>
}

const DEFAULT_API: SyncApi = { replacePlan, recordActual }

// One flush per session at a time; one asked for meanwhile runs after it.
const flushing = new Map<string, Promise<FlushResult>>()

/** Send what waits for `sessionId`, plan first, stopping at the first write that may yet
 * pass later (no signal, a server error). */
export function flushSync(sessionId: string, api: SyncApi = DEFAULT_API): Promise<FlushResult> {
  const running = flushing.get(sessionId)
  const next = (running ?? Promise.resolve()).then(() => flushOnce(sessionId, api))
  const tracked = next.finally(() => {
    if (flushing.get(sessionId) === tracked) flushing.delete(sessionId)
  })
  flushing.set(sessionId, tracked)
  return tracked
}

async function flushOnce(sessionId: string, api: SyncApi): Promise<FlushResult> {
  const result: FlushResult = { sent: false, dropped: 0, kept: false }
  const pending = pendingSync(sessionId)
  if (!pending) return result

  // `true` when the write is done with: sent, or refused for good.
  const attempt = async (send: () => Promise<unknown>): Promise<boolean> => {
    try {
      await send()
      result.sent = true
      return true
    } catch (error) {
      if (isRefusal(error)) {
        result.dropped += 1
        return true
      }
      result.kept = true
      return false
    }
  }

  if (pending.plan !== null) {
    const plan = pending.plan
    if (!(await attempt(() => api.replacePlan(sessionId, plan)))) return result
    // A newer plan queued while this one was on its way stays, to go next.
    update(sessionId, (now) => {
      if (JSON.stringify(now.plan) === JSON.stringify(plan)) now.plan = null
    })
  }
  for (const [blockId, actual] of Object.entries(pending.actuals)) {
    if (!(await attempt(() => api.recordActual(sessionId, blockId, actual)))) return result
    update(sessionId, (now) => {
      if (JSON.stringify(now.actuals[blockId]) === JSON.stringify(actual)) delete now.actuals[blockId]
    })
  }
  return result
}

// How often what waits is tried again while the app is open: a server error may pass.
const RETRY_MS = 30_000

/** Send what waits for `sessionId`, and refetch its plan once something reached the API. */
export function syncSession(queryClient: QueryClient, sessionId: string): Promise<FlushResult> {
  return flushSync(sessionId).then((result) => {
    if (result.sent || result.dropped > 0) {
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'blocks', sessionId] })
    }
    return result
  })
}

/** Every session's timer writes, sent while any staff screen is open: on arrival, when the
 * signal comes back, and every half minute. Mounted once, in the admin shell. */
export function useTimerSync(): void {
  const queryClient = useQueryClient()
  useEffect(() => {
    const flushAll = () => {
      for (const id of pendingSessions()) void syncSession(queryClient, id)
    }
    flushAll()
    window.addEventListener('online', flushAll)
    const timer = window.setInterval(flushAll, RETRY_MS)
    return () => {
      window.removeEventListener('online', flushAll)
      window.clearInterval(timer)
    }
  }, [queryClient])
}

function subscribeSync(onChange: () => void): () => void {
  window.addEventListener(SYNC_EVENT, onChange)
  return () => window.removeEventListener(SYNC_EVENT, onChange)
}

/** Whether the session's timer has writes on the phone that have not reached the API. */
export function usePendingSync(sessionId: string): boolean {
  return useSyncExternalStore(subscribeSync, () => pendingSync(sessionId) !== null)
}
