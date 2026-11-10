import type { ComponentProps, ReactNode } from 'react'
import './Chip.css'

type ChipProps = Omit<ComponentProps<'button'>, 'type' | 'aria-pressed'> & { pressed: boolean }

/** A filter that is on or off: a 44px pill, black while pressed. */
export function Chip({ pressed, className, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={className ? `chip ${className}` : 'chip'}
      {...rest}
    />
  )
}

/** A row of chips that scrolls sideways on a phone instead of wrapping. */
export function ChipGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="chip-group">
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
