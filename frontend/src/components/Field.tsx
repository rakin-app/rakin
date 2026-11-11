import { useId, type ComponentProps, type ReactNode } from 'react'
import { cx } from './classNames'
import { SearchIcon } from './icons'
import './Field.css'

/** A text input at 16px, so iOS Safari does not zoom in on focus. */
export function Input({ className, ...rest }: ComponentProps<'input'>) {
  return <input className={cx('control', className)} {...rest} />
}

/** A search box with the board's magnifier in it (#199). `className` sizes the box; the
 * rest goes to the input, as `Input` takes it. */
export function SearchInput({ className, ...rest }: Omit<ComponentProps<'input'>, 'type'>) {
  return (
    <span className={cx('search-control', className)}>
      <SearchIcon />
      <input type="search" className="control search-control__input" {...rest} />
    </span>
  )
}

export function Select({ className, ...rest }: ComponentProps<'select'>) {
  return <select className={cx('control', 'control--select', className)} {...rest} />
}

export function Textarea({ className, ...rest }: ComponentProps<'textarea'>) {
  return <textarea className={cx('control', 'control--textarea', className)} {...rest} />
}

/** What a `Field` hands its control, so the label, hint and error belong to it. */
export type ControlProps = { id: string; 'aria-invalid': boolean; 'aria-describedby': string | undefined }

/**
 * A labelled control, with its hint and its error underneath, both read out with it
 * (`aria-describedby`); an error also marks the control invalid.
 */
export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  error?: ReactNode
  className?: string
  children: (props: ControlProps) => ReactNode
}) {
  const id = useId()
  const hasError = error !== undefined && error !== null && error !== false && error !== ''
  const described = cx(hint ? `${id}-hint` : undefined, hasError && `${id}-error`)
  return (
    <div className={cx('field', className)}>
      <label htmlFor={id} className="field__label">
        {label}
      </label>
      {children({ id, 'aria-invalid': hasError, 'aria-describedby': described || undefined })}
      {hint && (
        <p id={`${id}-hint`} className="field__hint">
          {hint}
        </p>
      )}
      {hasError && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  )
}

/** A form error in the danger colour; give it an `id` the control points at. */
export function FieldError({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="field__error">
      {children}
    </p>
  )
}
