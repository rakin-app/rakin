import { queryOptions } from '@tanstack/react-query'
import { apiFetch } from './client'

/** A rank of the gym's scheme (backend `app.schemas.grading.Rank`). */
export type SchemeRank = {
  key: string
  label: string
  sub_ranks: { key: string; label: string }[]
}

/** The gym's grading scheme (`GET /api/gym/grading-scheme`): ranks lowest first. */
export type GradingScheme = {
  ranks: SchemeRank[]
  kids_ladder: SchemeRank[]
  goal_metric: 'classes_since_promotion' | 'time_in_rank' | null
}

/** A rank as awarded, with the scheme's labels (backend `app.schemas.grades.Rank`). */
export type Rank = {
  rank_key: string
  rank_label: string
  sub_rank: string | null
  sub_rank_label: string | null
  awarded_on: string
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
