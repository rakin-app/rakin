import type { ComponentProps } from 'react'
import type { GradingScheme, SchemeRank } from '../api/grading'
import { t } from '../i18n/es'
import { Select } from './Field'

const copy = t.admin.rankFilter

/** A belt to filter by (#219): exactly that rank, or it and every one above it on its
 * ladder ("Azul o superior"), by the order of the gym's scheme. */
export type RankChoice = { rank: string; orHigher: boolean }

/** Whether the gym grades at all: with no ranks there is nothing to filter by. */
export function hasRanks(scheme: GradingScheme | undefined): scheme is GradingScheme {
  return scheme !== undefined && scheme.ranks.length + scheme.kids_ladder.length > 0
}

/** The member list's parameters for a choice: `rank`, or `rank_min`. */
export function rankFilters(choice: RankChoice | null): { rank: string[]; rankMin?: string } {
  if (choice === null) return { rank: [] }
  return choice.orHigher ? { rank: [], rankMin: choice.rank } : { rank: [choice.rank] }
}

// One select, so the choice is one value: `is:<key>` or `min:<key>`. Keys hold no colon.
function encode(choice: RankChoice | null): string {
  return choice === null ? '' : `${choice.orHigher ? 'min' : 'is'}:${choice.rank}`
}

function decode(value: string): RankChoice | null {
  const [kind, rank] = value.split(':')
  return kind && rank ? { rank, orHigher: kind === 'min' } : null
}

function Options({ ladder }: { ladder: SchemeRank[] }) {
  // The top rank "o superior" is that rank alone: offered once.
  return ladder.flatMap((rank, index) => [
    <option key={`is:${rank.key}`} value={`is:${rank.key}`}>
      {rank.label}
    </option>,
    ...(index < ladder.length - 1
      ? [
          <option key={`min:${rank.key}`} value={`min:${rank.key}`}>
            {copy.orHigher(rank.label)}
          </option>,
        ]
      : []),
  ])
}

/** Every rank of the scheme, each exactly or "o superior", adults and kids apart as the
 * award form has them. "Todos" for no filter. */
export function RankFilter({
  scheme,
  value,
  onChange,
  anyLabel,
  ...rest
}: Omit<ComponentProps<'select'>, 'value' | 'onChange'> & {
  scheme: GradingScheme
  value: RankChoice | null
  onChange: (choice: RankChoice | null) => void
  anyLabel: string
}) {
  return (
    <Select {...rest} value={encode(value)} onChange={(event) => onChange(decode(event.target.value))}>
      <option value="">{anyLabel}</option>
      {scheme.kids_ladder.length > 0 && scheme.ranks.length > 0 ? (
        <>
          <optgroup label={copy.ranks}>
            <Options ladder={scheme.ranks} />
          </optgroup>
          <optgroup label={copy.kids}>
            <Options ladder={scheme.kids_ladder} />
          </optgroup>
        </>
      ) : (
        <Options ladder={scheme.ranks.length > 0 ? scheme.ranks : scheme.kids_ladder} />
      )}
    </Select>
  )
}
