import { useEffect, useRef, useState, type ComponentProps, type ReactNode } from 'react'
import { cx } from './classNames'
import './Chip.css'

type ChipProps = Omit<ComponentProps<'button'>, 'type' | 'aria-pressed'> & { pressed: boolean }

/** A filter that is on or off: a 44px pill, black while pressed. */
export function Chip({ pressed, className, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cx('chip', className)}
      {...rest}
    />
  )
}

/** Which ends of a sideways scroller have more past them. */
type Overflow = { start: boolean; end: boolean }

/** A row of chips that scrolls sideways on a phone instead of wrapping. Where more chips
 * lie past an edge, that edge fades, so the row never seems to end at a chip (#358). */
export function ChipGroup({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [overflow, setOverflow] = useState<Overflow>({ start: false, end: false })

  useEffect(() => {
    const row = ref.current
    if (!row) return
    const measure = () => {
      // A pixel of slack: zoom and rounding leave fractions at the very end.
      const start = row.scrollLeft > 1
      const end = row.scrollLeft + row.clientWidth < row.scrollWidth - 1
      setOverflow((was) => (was.start === start && was.end === end ? was : { start, end }))
    }
    measure()
    row.addEventListener('scroll', measure, { passive: true })
    // Not in every test environment; a resize is then simply not followed.
    const resized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    resized?.observe(row)
    return () => {
      row.removeEventListener('scroll', measure)
      resized?.disconnect()
    }
  }, [])

  return (
    <div
      ref={ref}
      role="group"
      aria-label={label}
      className="chip-group"
      data-more-start={overflow.start || undefined}
      data-more-end={overflow.end || undefined}
    >
      {children}
    </div>
  )
}

/** One of a few views of the same thing ("Este mes / Siempre"): pressing one leaves the others. */
export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="segmented__option"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
