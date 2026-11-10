import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import {
  flushSync,
  pendingSessions,
  pendingSync,
  queueActual,
  queuePlan,
  sparredAtMost,
  type PlannedBlock,
  type SyncApi,
} from './sessionBlocks'

const PLAN: PlannedBlock[] = [
  { id: 'b1', block_kind_id: 'k', planned_seconds: 600, rounds_planned: null, round_seconds: null, rest_seconds: null },
]

const offline = () => Promise.reject(new TypeError('Failed to fetch'))
const refused = (status: number) => () => Promise.reject(new ApiError(status, { detail: 'no' }))

function api(over: Partial<SyncApi> = {}) {
  const calls: string[] = []
  const stub: SyncApi = {
    replacePlan: vi.fn((sessionId: string) => {
      calls.push(`plan ${sessionId}`)
      return over.replacePlan ? over.replacePlan(sessionId, []) : Promise.resolve()
    }),
    recordActual: vi.fn((sessionId: string, blockId: string) => {
      calls.push(`actual ${sessionId} ${blockId}`)
      return over.recordActual
        ? over.recordActual(sessionId, blockId, { actual_seconds: 0, rounds_completed: null })
        : Promise.resolve()
    }),
  }
  return { stub, calls }
}

beforeEach(() => localStorage.clear())

describe('the timer sync queue', () => {
  it('sends the plan first, then what each block ran, and keeps nothing after', async () => {
    queuePlan('s1', PLAN)
    queueActual('s1', 'b1', { actual_seconds: 600, rounds_completed: null })
    expect(pendingSessions()).toEqual(['s1'])

    const { stub, calls } = api()
    const result = await flushSync('s1', stub)
    expect(calls).toEqual(['plan s1', 'actual s1 b1'])
    expect(stub.recordActual).toHaveBeenCalledWith('s1', 'b1', { actual_seconds: 600, rounds_completed: null })
    expect(result).toEqual({ sent: true, dropped: 0, kept: false })
    expect(pendingSync('s1')).toBeNull()
    expect(pendingSessions()).toEqual([])
  })

  it('keeps everything without signal, and sends it once the signal is back', async () => {
    queuePlan('s1', PLAN)
    queueActual('s1', 'b1', { actual_seconds: 600, rounds_completed: null })

    const down = api({ replacePlan: offline })
    expect(await flushSync('s1', down.stub)).toEqual({ sent: false, dropped: 0, kept: true })
    // The plan failed, so no result was tried: its block may not exist yet.
    expect(down.calls).toEqual(['plan s1'])
    expect(pendingSync('s1')).toEqual({ plan: PLAN, actuals: { b1: { actual_seconds: 600, rounds_completed: null } } })

    const up = api()
    await flushSync('s1', up.stub)
    expect(up.calls).toEqual(['plan s1', 'actual s1 b1'])
    expect(pendingSync('s1')).toBeNull()
  })

  it('keeps a result after a server error, to try again', async () => {
    queueActual('s1', 'b1', { actual_seconds: 60, rounds_completed: null })
    const { stub } = api({ recordActual: refused(503) })
    expect((await flushSync('s1', stub)).kept).toBe(true)
    expect(pendingSync('s1')?.actuals).toEqual({ b1: { actual_seconds: 60, rounds_completed: null } })
  })

  it.each([404, 409, 422])('drops a write the API refuses with %i, and goes on with the rest', async (status) => {
    queuePlan('s1', PLAN)
    queueActual('s1', 'b1', { actual_seconds: 60, rounds_completed: null })
    queueActual('s1', 'b2', { actual_seconds: 60, rounds_completed: null })
    const { stub, calls } = api({
      recordActual: (_s, blockId) => (blockId === 'b1' ? refused(status)() : Promise.resolve()),
    })
    expect(await flushSync('s1', stub)).toEqual({ sent: true, dropped: 1, kept: false })
    expect(calls).toEqual(['plan s1', 'actual s1 b1', 'actual s1 b2'])
    expect(pendingSync('s1')).toBeNull()
  })

  it('keeps a plan queued while the one before it was on its way', async () => {
    queuePlan('s1', PLAN)
    const newer = [...PLAN, { ...PLAN[0]!, id: 'b2' }]
    const { stub } = api({
      replacePlan: () => {
        queuePlan('s1', newer)
        return Promise.resolve()
      },
    })
    await flushSync('s1', stub)
    expect(pendingSync('s1')?.plan).toEqual(newer)
  })

  it('runs one flush at a time per session', async () => {
    queueActual('s1', 'b1', { actual_seconds: 60, rounds_completed: null })
    let release = () => {}
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    const { stub, calls } = api({ recordActual: () => held })
    const first = flushSync('s1', stub)
    const second = flushSync('s1', stub)
    await Promise.resolve()
    release()
    await Promise.all([first, second])
    // The second found nothing left to send.
    expect(calls).toEqual(['actual s1 b1'])
  })

  it('keeps sessions apart', () => {
    queuePlan('s1', PLAN)
    queuePlan('s2', PLAN)
    expect(pendingSessions().sort()).toEqual(['s1', 's2'])
  })
})

describe('sparredAtMost', () => {
  it('is the completed rounds and part of the next, if one was planned', () => {
    expect(sparredAtMost(3, 5, 300)).toBe(1200)
    expect(sparredAtMost(5, 5, 300)).toBe(1500)
    expect(sparredAtMost(0, 5, 300)).toBe(300)
  })
})
