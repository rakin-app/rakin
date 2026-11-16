import type { ReactNode } from 'react'
import { cx } from './classNames'
import { PlainList } from './Card'
import './BarList.css'

export type Bar = {
  key: string
  label: ReactNode
  /** The figure the bar stands for, as text: the bar itself is only decoration. */
  figure: ReactNode
  value: number
  /** `muted` for a bar that counts for less: not sparring, an archived tag. */
  muted?: boolean
}

/**
 * Rows of a name and its figure over a bar as long as its share of the longest (#141,
 * #243): "Tiempo de entrenamiento"'s block kinds and "Horas por etiqueta"'s tags.
 */
export function BarList({ bars, label }: { bars: Bar[]; label?: string }) {
  const longest = Math.max(...bars.map((bar) => bar.value), 1)
  return (
    <PlainList className="bar-list" aria-label={label}>
      {bars.map((bar) => (
        <li key={bar.key} className="bar-list__row">
          <span className="bar-list__line">
            <span>{bar.label}</span>
            <span className="bar-list__figure">{bar.figure}</span>
          </span>
          <span className="bar-list__bar" aria-hidden="true">
            <span
              className={cx('bar-list__fill', bar.muted && 'bar-list__fill--muted')}
              style={{ width: `${(bar.value / longest) * 100}%` }}
            />
          </span>
        </li>
      ))}
    </PlainList>
  )
}

/** A line of grey under or among the bars: loading, empty, or what a figure leaves out. */
export function BarNote({ children }: { children: ReactNode }) {
  return <p className="bar-note">{children}</p>
}

/** The figures could not be loaded. */
export function BarError({ children }: { children: ReactNode }) {
  return (
    <p className="bar-error" role="alert">
      {children}
    </p>
  )
}
