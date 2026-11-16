import { useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { personAttendanceQuery } from '../api/attendance'
import { ApiError } from '../api/client'
import { awardGrade, type Grading, type GradingScheme, type Rank } from '../api/grading'
import { useGymToday } from '../api/sessions'
import { useSubmit } from '../api/submit'
import { Button } from '../components/Button'
import { Input, Select } from '../components/Field'
import { t } from '../i18n/es'
import { HISTORY_WINDOW_YEARS, yearsBefore } from './historyWindow'
import { Banner, cardClass } from '../components/Card'

const copy = t.admin.member.grading.form

/** The rank and sub-rank the form starts on: the current rank's next sub-rank, else the
 * next rank, else the first. */
function nextRank(scheme: GradingScheme, current: Rank | null | undefined): { rank: string; sub: string | null } {
  const all = [...scheme.ranks, ...scheme.kids_ladder]
  const at = current ? all.findIndex((r) => r.key === current.rank_key) : -1
  const here = all[at]
  if (here && current) {
    const sub = here.sub_ranks.findIndex((s) => s.key === current.sub_rank)
    const following = here.sub_ranks[sub + 1]
    if (sub >= 0 && following) return { rank: here.key, sub: following.key }
  }
  const ladder = here && scheme.kids_ladder.includes(here) ? scheme.kids_ladder : scheme.ranks
  const rank = (here && ladder[ladder.indexOf(here) + 1]) ?? here ?? all[0]!
  return { rank: rank.key, sub: rank.sub_ranks[0]?.key ?? null }
}

/**
 * Award a rank: "Registrar graduación" on the ficha's Graduación, or, with `history`,
 * "Grado anterior" in its Historial (#296): a belt from before Rakin, as far back as
 * history goes, for someone with a plan or without, which tells nobody.
 */
export function GradeForm({
  personId,
  scheme,
  current,
  history = false,
  onCancel,
  onDone,
}: {
  personId: string
  scheme: GradingScheme
  current: Rank | null
  history?: boolean
  onCancel: () => void
  onDone: (grading: Grading) => void
}) {
  const queryClient = useQueryClient()
  const ids = { rank: useId(), sub: useId(), date: useId(), note: useId() }
  const start = nextRank(scheme, current)
  const [rankKey, setRankKey] = useState(start.rank)
  const [subRank, setSubRank] = useState<string | null>(start.sub)
  // Today in the gym's timezone, which the API refuses a later day than, until a day is picked.
  const today = useGymToday()
  const [picked, setAwardedOn] = useState<string | null>(null)
  const awardedOn = picked ?? today
  const [note, setNote] = useState('')
  const rank = [...scheme.ranks, ...scheme.kids_ladder].find((r) => r.key === rankKey)

  const award = useSubmit({
    mutationFn: () =>
      awardGrade(personId, {
        rank_key: rankKey,
        sub_rank: subRank,
        awarded_on: awardedOn,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(history ? { source: 'manual' as const } : {}),
      }),
    onSuccess: async (grading) => {
      onDone(grading)
      // A new rank restarts the count of classes since it.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['grades', personId] }),
        queryClient.invalidateQueries({ queryKey: personAttendanceQuery(personId).queryKey }),
      ])
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    award.mutate()
  }

  return (
    <form className={cardClass({}, 'member__form member__form--inset')} aria-label={history ? copy.historyTitle : copy.title} onSubmit={submit}>
      {history && <p className="member__detail">{copy.historyIntro}</p>}
      <label htmlFor={ids.rank} className="member__label">
        {copy.rank}
      </label>
      <Select
        id={ids.rank}
        value={rankKey}
        onChange={(e) => {
          setRankKey(e.target.value)
          const chosen = [...scheme.ranks, ...scheme.kids_ladder].find((r) => r.key === e.target.value)
          setSubRank(chosen?.sub_ranks[0]?.key ?? null)
        }}
      >
        {scheme.kids_ladder.length > 0 ? (
          <>
            <optgroup label={copy.ranks}>
              <RankOptions ranks={scheme.ranks} />
            </optgroup>
            <optgroup label={copy.kids}>
              <RankOptions ranks={scheme.kids_ladder} />
            </optgroup>
          </>
        ) : (
          <RankOptions ranks={scheme.ranks} />
        )}
      </Select>

      {rank && rank.sub_ranks.length > 0 && (
        <>
          <label htmlFor={ids.sub} className="member__label">
            {copy.subRank}
          </label>
          <Select id={ids.sub} value={subRank ?? ''} onChange={(e) => setSubRank(e.target.value)}>
            {rank.sub_ranks.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
        </>
      )}

      <label htmlFor={ids.date} className="member__label">
        {copy.date}
      </label>
      <Input
        id={ids.date}
        type="date"
        required
        min={today ? yearsBefore(today, HISTORY_WINDOW_YEARS) : undefined}
        max={today}
        value={awardedOn}
        onChange={(e) => setAwardedOn(e.target.value)}
      />

      <label htmlFor={ids.note} className="member__label">
        {copy.note}
      </label>
      <Input id={ids.note} type="text" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />

      {award.error && (
        <Banner tone="error">
          {refusal(award.error)}
        </Banner>
      )}

      <div className="member__form-actions">
        <Button disabled={award.isPending} onClick={onCancel}>
          {copy.cancel}
        </Button>
        <Button type="submit" variant="primary" disabled={award.isPending} busy={award.isPending}>
          {award.isPending ? copy.working : copy.submit}
        </Button>
      </div>
    </form>
  )
}

function RankOptions({ ranks }: { ranks: GradingScheme['ranks'] }) {
  return ranks.map((r) => (
    <option key={r.key} value={r.key}>
      {r.label}
    </option>
  ))
}

/** What the API's refusal `code` means to the admin; anything else is a plain failure. */
function refusal(error: Error): string {
  const refused = copy.refused
  const code =
    error instanceof ApiError && typeof error.body === 'object' && error.body !== null
      ? (error.body as { detail?: { code?: unknown } }).detail?.code
      : undefined
  return typeof code === 'string' && code in refused ? refused[code as keyof typeof refused] : refused.failed
}
