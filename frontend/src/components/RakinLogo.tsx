import { t } from '../i18n/es'
import { cx } from './classNames'
import './RakinLogo.css'

type Props = {
  /** What it sits on: `dark` (the shell's bar and sidebar) lightens the wordmark. */
  surface?: 'light' | 'dark'
  /** The symbol alone, without «rakin▪». */
  symbolOnly?: boolean
  className?: string
}

// The symbol's geometry, from docs/brand/build.py (#224): four mats turning around a
// half mat, on a 32-unit grid. Change it there first, then here.
const MATS = [
  [4, 4, 16, 6],
  [22, 4, 6, 16],
  [12, 22, 16, 6],
  [4, 12, 6, 16],
] as const

/**
 * Rakin's logo: the tatami symbol in its ring and the wordmark «rakin▪», whose square is the
 * centre mat (#224). It wears the theme's colours. Decorative: whoever places it says
 * "Rakin" in text for screen readers, or already does.
 */
export function RakinLogo({ surface = 'light', symbolOnly = false, className }: Props) {
  return (
    <span className={cx('rakin-logo', `rakin-logo--${surface}`, className)} aria-hidden="true">
      <svg className="rakin-logo__symbol" viewBox="0 0 32 32" focusable="false">
        <rect className="rakin-logo__tile" width="32" height="32" rx="7" />
        <rect className="rakin-logo__ring" x="1" y="1" width="30" height="30" rx="6" />
        {MATS.map(([x, y, width, height]) => (
          <rect key={`${x},${y}`} className="rakin-logo__mat" x={x} y={y} width={width} height={height} rx="1" />
        ))}
        <rect className="rakin-logo__centre" x="12" y="12" width="8" height="8" rx="1" />
      </svg>
      {!symbolOnly && (
        <span className="rakin-logo__word">
          {t.app.name}
          <span className="rakin-logo__square" />
        </span>
      )}
    </span>
  )
}
