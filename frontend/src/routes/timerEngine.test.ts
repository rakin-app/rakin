import { beforeEach, describe, expect, it } from 'vitest'
import {
  addMinute,
  advance,
  endClass,
  leftUnseen,
  pause,
  plannedBlock,
  remainingMs,
  replaceUpcoming,
  resume,
  savedRun,
  saveRun,
  skip,
  startRun,
  touch,
  type TimerBlock,
} from './timerEngine'

const S = 1000
const MIN = 60 * S

const block = (id: string, seconds: number): TimerBlock => ({
  id,
  kindId: `k-${id}`,
  kindName: id,
  sparring: false,
  seconds,
  rounds: null,
  roundSeconds: null,
  restSeconds: null,
})

const sparring = (id: string, rounds: number, roundSeconds: number, restSeconds: number): TimerBlock => ({
  id,
  kindId: 'k-sparring',
  kindName: 'Sparring',
  sparring: true,
  seconds: rounds * roundSeconds,
  rounds,
  roundSeconds,
  restSeconds,
})

const T0 = 1_700_000_000_000

describe('the timer engine', () => {
  it('counts a block down from its start, and goes to the next when it runs out', () => {
    const run = startRun([block('warmup', 600), block('technique', 1200)], T0)
    expect(remainingMs(run, T0 + 61 * S)).toBe(539 * S)

    const step = advance(run, T0 + 10 * MIN + 5 * S)
    expect(step.state.index).toBe(1)
    expect(step.finished).toEqual([{ blockId: 'warmup', actual_seconds: 600, rounds_completed: null }])
    expect(step.phaseEndedAt).toBe(T0 + 10 * MIN)
    // The next block started when the first ran out, not when it was looked at.
    expect(remainingMs(step.state, T0 + 10 * MIN + 5 * S)).toBe(1195 * S)
  })

  it('walks every phase that ran out while the phone was locked, rounds and rests included', () => {
    const run = startRun([block('technique', 300), sparring('sparring', 3, 120, 30)], T0)
    // 5 min technique, then round 1 (2 min), rest, round 2, rest: 10 min in, round 3 at 0:00.
    const step = advance(run, T0 + 10 * MIN + 20 * S)
    expect(step.state.index).toBe(1)
    expect(step.state.round).toBe(3)
    expect(step.state.resting).toBe(false)
    expect(remainingMs(step.state, T0 + 10 * MIN + 20 * S)).toBe(100 * S)
    expect(step.finished.map((r) => r.blockId)).toEqual(['technique'])

    const end = advance(step.state, T0 + 20 * MIN)
    expect(end.state.endedAt).toBe(T0 + 12 * MIN)
    // Rest is not sparring: three rounds of two minutes.
    expect(end.finished).toEqual([{ blockId: 'sparring', actual_seconds: 360, rounds_completed: 3 }])
  })

  it('stands still while paused, and resumes where it was', () => {
    const run = startRun([block('warmup', 600)], T0)
    const paused = pause(run, T0 + MIN).state
    expect(remainingMs(paused, T0 + 30 * MIN)).toBe(9 * MIN)
    expect(advance(paused, T0 + 30 * MIN).finished).toEqual([])
    const resumed = resume(paused, T0 + 30 * MIN)
    expect(remainingMs(resumed, T0 + 31 * MIN)).toBe(8 * MIN)
  })

  it('adds a minute to the phase running, and the block records it', () => {
    const run = addMinute(startRun([block('warmup', 600)], T0), T0 + MIN).state
    expect(remainingMs(run, T0 + MIN)).toBe(10 * MIN)
    expect(advance(run, T0 + 11 * MIN).finished).toEqual([
      { blockId: 'warmup', actual_seconds: 660, rounds_completed: null },
    ])
  })

  it('skips a block with what it ran, and a round as not completed', () => {
    const run = startRun([block('warmup', 600), sparring('sparring', 3, 120, 30)], T0)
    const skipped = skip(run, T0 + 4 * MIN)
    expect(skipped.finished).toEqual([{ blockId: 'warmup', actual_seconds: 240, rounds_completed: null }])
    expect(skipped.phaseEndedAt).toBeNull()

    // Round 1 skipped at 1:00 goes to its rest; the rest skipped goes to round 2.
    const rest = skip(skipped.state, T0 + 5 * MIN).state
    expect(rest.resting).toBe(true)
    const round2 = skip(rest, T0 + 5 * MIN + 10 * S).state
    expect(round2.round).toBe(2)
    expect(round2.resting).toBe(false)

    const ended = endClass(round2, T0 + 6 * MIN)
    expect(ended.state.endedAt).toBe(T0 + 6 * MIN)
    // 60 s of round 1 and 50 s of round 2, no round run out.
    expect(ended.finished).toEqual([{ blockId: 'sparring', actual_seconds: 110, rounds_completed: 0 }])
  })

  it('holds a sparring block to its rounds, as the API does', () => {
    // Two rounds of 2 min, each given a minute more: 6 min sparred, 2 rounds' worth recorded.
    let run = startRun([sparring('sparring', 2, 120, 0)], T0)
    run = addMinute(run, T0).state
    run = advance(run, T0 + 3 * MIN).state
    run = addMinute(run, T0 + 3 * MIN).state
    const step = advance(run, T0 + 10 * MIN)
    expect(step.finished).toEqual([{ blockId: 'sparring', actual_seconds: 240, rounds_completed: 2 }])
  })

  it('records what ran when the class is ended early, and not the blocks after', () => {
    const run = startRun([block('warmup', 600), block('technique', 1200)], T0)
    const step = endClass(run, T0 + 3 * MIN)
    expect(step.finished).toEqual([{ blockId: 'warmup', actual_seconds: 180, rounds_completed: null }])
    expect(step.state.endedAt).toBe(T0 + 3 * MIN)
    expect(step.state.blocks).toHaveLength(2)
  })

  it('ends a paused class at the pause', () => {
    const paused = pause(startRun([block('warmup', 600)], T0), T0 + 2 * MIN).state
    expect(endClass(paused, T0 + 9 * MIN).finished).toEqual([
      { blockId: 'warmup', actual_seconds: 120, rounds_completed: null },
    ])
  })

  it('changes only the blocks still to come', () => {
    const run = advance(startRun([block('a', 60), block('b', 60), block('c', 60)], T0), T0 + 70 * S).state
    const edited = replaceUpcoming(run, [block('d', 120)])
    expect(edited.blocks.map((b) => b.id)).toEqual(['a', 'b', 'd'])
    expect(edited.index).toBe(1)
  })

  it('keeps a block that started while its edit was open as it is', () => {
    const run = startRun([block('a', 60), block('b', 60), block('c', 60)], T0)
    // The edit opened during "a", with "b" and "c" to come; "b" started before it was saved.
    const moved = advance(run, T0 + 70 * S).state
    const edited = replaceUpcoming(moved, [{ ...block('b', 600) }, block('c', 30)])
    expect(edited.blocks.map((b) => [b.id, b.seconds])).toEqual([
      ['a', 60],
      ['b', 60],
      ['c', 30],
    ])
  })

  it('sends a sparring block as rounds and any other as seconds', () => {
    expect(plannedBlock(block('a', 600))).toEqual({
      id: 'a',
      block_kind_id: 'k-a',
      planned_seconds: 600,
      rounds_planned: null,
      round_seconds: null,
      rest_seconds: null,
    })
    expect(plannedBlock(sparring('s', 6, 300, 60))).toEqual({
      id: 's',
      block_kind_id: 'k-sparring',
      planned_seconds: null,
      rounds_planned: 6,
      round_seconds: 300,
      rest_seconds: 60,
    })
  })
})

