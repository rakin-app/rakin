import type { ReactNode } from 'react'
import type { Rank } from '../api/grading'
import './Belt.css'

// Drawn in a 120 × 24 box, scaled by CSS: the belt, the rank bar towards its tip, and
// the stripes on the bar from its tip end in.
const WIDTH = 120
const HEIGHT = 24
const BAR_END = 110
const BAR_MIN = 22
const BAR_MAX = 80
const STRIPE = 3
const PITCH = 6
// Black either side of the stripes, inside the bar.
const PAD = 3
const RANK_BAR = '#141414'
// A black belt's bar is red, as on a real one, so it shows on the belt.
const RANK_BAR_ON_BLACK = '#c8102e'
const STRIPE_COLOR = '#ffffff'

type Props = {
  // The belt's colour, then the stripe through a two-tone one.
  colors: string[]
  stripes: number
  maxStripes: number
  // The text alternative: `Azul, 3 grados`.
  label: string
  compact?: boolean
}

/** A rank's belt, drawn: its colour or two, the rank bar and the stripes earned on it. */
export function Belt({ colors, stripes, maxStripes, label, compact = false }: Props) {
  const [main = RANK_BAR, tone] = colors
  // Stripes close up when a scheme has many, so the bar stays short of the belt's end.
  const pitch = maxStripes > 1 ? Math.min(PITCH, (BAR_MAX - PAD * 2 - STRIPE) / (maxStripes - 1)) : PITCH
  const barWidth = maxStripes > 0 ? Math.max(BAR_MIN, PAD * 2 + pitch * (maxStripes - 1) + STRIPE) : 0
  const earned = Math.max(0, Math.min(stripes, maxStripes))
  return (
    <span className={`belt${compact ? ' belt--compact' : ''}`} role="img" aria-label={label}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" focusable="false">
        <rect className="belt__body" x="0.5" y="0.5" width={WIDTH - 1} height={HEIGHT - 1} rx="3" fill={main} />
        {tone && <rect x="0.5" y={HEIGHT / 3} width={WIDTH - 1} height={HEIGHT / 3} fill={tone} />}
        {barWidth > 0 && (
          <rect
            data-part="bar"
            x={BAR_END - barWidth}
            y="0.5"
            width={barWidth}
            height={HEIGHT - 1}
            fill={isDark(main) ? RANK_BAR_ON_BLACK : RANK_BAR}
          />
        )}
        {Array.from({ length: earned }, (_, n) => (
          <rect
            key={n}
            data-part="stripe"
            x={BAR_END - PAD - STRIPE - n * pitch}
            y="0.5"
            width={STRIPE}
            height={HEIGHT - 1}
            fill={STRIPE_COLOR}
          />
        ))}
      </svg>
    </span>
  )
}

/** A rank's belt, when the scheme gives it colours; else its label, as `fallback`. */
export function RankBelt({ rank, compact, fallback = null }: { rank: Rank; compact?: boolean; fallback?: ReactNode }) {
  if (!rank.belt) return fallback
  const { colors, stripes, max_stripes } = rank.belt
  return <Belt colors={colors} stripes={stripes} maxStripes={max_stripes} label={beltLabel(rank)} compact={compact} />
}

/** `Azul, 3 grados`; the rank alone with no stripes on it, `Azul`, or no sub-ranks, `9.º kyu`. */
export function beltLabel(rank: Rank): string {
  return rank.sub_rank_label && rank.belt?.stripes ? `${rank.rank_label}, ${rank.sub_rank_label}` : rank.rank_label
}

/** Near-black, by relative luminance: a bar that colour would not show. */
export function isDark(hex: string): boolean {
  const channels = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16) / 255)
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)) as [number, number, number]
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.03
}
