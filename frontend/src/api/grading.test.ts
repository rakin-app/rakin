import { describe, expect, it } from 'vitest'
import { goalProgress, monthsBetween, type GradingScheme, type Rank } from './grading'

const stripes = (target?: number) =>
  ['0', '1', '2'].map((key) => ({ key, label: `${key} grados`, target: key === '1' ? (target ?? null) : null }))

const SCHEME: GradingScheme = {
  ranks: [
    { key: 'white', label: 'Blanca', target: 100, sub_ranks: stripes(30) },
    { key: 'blue', label: 'Azul', target: null, sub_ranks: stripes() },
  ],
  kids_ladder: [{ key: 'grey', label: 'Gris', target: 20, sub_ranks: [] }],
  goal_metric: 'classes_since_promotion',
}

const at = (rank_key: string, sub_rank: string | null, awarded_on = '2026-04-11'): Rank => ({
  rank_key,
  rank_label: rank_key,
  sub_rank,
  sub_rank_label: sub_rank,
  awarded_on,
})

describe('goalProgress', () => {
  it("takes a sub-rank's own target, else its rank's, and names what comes next", () => {
    expect(goalProgress(SCHEME, at('white', '1'), 12, '2026-11-09')).toEqual({
      metric: 'classes_since_promotion',
      done: 12,
      target: 30,
      next: '2 grados',
    })
    // The last sub-rank leads to the next rank.
    expect(goalProgress(SCHEME, at('white', '2'), 70, '2026-11-09')).toMatchObject({ target: 100, next: 'Azul' })
    // The kids ladder is a ladder of its own; at its top there is nothing next.
    expect(goalProgress(SCHEME, at('grey', null), 5, '2026-11-09')).toMatchObject({ target: 20, next: null })
  })

  it('is null with no target, no goal metric, no count, or a rank the scheme no longer has', () => {
    expect(goalProgress(SCHEME, at('blue', '0'), 12, '2026-11-09')).toBeNull()
    expect(goalProgress({ ...SCHEME, goal_metric: null }, at('white', '1'), 12, '2026-11-09')).toBeNull()
    expect(goalProgress(SCHEME, at('white', '1'), null, '2026-11-09')).toBeNull()
    expect(goalProgress(SCHEME, at('red', null), 12, '2026-11-09')).toBeNull()
  })

  it('counts months in rank from the day it was awarded', () => {
    const months = { ...SCHEME, goal_metric: 'time_in_rank' as const }
    expect(goalProgress(months, at('white', '1', '2026-04-11'), null, '2026-11-09')).toMatchObject({
      metric: 'time_in_rank',
      done: 6,
      target: 30,
    })
  })
})

describe('monthsBetween', () => {
  it('counts a month once its day comes round', () => {
    expect(monthsBetween('2026-04-11', '2026-11-10')).toBe(6)
    expect(monthsBetween('2026-04-11', '2026-11-11')).toBe(7)
    expect(monthsBetween('2025-12-31', '2026-01-30')).toBe(0)
    expect(monthsBetween('2026-11-09', '2026-11-09')).toBe(0)
  })
})