describe('a run left unseen', () => {
  it('is one running past five minutes since it was last seen', () => {
    const run = startRun([block('warmup', 600)], T0)
    expect(leftUnseen(run, T0 + 5 * MIN)).toBe(false)
    expect(leftUnseen(run, T0 + 5 * MIN + 1)).toBe(true)
    expect(leftUnseen(touch(run, T0 + 4 * MIN), T0 + 9 * MIN)).toBe(false)
    // Paused, nothing runs: nothing to ask.
    expect(leftUnseen(pause(run, T0).state, T0 + 60 * MIN)).toBe(false)
    // Resumed, it is seen again.
    expect(leftUnseen(resume(pause(run, T0).state, T0 + 60 * MIN), T0 + 61 * MIN)).toBe(false)
  })

  it('is touched only every few seconds', () => {
    const run = startRun([block('warmup', 600)], T0)
    expect(touch(run, T0 + 1_000)).toBe(run)
    expect(touch(run, T0 + 5_000).lastSeen).toBe(T0 + 5_000)
  })
})

describe('the run kept on the phone', () => {
  beforeEach(() => localStorage.clear())

  it('comes back as it was saved', () => {
    const run = startRun([block('warmup', 600)], T0)
    saveRun('s1', run)
    expect(savedRun('s1')).toEqual(run)
    expect(savedRun('s2')).toBeNull()
  })

  it.each([
    ['without its results', (run: Record<string, unknown>) => delete run.results],
    ['with its results a list', (run: Record<string, unknown>) => (run.results = [])],
    ['with a block past the end', (run: Record<string, unknown>) => (run.index = 5)],
    ['with a text index', (run: Record<string, unknown>) => (run.index = '0')],
    ['without lastSeen', (run: Record<string, unknown>) => delete run.lastSeen],
    ['with a block missing its seconds', (run: Record<string, unknown>) => delete (run.blocks as Record<string, unknown>[])[0]!.seconds],
    ['with a sparring block without rounds', (run: Record<string, unknown>) => ((run.blocks as Record<string, unknown>[])[0]!.sparring = true)],
    ['with a result missing its seconds', (run: Record<string, unknown>) => (run.results = { warmup: { blockId: 'warmup' } })],
  ])('discards a run %s', (_what, spoil) => {
    const run = JSON.parse(JSON.stringify(startRun([block('warmup', 600)], T0))) as Record<string, unknown>
    spoil(run)
    localStorage.setItem('rakin:timer:s1', JSON.stringify(run))
    expect(savedRun('s1')).toBeNull()
  })

  it('ignores what it cannot read', () => {
    localStorage.setItem('rakin:timer:s1', '{"version":7}')
    expect(savedRun('s1')).toBeNull()
    localStorage.setItem('rakin:timer:s1', 'nope')
    expect(savedRun('s1')).toBeNull()
  })
})
