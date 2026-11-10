import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

export const GOAL_METRICS = ['classes_since_promotion', 'time_in_rank'] as const
export type GoalMetric = (typeof GOAL_METRICS)[number]

/**
 * A sub-rank of a rank. `target` is how much of the goal metric a member needs in it
 * before the next promotion: classes, or months in rank.
 */
export type SchemeSubRank = { key: string; label: string; target?: number | null }

/** A rank of the gym's scheme (backend `app.schemas.grading.Rank`); a sub-rank's own target wins over its rank's. */
export type SchemeRank = {
  key: string
  label: string
  target?: number | null
  // The belt's colour, then the stripe through a two-tone one, as `#rrggbb`; none for no belt.
  colors?: string[]
  sub_ranks: SchemeSubRank[]
}

/** The gym's grading scheme (`GET /api/gym/grading-scheme`): ranks lowest first. */
export type GradingScheme = {
  ranks: SchemeRank[]
  kids_ladder: SchemeRank[]
  goal_metric: GoalMetric | null
}

/** A starting point for a scheme (`GET /api/gym/grading-scheme/presets`). */
export type GradingPreset = { key: string; label: string; scheme: GradingScheme }

/**
 * How to draw a rank (backend `app.schemas.grades.Belt`): the scheme's colours, and the
 * stripes on the bar. A rank starts at its first sub-rank, with none.
 */
export type BeltDrawing = { colors: string[]; stripes: number; max_stripes: number }

/** A rank as awarded, with the scheme's labels (backend `app.schemas.grades.Rank`). */
export type Rank = {
  rank_key: string
  rank_label: string
  sub_rank: string | null
  sub_rank_label: string | null
  awarded_on: string
  // Null when the scheme gives the rank no colours: it shows as its label.
  belt?: BeltDrawing | null
}

export type GradeEvent = Rank & {
  id: string
  awarded_by_name: string | null
  note: string | null
  created_at: string
}

/** A person's rank and promotion log, newest first. */
export type Grading = {
  current: Rank | null
  events: GradeEvent[]
}

export type GradeAward = {
  rank_key: string
  sub_rank: string | null
  awarded_on: string
  note?: string
}

export function gradingSchemeQuery() {
  return queryOptions({
    queryKey: ['gym', 'grading-scheme'],
    queryFn: () => apiFetch<GradingScheme>('/api/gym/grading-scheme'),
  })
}

export const gradingPresetsQuery = queryOptions({
  queryKey: ['gym', 'grading-scheme', 'presets'],
  queryFn: () => apiFetch<GradingPreset[]>('/api/gym/grading-scheme/presets'),
})

/** Replaces the scheme whole; owner or admin only. A preset is applied by sending it. */
export function saveGradingScheme(scheme: GradingScheme): Promise<GradingScheme> {
  return apiFetch<GradingScheme>('/api/gym/grading-scheme', { method: 'PUT', body: JSON.stringify(scheme) })
}

export function gradesQuery(personId: string) {
  return queryOptions({
    queryKey: ['grades', personId],
    queryFn: () => apiFetch<Grading>(`/api/people/${encodeURIComponent(personId)}/grades`),
  })
}

export function awardGrade(personId: string, body: GradeAward): Promise<Grading> {
  return apiFetch<Grading>(`/api/people/${encodeURIComponent(personId)}/grades`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** `Azul · 2 grados`, or `9.º kyu` for a rank with no sub-ranks. */
export function rankLabel(rank: Rank): string {
  return rank.sub_rank_label ? `${rank.rank_label} · ${rank.sub_rank_label}` : rank.rank_label
}

/** Whole months from the ISO day `from` to `to`: a month counts once its day comes round. */
export function monthsBetween(from: string, to: string): number {
  const [fy, fm, fd] = from.split('-').map(Number) as [number, number, number]
  const [ty, tm, td] = to.split('-').map(Number) as [number, number, number]
  const months = (ty - fy) * 12 + (tm - fm) - (td < fd ? 1 : 0)
  return Math.max(0, months)
}

/** How far a member is towards their next promotion, by the scheme's goal metric. */
export type GoalProgress = {
  metric: GoalMetric
  done: number
  target: number
  // What comes next in their ladder, with the scheme's labels; null at the top.
  next: string | null
}

/**
 * Their progress, or null when there is nothing to show: no goal metric, no target on
 * their rank or sub-rank (a sub-rank's own wins over its rank's), or nothing counted.
 * Classes come from `sincePromotion`; months in rank from the day they were awarded it.
 */
export function goalProgress(
  scheme: GradingScheme,
  current: Rank,
  sincePromotion: number | null,
  today: string,
): GoalProgress | null {
  const metric = scheme.goal_metric
  if (metric === null) return null
  const ladder = [scheme.ranks, scheme.kids_ladder].find((l) => l.some((r) => r.key === current.rank_key))
  const index = ladder?.findIndex((r) => r.key === current.rank_key) ?? -1
  const rank = ladder?.[index]
  if (!ladder || !rank) return null
  const subIndex = rank.sub_ranks.findIndex((s) => s.key === current.sub_rank)
  const target = rank.sub_ranks[subIndex]?.target ?? rank.target ?? null
  if (target == null) return null
  const done = metric === 'classes_since_promotion' ? sincePromotion : monthsBetween(current.awarded_on, today)
  if (done === null) return null
  const nextSub = subIndex >= 0 ? rank.sub_ranks[subIndex + 1] : undefined
  // A sub-rank is named with its rank, as the member's rank is: `Azul · 3 grados`.
  const next = nextSub ? `${rank.label} · ${nextSub.label}` : (ladder[index + 1]?.label ?? null)
  return { metric, done, target, next }
}
